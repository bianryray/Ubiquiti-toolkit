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

        Keep it minimal: every extra set-inform sends a fresh adoption request
        to the controller, which can overwhelm hosted controllers (HostiFi,
        UI.com cloud, etc). So we fire *one* command and trust the result.
        We only fall back to `mca-cli set-inform` if the direct binary is
        literally missing on the device (older firmware / UniFi-OS consoles).
        """
        results: Dict = {"ip": self.host, "attempts": []}

        def record(cmd: str, ok, out: str, err: str):
            results.setdefault("attempts", []).append(
                {
                    "cmd": cmd,
                    "ok": ok,
                    "out": (out or "").strip(),
                    "err": (err or "").strip(),
                }
            )

        if not controller_url:
            self.log("No controller URL provided; skipping set-inform.")
            results["adopted"] = False
            return results

        inform = build_inform_url(controller_url)
        primary = f"set-inform {inform}"
        fallback = f"mca-cli set-inform {inform}"

        # Indicators that the *binary itself* isn't present -- the ONLY case
        # where we're willing to send a second inform request.
        missing_binary_markers = (
            "command not found",
            "not found",
            "no such file",
            "unrecognized",
        )

        def _attempt(cmd: str) -> Tuple[Optional[bool], str, str, str]:
            if dry_run:
                self.log(f"[DRY RUN] Would run: {cmd}")
                record(cmd, None, "(dry run)", "")
                return None, "", "", ""
            self.log(f"Running: {cmd}")
            ok, out, err = self.run(cmd)
            record(cmd, ok, out, err)
            # Echo whatever the device actually replied with so the user
            # sees the real "Adoption request sent to ..." line instead of a
            # summary that hides it.
            if out and out.strip():
                for line in out.strip().splitlines():
                    self.log(f"  {line}")
            if err and err.strip():
                for line in err.strip().splitlines():
                    self.log(f"  (stderr) {line}")
            combined = ((out or "") + "\n" + (err or "")).lower()
            return ok, out, err, combined

        # ---- 1. One attempt with the canonical command ---------------
        ok, out, err, combined = _attempt(primary)
        if dry_run:
            # No second command on dry run either.
            results["adopted"] = None
            return results

        missing = any(m in combined for m in missing_binary_markers)

        if ok and not missing:
            results["adopted"] = True
            results["successful_cmd"] = primary
            self.log(
                "[OK] Adopted. Finish the pairing in your UniFi Network "
                "controller (Devices -> Pending Adoption)."
            )
            return results

        # ---- 2. Only fall back if the binary was missing -------------
        if not missing:
            # Something else went wrong (auth, network, non-zero exit with
            # a real error). DON'T spam a second set-inform at the
            # controller -- report failure and stop.
            results["adopted"] = False
            self.log(
                "Adoption failed. Not retrying -- a second set-inform would "
                "just send another adoption request to the controller."
            )
            return results

        self.log("`set-inform` binary not found on device; "
                 "falling back to `mca-cli set-inform` (one retry only).")
        ok2, out2, err2, combined2 = _attempt(fallback)
        if ok2 and not any(m in combined2 for m in missing_binary_markers):
            results["adopted"] = True
            results["successful_cmd"] = fallback
            self.log(
                "[OK] Adopted via mca-cli. Finish the pairing in your "
                "UniFi Network controller (Devices -> Pending Adoption)."
            )
            return results

        results["adopted"] = False
        self.log(
            "Adoption attempts did not succeed. "
            "Check controller URL (/inform), port 8080, "
            "or reset if previously adopted."
        )
        return results

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
