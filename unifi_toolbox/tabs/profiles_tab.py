from tkinter import messagebox

import customtkinter as ctk

from ..core.profiles import ProfileManager, Profile
from ..utils import LogFn, DEFAULT_SSH_PORT
from .. import theme as T


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
        T.page_header(
            self, "Profiles",
            "Save controller, SSH and console settings so you don't retype them per site.",
        )

        # ── Save controls ────────────────────────────────────
        save = T.card(self, "Save Current Settings",
                      "Stores what's filled in on the SSH Adoption and Console tabs")
        r = T.row(save)
        self.var_name = ctk.StringVar()
        e = T.entry(r, self.var_name, width=260)
        e.pack(side="left", padx=(0, 8))
        e.bind("<Return>", lambda ev: self._on_save())
        T.button(r, "Save Profile", self._on_save, kind="primary").pack(side="left")
        self.var_auto_load = ctk.BooleanVar(value=self.manager.get_auto_load())
        T.switch(r, "Load last used profile on startup", self.var_auto_load,
                 self._on_auto_load_toggle).pack(side="right")

        # ── Profile list ─────────────────────────────────────
        lst = T.card(self, "Saved Profiles", expand=True)
        self.profiles_scroll = ctk.CTkScrollableFrame(
            lst, fg_color="transparent",
            scrollbar_button_color=T.BORDER_INPUT,
        )
        self.profiles_scroll.pack(fill="both", expand=True)

    def _refresh_list(self):
        for widget in self.profiles_scroll.winfo_children():
            widget.destroy()

        profiles = self.manager.list_profiles()
        if not profiles:
            T.label(self.profiles_scroll,
                    "No saved profiles yet - fill in your settings and save one above.",
                    dim=True).pack(pady=24)
            return

        last = self.manager.get_last_used()
        for name in profiles:
            profile = self.manager.get(name)
            row = ctk.CTkFrame(self.profiles_scroll, fg_color=T.BG_CARD_ALT,
                               corner_radius=T.RADIUS_SM, border_width=1,
                               border_color=T.BORDER)
            row.pack(fill="x", pady=4, padx=(0, 6))

            text = ctk.CTkFrame(row, fg_color="transparent")
            text.pack(side="left", fill="x", expand=True, padx=14, pady=10)
            title = T.label(text, name, bold=True)
            title.pack(anchor="w")
            info_parts = []
            if profile.controller_url:
                info_parts.append(f"Controller {profile.controller_url}")
            if profile.ssh_username:
                info_parts.append(f"SSH {profile.ssh_username}")
            if profile.console_ip:
                info_parts.append(f"Console {profile.console_ip}")
            sub = "   \u00b7   ".join(info_parts) if info_parts else "Empty profile"
            if name == last:
                sub += "   \u00b7   last used"
            T.label(text, sub, dim=True, small=True).pack(anchor="w")

            T.button(row, "Delete", lambda n=name: self._delete_profile(n),
                     kind="ghost", width=70, text_color=T.DANGER).pack(
                side="right", padx=(4, 12), pady=10)
            T.button(row, "Load", lambda n=name: self._load_profile(n),
                     kind="primary", width=70).pack(side="right", pady=10)

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
        self._refresh_list()

    def _delete_profile(self, name: str):
        if not messagebox.askyesno("Delete profile", f"Delete profile '{name}'?"):
            return
        if self.manager.delete(name):
            self.log(f"Profile '{name}' deleted.")
            self._refresh_list()

    def _on_auto_load_toggle(self):
        self.manager.set_auto_load(self.var_auto_load.get())
