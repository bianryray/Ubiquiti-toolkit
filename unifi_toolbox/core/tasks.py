import threading
import time
from typing import Optional, List, Dict

from .ssh_manager import SSHManager
from ..utils import LogFn, noop_log, build_inform_url, SSHOptions


class ControlledTask:
    """Base class providing pause/stop controls for threaded tasks."""

    def __init__(self, log: LogFn = noop_log):
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.clear()
        self.log = log

    def pause(self):
        self._pause_event.set()
        self.log("Paused.")

    def resume(self):
        if self._pause_event.is_set():
            self._pause_event.clear()
            self.log("Resumed.")

    def stop(self):
        self._stop_event.set()
        self.log("Stop requested.")

    def _check_controls(self):
        if self._stop_event.is_set():
            raise RuntimeError("Task stopped by user.")
        while self._pause_event.is_set():
            time.sleep(0.2)
            if self._stop_event.is_set():
                raise RuntimeError("Task stopped by user.")


class AdoptionTask(ControlledTask):
    """Runs SSH adoption on a single device with pause/stop support."""

    def __init__(
        self,
        ssh: SSHManager,
        controller_url: Optional[str],
        dry_run: bool,
        log: LogFn = noop_log,
    ):
        super().__init__(log=log)
        self.ssh = ssh
        self.controller_url = controller_url
        self.dry_run = dry_run
        self.thread: Optional[threading.Thread] = None

    def start(self):
        if self.thread and self.thread.is_alive():
            self.log("Task already running.")
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self._check_controls()
            self.ssh.adopt(
                self.controller_url or "", dry_run=self.dry_run
            )
        except RuntimeError as e:
            self.log(str(e))
        except Exception as e:
            self.log(f"Error: {e}")


class BatchAdoptionTask(ControlledTask):
    """Runs SSH adoption across multiple devices sequentially."""

    def __init__(
        self,
        targets: List[str],
        username: str,
        password: str,
        controller_url: Optional[str],
        port: int = 22,
        dry_run: bool = False,
        ssh_options: Optional[SSHOptions] = None,
        log: LogFn = noop_log,
        on_progress: Optional[callable] = None,
    ):
        super().__init__(log=log)
        self.targets = targets
        self.username = username
        self.password = password
        self.controller_url = controller_url
        self.port = port
        self.dry_run = dry_run
        self.ssh_options = ssh_options or SSHOptions()
        self.on_progress = on_progress
        self.results: List[Dict] = []
        self.thread: Optional[threading.Thread] = None

    def start(self):
        if self.thread and self.thread.is_alive():
            self.log("Batch task already running.")
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        total = len(self.targets)
        self.log(f"Starting batch adoption: {total} device(s)")
        self.log("=" * 60)

        for i, ip in enumerate(self.targets, 1):
            try:
                self._check_controls()
            except RuntimeError as e:
                self.log(str(e))
                break

            self.log(f"\n[{i}/{total}] Adopting {ip} ...")
            ssh = SSHManager(
                ip,
                self.username,
                self.password,
                port=self.port,
                log=self.log,
                options=self.ssh_options,
            )
            result = ssh.adopt(
                self.controller_url or "", dry_run=self.dry_run
            )
            self.results.append(result)

            if self.on_progress:
                try:
                    self.on_progress(i, total, result)
                except Exception:
                    pass

        self.log("\n" + "=" * 60)
        adopted = sum(1 for r in self.results if r.get("adopted"))
        self.log(
            f"Batch complete: {adopted}/{len(self.results)} succeeded"
        )


class ResetTask(ControlledTask):
    """Runs factory reset via SSH."""

    def __init__(
        self,
        ssh: SSHManager,
        which: str,
        log: LogFn = noop_log,
    ):
        super().__init__(log=log)
        self.ssh = ssh
        self.which = which
        self.thread: Optional[threading.Thread] = None

    def start(self):
        if self.thread and self.thread.is_alive():
            self.log("Reset already in progress.")
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self._check_controls()
            if self.which == "syswrapper":
                self.log(
                    "Issuing factory reset: syswrapper.sh restore-default ..."
                )
                ok, out, err = self.ssh.factory_reset_syswrapper()
            else:
                self.log("Issuing factory reset: set-default ...")
                ok, out, err = self.ssh.factory_reset_setdefault()
            self._check_controls()
            if ok:
                self.log(
                    "Reset command sent. Device may reboot shortly."
                )
            else:
                self.log(
                    f"Reset failed or returned non-zero. stderr: {err.strip()}"
                )
                if out.strip():
                    self.log(out.strip())
        except RuntimeError as e:
            self.log(str(e))
        except Exception as e:
            self.log(f"Error: {e}")
