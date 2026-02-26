import queue
import customtkinter as ctk

from .tabs.ssh_tab import SSHTab
from .tabs.console_tab import ConsoleTab
from .tabs.discovery_tab import DiscoveryTab
from .tabs.profiles_tab import ProfilesTab


class UniFiToolboxApp(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title("UniFi Toolbox")
        self.geometry("1050x750")
        self.minsize(900, 600)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.log_queue = queue.Queue()
        self._build_ui()
        self._poll_log_queue()

    def _build_ui(self):
        # --- Top bar ---
        top_bar = ctk.CTkFrame(self, height=40)
        top_bar.pack(fill="x", padx=10, pady=(10, 0))

        ctk.CTkLabel(top_bar, text="UniFi Toolbox", font=("", 18, "bold")).pack(side="left", padx=10)

        self.var_theme = ctk.StringVar(value="dark")
        ctk.CTkSegmentedButton(
            top_bar, values=["Dark", "Light"],
            command=self._on_theme_change, width=120
        ).pack(side="right", padx=10)

        # --- Tab view ---
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=5)

        tab_ssh = self.tabview.add("SSH Adoption")
        tab_console = self.tabview.add("Console / API")
        tab_discovery = self.tabview.add("Discovery")
        tab_profiles = self.tabview.add("Profiles")

        # Create tab instances
        self.ssh_tab = SSHTab(tab_ssh, log_fn=self.log_threadsafe)
        self.ssh_tab.pack(fill="both", expand=True)

        self.console_tab = ConsoleTab(tab_console, log_fn=self.log_threadsafe)
        self.console_tab.pack(fill="both", expand=True)

        self.discovery_tab = DiscoveryTab(
            tab_discovery, log_fn=self.log_threadsafe,
            on_adopt_selected=self._on_discovery_adopt
        )
        self.discovery_tab.pack(fill="both", expand=True)

        self.profiles_tab = ProfilesTab(
            tab_profiles, log_fn=self.log_threadsafe,
            get_fields_fn=self._get_all_fields,
            load_fields_fn=self._load_all_fields,
        )
        self.profiles_tab.pack(fill="both", expand=True)

        # --- Log panel ---
        log_frame = ctk.CTkFrame(self)
        log_frame.pack(fill="x", padx=10, pady=(0, 10))

        log_header = ctk.CTkFrame(log_frame)
        log_header.pack(fill="x", padx=5, pady=(5, 0))
        ctk.CTkLabel(log_header, text="Log", font=("", 13, "bold")).pack(side="left", padx=5)
        ctk.CTkButton(
            log_header, text="Clear", width=60,
            command=self._clear_log
        ).pack(side="right", padx=5)

        self.log_box = ctk.CTkTextbox(log_frame, height=150, wrap="word")
        self.log_box.pack(fill="x", padx=5, pady=5)
        self._log("Ready. Choose a tab to get started.")

    # --- Logging ---

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

    # --- Theme ---

    def _on_theme_change(self, value):
        ctk.set_appearance_mode(value.lower())

    # --- Profile integration ---

    def _get_all_fields(self) -> dict:
        fields = {}
        fields.update(self.ssh_tab.get_profile_fields())
        fields.update(self.console_tab.get_profile_fields())
        return fields

    def _load_all_fields(self, profile):
        self.ssh_tab.load_from_profile(profile)
        self.console_tab.load_from_profile(profile)

    # --- Discovery -> SSH bridge ---

    def _on_discovery_adopt(self, ips: list):
        self.tabview.set("SSH Adoption")
        self.ssh_tab.mode_var.set("batch")
        self.ssh_tab._on_mode_change()
        self.ssh_tab.var_batch.set(", ".join(ips))
        self.log_threadsafe(f"{len(ips)} device(s) loaded into SSH batch. Configure credentials and run adoption.")
