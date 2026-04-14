import threading
from typing import Optional

import customtkinter as ctk

from ..core.ssh_manager import SSHManager
from ..core.tasks import AdoptionTask, BatchAdoptionTask, ResetTask
from ..utils import DEFAULT_SSH_PORT, SSHOptions, parse_ip_targets, LogFn

# Shared palette
_CARD = "#2a2a3e"
_ACCENT = "#0f3460"
_GREEN = "#00b894"
_GREEN_HOVER = "#00a381"
_RED = "#e94560"
_RED_HOVER = "#c73e54"
_DIM = "#8a8a9a"
_LABEL_FONT = ("Segoe UI", 12)
_HEADING_FONT = ("Segoe UI", 13, "bold")
_ENTRY_W = 260


def _section(parent, title: str) -> ctk.CTkFrame:
    """Create a styled section card with a heading."""
    card = ctk.CTkFrame(parent, fg_color=_CARD, corner_radius=8)
    card.pack(fill="x", padx=4, pady=(0, 8))
    ctk.CTkLabel(
        card, text=title, font=_HEADING_FONT,
        text_color="#ffffff", anchor="w",
    ).pack(fill="x", padx=14, pady=(10, 2))
    sep = ctk.CTkFrame(card, height=1, fg_color="#3a3a4e")
    sep.pack(fill="x", padx=14, pady=(0, 8))
    return card


class SSHTab(ctk.CTkFrame):
    """SSH adoption tab -- single device and batch mode."""

    def __init__(self, parent, log_fn: LogFn, on_find_devices=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.log = log_fn
        self.on_find_devices = on_find_devices  # callback to switch to Discovery tab
        self.current_task = None
        self._build_ui()

    def _build_ui(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # ── Mode toggle ──────────────────────────────────────
        mode_card = _section(scroll, "Mode")
        mode_row = ctk.CTkFrame(mode_card, fg_color="transparent")
        mode_row.pack(fill="x", padx=14, pady=(0, 10))

        self.mode_var = ctk.StringVar(value="single")
        ctk.CTkRadioButton(
            mode_row, text="Single Device", variable=self.mode_var,
            value="single", command=self._on_mode_change,
            font=_LABEL_FONT, radiobutton_width=18, radiobutton_height=18,
        ).pack(side="left", padx=(0, 24))
        ctk.CTkRadioButton(
            mode_row, text="Batch", variable=self.mode_var,
            value="batch", command=self._on_mode_change,
            font=_LABEL_FONT, radiobutton_width=18, radiobutton_height=18,
        ).pack(side="left")

        # ── Connection ───────────────────────────────────────
        conn_card = _section(scroll, "Connection")
        grid = ctk.CTkFrame(conn_card, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 10))
        grid.columnconfigure(1, weight=1)

        r = 0
        # Single IP
        self.lbl_ip = ctk.CTkLabel(grid, text="Device IP", font=_LABEL_FONT, anchor="e")
        self.lbl_ip.grid(row=r, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_ip = ctk.StringVar()
        self.ent_ip = ctk.CTkEntry(grid, textvariable=self.var_ip, width=_ENTRY_W, height=32)
        self.ent_ip.grid(row=r, column=1, sticky="w", pady=4)

        # Quick link to the Discovery tab so you don't have to leave Connection
        self.btn_find = ctk.CTkButton(
            grid, text="Find on network", command=self._on_find_devices,
            width=130, height=32, font=("Segoe UI", 11),
            fg_color="transparent", hover_color="#3a3a4e",
            border_width=1, border_color="#4a4a5e",
        )
        self.btn_find.grid(row=r, column=2, sticky="w", padx=(10, 0), pady=4)

        # Batch targets (hidden by default)
        self.lbl_batch = ctk.CTkLabel(grid, text="Targets", font=_LABEL_FONT, anchor="e")
        self.var_batch = ctk.StringVar()
        self.ent_batch = ctk.CTkEntry(
            grid, textvariable=self.var_batch, width=420, height=32,
            placeholder_text="IPs, range (1.1.1.1-50), or CIDR (1.1.1.0/24)",
        )
        self.lbl_batch_hint = ctk.CTkLabel(
            grid, text="Comma/newline separated, range, or CIDR",
            font=("Segoe UI", 11), text_color=_DIM,
        )

        r = 3
        ctk.CTkLabel(grid, text="Username", font=_LABEL_FONT, anchor="e").grid(
            row=r, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_user = ctk.StringVar(value="ubnt")
        self.ent_user = ctk.CTkEntry(grid, textvariable=self.var_user, width=_ENTRY_W, height=32)
        self.ent_user.grid(row=r, column=1, sticky="w", pady=4)

        r = 4
        ctk.CTkLabel(grid, text="Password", font=_LABEL_FONT, anchor="e").grid(
            row=r, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_pass = ctk.StringVar()
        self.ent_pass = ctk.CTkEntry(grid, textvariable=self.var_pass, show="*", width=_ENTRY_W, height=32)
        self.ent_pass.grid(row=r, column=1, sticky="w", pady=4)

        # Default credentials toggle: auto-fill + lock user/pass to ubnt/ubnt
        self.var_default_creds = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            grid, text="Use default ubnt / ubnt (factory-fresh devices)",
            variable=self.var_default_creds, command=self._on_toggle_default_creds,
            font=("Segoe UI", 11), checkbox_width=18, checkbox_height=18,
        ).grid(row=r, column=2, sticky="w", padx=(16, 0), pady=4)

        r = 5
        ctk.CTkLabel(grid, text="Controller URL", font=_LABEL_FONT, anchor="e").grid(
            row=r, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_ctrl = ctk.StringVar()
        ctk.CTkEntry(
            grid, textvariable=self.var_ctrl, width=340, height=32,
            placeholder_text="http://192.168.1.1:8080",
        ).grid(row=r, column=1, sticky="w", pady=4)

        r = 6
        ctk.CTkLabel(grid, text="SSH Port", font=_LABEL_FONT, anchor="e").grid(
            row=r, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_port = ctk.StringVar(value=str(DEFAULT_SSH_PORT))
        ctk.CTkEntry(grid, textvariable=self.var_port, width=80, height=32).grid(
            row=r, column=1, sticky="w", pady=4)

        r = 7
        self.var_dry = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            grid, text="Dry run (don't execute)", variable=self.var_dry,
            font=_LABEL_FONT, checkbox_width=20, checkbox_height=20,
        ).grid(row=r, column=1, sticky="w", pady=4)

        # ── SSH Options ──────────────────────────────────────
        opts_card = _section(scroll, "SSH Options")
        opts = ctk.CTkFrame(opts_card, fg_color="transparent")
        opts.pack(fill="x", padx=14, pady=(0, 10))

        row1 = ctk.CTkFrame(opts, fg_color="transparent")
        row1.pack(fill="x", pady=2)
        self.var_accept_key = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            row1, text="Auto-accept host keys", variable=self.var_accept_key,
            font=_LABEL_FONT, checkbox_width=20, checkbox_height=20,
        ).pack(side="left", padx=(0, 30))
        self.var_try_kbd = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            row1, text="Try keyboard-interactive auth", variable=self.var_try_kbd,
            font=_LABEL_FONT, checkbox_width=20, checkbox_height=20,
        ).pack(side="left")

        row2 = ctk.CTkFrame(opts, fg_color="transparent")
        row2.pack(fill="x", pady=(6, 2))
        self.var_use_pkey = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            row2, text="Use SSH private key", variable=self.var_use_pkey,
            font=_LABEL_FONT, checkbox_width=20, checkbox_height=20,
        ).pack(side="left")

        key_row = ctk.CTkFrame(opts, fg_color="transparent")
        key_row.pack(fill="x", pady=2)
        ctk.CTkLabel(key_row, text="Key file", font=_LABEL_FONT).pack(side="left", padx=(20, 10))
        self.var_pkey_path = ctk.StringVar()
        ctk.CTkEntry(key_row, textvariable=self.var_pkey_path, width=280, height=32).pack(side="left")
        ctk.CTkLabel(key_row, text="Passphrase", font=_LABEL_FONT).pack(side="left", padx=(20, 10))
        self.var_pkey_pw = ctk.StringVar()
        ctk.CTkEntry(key_row, textvariable=self.var_pkey_pw, show="*", width=200, height=32).pack(side="left")

        # ── Actions ──────────────────────────────────────────
        actions_card = _section(scroll, "Actions")
        btn_row = ctk.CTkFrame(actions_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 10))

        self.btn_detect = ctk.CTkButton(
            btn_row, text="Detect Model", command=self._on_detect,
            width=130, height=34, font=_LABEL_FONT,
            fg_color=_ACCENT, hover_color="#1a4a70",
        )
        self.btn_detect.pack(side="left", padx=(0, 8))

        self.btn_adopt = ctk.CTkButton(
            btn_row, text="Run Adoption", command=self._on_adopt,
            width=140, height=34, font=("Segoe UI", 12, "bold"),
            fg_color=_GREEN, hover_color=_GREEN_HOVER, text_color="#1a1a2e",
        )
        self.btn_adopt.pack(side="left", padx=(0, 8))

        self.btn_pause = ctk.CTkButton(
            btn_row, text="Pause", command=self._on_pause,
            width=80, height=34, font=_LABEL_FONT,
            fg_color="transparent", hover_color="#3a3a4e",
            border_width=1, border_color="#4a4a5e",
        )
        self.btn_pause.pack(side="left", padx=(0, 8))

        self.btn_stop = ctk.CTkButton(
            btn_row, text="Stop", command=self._on_stop,
            width=80, height=34, font=_LABEL_FONT,
            fg_color=_RED, hover_color=_RED_HOVER,
        )
        self.btn_stop.pack(side="left")

        # ── Quick command ────────────────────────────────────
        quick_card = _section(scroll, "Quick SSH Command")
        quick_row = ctk.CTkFrame(quick_card, fg_color="transparent")
        quick_row.pack(fill="x", padx=14, pady=(0, 10))

        self.var_quick_cmd = ctk.StringVar(value="info")
        ctk.CTkEntry(
            quick_row, textvariable=self.var_quick_cmd,
            width=400, height=32,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            quick_row, text="Run", command=self._on_quick_cmd,
            width=60, height=32, font=_LABEL_FONT,
            fg_color=_ACCENT, hover_color="#1a4a70",
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            quick_row, text="Test SSH", command=self._on_test_ssh,
            width=90, height=32, font=_LABEL_FONT,
            fg_color="transparent", hover_color="#3a3a4e",
            border_width=1, border_color="#4a4a5e",
        ).pack(side="left")

        # ── Factory reset ────────────────────────────────────
        reset_card = _section(scroll, "Factory Reset")
        reset_row = ctk.CTkFrame(reset_card, fg_color="transparent")
        reset_row.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkButton(
            reset_row, text="syswrapper.sh restore-default",
            command=self._on_reset_sys,
            width=250, height=34, font=_LABEL_FONT,
            fg_color=_RED, hover_color=_RED_HOVER,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            reset_row, text="set-default",
            command=self._on_reset_set,
            width=120, height=34, font=_LABEL_FONT,
            fg_color=_RED, hover_color=_RED_HOVER,
        ).pack(side="left")

        # Initial mode state
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
        if is_batch:
            self.lbl_ip.grid_remove()
            self.ent_ip.grid_remove()
            # In batch mode the user already has IPs (often from Discovery),
            # so the per-device "Find on network" shortcut is just clutter.
            self.btn_find.grid_remove()
            self.lbl_batch.grid(row=0, column=0, sticky="ne", padx=(0, 10), pady=4)
            self.ent_batch.grid(row=0, column=1, columnspan=2, sticky="w", pady=4)
            self.lbl_batch_hint.grid(row=1, column=1, columnspan=2, sticky="w")
            self.btn_adopt.configure(text="Run Batch Adoption")
        else:
            self.lbl_batch.grid_remove()
            self.ent_batch.grid_remove()
            self.lbl_batch_hint.grid_remove()
            self.lbl_ip.grid(row=0, column=0, sticky="e", padx=(0, 10), pady=4)
            self.ent_ip.grid(row=0, column=1, sticky="w", pady=4)
            self.btn_find.grid(row=0, column=2, sticky="w", padx=(10, 0), pady=4)
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
        try:
            ssh = self._make_ssh()
        except Exception as e:
            self.log(f"Error: {e}")
            return
        self.log("Factory reset (set-default) ...")
        task = ResetTask(ssh, which="set-default", log=self.log)
        self.current_task = task
        task.start()

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
