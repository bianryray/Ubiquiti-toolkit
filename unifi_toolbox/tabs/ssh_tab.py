import threading
from typing import Optional

import customtkinter as ctk

from ..core.ssh_manager import SSHManager
from ..core.tasks import AdoptionTask, BatchAdoptionTask, ResetTask
from ..utils import DEFAULT_SSH_PORT, SSHOptions, parse_ip_targets, LogFn


class SSHTab(ctk.CTkFrame):
    """SSH adoption tab — single device and batch mode."""

    def __init__(self, parent, log_fn: LogFn, **kwargs):
        super().__init__(parent, **kwargs)
        self.log = log_fn
        self.current_task = None
        self._build_ui()

    def _build_ui(self):
        # Mode toggle
        self.mode_var = ctk.StringVar(value="single")
        mode_frame = ctk.CTkFrame(self)
        mode_frame.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkLabel(mode_frame, text="Mode:").pack(side="left", padx=5)
        ctk.CTkRadioButton(
            mode_frame, text="Single Device", variable=self.mode_var,
            value="single", command=self._on_mode_change
        ).pack(side="left", padx=10)
        ctk.CTkRadioButton(
            mode_frame, text="Batch", variable=self.mode_var,
            value="batch", command=self._on_mode_change
        ).pack(side="left", padx=10)

        # --- Connection frame ---
        conn_frame = ctk.CTkFrame(self)
        conn_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(conn_frame, text="Connection", font=("", 14, "bold")).pack(anchor="w", padx=10, pady=(5, 0))

        grid = ctk.CTkFrame(conn_frame)
        grid.pack(fill="x", padx=10, pady=5)

        # Single IP
        self.lbl_ip = ctk.CTkLabel(grid, text="Device IP:")
        self.lbl_ip.grid(row=0, column=0, sticky="e", padx=5, pady=3)
        self.var_ip = ctk.StringVar()
        self.ent_ip = ctk.CTkEntry(grid, textvariable=self.var_ip, width=220)
        self.ent_ip.grid(row=0, column=1, sticky="w", padx=5, pady=3)

        # Batch targets (hidden by default)
        self.lbl_batch = ctk.CTkLabel(grid, text="Targets:")
        self.var_batch = ctk.StringVar()
        self.ent_batch = ctk.CTkEntry(grid, textvariable=self.var_batch, width=400,
                                       placeholder_text="IPs, range (1.1.1.1-50), or CIDR (1.1.1.0/24)")
        self.lbl_batch_hint = ctk.CTkLabel(grid, text="Comma/newline separated, range, or CIDR",
                                            font=("", 11), text_color="gray")

        # Username
        ctk.CTkLabel(grid, text="Username:").grid(row=3, column=0, sticky="e", padx=5, pady=3)
        self.var_user = ctk.StringVar(value="ubnt")
        ctk.CTkEntry(grid, textvariable=self.var_user, width=220).grid(row=3, column=1, sticky="w", padx=5, pady=3)

        # Password
        ctk.CTkLabel(grid, text="Password:").grid(row=4, column=0, sticky="e", padx=5, pady=3)
        self.var_pass = ctk.StringVar()
        ctk.CTkEntry(grid, textvariable=self.var_pass, show="*", width=220).grid(row=4, column=1, sticky="w", padx=5, pady=3)

        # Controller URL
        ctk.CTkLabel(grid, text="Controller URL:").grid(row=5, column=0, sticky="e", padx=5, pady=3)
        self.var_ctrl = ctk.StringVar()
        ctk.CTkEntry(grid, textvariable=self.var_ctrl, width=300,
                      placeholder_text="http://192.168.1.1:8080").grid(row=5, column=1, sticky="w", padx=5, pady=3)

        # SSH Port
        ctk.CTkLabel(grid, text="SSH Port:").grid(row=6, column=0, sticky="e", padx=5, pady=3)
        self.var_port = ctk.StringVar(value=str(DEFAULT_SSH_PORT))
        ctk.CTkEntry(grid, textvariable=self.var_port, width=80).grid(row=6, column=1, sticky="w", padx=5, pady=3)

        # Dry run
        self.var_dry = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(grid, text="Dry run (don't execute)", variable=self.var_dry).grid(
            row=7, column=1, sticky="w", padx=5, pady=3
        )

        # --- SSH Options ---
        opts_frame = ctk.CTkFrame(self)
        opts_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(opts_frame, text="SSH Options", font=("", 14, "bold")).pack(anchor="w", padx=10, pady=(5, 0))

        opts_grid = ctk.CTkFrame(opts_frame)
        opts_grid.pack(fill="x", padx=10, pady=5)

        self.var_accept_key = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts_grid, text="Auto-accept host keys", variable=self.var_accept_key).grid(
            row=0, column=0, sticky="w", padx=5, pady=3
        )
        self.var_try_kbd = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opts_grid, text="Try keyboard-interactive auth", variable=self.var_try_kbd).grid(
            row=0, column=1, sticky="w", padx=15, pady=3
        )
        self.var_use_pkey = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opts_grid, text="Use SSH private key", variable=self.var_use_pkey).grid(
            row=1, column=0, sticky="w", padx=5, pady=3
        )
        ctk.CTkLabel(opts_grid, text="Key file:").grid(row=1, column=1, sticky="e", padx=5, pady=3)
        self.var_pkey_path = ctk.StringVar()
        ctk.CTkEntry(opts_grid, textvariable=self.var_pkey_path, width=250).grid(
            row=1, column=2, sticky="w", padx=5, pady=3
        )
        ctk.CTkLabel(opts_grid, text="Passphrase:").grid(row=2, column=1, sticky="e", padx=5, pady=3)
        self.var_pkey_pw = ctk.StringVar()
        ctk.CTkEntry(opts_grid, textvariable=self.var_pkey_pw, show="*", width=200).grid(
            row=2, column=2, sticky="w", padx=5, pady=3
        )

        # --- Action buttons ---
        btn_frame = ctk.CTkFrame(self)
        btn_frame.pack(fill="x", padx=10, pady=5)

        self.btn_detect = ctk.CTkButton(btn_frame, text="Detect Model", command=self._on_detect, width=130)
        self.btn_detect.pack(side="left", padx=5)
        self.btn_adopt = ctk.CTkButton(btn_frame, text="Run Adoption", command=self._on_adopt,
                                        fg_color="#2b7a0b", hover_color="#1e5a08", width=130)
        self.btn_adopt.pack(side="left", padx=5)
        self.btn_pause = ctk.CTkButton(btn_frame, text="Pause", command=self._on_pause, width=80)
        self.btn_pause.pack(side="left", padx=5)
        self.btn_stop = ctk.CTkButton(btn_frame, text="Stop", command=self._on_stop,
                                       fg_color="#a31515", hover_color="#7a1010", width=80)
        self.btn_stop.pack(side="left", padx=5)

        # --- Quick command ---
        quick_frame = ctk.CTkFrame(self)
        quick_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(quick_frame, text="Quick SSH Command", font=("", 14, "bold")).pack(anchor="w", padx=10, pady=(5, 0))

        quick_row = ctk.CTkFrame(quick_frame)
        quick_row.pack(fill="x", padx=10, pady=5)
        self.var_quick_cmd = ctk.StringVar(value="info")
        ctk.CTkEntry(quick_row, textvariable=self.var_quick_cmd, width=400).pack(side="left", padx=5)
        ctk.CTkButton(quick_row, text="Run", command=self._on_quick_cmd, width=60).pack(side="left", padx=5)
        ctk.CTkButton(quick_row, text="Test SSH", command=self._on_test_ssh, width=80).pack(side="left", padx=5)

        # --- Factory reset ---
        reset_frame = ctk.CTkFrame(self)
        reset_frame.pack(fill="x", padx=10, pady=(5, 10))
        ctk.CTkLabel(reset_frame, text="Factory Reset", font=("", 14, "bold")).pack(anchor="w", padx=10, pady=(5, 0))

        reset_row = ctk.CTkFrame(reset_frame)
        reset_row.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(reset_row, text="syswrapper.sh restore-default",
                       command=self._on_reset_sys, fg_color="#a31515", hover_color="#7a1010",
                       width=240).pack(side="left", padx=5)
        ctk.CTkButton(reset_row, text="set-default",
                       command=self._on_reset_set, fg_color="#a31515", hover_color="#7a1010",
                       width=120).pack(side="left", padx=5)

        # Initial mode state
        self._on_mode_change()

    def _on_mode_change(self):
        is_batch = self.mode_var.get() == "batch"
        if is_batch:
            self.lbl_ip.grid_remove()
            self.ent_ip.grid_remove()
            self.lbl_batch.grid(row=0, column=0, sticky="ne", padx=5, pady=3)
            self.ent_batch.grid(row=0, column=1, columnspan=2, sticky="w", padx=5, pady=3)
            self.lbl_batch_hint.grid(row=1, column=1, columnspan=2, sticky="w", padx=5)
            self.btn_adopt.configure(text="Run Batch Adoption")
        else:
            self.lbl_batch.grid_remove()
            self.ent_batch.grid_remove()
            self.lbl_batch_hint.grid_remove()
            self.lbl_ip.grid(row=0, column=0, sticky="e", padx=5, pady=3)
            self.ent_ip.grid(row=0, column=1, sticky="w", padx=5, pady=3)
            self.btn_adopt.configure(text="Run Adoption")

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
            targets=targets,
            username=user,
            password=pwd,
            controller_url=ctrl,
            port=self._get_port(),
            dry_run=self.var_dry.get(),
            ssh_options=self._get_ssh_options(),
            log=self.log,
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

    # --- Profile integration ---

    def load_from_profile(self, profile):
        """Populate fields from a Profile object."""
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
        """Return current field values for saving to a profile."""
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
