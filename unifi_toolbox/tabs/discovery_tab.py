import csv
import ipaddress
import re
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk

from ..core.discovery import NetworkScanner, get_local_subnets
from ..utils import LogFn
from ..theme import (
    BG_CARD, BG_CARD_ALT, SEPARATOR, BORDER, TEXT_ON_CARD, TEXT_DIM,
    SUCCESS, SUCCESS_HOVER, TEXT_ON_SUCCESS, DANGER, DANGER_HOVER,
    GHOST_HOVER, ROW_STRIPE,
    FONT_LABEL, FONT_HEADING, FONT_SMALL, FONT_SMALL_BOLD, FONT_BTN_BOLD,
    FONT_MONO, section_card,
)

# (key, header text, width)
COLUMNS = [
    ("ip", "IP Address", 140),
    ("mac", "MAC", 160),
    ("vendor", "Manufacturer", 180),
    ("ports", "Open Ports", 120),
    ("banner", "SSH Banner", 240),
]

_HEX_ONLY = re.compile(r"^[0-9a-fA-F:.\-]+$")


def _norm_mac(mac: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", mac or "").upper()


def _sort_key(result: dict, key: str):
    """Sort key per column. Blank values always sort last (see caller)."""
    if key == "ip":
        try:
            return int(ipaddress.ip_address(result["ip"]))
        except ValueError:
            return 0
    if key == "mac":
        return _norm_mac(result.get("mac", ""))
    if key == "ports":
        return tuple(result.get("ports") or ())
    return (result.get(key) or "").lower()


def _matches(result: dict, terms) -> bool:
    """Every search term must match one of the columns. MAC matching ignores
    separators, so 'aabbcc', 'aa:bb:cc' and 'AA-BB-CC' all find the same row."""
    haystack = " ".join([
        result.get("ip", ""),
        result.get("mac", ""),
        result.get("vendor", ""),
        " ".join(str(p) for p in result.get("ports", [])),
        result.get("banner", ""),
    ]).lower()
    mac = _norm_mac(result.get("mac", ""))
    for term in terms:
        if term in haystack:
            continue
        if _HEX_ONLY.match(term):
            hex_term = _norm_mac(term)
            if len(hex_term) >= 2 and hex_term in mac:
                continue
        return False
    return True


class DiscoveryTab(ctk.CTkFrame):
    """Network discovery tab -- scan for Ubiquiti devices on the LAN."""

    def __init__(self, parent, log_fn: LogFn, on_adopt_selected=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.log = log_fn
        self.on_adopt_selected = on_adopt_selected
        self.scanner = None
        # Each entry: {"data": dict, "var": BooleanVar, "row": CTkFrame}
        self.entries = []
        self.sort_key = "ip"
        self.sort_desc = False
        self._refresh_pending = False
        self._header_btns = {}
        self._build_ui()

    # Back-compat helpers (results / check_vars used to be public lists)
    @property
    def results(self):
        return [e["data"] for e in self.entries]

    def _build_ui(self):
        # ── Scan controls ────────────────────────────────────
        ctrl_card = section_card(self, "Network Scan")
        row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(row, text="Subnet", font=FONT_LABEL).pack(side="left", padx=(0, 8))
        subnets = get_local_subnets()
        self.var_subnet = ctk.StringVar(value=subnets[0] if subnets else "")
        self.subnet_box = ctk.CTkComboBox(
            row, variable=self.var_subnet, values=subnets, width=200, height=32,
        )
        self.subnet_box.pack(side="left", padx=(0, 8))
        self.subnet_box.bind("<Return>", lambda e: self._on_scan())

        self.btn_scan = ctk.CTkButton(
            row, text="Scan", command=self._on_scan,
            width=80, height=32, font=FONT_BTN_BOLD,
            fg_color=SUCCESS, hover_color=SUCCESS_HOVER, text_color=TEXT_ON_SUCCESS,
        )
        self.btn_scan.pack(side="left", padx=(0, 8))

        self.btn_stop = ctk.CTkButton(
            row, text="Stop", command=self._on_stop,
            width=80, height=32, font=FONT_LABEL,
            fg_color=DANGER, hover_color=DANGER_HOVER, state="disabled",
        )
        self.btn_stop.pack(side="left", padx=(0, 12))

        self.progress = ctk.CTkProgressBar(row, width=160, height=10)
        self.progress.set(0)
        self.progress.pack(side="left", padx=(0, 8))

        self.var_progress = ctk.StringVar(value="")
        ctk.CTkLabel(
            row, textvariable=self.var_progress,
            font=FONT_SMALL, text_color=TEXT_DIM,
        ).pack(side="left")

        # ── Results ──────────────────────────────────────────
        results_card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=8)
        results_card.pack(fill="both", expand=True, padx=4, pady=(0, 8))

        results_header = ctk.CTkFrame(results_card, fg_color="transparent")
        results_header.pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            results_header, text="Discovered Devices", font=FONT_HEADING,
            text_color=TEXT_ON_CARD,
        ).pack(side="left")

        self.var_count = ctk.StringVar(value="")
        ctk.CTkLabel(
            results_header, textvariable=self.var_count,
            font=FONT_SMALL, text_color=TEXT_DIM,
        ).pack(side="right")

        self.var_only_ubnt = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            results_header, text="Only Ubiquiti", variable=self.var_only_ubnt,
            command=self._refresh_view, font=FONT_LABEL,
            checkbox_width=18, checkbox_height=18, text_color=TEXT_ON_CARD,
        ).pack(side="right", padx=(0, 14))

        ctk.CTkButton(
            results_header, text="✕", width=28, height=28,
            fg_color="transparent", hover_color=GHOST_HOVER,
            text_color=TEXT_DIM, command=self._clear_search,
        ).pack(side="right", padx=(2, 12))

        # No textvariable: CTkEntry hides its placeholder when one is set.
        self.search_entry = ctk.CTkEntry(
            results_header, width=300, height=30,
            placeholder_text="Search MAC, IP, manufacturer...  (Ctrl+F)",
        )
        self.search_entry.pack(side="right")
        self.search_entry.bind("<Escape>", lambda e: self._clear_search())
        self.search_entry.bind("<KeyRelease>", lambda e: self._schedule_refresh())

        sep = ctk.CTkFrame(results_card, height=1, fg_color=SEPARATOR)
        sep.pack(fill="x", padx=14, pady=(4, 4))

        # Column headers -- click to sort, click again to reverse.
        header = ctk.CTkFrame(results_card, fg_color=BG_CARD_ALT, corner_radius=0)
        header.pack(fill="x", padx=14, pady=(0, 2))
        ctk.CTkLabel(header, text="", width=36).pack(side="left")
        for key, title, width in COLUMNS:
            btn = ctk.CTkButton(
                header, text=title, width=width, height=26, anchor="w",
                font=FONT_SMALL_BOLD, text_color=TEXT_DIM,
                fg_color="transparent", hover_color=GHOST_HOVER, corner_radius=4,
                command=lambda k=key: self._on_sort(k),
            )
            btn.pack(side="left")
            self._header_btns[key] = (btn, title)
        self._update_header_labels()

        # Scrollable results
        self.results_scroll = ctk.CTkScrollableFrame(
            results_card, fg_color="transparent",
        )
        self.results_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 4))

        self.empty_label = ctk.CTkLabel(
            self.results_scroll, text="No scan yet. Pick a subnet and press Scan.",
            font=FONT_SMALL, text_color=TEXT_DIM,
        )
        self.empty_label.pack(pady=20)

        ctk.CTkLabel(
            results_card,
            text="Tip: click a column to sort - right-click a row for more options - "
                 "double-click to tick/untick",
            font=FONT_SMALL, text_color=TEXT_DIM, anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 8))

        # ── Bottom actions ───────────────────────────────────
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=4, pady=(0, 4))

        def ghost(text, cmd, width):
            ctk.CTkButton(
                bottom, text=text, command=cmd,
                width=width, height=32, font=FONT_LABEL,
                fg_color="transparent", hover_color=GHOST_HOVER,
                border_width=1, border_color=BORDER, text_color=TEXT_ON_CARD,
            ).pack(side="left", padx=(0, 6))

        ghost("Select All", self._select_all, 90)
        ghost("Deselect All", self._deselect_all, 100)
        ghost("Copy IPs", lambda: self._copy_selected("ip"), 80)
        ghost("Copy MACs", lambda: self._copy_selected("mac"), 90)
        ghost("Export CSV...", self._export_csv, 100)

        ctk.CTkButton(
            bottom, text="Adopt Selected", command=self._adopt_selected,
            width=140, height=32, font=FONT_BTN_BOLD,
            fg_color=SUCCESS, hover_color=SUCCESS_HOVER, text_color=TEXT_ON_SUCCESS,
        ).pack(side="right")

        # Right-click menu (rebuilt per row on demand)
        self._menu = tk.Menu(self, tearoff=0)

    # ── Public ───────────────────────────────────────────────

    def focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    # ── Scan logic ───────────────────────────────────────────

    def _on_scan(self):
        subnet = self.var_subnet.get().strip()
        if not subnet:
            self.log("Enter a subnet to scan.")
            return

        self._clear_results()
        self.btn_scan.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.empty_label.configure(text="Scanning...")
        self.scanner = NetworkScanner(log=self.log, max_workers=50)

        def on_found(result):
            self.after(0, lambda r=result: self._add_result(r))

        def on_progress(scanned, total):
            def ui():
                self.var_progress.set(f"{scanned}/{total} scanned")
                self.progress.set(scanned / total if total else 0)
            self.after(0, ui)

        def worker():
            try:
                self.scanner.scan_subnet(
                    subnet, on_found=on_found, on_progress=on_progress,
                )
            except Exception as e:
                self.log(f"Scan error: {e}")
            finally:
                self.after(0, self._on_scan_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_done(self):
        self.btn_scan.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        n = len(self.entries)
        ubnt = sum(1 for e in self.entries if self._is_ubnt(e["data"]))
        self.var_progress.set(f"Done - {n} found ({ubnt} Ubiquiti)")
        self.progress.set(1)
        if not self.entries:
            self.empty_label.configure(text="No devices found on that subnet.")
        self._refresh_view()

    def _on_stop(self):
        if self.scanner:
            self.scanner.stop()

    def _clear_results(self):
        for e in self.entries:
            e["row"].destroy()
        self.entries = []
        self.var_progress.set("")
        self.progress.set(0)
        self._update_count(0)
        self.empty_label.pack(pady=20)

    @staticmethod
    def _is_ubnt(result) -> bool:
        return "ubiquiti" in (result.get("vendor") or "").lower()

    def _add_result(self, result):
        if self.empty_label.winfo_ismapped():
            self.empty_label.pack_forget()

        var = ctk.BooleanVar(value=True)
        row = ctk.CTkFrame(self.results_scroll, fg_color="transparent", corner_radius=4)
        entry = {"data": result, "var": var, "row": row}

        ctk.CTkCheckBox(
            row, text="", variable=var, width=36,
            checkbox_width=18, checkbox_height=18,
        ).pack(side="left")

        vendor = result.get("vendor", "") or "—"
        is_ubnt = self._is_ubnt(result)
        cells = [
            (result["ip"], FONT_LABEL, TEXT_ON_CARD),
            (result.get("mac", "") or "—", FONT_MONO, TEXT_DIM),
            (vendor, FONT_LABEL, SUCCESS if is_ubnt else TEXT_DIM),
            (", ".join(str(p) for p in result.get("ports", [])), FONT_LABEL, TEXT_ON_CARD),
            ((result.get("banner", "") or "")[:60], FONT_SMALL, TEXT_DIM),
        ]
        widgets = [row]
        for (key, _title, width), (text, font, color) in zip(COLUMNS, cells):
            lbl = ctk.CTkLabel(
                row, text=text, width=width, font=font, anchor="w", text_color=color,
            )
            lbl.pack(side="left")
            widgets.append(lbl)

        for w in widgets:
            w.bind("<Button-3>", lambda ev, en=entry: self._show_menu(ev, en))
            w.bind("<Double-Button-1>", lambda ev, v=var: v.set(not v.get()))

        self.entries.append(entry)
        self._schedule_refresh()

    # ── Sort / filter / render ───────────────────────────────

    def _on_sort(self, key):
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, False
        self._update_header_labels()
        self._refresh_view()

    def _update_header_labels(self):
        for key, (btn, title) in self._header_btns.items():
            if key == self.sort_key:
                arrow = " ▼" if self.sort_desc else " ▲"
                btn.configure(text=title + arrow, text_color=TEXT_ON_CARD)
            else:
                btn.configure(text=title, text_color=TEXT_DIM)

    def _schedule_refresh(self):
        # Coalesce bursts (scan results, keystrokes) into one redraw.
        if not self._refresh_pending:
            self._refresh_pending = True
            self.after(120, self._refresh_view)

    def _visible_entries(self):
        terms = self.search_entry.get().strip().lower().split()
        only_ubnt = self.var_only_ubnt.get()
        visible = [
            e for e in self.entries
            if (not only_ubnt or self._is_ubnt(e["data"]))
            and (not terms or _matches(e["data"], terms))
        ]
        key = self.sort_key
        filled = [e for e in visible if _sort_key(e["data"], key) not in ("", ())]
        blank = [e for e in visible if _sort_key(e["data"], key) in ("", ())]
        filled.sort(
            key=lambda e: (_sort_key(e["data"], key), _sort_key(e["data"], "ip")),
            reverse=self.sort_desc,
        )
        blank.sort(key=lambda e: _sort_key(e["data"], "ip"))
        return filled + blank  # devices without a MAC/vendor always go last

    def _refresh_view(self):
        self._refresh_pending = False
        visible = self._visible_entries()
        for e in self.entries:
            e["row"].pack_forget()
        for i, e in enumerate(visible):
            e["row"].configure(fg_color=ROW_STRIPE if i % 2 == 0 else "transparent")
            e["row"].pack(fill="x", pady=1)
        self._update_count(len(visible))
        if self.entries and not visible:
            self.empty_label.configure(text="No devices match your search.")
            self.empty_label.pack(pady=20)
        elif self.entries:
            self.empty_label.pack_forget()

    def _update_count(self, shown):
        total = len(self.entries)
        if not total:
            self.var_count.set("")
        elif shown == total:
            self.var_count.set(f"{total} device(s)")
        else:
            self.var_count.set(f"Showing {shown} of {total}")

    def _clear_search(self):
        self.search_entry.delete(0, "end")
        self.focus_set()  # drop focus so the placeholder text comes back
        self._refresh_view()

    # ── Selection helpers ────────────────────────────────────

    def _select_all(self):
        for e in self._visible_entries():
            e["var"].set(True)

    def _deselect_all(self):
        for e in self._visible_entries():
            e["var"].set(False)

    def _selected(self):
        """Ticked rows that are currently visible, in on-screen order."""
        return [e["data"] for e in self._visible_entries() if e["var"].get()]

    def _copy(self, text: str, what: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log(f"Copied {what} to clipboard.")

    def _copy_selected(self, field):
        values = [r.get(field, "") for r in self._selected() if r.get(field)]
        if not values:
            self.log("Nothing selected to copy.")
            return
        self._copy("\n".join(values), f"{len(values)} {field.upper()}(s)")

    def _export_csv(self):
        rows = [e["data"] for e in self._visible_entries()]
        if not rows:
            self.log("No results to export.")
            return
        path = filedialog.asksaveasfilename(
            title="Export scan results", defaultextension=".csv",
            initialfile=f"unifi-scan-{datetime.now():%Y%m%d-%H%M%S}.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["IP", "MAC", "Manufacturer", "Open Ports", "SSH Banner"])
                for r in rows:
                    w.writerow([
                        r.get("ip", ""), r.get("mac", ""), r.get("vendor", ""),
                        " ".join(str(p) for p in r.get("ports", [])),
                        r.get("banner", ""),
                    ])
            self.log(f"Exported {len(rows)} row(s) to {path}")
        except OSError as e:
            self.log(f"Export failed: {e}")

    # ── Right-click menu ─────────────────────────────────────

    def _show_menu(self, event, entry):
        r = entry["data"]
        m = self._menu
        m.delete(0, "end")
        m.add_command(label=f"Copy IP  ({r['ip']})",
                      command=lambda: self._copy(r["ip"], "IP"))
        if r.get("mac"):
            m.add_command(label=f"Copy MAC  ({r['mac']})",
                          command=lambda: self._copy(r["mac"], "MAC"))
        m.add_separator()
        ports = r.get("ports", [])
        if 443 in ports or 8443 in ports:
            port = "" if 443 in ports else ":8443"
            m.add_command(label="Open web UI (https)",
                          command=lambda: webbrowser.open(f"https://{r['ip']}{port}"))
        if 8080 in ports:
            m.add_command(label="Open http://:8080",
                          command=lambda: webbrowser.open(f"http://{r['ip']}:8080"))
        m.add_command(label="Adopt this device",
                      command=lambda: self._adopt([r["ip"]]))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    # ── Adoption bridge ──────────────────────────────────────

    def _adopt_selected(self):
        self._adopt([r["ip"] for r in self._selected()])

    def _adopt(self, ips):
        if not ips:
            self.log("No devices selected.")
            return
        self.log(f"Sending {len(ips)} device(s) to SSH tab for adoption ...")
        if self.on_adopt_selected:
            self.on_adopt_selected(ips)
