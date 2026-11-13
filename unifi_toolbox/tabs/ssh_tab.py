import threading
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from ..core.ssh_manager import SSHManager
from ..core.tasks import AdoptionTask, BatchAdoptionTask, ResetTask
from ..utils import DEFAULT_SSH_PORT, SSHOptions, parse_ip_targets, LogFn
from .. import theme as T

_MODES = {"Single device": "single", "Batch": "batch"}


class SSHTab(ctk.CTkFrame):
    """SSH adoption tab -- single device and batch mode."""

    def __init__(self, parent, log_fn: LogFn, on_find_devices=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.log = log_fn
        self.on_find_devices = on_find_devices  # callback to switch to Discovery tab
        self.current_task = None
        self._build_ui()

    def _build_ui(self):
        page = T.scroll_page(self)
        T.page_header(
            page, "SSH Adoption",
            "Point devices at your controller over SSH - one device or a whole batch.",
        )

        # ── Target ───────────────────────────────────────────
        target, target_actions = T.card(
            page, "Target", "Which device(s) to connect to", actions=True)
        self.mode_var = ctk.StringVar(value="single")
        self._mode_label = ctk.StringVar(value="Single device")
        T.segmented(
            target_actions, list(_MODES), var=self._mode_label,
            command=lambda v: (self.mode_var.set(_MODES[v]), self._on_mode_change()),
            width=220,
        ).pack(side="right")

        grid = ctk.CTkFrame(target, fg_color="transparent")
        grid.pack(fill="x")
        self.var_ip = ctk.StringVar()

        def ip_and_find(cell):
            box = ctk.CTkFrame(cell, fg_color="transparent")
            self.ent_ip = T.entry(box, self.var_ip, width=240)
            self.ent_ip.pack(side="left")
            self.btn_find = T.button(box, "Find on network", self._on_find_devices,
                                     kind="secondary")
            self.btn_find.pack(side="left", padx=(8, 0))
            return box

        self.cell_ip = T.field(grid, 0, 0, "DEVICE IP", ip_and_find)

        self.var_batch = ctk.StringVar()
        self.cell_batch = T.field(
            grid, 0, 0, "TARGETS",
            lambda c: T.entry(c, self.var_batch, width=520),
            hint="Comma separated IPs, a range (192.168.1.10-50) or CIDR (192.168.1.0/24)",
        )
        self.ent_batch = self.cell_batch.input

        # ── Credentials ──────────────────────────────────────
        creds = T.card(page, "Credentials", "Factory-fresh devices use ubnt / ubnt")
        cgrid = ctk.CTkFrame(creds, fg_color="transparent")
        cgrid.pack(fill="x")
        self.var_user = ctk.StringVar(value="ubnt")
        self.var_pass = ctk.StringVar()
        self.var_port = ctk.StringVar(value=str(DEFAULT_SSH_PORT))
        self.ent_user = T.field(cgrid, 0, 0, "USERNAME",
                                lambda c: T.entry(c, self.var_user, width=200)).input
        self.ent_pass = T.field(cgrid, 0, 1, "PASSWORD",
                                lambda c: T.entry(c, self.var_pass, width=200, show="\u2022")).input
        T.field(cgrid, 0, 2, "SSH PORT", lambda c: T.entry(c, self.var_port, width=80))
        self.var_default_creds = ctk.BooleanVar(value=False)
        T.switch(creds, "Use default ubnt / ubnt", self.var_default_creds,
                 self._on_toggle_default_creds).pack(anchor="w")

        # ── Controller ───────────────────────────────────────
        ctrl = T.card(page, "Controller", "Where adopted devices should report in")
        self.var_ctrl = ctk.StringVar()
        cg = ctk.CTkFrame(ctrl, fg_color="transparent")
        cg.pack(fill="x")
        T.field(
            cg, 0, 0, "CONTROLLER URL",
            lambda c: T.entry(c, self.var_ctrl, width=360),
            hint="e.g. http://192.168.1.1:8080  -  no /inform, no https, no 8443",
        )
        self.var_dry = ctk.BooleanVar(value=False)
        T.switch(ctrl, "Dry run - show the commands without running them",
                 self.var_dry).pack(anchor="w")

        # ── Run ──────────────────────────────────────────────
        run = T.card(page, "Run")
        btn_row = T.row(run)
        self.btn_adopt = T.button(btn_row, "Run Adoption", self._on_adopt,
                                  kind="success", width=170)
        self.btn_adopt.pack(side="left", padx=(0, 8))
        self.btn_detect = T.button(btn_row, "Detect Model", self._on_detect)
        self.btn_detect.pack(side="left", padx=(0, 8))
        self.btn_pause = T.button(btn_row, "Pause", self._on_pause, width=90)
        self.btn_pause.pack(side="left", padx=(0, 8))
        self.btn_stop = T.button(btn_row, "Stop", self._on_stop,
                                 kind="danger-outline", width=90)
        self.btn_stop.pack(side="left")

        # ── SSH options ──────────────────────────────────────
        opts = T.card(page, "SSH Options", "Advanced - the defaults suit most devices")
        o1 = T.row(opts, pady=(0, 10))
        self.var_accept_key = ctk.BooleanVar(value=True)
        T.checkbox(o1, "Auto-accept host keys", self.var_accept_key).pack(side="left", padx=(0, 28))
        self.var_try_kbd = ctk.BooleanVar(value=True)
        T.checkbox(o1, "Try keyboard-interactive auth", self.var_try_kbd).pack(side="left", padx=(0, 28))
        self.var_use_pkey = ctk.BooleanVar(value=False)
        T.checkbox(o1, "Use SSH private key", self.var_use_pkey).pack(side="left")
        kgrid = ctk.CTkFrame(opts, fg_color="transparent")
        kgrid.pack(fill="x")
        self.var_pkey_path = ctk.StringVar()
        self.var_pkey_pw = ctk.StringVar()
        T.field(kgrid, 0, 0, "KEY FILE", lambda c: T.entry(c, self.var_pkey_path, width=320))
        T.field(kgrid, 0, 1, "PASSPHRASE",
                lambda c: T.entry(c, self.var_pkey_pw, width=200, show="\u2022"))

        # ── Quick command ────────────────────────────────────
        quick = T.card(page, "Quick SSH Command", "Run one command on the device above")
        q = T.row(quick)
        self.var_quick_cmd = ctk.StringVar(value="info")
        qe = T.entry(q, self.var_quick_cmd, width=420, mono=True)
        qe.pack(side="left", padx=(0, 8))
        qe.bind("<Return>", lambda e: self._on_quick_cmd())
        T.button(q, "Run", self._on_quick_cmd, kind="primary", width=80).pack(side="left", padx=(0, 8))
        T.button(q, "Test SSH", self._on_test_ssh).pack(side="left")

        # ── Factory reset ────────────────────────────────────
        reset = T.card(page, "Factory Reset",
                       "Wipes the device's configuration. You'll be asked to confirm.")
        r = T.row(reset)
        T.button(r, "syswrapper.sh restore-default", self._on_reset_sys,
                 kind="danger-outline").pack(side="left", padx=(0, 8))
        T.button(r, "set-default", self._on_reset_set,
                 kind="danger-outline", width=120).pack(side="left")

        self._on_mode_change()

    # ── Default credentials lock ────────────────────────────

    def _on_toggle_default_creds(self):
        """When checked, fill user/pass with ubnt/ubnt and lock the fields."""
        if self.var_default_creds.get():
            self.var_user.set("ubnt")
            self.var_pass.set("ubnt")
            self.ent_user.configure(state="disabled")
            self.ent_pass.configure(state="disabled")
            self.log("Using default credentials (ubnt / ubnt).")
        else:
            self.ent_user.configure(state="normal")
            self.ent_pass.configure(state="normal")

    # ── Find devices (switch to Discovery) ──────────────────

    def _on_find_devices(self):
        if self.on_find_devices:
            self.on_find_devices()
        else:
            self.log("Discovery tab is not wired up.")

    # ── Mode toggle ─────────────────────────────────────────

    def _on_mode_change(self):
        is_batch = self.mode_var.get() == "batch"
        self._mode_label.set("Batch" if is_batch else "Single device")
        if is_batch:
            # In batch mode the user already has IPs (often from Discovery),
            # so the single-device field and "Find on network" are clutter.
            self.cell_ip.grid_remove()
            self.cell_batch.grid()
            self.btn_adopt.configure(text="Run Batch Adoption")
        else:
            self.cell_batch.grid_remove()
            self.cell_ip.grid()
            self.btn_adopt.configure(text="Run Adoption")

    # ── Helpers ──────────────────────────────────────────────

    def _get_ssh_options(self) -> SSHOptions:
        return SSHOptions(
            accept_unknown_host_key=self.var_accept_key.get(),
            try_keyboard_interactive=self.var_try_kbd.get(),
            use_pkey=self.var_use_pkey.get(),
            pkey_path=self.var_pkey_path.get().strip() or None,
            pkey_passphrase=self.var_pkey_pw.get() or None,
        )

    def _get_port(self) -> int:
        try:
            return int(self.var_port.get().strip())
        except ValueError:
            return DEFAULT_SSH_PORT

    def _make_ssh(self, ip: Optional[str] = None) -> SSHManager:
        ip = ip or self.var_ip.get().strip()
        user = self.var_user.get().strip()
        pwd = self.var_pass.get()
        if not ip or not user:
            raise ValueError("IP and username are required.")
        return SSHManager(
            ip, user, pwd,
            port=self._get_port(),
            log=self.log,
            options=self._get_ssh_options(),
        )

    # ── Actions ──────────────────────────────────────────────

    def _on_detect(self):
        def worker():
            try:
                ssh = self._make_ssh()
                ssh.detect_model()
            except Exception as e:
                self.log(f"Model detection error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _on_adopt(self):
        if self.mode_var.get() == "batch":
            self._on_batch_adopt()
        else:
            self._on_single_adopt()

    def _on_single_adopt(self):
        try:
            ssh = self._make_ssh()
        except Exception as e:
            self.log(f"Error: {e}")
            return
        ctrl = self.var_ctrl.get().strip() or None
        self.log("\n" + "=" * 60)
        self.log(f"Starting SSH adoption for {ssh.host} (dry_run={self.var_dry.get()}) ...")
        task = AdoptionTask(ssh, controller_url=ctrl, dry_run=self.var_dry.get(), log=self.log)
        self.current_task = task
        task.start()

    def _on_batch_adopt(self):
        raw = self.var_batch.get().strip()
        if not raw:
            self.log("Error: No targets entered for batch adoption.")
            return
        targets = parse_ip_targets(raw)
        if not targets:
            self.log("Error: Could not parse any valid IPs from input.")
            return
        user = self.var_user.get().strip()
        pwd = self.var_pass.get()
        if not user:
            self.log("Error: Username is required.")
            return
        ctrl = self.var_ctrl.get().strip() or None
        self.log(f"\nBatch adoption: {len(targets)} target(s) parsed")
        task = BatchAdoptionTask(
            targets=targets, username=user, password=pwd,
            controller_url=ctrl, port=self._get_port(),
            dry_run=self.var_dry.get(),
            ssh_options=self._get_ssh_options(), log=self.log,
        )
        self.current_task = task
        task.start()

    def _on_pause(self):
        if self.current_task is None:
            self.log("No active task to pause/resume.")
            return
        if hasattr(self.current_task, "_pause_event") and self.current_task._pause_event.is_set():
            self.current_task.resume()
            self.btn_pause.configure(text="Pause")
        else:
            self.current_task.pause()
            self.btn_pause.configure(text="Resume")

    def _on_stop(self):
        if self.current_task is None:
            self.log("No active task to stop.")
            return
        self.current_task.stop()
        self.current_task = None
        self.btn_pause.configure(text="Pause")

    def _on_test_ssh(self):
        def worker():
            try:
                ssh = self._make_ssh()
                for cmd in ["echo connected", "true"]:
                    ok, out, err = ssh.run(cmd)
                    if ok:
                        self.log("SSH test succeeded.")
                        return
                self.log("SSH test failed.")
            except Exception as e:
                self.log(f"SSH test error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _on_quick_cmd(self):
        cmd = self.var_quick_cmd.get().strip()
        if not cmd:
            self.log("Enter a command to run.")
            return
        def worker():
            try:
                ssh = self._make_ssh()
                ssh.run_visible(cmd)
            except Exception as e:
                self.log(f"Error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _on_reset_sys(self):
        if not self._confirm_reset():
            return
        try:
            ssh = self._make_ssh()
        except Exception as e:
            self.log(f"Error: {e}")
            return
        self.log("Factory reset (syswrapper) ...")
        task = ResetTask(ssh, which="syswrapper", log=self.log)
        self.current_task = task
        task.start()

    def _on_reset_set(self):
        if not self._confirm_reset():
            return
        try:
            ssh = self._make_ssh()
        except Exception as e:
            self.log(f"Error: {e}")
            return
        self.log("Factory reset (set-default) ...")
        task = ResetTask(ssh, which="set-default", log=self.log)
        self.current_task = task
        task.start()

    def _confirm_reset(self) -> bool:
        target = self.var_ip.get().strip() or "(no IP entered)"
        return messagebox.askyesno(
            "Factory reset",
            f"Factory-reset {target}?\n\nThis erases its configuration and "
            "it will need to be adopted again.",
            icon="warning",
        )

    # ── Profile integration ──────────────────────────────────

    def load_from_profile(self, profile):
        self.var_ctrl.set(profile.controller_url or "")
        self.var_user.set(profile.ssh_username or "ubnt")
        self.var_pass.set(profile.ssh_password or "")
        self.var_port.set(str(profile.ssh_port or DEFAULT_SSH_PORT))
        self.var_accept_key.set(profile.accept_host_key)
        self.var_try_kbd.set(profile.try_keyboard_interactive)
        self.var_use_pkey.set(profile.use_pkey)
        self.var_pkey_path.set(profile.pkey_path or "")
        self.var_pkey_pw.set(profile.pkey_passphrase or "")

    def get_profile_fields(self) -> dict:
        return {
            "controller_url": self.var_ctrl.get().strip(),
            "ssh_username": self.var_user.get().strip(),
            "ssh_password": self.var_pass.get(),
            "ssh_port": self._get_port(),
            "accept_host_key": self.var_accept_key.get(),
            "try_keyboard_interactive": self.var_try_kbd.get(),
            "use_pkey": self.var_use_pkey.get(),
            "pkey_path": self.var_pkey_path.get().strip(),
            "pkey_passphrase": self.var_pkey_pw.get(),
        }
