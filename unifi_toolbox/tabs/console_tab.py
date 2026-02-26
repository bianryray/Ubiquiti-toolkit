import threading
import webbrowser

import customtkinter as ctk

from ..core.api_client import UniFiAPI
from ..utils import LogFn


class ConsoleTab(ctk.CTkFrame):
    """Console/API tab for managing UniFi controllers."""

    def __init__(self, parent, log_fn: LogFn, **kwargs):
        super().__init__(parent, **kwargs)
        self.log = log_fn
        self._build_ui()

    def _build_ui(self):
        # --- Connection ---
        conn_frame = ctk.CTkFrame(self)
        conn_frame.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkLabel(conn_frame, text="Console Connection", font=("", 14, "bold")).pack(
            anchor="w", padx=10, pady=(5, 0)
        )

        grid = ctk.CTkFrame(conn_frame)
        grid.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(grid, text="Console IP:").grid(row=0, column=0, sticky="e", padx=5, pady=3)
        self.var_ip = ctk.StringVar()
        ctk.CTkEntry(grid, textvariable=self.var_ip, width=220).grid(row=0, column=1, sticky="w", padx=5, pady=3)

        ctk.CTkLabel(grid, text="Admin Username:").grid(row=1, column=0, sticky="e", padx=5, pady=3)
        self.var_user = ctk.StringVar()
        ctk.CTkEntry(grid, textvariable=self.var_user, width=220).grid(row=1, column=1, sticky="w", padx=5, pady=3)

        ctk.CTkLabel(grid, text="Admin Password:").grid(row=2, column=0, sticky="e", padx=5, pady=3)
        self.var_pass = ctk.StringVar()
        ctk.CTkEntry(grid, textvariable=self.var_pass, show="*", width=220).grid(
            row=2, column=1, sticky="w", padx=5, pady=3
        )

        self.var_ssl = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(grid, text="Verify SSL (uncheck for self-signed)", variable=self.var_ssl).grid(
            row=3, column=1, sticky="w", padx=5, pady=3
        )

        # --- Actions ---
        btn_frame = ctk.CTkFrame(self)
        btn_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkButton(btn_frame, text="Open Web Setup", command=self._open_web, width=140).pack(
            side="left", padx=5
        )
        ctk.CTkButton(btn_frame, text="List Sites", command=self._list_sites, width=100).pack(
            side="left", padx=5
        )
        ctk.CTkButton(btn_frame, text="Create Site", command=self._create_site, width=110).pack(
            side="left", padx=5
        )
        ctk.CTkButton(
            btn_frame, text="Adopt by MAC", command=self._adopt_mac,
            fg_color="#2b7a0b", hover_color="#1e5a08", width=120
        ).pack(side="left", padx=5)

        # --- Site / MAC inputs ---
        detail_frame = ctk.CTkFrame(self)
        detail_frame.pack(fill="x", padx=10, pady=5)

        detail_grid = ctk.CTkFrame(detail_frame)
        detail_grid.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(detail_grid, text="Site Name:").grid(row=0, column=0, sticky="e", padx=5, pady=3)
        self.var_site = ctk.StringVar(value="default")
        ctk.CTkEntry(detail_grid, textvariable=self.var_site, width=220).grid(
            row=0, column=1, sticky="w", padx=5, pady=3
        )

        ctk.CTkLabel(detail_grid, text="Device MAC:").grid(row=1, column=0, sticky="e", padx=5, pady=3)
        self.var_mac = ctk.StringVar()
        ctk.CTkEntry(detail_grid, textvariable=self.var_mac, width=220,
                      placeholder_text="aa:bb:cc:dd:ee:ff").grid(
            row=1, column=1, sticky="w", padx=5, pady=3
        )

        ctk.CTkLabel(
            detail_frame,
            text="Hint: UXG -> adopt to existing site. UDM/UDR/UDM-Pro -> create its own site.",
            font=("", 11), text_color="gray",
        ).pack(anchor="w", padx=15, pady=(0, 5))

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

    # --- Profile integration ---

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
