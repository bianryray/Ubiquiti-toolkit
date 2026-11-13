import os
import queue
import re
import sys
import threading
import tkinter.font as tkfont
from datetime import datetime
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import theme as T
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
from .tabs.nettest_tab import NetTestTab

# (key, label, Segoe Fluent/MDL2 icon codepoint)
PAGES = [
    ("ssh", "SSH Adoption", "\ue756"),           # CommandPrompt
    ("console", "Console / API", "\ue774"),      # Globe
    ("discovery", "Discovery", "\ue721"),        # Search
    ("troubleshoot", "Troubleshoot", "\ue90f"),  # Repair
    ("profiles", "Profiles", "\ue77b"),          # Contact
    ("nettest", "Network Tests", "\ue9d9"),      # Diagnostic (BETA section)
]
BETA_PAGES = {"nettest"}

# Log line colouring: (regex, (light, dark))
_LOG_RULES = [
    ("err", re.compile(r"\b(error|failed|failure|refused|denied|timed out|invalid)\b", re.I),
     ("#b91c1c", "#f87171")),
    ("ok", re.compile(r"\b(success|succeeded|adopted|complete|saved|loaded|updated|"
                      r"adoption request sent)\b", re.I), ("#15803d", "#4ade80")),
    ("warn", re.compile(r"\b(warning|stopped|paused|skipp)", re.I), ("#b45309", "#fbbf24")),
    ("head", re.compile(r"^\s*(={3,}|-{3}|Found:)"), ("#1d4ed8", "#60a5fa")),
]


def _plain_notes(md: str) -> str:
    """Light markdown cleanup so release notes read well in a plain textbox."""
    out = []
    for line in (md or "").strip().splitlines():
        stripped = line.lstrip("#").strip()
        if line.startswith("#"):
            line = stripped.upper()
        elif line.lstrip().startswith("- "):
            indent = len(line) - len(line.lstrip())
            line = " " * indent + "• " + line.lstrip()[2:]
        out.append(line.replace("**", "").replace("`", ""))
    return "\n".join(out)


class NavItem(ctk.CTkFrame):
    """Sidebar entry: icon + label, with hover and selected states."""

    def __init__(self, parent, text, icon, icon_font, command):
        super().__init__(parent, fg_color="transparent", corner_radius=T.RADIUS_SM,
                         height=40, cursor="hand2")
        self.pack_propagate(False)
        self.command = command
        self.selected = False
        self.bar = ctk.CTkFrame(self, width=3, corner_radius=2, fg_color="transparent")
        self.bar.pack(side="left", fill="y", pady=9)
        self.icon = None
        if icon_font:
            self.icon = ctk.CTkLabel(self, text=icon, width=26, font=(icon_font, 15),
                                     text_color=T.TEXT_DIM)
            self.icon.pack(side="left", padx=(10, 6))
        self.text = ctk.CTkLabel(self, text=text, font=T.FONT_NAV, text_color=T.TEXT_DIM,
                                 anchor="w")
        self.text.pack(side="left", fill="x", expand=True, padx=(0 if icon_font else 14, 0))
        for w in (self, self.bar, self.text) + ((self.icon,) if self.icon else ()):
            w.bind("<Button-1>", lambda e: self.command())
            w.bind("<Enter>", lambda e: self._hover(True))
            w.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, on):
        if not self.selected:
            self.configure(fg_color=T.BG_HOVER if on else "transparent")

    def set_selected(self, on):
        self.selected = on
        self.configure(fg_color=T.ACCENT_SOFT if on else "transparent")
        self.bar.configure(fg_color=T.ACCENT if on else "transparent")
        color = T.ACCENT if on else T.TEXT_DIM
        self.text.configure(text_color=T.TEXT if on else T.TEXT_DIM,
                            font=(T.FONT_NAV[0], T.FONT_NAV[1], "bold") if on else T.FONT_NAV)
        if self.icon:
            self.icon.configure(text_color=color)


class UniFiToolboxApp(ctk.CTk):
    """Main application window."""

    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=T.BG_APP)
        self.title(f"UniFi Toolbox v{__version__}")
        self.geometry("1320x860")
        self.minsize(1140, 700)

        self.log_queue = queue.Queue()
        self._update_info = None
        self._updating = False
        self._log_open = True
        self.pages = {}
        self.nav = {}
        cleanup_old_build()

        families = set(tkfont.families(self))
        self._icon_font = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets")
                                if f in families), None)
        self._build_ui()
        self._restore_settings()
        self._bind_shortcuts()
        self._poll_log_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Quiet check on startup; only surfaces if an update exists.
        self.after(1500, lambda: self._check_updates(manual=False))

    # ── Layout ──────────────────────────────────────────────────

    def _build_ui(self):
        # Sidebar
        side = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=T.BG_SIDEBAR,
                            border_width=0)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        ctk.CTkFrame(self, width=1, corner_radius=0, fg_color=T.BORDER).pack(side="left", fill="y")

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(22, 26))
        logo = ctk.CTkFrame(brand, width=36, height=36, corner_radius=9, fg_color=T.ACCENT)
        logo.pack(side="left")
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="U", font=("Segoe UI", 17, "bold"),
                     text_color="#ffffff").pack(expand=True)
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(names, text="UniFi Toolbox", font=("Segoe UI", 15, "bold"),
                     text_color=T.TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(names, text=f"Version {__version__}", font=T.FONT_SMALL,
                     text_color=T.TEXT_DIM, anchor="w").pack(fill="x")

        ctk.CTkLabel(side, text="TOOLS", font=T.FONT_SMALL_BOLD, text_color=T.TEXT_FAINT,
                     anchor="w").pack(fill="x", padx=22, pady=(0, 6))
        beta_label_done = False
        for key, label, icon in PAGES:
            if key in BETA_PAGES and not beta_label_done:
                ctk.CTkLabel(side, text="BETA", font=T.FONT_SMALL_BOLD, text_color=T.WARNING,
                             anchor="w").pack(fill="x", padx=22, pady=(18, 6))
                beta_label_done = True
            item = NavItem(side, label, icon, self._icon_font,
                           command=lambda k=key: self.show_page(k))
            item.pack(fill="x", padx=12, pady=2)
            self.nav[key] = item

        # Sidebar footer
        foot = ctk.CTkFrame(side, fg_color="transparent")
        foot.pack(side="bottom", fill="x", padx=14, pady=16)
        self.btn_check_updates = T.button(
            foot, "Check for Updates", lambda: self._check_updates(manual=True),
            kind="secondary", width=200,
        )
        self.btn_check_updates.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(foot, text="APPEARANCE", font=T.FONT_SMALL_BOLD,
                     text_color=T.TEXT_FAINT, anchor="w").pack(fill="x", pady=(0, 4))
        self.theme_toggle = T.segmented(foot, ["Light", "Dark", "System"],
                                        command=self._on_theme_change)
        self.theme_toggle.set("Dark")
        self.theme_toggle.pack(fill="x")

        # Main column
        main = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        main.pack(side="left", fill="both", expand=True)
        self.main = main

        # Update banner (hidden until an update is found)
        self.update_banner = ctk.CTkFrame(main, fg_color=T.BG_UPDATE, corner_radius=T.RADIUS,
                                          border_width=1, border_color=T.ACCENT_SOFT)
        self.update_banner_label = ctk.CTkLabel(
            self.update_banner, text="", font=T.FONT_LABEL_BOLD, text_color=T.TEXT)
        self.update_banner_label.pack(side="left", padx=16, pady=10)
        self.update_btn = T.button(
            self.update_banner, "Update Now" if is_frozen() else "Download Update",
            self._on_download_update, kind="primary", width=150, height=30)
        self.update_btn.pack(side="right", padx=(6, 12), pady=8)
        self.update_dismiss = T.button(self.update_banner, "Dismiss",
                                       lambda: self.update_banner.pack_forget(),
                                       kind="ghost", width=80, height=30)
        self.update_dismiss.pack(side="right", pady=8)
        self.update_notes_btn = T.button(self.update_banner, "What's New",
                                         self._show_release_notes, kind="ghost",
                                         width=100, height=30)
        self.update_notes_btn.pack(side="right", pady=8)

        # Activity log (bottom) -- packed before the pages so it keeps its height
        self._build_log(main)

        # Pages
        self.page_host = ctk.CTkFrame(main, fg_color="transparent")
        self.page_host.pack(fill="both", expand=True, padx=24, pady=(22, 10))

        def host():
            f = ctk.CTkFrame(self.page_host, fg_color="transparent")
            return f

        self.ssh_tab = SSHTab(host(), log_fn=self.log_threadsafe,
                              on_find_devices=lambda: self.show_page("discovery"))
        self.console_tab = ConsoleTab(host(), log_fn=self.log_threadsafe)
        self.discovery_tab = DiscoveryTab(host(), log_fn=self.log_threadsafe,
                                          on_adopt_selected=self._on_discovery_adopt)
        self.troubleshoot_tab = TroubleshootTab(host(), log_fn=self.log_threadsafe)
        self.profiles_tab = ProfilesTab(host(), log_fn=self.log_threadsafe,
                                        get_fields_fn=self._get_all_fields,
                                        load_fields_fn=self._load_all_fields)
        self.nettest_tab = NetTestTab(
            host(), log_fn=self.log_threadsafe,
            get_ssh_login=lambda: (self.ssh_tab.var_user.get(), self.ssh_tab.var_pass.get(),
                                   self.ssh_tab._get_port()),
        )
        for key, tab in (("ssh", self.ssh_tab), ("console", self.console_tab),
                         ("discovery", self.discovery_tab),
                         ("troubleshoot", self.troubleshoot_tab),
                         ("profiles", self.profiles_tab),
                         ("nettest", self.nettest_tab)):
            tab.pack(fill="both", expand=True)
            self.pages[key] = tab.master
        self.show_page("ssh")

    def show_page(self, key: str):
        for k, frame in self.pages.items():
            if k == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
            self.nav[k].set_selected(k == key)
        self._current_page = key

    def _build_log(self, main):
        panel = ctk.CTkFrame(main, fg_color=T.BG_CARD, corner_radius=T.RADIUS,
                             border_width=1, border_color=T.BORDER)
        panel.pack(side="bottom", fill="x", padx=24, pady=(0, 18))
        self.log_panel = panel

        head = ctk.CTkFrame(panel, fg_color="transparent", cursor="hand2")
        head.pack(fill="x", padx=14, pady=8)
        self.log_toggle = ctk.CTkLabel(head, text="▾", width=16, font=T.FONT_LABEL,
                                       text_color=T.TEXT_DIM)
        self.log_toggle.pack(side="left")
        title = ctk.CTkLabel(head, text="Activity", font=T.FONT_LABEL_BOLD, text_color=T.TEXT)
        title.pack(side="left", padx=(4, 12))
        self.var_last_log = ctk.StringVar(value="")
        self.last_log_label = ctk.CTkLabel(head, textvariable=self.var_last_log,
                                           font=T.FONT_SMALL, text_color=T.TEXT_DIM, anchor="w")
        for w in (head, self.log_toggle, title, self.last_log_label):
            w.bind("<Button-1>", lambda e: self._toggle_log())

        for label, cmd in (("Clear", self._clear_log), ("Save", self._save_log),
                           ("Copy", self._copy_log)):
            T.button(head, label, cmd, kind="ghost", width=56, height=26).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            panel, height=130, wrap="word", font=T.FONT_MONO,
            fg_color=T.BG_LOG, text_color=T.TEXT_LOG, corner_radius=T.RADIUS_SM,
            border_width=0, activate_scrollbars=True,
        )
        self.log_box.pack(fill="x", padx=12, pady=(0, 12))
        self._apply_log_colors()
        self._log("Ready. Pick a tool on the left to get started.")

    def _toggle_log(self):
        self._log_open = not self._log_open
        if self._log_open:
            self.log_box.pack(fill="x", padx=12, pady=(0, 12))
            self.last_log_label.pack_forget()
            self.log_toggle.configure(text="▾")
            self.log_box.see("end")
        else:
            self.log_box.pack_forget()
            self.last_log_label.pack(side="left", fill="x", expand=True)
            self.log_toggle.configure(text="▸")

    def _apply_log_colors(self):
        dark = ctk.get_appearance_mode() == "Dark"
        self.log_box.tag_config("ts", foreground="#5d6b7d" if dark else "#94a3b8")
        for tag, _rx, (light, darkc) in _LOG_RULES:
            self.log_box.tag_config(tag, foreground=darkc if dark else light)

    # ── Logging ─────────────────────────────────────────────────

    def _log(self, text: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        tag = next((t for t, rx, _c in _LOG_RULES if rx.search(text)), None)
        self.log_box.insert("end", f"{stamp}  ", ("ts",))
        self.log_box.insert("end", text + "\n", (tag,) if tag else ())
        self.log_box.see("end")
        last = text.strip().splitlines()[-1] if text.strip() else ""
        self.var_last_log.set(last[:140])

    def log_threadsafe(self, text: str):
        self.log_queue.put(text)

    def _poll_log_queue(self):
        try:
            while True:
                self._log(self.log_queue.get_nowait())
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

    # ── Settings / shortcuts ────────────────────────────────────

    @property
    def _settings(self):
        return self.profiles_tab.manager  # one shared settings store

    def _restore_settings(self):
        mode = self._settings.get_setting("appearance", "Dark")
        if mode in ("Light", "Dark", "System"):
            self.theme_toggle.set(mode)
            self._on_theme_change(mode, save=False)
        geo = self._settings.get_setting("window_geometry")
        if geo and re.fullmatch(r"\d+x\d+[+-]-?\d+[+-]-?\d+", geo):
            self.geometry(geo)
        if self._settings.get_setting("log_open", True) is False:
            self._toggle_log()

    def _on_close(self):
        try:
            if self.state() == "normal":
                self._settings.set_setting("window_geometry", self.geometry())
            self._settings.set_setting("log_open", self._log_open)
        except Exception:
            pass
        self.destroy()

    def _bind_shortcuts(self):
        for i, (key, _label, _icon) in enumerate(PAGES, start=1):
            self.bind_all(f"<Control-Key-{i}>", lambda e, k=key: self.show_page(k))
        self.bind_all("<Control-f>", self._on_find_shortcut)
        self.bind_all("<Control-l>", lambda e: self._clear_log())

    def _on_find_shortcut(self, _event=None):
        self.show_page("discovery")
        self.discovery_tab.focus_search()

    def _on_theme_change(self, value, save=True):
        ctk.set_appearance_mode(value.lower())
        self.after(50, self._apply_log_colors)
        if save:
            self._settings.set_setting("appearance", value)

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
        self.update_banner.pack(fill="x", padx=24, pady=(18, 0), before=self.page_host)

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
        self.show_page("ssh")
        self.ssh_tab.mode_var.set("batch")
        self.ssh_tab._on_mode_change()
        self.ssh_tab.var_batch.set(", ".join(ips))
        self.log_threadsafe(f"{len(ips)} device(s) loaded into SSH batch. Configure credentials and run adoption.")
