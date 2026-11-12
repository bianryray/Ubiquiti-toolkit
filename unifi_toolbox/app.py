import os
import queue
import sys
import threading
from datetime import datetime
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .version import __version__
from .core.updater import (
    check_for_update_async, open_download_page, is_frozen,
    download_update, staging_path_for, launch_swap_and_restart,
    cleanup_old_build,
)
from .tabs.ssh_tab import SSHTab
from .tabs.console_tab import ConsoleTab
from .tabs.discovery_tab import DiscoveryTab
from .tabs.troubleshoot_tab import TroubleshootTab
from .tabs.profiles_tab import ProfilesTab

# -- Color palette --
# Each tuple is (light_mode_color, dark_mode_color). CustomTkinter switches
# automatically based on the current appearance mode.
CLR_BG_DARK = "#1a1a2e"
CLR_HEADER = ("#2a3e5c", "#16213e")
CLR_ACCENT = ("#3b5998", "#0f3460")
CLR_HIGHLIGHT = "#e94560"
CLR_SUCCESS = "#00b894"
CLR_TEXT = ("#1a1a2e", "#eaeaea")
CLR_TEXT_DIM = ("#6a6a7a", "#8a8a9a")
CLR_CARD = ("#ffffff", "#2a2a3e")
CLR_UPDATE_BG = ("#dde9ff", "#1e3a5f")
CLR_LOG_BG = ("#fafafa", "#1e1e2e")
CLR_LOG_TEXT = ("#2a2a3e", "#d4d4d4")
CLR_BORDER = ("#d0d0dc", "#4a4a5e")
CLR_GHOST_HOVER = ("#e4e4ec", "#3a3a4e")


def _plain_notes(md: str) -> str:
    """Light markdown cleanup so release notes read well in a plain textbox."""
    out = []
    for line in (md or "").strip().splitlines():
        stripped = line.lstrip("#").strip()
        if line.startswith("#"):
            line = stripped.upper()
        elif line.lstrip().startswith("- "):
            indent = len(line) - len(line.lstrip())
            line = " " * indent + "\u2022 " + line.lstrip()[2:]
        out.append(line.replace("**", "").replace("`", ""))
    return "\n".join(out)


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
        self._updating = False
        cleanup_old_build()
        self._build_ui()
        self._bind_shortcuts()
        self._poll_log_queue()
        # Quiet check on startup; only surfaces if an update exists.
        self.after(1500, lambda: self._check_updates(manual=False))

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

        self.btn_check_updates = ctk.CTkButton(
            right_frame, text="Check for Updates", width=140, height=28,
            font=("Segoe UI", 12),
            fg_color="transparent", hover_color="#2a4a6f",
            border_width=1, border_color="#4a6a8f", text_color="#ffffff",
            command=lambda: self._check_updates(manual=True),
        )
        self.btn_check_updates.pack(side="right", padx=(0, 12), pady=14)

        # ── Update banner (hidden by default) ───────────────────
        self.update_banner = ctk.CTkFrame(self, height=40, fg_color=CLR_UPDATE_BG, corner_radius=0)
        self.update_banner_label = ctk.CTkLabel(
            self.update_banner, text="",
            font=("Segoe UI", 12), text_color="#ffffff",
        )
        self.update_banner_label.pack(side="left", padx=20, pady=8)

        self.update_btn = ctk.CTkButton(
            self.update_banner, text="Update Now" if is_frozen() else "Download Update",
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

        self.update_notes_btn = ctk.CTkButton(
            self.update_banner, text="What's New", width=90, height=28,
            font=("Segoe UI", 11),
            fg_color="transparent", hover_color="#2a4a6f",
            border_width=1, border_color="#4a6a8f",
            command=self._show_release_notes,
        )
        self.update_notes_btn.pack(side="right", padx=(0, 8), pady=6)
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
        tab_troubleshoot = self.tabview.add("  Troubleshoot  ")
        tab_profiles = self.tabview.add("  Profiles  ")

        self.ssh_tab = SSHTab(
            tab_ssh, log_fn=self.log_threadsafe,
            on_find_devices=lambda: self.tabview.set("  Discovery  "),
        )
        self.ssh_tab.pack(fill="both", expand=True)

        self.console_tab = ConsoleTab(tab_console, log_fn=self.log_threadsafe)
        self.console_tab.pack(fill="both", expand=True)

        self.discovery_tab = DiscoveryTab(
            tab_discovery, log_fn=self.log_threadsafe,
            on_adopt_selected=self._on_discovery_adopt,
        )
        self.discovery_tab.pack(fill="both", expand=True)

        self.troubleshoot_tab = TroubleshootTab(
            tab_troubleshoot, log_fn=self.log_threadsafe,
        )
        self.troubleshoot_tab.pack(fill="both", expand=True)

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

        for label, cmd in (("Clear", self._clear_log),
                           ("Save...", self._save_log),
                           ("Copy", self._copy_log)):
            ctk.CTkButton(
                log_header, text=label, width=60, height=26,
                font=("Segoe UI", 11),
                fg_color="transparent", hover_color=CLR_GHOST_HOVER,
                border_width=1, border_color=CLR_BORDER, text_color=CLR_TEXT,
                command=cmd,
            ).pack(side="right", padx=(6, 0))

        self.log_box = ctk.CTkTextbox(
            log_frame, height=130, wrap="word",
            font=("Consolas", 12),
            fg_color=CLR_LOG_BG, text_color=CLR_LOG_TEXT,
            corner_radius=6,
        )
        self.log_box.pack(fill="x", padx=12, pady=(6, 10))
        self._log("Ready. Choose a tab to get started.")

    # ── Logging ─────────────────────────────────────────────────

    def _log(self, text: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{stamp}] {text}\n")
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

    def _copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.log_box.get("1.0", "end").rstrip())
        self._log("Log copied to clipboard.")

    def _save_log(self):
        path = filedialog.asksaveasfilename(
            title="Save log", defaultextension=".txt",
            initialfile=f"unifi-toolbox-log-{datetime.now():%Y%m%d-%H%M%S}.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_box.get("1.0", "end"))
            self._log(f"Log saved to {path}")
        except OSError as e:
            self._log(f"Could not save log: {e}")

    # ── Keyboard shortcuts ──────────────────────────────────────

    def _bind_shortcuts(self):
        tabs = ["  SSH Adoption  ", "  Console / API  ", "  Discovery  ",
                "  Troubleshoot  ", "  Profiles  "]
        for i, name in enumerate(tabs, start=1):
            self.bind_all(f"<Control-Key-{i}>", lambda e, n=name: self.tabview.set(n))
        self.bind_all("<Control-f>", self._on_find_shortcut)
        self.bind_all("<Control-l>", lambda e: self._clear_log())

    def _on_find_shortcut(self, _event=None):
        self.tabview.set("  Discovery  ")
        self.discovery_tab.focus_search()

    # ── Theme ───────────────────────────────────────────────────

    def _on_theme_change(self, value):
        ctk.set_appearance_mode(value.lower())

    # ── Auto-update ─────────────────────────────────────────────

    def _check_updates(self, manual: bool):
        if manual:
            self.btn_check_updates.configure(state="disabled", text="Checking...")
            self._log("Checking GitHub for updates...")

        def on_result(info):
            self.after(0, lambda: self._on_update_result(info, manual))

        check_for_update_async(on_result)

    def _on_update_result(self, info, manual: bool):
        self.btn_check_updates.configure(state="normal", text="Check for Updates")
        if info.available:
            self._update_info = info
            self._log(info.message)
            self._show_update_banner()
        elif manual:
            self._log(info.message)
            if info.status == "current":
                messagebox.showinfo("UniFi Toolbox", info.message)
            else:
                messagebox.showwarning("Update check", info.message)

    def _show_update_banner(self):
        if not self._update_info:
            return
        self.update_banner_label.configure(text=self._update_info.message)
        self.update_btn.configure(state="normal")
        # Insert banner right after header
        self.update_banner.pack(fill="x", after=self.winfo_children()[0])

    def _show_release_notes(self):
        info = self._update_info
        if not info:
            return
        win = ctk.CTkToplevel(self)
        win.title(f"What's new in v{info.version}")
        win.geometry("620x460")
        win.transient(self)
        box = ctk.CTkTextbox(win, wrap="word", font=("Segoe UI", 12))
        box.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        box.insert("1.0", _plain_notes(info.body) or "No release notes were published.")
        box.configure(state="disabled")
        ctk.CTkButton(
            win, text="Open release page",
            command=lambda: open_download_page(info.url),
        ).pack(pady=(0, 12))
        win.after(100, win.lift)

    def _on_download_update(self):
        info = self._update_info
        if not info or self._updating:
            return
        # Running from source, or the release has no .exe attached:
        # send the user to the release page instead.
        if not is_frozen() or not info.download_url:
            open_download_page(info.download_url or info.url)
            self._log(f"Opening download page for v{info.version}...")
            return

        current_exe = os.path.abspath(sys.executable)
        dest = staging_path_for(current_exe)
        self._updating = True
        self.update_btn.configure(state="disabled", text="Downloading...")
        self._log(f"Downloading v{info.version} ...")

        def progress(done, total):
            if total:
                pct = int(done * 100 / total)
                self.after(0, lambda: self.update_btn.configure(text=f"Downloading {pct}%"))

        def worker():
            try:
                download_update(info.download_url, dest, on_progress=progress)
            except Exception as e:
                err = str(e)  # `e` is cleared when the except block ends
                self.after(0, lambda: self._on_update_failed(err))
                return
            self.after(0, lambda: self._finish_update(dest, current_exe))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_failed(self, err: str):
        self._updating = False
        self.update_btn.configure(state="normal", text="Update Now")
        self._log(f"Update failed: {err}")
        messagebox.showerror(
            "Update failed",
            f"{err}\n\nYou can download the new version manually from the release page.",
        )

    def _finish_update(self, new_exe: str, current_exe: str):
        self._log("Download complete. Restarting to finish the update...")
        if not messagebox.askokcancel(
            "Install update",
            f"UniFi Toolbox v{self._update_info.version} is ready.\n\n"
            "The app will close, update itself and reopen. Continue?",
        ):
            self._updating = False
            self.update_btn.configure(state="normal", text="Update Now")
            self._log(f"Update postponed. Downloaded file kept at {new_exe}")
            return
        try:
            launch_swap_and_restart(new_exe, current_exe)
        except Exception as e:
            self._on_update_failed(f"Could not start the installer step: {e}")
            return
        self.after(200, self.destroy)

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
