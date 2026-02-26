import customtkinter as ctk

from ..core.profiles import ProfileManager, Profile
from ..utils import LogFn, DEFAULT_SSH_PORT

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


def _section(parent, title: str) -> ctk.CTkFrame:
    card = ctk.CTkFrame(parent, fg_color=_CARD, corner_radius=8)
    card.pack(fill="x", padx=4, pady=(0, 8))
    ctk.CTkLabel(
        card, text=title, font=_HEADING_FONT,
        text_color="#ffffff", anchor="w",
    ).pack(fill="x", padx=14, pady=(10, 2))
    sep = ctk.CTkFrame(card, height=1, fg_color="#3a3a4e")
    sep.pack(fill="x", padx=14, pady=(0, 8))
    return card


class ProfilesTab(ctk.CTkFrame):
    """Profiles management tab -- save/load/delete connection profiles."""

    def __init__(self, parent, log_fn: LogFn, get_fields_fn=None, load_fields_fn=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.log = log_fn
        self.get_fields_fn = get_fields_fn
        self.load_fields_fn = load_fields_fn
        self.manager = ProfileManager()
        self._build_ui()
        self._refresh_list()

        if self.manager.get_auto_load():
            last = self.manager.get_last_used()
            if last:
                self.after(500, lambda: self._load_profile(last))

    def _build_ui(self):
        # ── Profile list ─────────────────────────────────────
        list_card = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=8)
        list_card.pack(fill="both", expand=True, padx=4, pady=(0, 8))

        list_header = ctk.CTkFrame(list_card, fg_color="transparent")
        list_header.pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            list_header, text="Saved Profiles", font=_HEADING_FONT,
            text_color="#ffffff",
        ).pack(side="left")

        sep = ctk.CTkFrame(list_card, height=1, fg_color="#3a3a4e")
        sep.pack(fill="x", padx=14, pady=(0, 8))

        self.profiles_scroll = ctk.CTkScrollableFrame(
            list_card, fg_color="transparent",
        )
        self.profiles_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        # ── Save controls ────────────────────────────────────
        save_card = _section(self, "Save Current Settings")
        save_row = ctk.CTkFrame(save_card, fg_color="transparent")
        save_row.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(save_row, text="Profile Name", font=_LABEL_FONT).pack(
            side="left", padx=(0, 8))
        self.var_name = ctk.StringVar()
        ctk.CTkEntry(save_row, textvariable=self.var_name, width=220, height=32).pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(
            save_row, text="Save", command=self._on_save,
            width=80, height=32, font=("Segoe UI", 12, "bold"),
            fg_color=_GREEN, hover_color=_GREEN_HOVER, text_color="#1a1a2e",
        ).pack(side="left")

        # ── Settings ─────────────────────────────────────────
        settings_card = _section(self, "Settings")
        settings_inner = ctk.CTkFrame(settings_card, fg_color="transparent")
        settings_inner.pack(fill="x", padx=14, pady=(0, 10))

        self.var_auto_load = ctk.BooleanVar(value=self.manager.get_auto_load())
        ctk.CTkCheckBox(
            settings_inner, text="Auto-load last used profile on startup",
            variable=self.var_auto_load, command=self._on_auto_load_toggle,
            font=_LABEL_FONT, checkbox_width=20, checkbox_height=20,
        ).pack(anchor="w")

    def _refresh_list(self):
        for widget in self.profiles_scroll.winfo_children():
            widget.destroy()

        profiles = self.manager.list_profiles()
        if not profiles:
            ctk.CTkLabel(
                self.profiles_scroll, text="No saved profiles yet.",
                text_color=_DIM, font=_LABEL_FONT,
            ).pack(pady=16)
            return

        for idx, name in enumerate(profiles):
            profile = self.manager.get(name)
            bg = "#282840" if idx % 2 == 0 else "transparent"
            row = ctk.CTkFrame(self.profiles_scroll, fg_color=bg, corner_radius=6)
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(
                row, text=name, font=("Segoe UI", 13, "bold"),
                width=180, anchor="w",
            ).pack(side="left", padx=(10, 8), pady=8)

            info_parts = []
            if profile.controller_url:
                info_parts.append(f"ctrl={profile.controller_url}")
            if profile.ssh_username:
                info_parts.append(f"user={profile.ssh_username}")
            if profile.console_ip:
                info_parts.append(f"console={profile.console_ip}")
            ctk.CTkLabel(
                row,
                text=" | ".join(info_parts) if info_parts else "(empty)",
                text_color=_DIM, font=("Segoe UI", 11), anchor="w",
            ).pack(side="left", padx=4, pady=8, fill="x", expand=True)

            ctk.CTkButton(
                row, text="Delete", width=70, height=28,
                fg_color=_RED, hover_color=_RED_HOVER,
                font=("Segoe UI", 11),
                command=lambda n=name: self._delete_profile(n),
            ).pack(side="right", padx=(4, 10), pady=8)

            ctk.CTkButton(
                row, text="Load", width=70, height=28,
                fg_color=_ACCENT, hover_color="#1a4a70",
                font=("Segoe UI", 11),
                command=lambda n=name: self._load_profile(n),
            ).pack(side="right", pady=8)

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
