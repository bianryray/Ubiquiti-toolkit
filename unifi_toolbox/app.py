import os
import queue
import customtkinter as ctk

from .version import __version__
from .core.updater import check_for_update_async, open_download_page
from .tabs.ssh_tab import SSHTab
from .tabs.console_tab import ConsoleTab
from .tabs.discovery_tab import DiscoveryTab
from .tabs.profiles_tab import ProfilesTab

# -- Color palette --
CLR_BG_DARK = "#1a1a2e"
CLR_HEADER = "#16213e"
CLR_ACCENT = "#0f3460"
CLR_HIGHLIGHT = "#e94560"
CLR_SUCCESS = "#00b894"
CLR_TEXT = "#eaeaea"
CLR_TEXT_DIM = "#8a8a9a"
CLR_CARD = "#2a2a3e"
CLR_UPDATE_BG = "#1e3a5f"


class UniFiToolboxApp(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title(f"UniFi Toolbox v{__version__}")
        self.geometry("1100x800")
        self.minsize(950, 650)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.log_queue = queue.Queue()
        self._update_info = None
        self._build_ui()
        self._poll_log_queue()
        self._check_updates()

    def _build_ui(self):
        # ── Header bar ──────────────────────────────────────────
        header = ctk.CTkFrame(self, height=56, fg_color=CLR_HEADER, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(side="left", padx=20, fill="y")

        ctk.CTkLabel(
            title_frame, text="UniFi Toolbox",
            font=("Segoe UI", 22, "bold"), text_color="#ffffff",
        ).pack(side="left", pady=12)

        ctk.CTkLabel(
            title_frame, text=f"  v{__version__}",
            font=("Segoe UI", 12), text_color=CLR_TEXT_DIM,
        ).pack(side="left", pady=12)

        # Right side controls
        right_frame = ctk.CTkFrame(header, fg_color="transparent")
        right_frame.pack(side="right", padx=20, fill="y")

        self.theme_toggle = ctk.CTkSegmentedButton(
            right_frame, values=["Dark", "Light"],
            command=self._on_theme_change, width=120,
            font=("Segoe UI", 12),
        )
        self.theme_toggle.set("Dark")
        self.theme_toggle.pack(side="right", pady=14)

        # ── Update banner (hidden by default) ───────────────────
        self.update_banner = ctk.CTkFrame(self, height=40, fg_color=CLR_UPDATE_BG, corner_radius=0)
        self.update_banner_label = ctk.CTkLabel(
            self.update_banner, text="",
            font=("Segoe UI", 12), text_color="#ffffff",
        )
        self.update_banner_label.pack(side="left", padx=20, pady=8)

        self.update_btn = ctk.CTkButton(
            self.update_banner, text="Download Update",
            font=("Segoe UI", 12, "bold"),
            fg_color=CLR_HIGHLIGHT, hover_color="#c73e54",
            width=140, height=28,
            command=self._on_download_update,
        )
        self.update_btn.pack(side="right", padx=20, pady=6)

        self.update_dismiss = ctk.CTkButton(
            self.update_banner, text="Dismiss", width=70, height=28,
            font=("Segoe UI", 11),
            fg_color="transparent", hover_color="#2a4a6f",
            border_width=1, border_color="#4a6a8f",
            command=lambda: self.update_banner.pack_forget(),
        )
        self.update_dismiss.pack(side="right", pady=6)
        # Banner is hidden until an update is found

        # ── Main content ────────────────────────────────────────
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=(8, 0))

        # Tab view
        self.tabview = ctk.CTkTabview(
            content,
            segmented_button_fg_color=CLR_ACCENT,
            segmented_button_selected_color=CLR_HIGHLIGHT,
            segmented_button_selected_hover_color="#c73e54",
            segmented_button_unselected_color=CLR_ACCENT,
            segmented_button_unselected_hover_color="#1a4a70",
            fg_color="transparent",
        )
        self.tabview.pack(fill="both", expand=True)

        tab_ssh = self.tabview.add("  SSH Adoption  ")
        tab_console = self.tabview.add("  Console / API  ")
        tab_discovery = self.tabview.add("  Discovery  ")
        tab_profiles = self.tabview.add("  Profiles  ")

        self.ssh_tab = SSHTab(tab_ssh, log_fn=self.log_threadsafe)
        self.ssh_tab.pack(fill="both", expand=True)

        self.console_tab = ConsoleTab(tab_console, log_fn=self.log_threadsafe)
        self.console_tab.pack(fill="both", expand=True)

        self.discovery_tab = DiscoveryTab(
            tab_discovery, log_fn=self.log_threadsafe,
            on_adopt_selected=self._on_discovery_adopt,
        )
        self.discovery_tab.pack(fill="both", expand=True)

        self.profiles_tab = ProfilesTab(
            tab_profiles, log_fn=self.log_threadsafe,
            get_fields_fn=self._get_all_fields,
            load_fields_fn=self._load_all_fields,
        )
        self.profiles_tab.pack(fill="both", expand=True)

        # ── Log panel ───────────────────────────────────────────
        log_frame = ctk.CTkFrame(self, fg_color=CLR_CARD, corner_radius=8)
        log_frame.pack(fill="x", padx=16, pady=(4, 12))

        log_header = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header.pack(fill="x", padx=12, pady=(8, 0))

        ctk.CTkLabel(
            log_header, text="Log Output",
            font=("Segoe UI", 13, "bold"), text_color=CLR_TEXT,
        ).pack(side="left")

        ctk.CTkButton(
            log_header, text="Clear", width=60, height=26,
            font=("Segoe UI", 11),
            fg_color="transparent", hover_color="#3a3a4e",
            border_width=1, border_color="#4a4a5e",
            command=self._clear_log,
        ).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            log_frame, height=130, wrap="word",
            font=("Consolas", 12),
            fg_color="#1e1e2e", text_color="#d4d4d4",
            corner_radius=6,
        )
        self.log_box.pack(fill="x", padx=12, pady=(6, 10))
        self._log("Ready. Choose a tab to get started.")

    # ── Logging ─────────────────────────────────────────────────

    def _log(self, text: str):
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

    def log_threadsafe(self, text: str):
        self.log_queue.put(text)

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._log(msg)
        except queue.Empty:
            pass
        self.after(80, self._poll_log_queue)

    def _clear_log(self):
        self.log_box.delete("1.0", "end")

    # ── Theme ───────────────────────────────────────────────────

    def _on_theme_change(self, value):
        ctk.set_appearance_mode(value.lower())

    # ── Auto-update ─────────────────────────────────────────────

    def _check_updates(self):
        def on_result(info):
            if info:
                self._update_info = info
                self.after(0, self._show_update_banner)

        check_for_update_async(on_result)

    def _show_update_banner(self):
        if not self._update_info:
            return
        ver = self._update_info["version"]
        self.update_banner_label.configure(
            text=f"A new version is available: v{ver}  (you have v{__version__})"
        )
        # Insert banner right after header
        self.update_banner.pack(fill="x", after=self.winfo_children()[0])

    def _on_download_update(self):
        if self._update_info:
            url = self._update_info.get("download_url") or self._update_info.get("url", "")
            if url:
                open_download_page(url)
                self._log(f"Opening download page for v{self._update_info['version']}...")

    # ── Profile integration ─────────────────────────────────────

    def _get_all_fields(self) -> dict:
        fields = {}
        fields.update(self.ssh_tab.get_profile_fields())
        fields.update(self.console_tab.get_profile_fields())
        return fields

    def _load_all_fields(self, profile):
        self.ssh_tab.load_from_profile(profile)
        self.console_tab.load_from_profile(profile)

    # ── Discovery -> SSH bridge ─────────────────────────────────

    def _on_discovery_adopt(self, ips: list):
        self.tabview.set("  SSH Adoption  ")
        self.ssh_tab.mode_var.set("batch")
        self.ssh_tab._on_mode_change()
        self.ssh_tab.var_batch.set(", ".join(ips))
        self.log_threadsafe(f"{len(ips)} device(s) loaded into SSH batch. Configure credentials and run adoption.")
