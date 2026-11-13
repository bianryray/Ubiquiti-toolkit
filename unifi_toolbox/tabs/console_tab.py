import threading
import webbrowser

import customtkinter as ctk

from ..core.api_client import UniFiAPI
from ..utils import LogFn
from .. import theme as T


class ConsoleTab(ctk.CTkFrame):
    """Console/API tab for managing UniFi controllers."""

    def __init__(self, parent, log_fn: LogFn, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.log = log_fn
        self._build_ui()

    def _build_ui(self):
        page = T.scroll_page(self)
        T.page_header(
            page, "Console / API",
            "Sign in to a UniFi OS console to list or create sites and adopt devices by MAC.",
        )

        # ── Console Connection ───────────────────────────────
        conn = T.card(page, "Console", "UDM, UDR, UDM-Pro, Cloud Key or self-hosted controller")
        g = ctk.CTkFrame(conn, fg_color="transparent")
        g.pack(fill="x")
        self.var_ip = ctk.StringVar()
        self.var_user = ctk.StringVar()
        self.var_pass = ctk.StringVar()
        T.field(g, 0, 0, "CONSOLE IP", lambda c: T.entry(c, self.var_ip, width=220))
        T.field(g, 0, 1, "ADMIN USERNAME", lambda c: T.entry(c, self.var_user, width=200))
        T.field(g, 0, 2, "ADMIN PASSWORD",
                lambda c: T.entry(c, self.var_pass, width=200, show="\u2022"))
        self.var_ssl = ctk.BooleanVar(value=False)
        bottom = T.row(conn)
        T.switch(bottom, "Verify SSL certificate (leave off for self-signed)",
                 self.var_ssl).pack(side="left")
        T.button(bottom, "Open Web UI", self._open_web, kind="secondary").pack(side="right")

        # ── Sites ────────────────────────────────────────────
        sites = T.card(page, "Sites", "Results appear in the activity log")
        sg = ctk.CTkFrame(sites, fg_color="transparent")
        sg.pack(fill="x")
        self.var_site = ctk.StringVar(value="default")
        T.field(sg, 0, 0, "SITE NAME", lambda c: T.entry(c, self.var_site, width=220))
        sr = T.row(sites)
        T.button(sr, "List Sites", self._list_sites, kind="primary").pack(side="left", padx=(0, 8))
        T.button(sr, "Create Site", self._create_site).pack(side="left")

        # ── Adopt by MAC ─────────────────────────────────────
        adopt = T.card(
            page, "Adopt by MAC",
            "UXG / UAP / USW: adopt into an existing site.  UDM / UDR / UDM-Pro run "
            "their own controller - create a site on the device itself.",
        )
        ag = ctk.CTkFrame(adopt, fg_color="transparent")
        ag.pack(fill="x")
        self.var_mac = ctk.StringVar()
        T.field(ag, 0, 0, "DEVICE MAC",
                lambda c: T.entry(c, self.var_mac, width=220, mono=True),
                hint="aa:bb:cc:dd:ee:ff  -  uses the Site Name above")
        T.button(adopt, "Adopt Device", self._adopt_mac, kind="success",
                 width=150).pack(anchor="w")

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
