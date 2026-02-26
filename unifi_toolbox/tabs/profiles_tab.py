import customtkinter as ctk

from ..core.profiles import ProfileManager, Profile
from ..utils import LogFn, DEFAULT_SSH_PORT


class ProfilesTab(ctk.CTkFrame):
    """Profiles management tab — save/load/delete connection profiles."""

    def __init__(self, parent, log_fn: LogFn, get_fields_fn=None, load_fields_fn=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.log = log_fn
        self.get_fields_fn = get_fields_fn  # Returns merged dict of current fields from all tabs
        self.load_fields_fn = load_fields_fn  # Loads a Profile into all tabs
        self.manager = ProfileManager()
        self._build_ui()
        self._refresh_list()

        # Auto-load last used profile
        if self.manager.get_auto_load():
            last = self.manager.get_last_used()
            if last:
                self.after(500, lambda: self._load_profile(last))

    def _build_ui(self):
        # --- Profile list ---
        list_frame = ctk.CTkFrame(self)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(10, 5))
        ctk.CTkLabel(list_frame, text="Saved Profiles", font=("", 14, "bold")).pack(
            anchor="w", padx=10, pady=(5, 0)
        )

        self.profiles_scroll = ctk.CTkScrollableFrame(list_frame, height=200)
        self.profiles_scroll.pack(fill="both", expand=True, padx=10, pady=5)

        # --- New/save controls ---
        save_frame = ctk.CTkFrame(self)
        save_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(save_frame, text="Save Current Settings", font=("", 14, "bold")).pack(
            anchor="w", padx=10, pady=(5, 0)
        )

        row = ctk.CTkFrame(save_frame)
        row.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(row, text="Profile Name:").pack(side="left", padx=5)
        self.var_name = ctk.StringVar()
        ctk.CTkEntry(row, textvariable=self.var_name, width=200).pack(side="left", padx=5)
        ctk.CTkButton(
            row, text="Save", command=self._on_save, width=80,
            fg_color="#2b7a0b", hover_color="#1e5a08"
        ).pack(side="left", padx=5)

        # --- Settings ---
        settings_frame = ctk.CTkFrame(self)
        settings_frame.pack(fill="x", padx=10, pady=(5, 10))

        self.var_auto_load = ctk.BooleanVar(value=self.manager.get_auto_load())
        ctk.CTkCheckBox(
            settings_frame, text="Auto-load last used profile on startup",
            variable=self.var_auto_load, command=self._on_auto_load_toggle
        ).pack(anchor="w", padx=15, pady=10)

    def _refresh_list(self):
        for widget in self.profiles_scroll.winfo_children():
            widget.destroy()

        profiles = self.manager.list_profiles()
        if not profiles:
            ctk.CTkLabel(
                self.profiles_scroll, text="No saved profiles yet.",
                text_color="gray"
            ).pack(pady=10)
            return

        for name in profiles:
            profile = self.manager.get(name)
            row = ctk.CTkFrame(self.profiles_scroll)
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(row, text=name, font=("", 13, "bold"), width=180).pack(side="left", padx=10)

            info_parts = []
            if profile.controller_url:
                info_parts.append(f"ctrl={profile.controller_url}")
            if profile.ssh_username:
                info_parts.append(f"user={profile.ssh_username}")
            if profile.console_ip:
                info_parts.append(f"console={profile.console_ip}")
            ctk.CTkLabel(row, text=" | ".join(info_parts) if info_parts else "(empty)",
                         text_color="gray", font=("", 11)).pack(side="left", padx=5)

            ctk.CTkButton(
                row, text="Load", width=60,
                command=lambda n=name: self._load_profile(n)
            ).pack(side="right", padx=5)
            ctk.CTkButton(
                row, text="Delete", width=60,
                fg_color="#a31515", hover_color="#7a1010",
                command=lambda n=name: self._delete_profile(n)
            ).pack(side="right", padx=2)

    def _on_save(self):
        name = self.var_name.get().strip()
        if not name:
            self.log("Enter a profile name.")
            return

        fields = {}
        if self.get_fields_fn:
            fields = self.get_fields_fn()

        profile = Profile(
            name=name,
            controller_url=fields.get("controller_url", ""),
            ssh_username=fields.get("ssh_username", "ubnt"),
            ssh_password=fields.get("ssh_password", ""),
            ssh_port=fields.get("ssh_port", DEFAULT_SSH_PORT),
            console_ip=fields.get("console_ip", ""),
            console_username=fields.get("console_username", ""),
            console_password=fields.get("console_password", ""),
            verify_ssl=fields.get("verify_ssl", False),
            accept_host_key=fields.get("accept_host_key", True),
            try_keyboard_interactive=fields.get("try_keyboard_interactive", True),
            use_pkey=fields.get("use_pkey", False),
            pkey_path=fields.get("pkey_path", ""),
            pkey_passphrase=fields.get("pkey_passphrase", ""),
        )
        self.manager.save(profile)
        self.manager.set_last_used(name)
        self.log(f"Profile '{name}' saved.")
        self._refresh_list()

    def _load_profile(self, name: str):
        profile = self.manager.get(name)
        if not profile:
            self.log(f"Profile '{name}' not found.")
            return
        self.manager.set_last_used(name)
        if self.load_fields_fn:
            self.load_fields_fn(profile)
        self.log(f"Profile '{name}' loaded.")

    def _delete_profile(self, name: str):
        if self.manager.delete(name):
            self.log(f"Profile '{name}' deleted.")
            self._refresh_list()

    def _on_auto_load_toggle(self):
        self.manager.set_auto_load(self.var_auto_load.get())
