import time
import socket
import os
from typing import Tuple, Dict, List, Optional

import paramiko

from ..utils import (
    DEFAULT_SSH_PORT,
    SSH_TIMEOUT,
    CONSOLE_KEYWORDS,
    LogFn,
    noop_log,
    build_inform_url,
    SSHOptions,
)


class SSHManager:
    """Manages SSH connections to Ubiquiti devices."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = DEFAULT_SSH_PORT,
        log: LogFn = noop_log,
        options: Optional[SSHOptions] = None,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.log = log
        self.options = options or SSHOptions()
        self.last_auth_method: Optional[str] = None

    # -------------------- Helpers -------------------- #

    def _load_pkey(self, path: str, passphrase: Optional[str] = None):
        key_types = [
            getattr(paramiko, "Ed25519Key", None),
            paramiko.RSAKey,
            getattr(paramiko, "ECDSAKey", None),
            getattr(paramiko, "DSSKey", None),
        ]
        for Key in key_types:
            if Key is None:
                continue
            try:
                return Key.from_private_key_file(path, password=passphrase)
            except Exception:
                continue
        raise RuntimeError(
            "Unable to load private key. Tried Ed25519/RSA/ECDSA/DSS."
        )

    def _add_to_known_hosts(self, hostname: str, key):
        try:
            kh_path = os.path.expanduser("~/.ssh/known_hosts")
            os.makedirs(os.path.dirname(kh_path), exist_ok=True)
            hostkeys = paramiko.HostKeys()
            if os.path.exists(kh_path):
                try:
                    hostkeys.load(kh_path)
                except Exception:
                    hostkeys = paramiko.HostKeys()
            hostkeys.add(hostname, key.get_name(), key)
            hostkeys.save(kh_path)
        except Exception:
            pass

    def _verify_or_accept_server_key(self, t: paramiko.Transport):
        server_key = t.get_remote_server_key()
        if self.options.accept_unknown_host_key:
            self._add_to_known_hosts(self.host, server_key)
            return True
        kh_path = os.path.expanduser("~/.ssh/known_hosts")
        hk = paramiko.HostKeys()
        if os.path.exists(kh_path):
            try:
                hk.load(kh_path)
            except Exception:
                pass
        if hk.check(self.host, server_key):
            return True
        raise paramiko.ssh_exception.SSHException(
            f"Server '{self.host}' not found in known_hosts"
        )

    # -------------------- Connect -------------------- #

    def _connect(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        policy = (
            paramiko.AutoAddPolicy()
            if self.options.accept_unknown_host_key
            else paramiko.RejectPolicy()
        )
        client.set_missing_host_key_policy(policy)
        try:
            client.load_system_host_keys()
        except Exception:
            pass

        try:
            kwargs = dict(
                hostname=self.host,
                port=self.port,
                username=self.username,
                timeout=SSH_TIMEOUT,
                banner_timeout=self.options.banner_timeout,
                auth_timeout=self.options.auth_timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            if self.options.use_pkey and self.options.pkey_path:
                pkey = self._load_pkey(
                    self.options.pkey_path, self.options.pkey_passphrase
                )
                kwargs.update(dict(pkey=pkey, password=None))
            else:
                kwargs.update(dict(password=self.password))
            client.connect(**kwargs)
            self.last_auth_method = (
                "publickey" if self.options.use_pkey else "password"
            )
            self.log(f"SSH connected (method: {self.last_auth_method})")
            return client
        except Exception as e:
            msg = str(e)
            if self.options.try_keyboard_interactive and (
                "keyboard" in msg.lower()
                or "allowed types" in msg.lower()
                or "authentication failed" in msg.lower()
            ):
                return self._connect_interactive()
            raise

    def _connect_interactive(self) -> paramiko.SSHClient:
        last_err = None
        for attempt in range(3):
            try:
                sock = socket.create_connection(
                    (self.host, self.port), timeout=SSH_TIMEOUT
                )
                t = paramiko.Transport(sock)
                t.banner_timeout = self.options.banner_timeout
                t.auth_timeout = self.options.auth_timeout
                t.start_client(timeout=self.options.banner_timeout)
                self._verify_or_accept_server_key(t)

                def handler(title, instructions, prompts):
                    return [self.password for _ in prompts]

                try:
                    t.auth_interactive(self.username, handler)
                except paramiko.ssh_exception.SSHException:
                    try:
                        t.auth_password(self.username, self.password)
                    except Exception:
                        raise

                if not t.is_authenticated():
                    raise paramiko.ssh_exception.AuthenticationException(
                        "Authentication failed."
                    )

                client = paramiko.SSHClient()
                client._transport = t
                self.last_auth_method = "keyboard-interactive"
                self.log(
                    f"SSH connected (method: {self.last_auth_method})"
                )
                return client
            except Exception as e2:
                last_err = e2
                if "Error reading SSH protocol banner" in str(
                    e2
                ) or "timed out" in str(e2).lower():
                    time.sleep(1.2)
                    continue
                break
        raise RuntimeError(f"SSH interactive auth failed: {last_err}")

    # -------------------- Exec -------------------- #

    def run(
        self, cmd: str, timeout: int = SSH_TIMEOUT
    ) -> Tuple[bool, str, str]:
        try:
            client = self._connect()
        except Exception as e:
            return False, "", f"SSH connection failed: {e}"
        try:
            stdin, stdout, stderr = client.exec_command(
                cmd, timeout=timeout
            )
            out = stdout.read().decode(errors="ignore")
            err = stderr.read().decode(errors="ignore")
            exit_status = stdout.channel.recv_exit_status()
            client.close()
            return (exit_status == 0), out, err
        except Exception as e:
            client.close()
            return False, "", f"Command execution failed: {e}"

    def run_until_marker(
        self,
        cmd: str,
        success_markers: Tuple[str, ...],
        failure_markers: Tuple[str, ...] = (),
        timeout: int = SSH_TIMEOUT,
    ) -> Tuple[str, str]:
        """Run `cmd` and stream output until a marker matches or we time out.

        Why this exists: `set-inform` (and especially `mca-cli set-inform`)
        keep the SSH session alive until the device finishes informing the
        controller -- which can take 10-30s and sometimes never closes
        cleanly. We don't want to wait that long, and we don't want to read
        with `.read()` (blocks until EOF). Instead we poll the channel,
        accumulate output, and close the connection as soon as we see the
        canonical success line ("Adoption request sent to ...").

        Returns: (status, captured_output)
            status in {"success", "failure", "timeout", "ssh_error"}
        """
        try:
            client = self._connect()
        except Exception as e:
            return "ssh_error", f"SSH connection failed: {e}"

        success_lc = tuple(m.lower() for m in success_markers)
        failure_lc = tuple(m.lower() for m in failure_markers)
        captured_parts: List[str] = []

        def _check_markers() -> Optional[str]:
            text = "".join(captured_parts).lower()
            for m in success_lc:
                if m in text:
                    return "success"
            for m in failure_lc:
                if m in text:
                    return "failure"
            return None

        try:
            stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            chan = stdout.channel
            chan.settimeout(0.0)  # non-blocking reads via recv_ready()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                got_data = False
                if chan.recv_ready():
                    try:
                        data = chan.recv(4096).decode(errors="ignore")
                        if data:
                            captured_parts.append(data)
                            got_data = True
                    except Exception:
                        pass
                if chan.recv_stderr_ready():
                    try:
                        data = chan.recv_stderr(4096).decode(errors="ignore")
                        if data:
                            captured_parts.append(data)
                            got_data = True
                    except Exception:
                        pass
                if got_data:
                    hit = _check_markers()
                    if hit:
                        try:
                            client.close()
                        except Exception:
                            pass
                        return hit, "".join(captured_parts)
                if chan.exit_status_ready() and not (
                    chan.recv_ready() or chan.recv_stderr_ready()
                ):
                    # Command finished cleanly. Final marker check.
                    hit = _check_markers()
                    try:
                        client.close()
                    except Exception:
                        pass
                    if hit:
                        return hit, "".join(captured_parts)
                    return "failure", "".join(captured_parts)
                if not got_data:
                    time.sleep(0.1)
            # Hit timeout. If something useful arrived, hand it back.
            try:
                client.close()
            except Exception:
                pass
            hit = _check_markers()
            if hit:
                return hit, "".join(captured_parts)
            return "timeout", "".join(captured_parts)
        except Exception as e:
            try:
                client.close()
            except Exception:
                pass
            captured_parts.append(f"\n[exec error] {e}")
            hit = _check_markers()
            if hit:
                return hit, "".join(captured_parts)
            return "ssh_error", "".join(captured_parts)

    def run_interactive(
        self,
        cmd: str,
        success_markers: Tuple[str, ...],
        failure_markers: Tuple[str, ...] = (),
        timeout: int = SSH_TIMEOUT,
        drain_seconds: float = 2.5,
    ) -> Tuple[str, str]:
        """Open an interactive shell, type `cmd`, watch output for markers.

        Why this and not exec_command():
            On many Ubiquiti devices `set-inform` is NOT a binary on PATH --
            it's a shell function defined in /etc/profile.d/ that's only
            loaded when you get a real interactive login shell. paramiko's
            exec_command() is a non-login non-interactive shell, so the
            function never gets defined and you see "set-inform: not found"
            even though typing it manually after SSHing in works fine.
            invoke_shell() gives us the same context the user gets by hand.

        Returns: (status, captured_output)
            status in {"success", "failure", "timeout", "ssh_error"}
            captured_output includes everything the shell printed,
            including the MOTD banner.
        """
        try:
            client = self._connect()
        except Exception as e:
            return "ssh_error", f"SSH connection failed: {e}"

        success_lc = tuple(m.lower() for m in success_markers)
        failure_lc = tuple(m.lower() for m in failure_markers)
        captured: List[str] = []

        def _check() -> Optional[str]:
            text = "".join(captured).lower()
            for m in success_lc:
                if m in text:
                    return "success"
            for m in failure_lc:
                if m in text:
                    return "failure"
            return None

        chan = None
        try:
            chan = client.invoke_shell(width=200, height=50)
            chan.settimeout(0.0)

            # Drain the login banner / MOTD before sending our command. We
            # don't try to detect a "prompt" -- prompt regexes vary wildly
            # across Ubiquiti firmwares -- a fixed drain window is reliable
            # enough.
            drain_until = time.monotonic() + drain_seconds
            while time.monotonic() < drain_until:
                if chan.recv_ready():
                    try:
                        data = chan.recv(4096).decode(errors="ignore")
                        if data:
                            captured.append(data)
                    except Exception:
                        pass
                else:
                    time.sleep(0.1)

            # Type the command + Enter, exactly like a user would.
            try:
                chan.send(cmd + "\n")
            except Exception as e:
                try:
                    client.close()
                except Exception:
                    pass
                return "ssh_error", f"Couldn't send command: {e}"

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if chan.recv_ready():
                    try:
                        data = chan.recv(4096).decode(errors="ignore")
                        if data:
                            captured.append(data)
                            hit = _check()
                            if hit:
                                try:
                                    chan.send("exit\n")
                                except Exception:
                                    pass
                                try:
                                    client.close()
                                except Exception:
                                    pass
                                return hit, "".join(captured)
                    except Exception:
                        pass
                else:
                    time.sleep(0.1)

            # Timeout.
            try:
                chan.send("exit\n")
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
            hit = _check()
            if hit:
                return hit, "".join(captured)
            return "timeout", "".join(captured)
        except Exception as e:
            try:
                client.close()
            except Exception:
                pass
            return "ssh_error", f"Interactive shell error: {e}"

    def run_visible(
        self, cmd: str, timeout: int = SSH_TIMEOUT
    ) -> Tuple[bool, str, str]:
        self.log(f">> {self.host}: {cmd}")
        ok, out, err = self.run(cmd, timeout=timeout)
        if ok:
            self.log("<< OK")
            if out.strip():
                self.log(out.strip())
            if err.strip():
                self.log(f"(stderr) {err.strip()}")
        else:
            self.log("<< FAILED")
            if err.strip():
                self.log(f"(stderr) {err.strip()}")
            if out.strip():
                self.log(out.strip())
        return ok, out, err

    # -------------------- High level ops -------------------- #

    def detect_model(self) -> Tuple[str, str]:
        probes = [
            "ubnt-device-info",
            "cat /etc/board.info",
            "cat /usr/lib/version",
            "cat /etc/version",
            "mca-cli show | sed -n '1,80p'",
            "info",
        ]
        text = ""
        for cmd in probes:
            ok, out, err = self.run(cmd)
            if ok and (out.strip() or err.strip()):
                text += f"\n# {cmd}\n{out or ''}\n{err or ''}\n"
                if len(text) > 2000:
                    break
        model = "console" if CONSOLE_KEYWORDS.search(text or "") else "leaf"
        self.log(f"Model detection: {model.upper()}")
        return model, text

    def adopt(
        self, controller_url: str, dry_run: bool = False
    ) -> Dict:
        """Send a single set-inform to the device.

        Two key invariants:
          1. We send `set-inform` ONCE. Hosted controllers (HostiFi, UI.com
             cloud) get hammered if multiple inform requests fan in from
             one device, so we never fall through to a second set-inform on
             the same device unless the first one literally couldn't find
             the binary.
          2. We use the canonical success line as the trigger to stop:
             "Adoption request sent to '<url>'. Use UniFi Network to
             complete the adopt process." When that appears in stdout we
             know the command worked, and we close our SSH connection
             without waiting for the device-side adoption flow to fully
             settle (which can take 30s+ and sometimes never closes the
             channel cleanly).
        """
        results: Dict = {"ip": self.host, "attempts": []}

        def record(cmd: str, status, out: str):
            results.setdefault("attempts", []).append(
                {
                    "cmd": cmd,
                    "status": status,
                    "out": (out or "").strip(),
                }
            )

        if not controller_url:
            self.log("No controller URL provided; skipping set-inform.")
            results["adopted"] = False
            return results

        inform = build_inform_url(controller_url)

        # Type the command into a real interactive shell -- on Ubiquiti
        # devices `set-inform` is often a shell function defined in
        # /etc/profile.d/ that's only available in an interactive login
        # context, NOT in paramiko's exec_command() shell.
        primary = f"set-inform {inform}"
        fallback = f"mca-cli set-inform {inform}"

        # Canonical success line printed by the set-inform binary on every
        # currently-shipping firmware.
        success_markers = (
            "adoption request sent",
            "successfully informed",
        )
        # Failure markers we treat as terminal -- give up immediately.
        other_failure_markers = (
            "permission denied",
            "operation not permitted",
            "no such file or directory",
        )

        # ---- Primary attempt --------------------------------------------
        if dry_run:
            self.log(f"[DRY RUN] Would run: set-inform {inform}")
            record(primary, "dry_run", "")
            results["adopted"] = None
            return results

        self.log(f"Sending: set-inform {inform}")
        status, output = self.run_interactive(
            primary,
            success_markers=success_markers,
            failure_markers=other_failure_markers,
            timeout=25,
        )
        record(primary, status, output)
        # Echo only the bit after our command was sent (keeps the MOTD
        # noise out of the visible log). The interactive shell echoes our
        # command back, so split on it.
        relevant = output.split(primary, 1)[-1]
        for line in relevant.strip().splitlines():
            line = line.rstrip()
            if line:
                self.log(f"  {line}")

        if status == "success":
            results["adopted"] = True
            results["successful_cmd"] = "set-inform"
            self.log(
                "[OK] Adopted. Finish the pairing in your UniFi Network "
                "controller (Devices -> Pending Adoption)."
            )
            return results

        # ---- Decide whether to retry ------------------------------------
        out_lc = output.lower()
        # `ash` prints "set-inform: not found" when neither /etc/profile
        # nor the bare PATH had it. THAT is the only legitimate reason to
        # retry with mca-cli.
        binary_missing = (
            ("set-inform" in out_lc and "not found" in out_lc)
            or "command not found" in out_lc
        )

        if not binary_missing:
            # Real error (network, permission, controller URL bad, etc).
            # Don't fire a second inform.
            results["adopted"] = False
            self.log(
                "Adoption failed. Not retrying with a second command -- "
                "that would just queue another adoption request at the "
                "controller. See checklist below."
            )
            self._log_failure_checklist()
            return results

        # ---- Single fallback: mca-cli set-inform ------------------------
        self.log(
            "`set-inform` not available even in interactive shell; "
            "trying `mca-cli set-inform` once."
        )
        status2, output2 = self.run_interactive(
            fallback,
            success_markers=success_markers,
            failure_markers=other_failure_markers,
            timeout=25,
        )
        record(fallback, status2, output2)
        relevant2 = output2.split(fallback, 1)[-1]
        for line in relevant2.strip().splitlines():
            line = line.rstrip()
            if line:
                self.log(f"  {line}")

        if status2 == "success":
            results["adopted"] = True
            results["successful_cmd"] = "mca-cli set-inform"
            self.log(
                "[OK] Adopted via mca-cli. Finish the pairing in your "
                "UniFi Network controller (Devices -> Pending Adoption)."
            )
            return results

        results["adopted"] = False
        self._log_failure_checklist()
        return results

    def _log_failure_checklist(self):
        self.log(
            "[FAIL] Adoption did not succeed. Things to check:\n"
            "  1. Controller URL is reachable from the device "
            "(http://<controller-ip>:8080, NOT https, NOT port 443/8443).\n"
            "  2. Device hasn't already been adopted by another controller "
            "(factory-reset it via the Factory Reset section if so).\n"
            "  3. SSH credentials are correct (try the 'Use default ubnt / "
            "ubnt' checkbox for factory-fresh devices).\n"
            "  4. For older firmware, try SSHing in manually and running:\n"
            "       set-inform http://<controller-ip>:8080/inform\n"
            "     so you can see the device's full response."
        )

    def factory_reset_syswrapper(self) -> Tuple[bool, str, str]:
        return self.run("syswrapper.sh restore-default")

    def factory_reset_setdefault(self) -> Tuple[bool, str, str]:
        return self.run("set-default")

    @staticmethod
    def tcp_check(host: str, port: int, timeout: int = 2) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False
