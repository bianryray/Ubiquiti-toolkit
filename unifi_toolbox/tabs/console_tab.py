import threading
import webbrowser

import customtkinter as ctk

from ..core.api_client import UniFiAPI
from ..utils import LogFn

# Shared palette
_CARD = "#2a2a3e"
_ACCENT = "#0f3460"
_GREEN = "#00b894"
_GREEN_HOVER = "#00a381"
_DIM = "#8a8a9a"
_LABEL_FONT = ("Segoe UI", 12)
_HEADING_FONT = ("Segoe UI", 13, "bold")
_ENTRY_W = 260


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


class ConsoleTab(ctk.CTkFrame):
    """Console/API tab for managing UniFi controllers."""

    def __init__(self, parent, log_fn: LogFn, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.log = log_fn
        self._build_ui()

    def _build_ui(self):
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # ── Console Connection ───────────────────────────────
        conn_card = _section(scroll, "Console Connection")
        grid = ctk.CTkFrame(conn_card, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 10))
        grid.columnconfigure(1, weight=1)

        ctk.CTkLabel(grid, text="Console IP", font=_LABEL_FONT, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_ip = ctk.StringVar()
        ctk.CTkEntry(grid, textvariable=self.var_ip, width=_ENTRY_W, height=32).grid(
            row=0, column=1, sticky="w", pady=4)

        ctk.CTkLabel(grid, text="Admin Username", font=_LABEL_FONT, anchor="e").grid(
            row=1, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_user = ctk.StringVar()
        ctk.CTkEntry(grid, textvariable=self.var_user, width=_ENTRY_W, height=32).grid(
            row=1, column=1, sticky="w", pady=4)

        ctk.CTkLabel(grid, text="Admin Password", font=_LABEL_FONT, anchor="e").grid(
            row=2, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_pass = ctk.StringVar()
        ctk.CTkEntry(grid, textvariable=self.var_pass, show="*", width=_ENTRY_W, height=32).grid(
            row=2, column=1, sticky="w", pady=4)

        self.var_ssl = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            grid, text="Verify SSL (uncheck for self-signed)", variable=self.var_ssl,
            font=_LABEL_FONT, checkbox_width=20, checkbox_height=20,
        ).grid(row=3, column=1, sticky="w", pady=4)

        # ── Actions ──────────────────────────────────────────
        actions_card = _section(scroll, "Actions")
        btn_row = ctk.CTkFrame(actions_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkButton(
            btn_row, text="Open Web Setup", command=self._open_web,
            width=140, height=34, font=_LABEL_FONT,
            fg_color=_ACCENT, hover_color="#1a4a70",
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="List Sites", command=self._list_sites,
            width=100, height=34, font=_LABEL_FONT,
            fg_color="transparent", hover_color="#3a3a4e",
            border_width=1, border_color="#4a4a5e",
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="Create Site", command=self._create_site,
            width=110, height=34, font=_LABEL_FONT,
            fg_color="transparent", hover_color="#3a3a4e",
            border_width=1, border_color="#4a4a5e",
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="Adopt by MAC", command=self._adopt_mac,
            width=130, height=34, font=("Segoe UI", 12, "bold"),
            fg_color=_GREEN, hover_color=_GREEN_HOVER, text_color="#1a1a2e",
        ).pack(side="left")

        # ── Site / MAC inputs ────────────────────────────────
        detail_card = _section(scroll, "Site & Device")
        detail_grid = ctk.CTkFrame(detail_card, fg_color="transparent")
        detail_grid.pack(fill="x", padx=14, pady=(0, 6))
        detail_grid.columnconfigure(1, weight=1)

        ctk.CTkLabel(detail_grid, text="Site Name", font=_LABEL_FONT, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_site = ctk.StringVar(value="default")
        ctk.CTkEntry(detail_grid, textvariable=self.var_site, width=_ENTRY_W, height=32).grid(
            row=0, column=1, sticky="w", pady=4)

        ctk.CTkLabel(detail_grid, text="Device MAC", font=_LABEL_FONT, anchor="e").grid(
            row=1, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_mac = ctk.StringVar()
        ctk.CTkEntry(
            detail_grid, textvariable=self.var_mac, width=_ENTRY_W, height=32,
            placeholder_text="aa:bb:cc:dd:ee:ff",
        ).grid(row=1, column=1, sticky="w", pady=4)

        ctk.CTkLabel(
            detail_card,
            text="Hint: UXG -> adopt to existing site. UDM/UDR/UDM-Pro -> create its own site.",
            font=("Segoe UI", 11), text_color=_DIM,
        ).pack(anchor="w", padx=14, pady=(0, 10))

    # ── Logic ────────────────────────────────────────────────

    def _get_api(self) -> UniFiAPI:
        ip = self.var_ip.get().strip()
        user = self.var_user.get().strip()
        pwd = self.var_pass.get()
        if not ip:
            raise ValueError("Console IP is required.")
        if not user or not pwd:
            raise ValueError("Admin username and password are required.")
        api = UniFiAPI(
            f"https://{ip}",
            verify_ssl=self.var_ssl.get(),
            log=self.log,
        )
        api.login(user, pwd)
        return api

    def _open_web(self):
        ip = self.var_ip.get().strip()
        if not ip:
            self.log("Enter the console IP.")
            return
        url = f"https://{ip}/"
        self.log(f"Opening {url} ...")
        try:
            webbrowser.open(url)
        except Exception as e:
            self.log(f"Browser error: {e}")

    def _list_sites(self):
        def worker():
            try:
                api = self._get_api()
                sites = api.list_sites()
                self.log("Sites:")
                for s in sites:
                    desc = f" - {s['desc']}" if s.get("desc") else ""
                    self.log(f"  {s['name']} (id={s['id']}){desc}")
            except Exception as e:
                self.log(f"List sites error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _create_site(self):
        site = self.var_site.get().strip()
        if not site:
            self.log("Enter a site name.")
            return
        def worker():
            try:
                api = self._get_api()
                api.create_site(site)
                self.log(f"Site '{site}' creation requested.")
            except Exception as e:
                self.log(f"Create site error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _adopt_mac(self):
        site = self.var_site.get().strip()
        mac = self.var_mac.get().strip()
        if not site or not mac:
            self.log("Both Site Name and Device MAC are required.")
            return
        def worker():
            try:
                api = self._get_api()
                api.adopt_device(site, mac)
                self.log(f"Adopt command sent for {mac} into site '{site}'.")
            except Exception as e:
                self.log(f"Adopt error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    # ── Profile integration ──────────────────────────────────

    def load_from_profile(self, profile):
        self.var_ip.set(profile.console_ip or "")
        self.var_user.set(profile.console_username or "")
        self.var_pass.set(profile.console_password or "")
        self.var_ssl.set(profile.verify_ssl)

    def get_profile_fields(self) -> dict:
        return {
            "console_ip": self.var_ip.get().strip(),
            "console_username": self.var_user.get().strip(),
            "console_password": self.var_pass.get(),
            "verify_ssl": self.var_ssl.get(),
        }
