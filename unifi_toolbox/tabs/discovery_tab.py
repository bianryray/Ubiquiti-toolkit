import threading

import customtkinter as ctk

from ..core.discovery import NetworkScanner, get_local_subnets
from ..utils import LogFn
from ..theme import (
    BG_CARD, BG_CARD_ALT, SEPARATOR, BORDER, TEXT_ON_CARD, TEXT_DIM,
    SUCCESS, SUCCESS_HOVER, TEXT_ON_SUCCESS, DANGER, DANGER_HOVER,
    GHOST_HOVER, ROW_STRIPE,
    FONT_LABEL, FONT_HEADING, FONT_SMALL, FONT_SMALL_BOLD, FONT_BTN_BOLD,
    section_card,
)


class DiscoveryTab(ctk.CTkFrame):
    """Network discovery tab -- scan for Ubiquiti devices on the LAN."""

    def __init__(self, parent, log_fn: LogFn, on_adopt_selected=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.log = log_fn
        self.on_adopt_selected = on_adopt_selected
        self.scanner = None
        self.results = []
        self.check_vars = []
        self._build_ui()

    def _build_ui(self):
        # ── Scan controls ────────────────────────────────────
        ctrl_card = section_card(self, "Network Scan")
        row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(row, text="Subnet", font=FONT_LABEL).pack(side="left", padx=(0, 8))
        self.var_subnet = ctk.StringVar()
        subnets = get_local_subnets()
        if subnets:
            self.var_subnet.set(subnets[0])
        ctk.CTkEntry(
            row, textvariable=self.var_subnet, width=200, height=32,
        ).pack(side="left", padx=(0, 8))

        self.btn_scan = ctk.CTkButton(
            row, text="Scan", command=self._on_scan,
            width=80, height=32, font=FONT_BTN_BOLD,
            fg_color=SUCCESS, hover_color=SUCCESS_HOVER, text_color=TEXT_ON_SUCCESS,
        )
        self.btn_scan.pack(side="left", padx=(0, 8))

        self.btn_stop = ctk.CTkButton(
            row, text="Stop", command=self._on_stop,
            width=80, height=32, font=FONT_LABEL,
            fg_color=DANGER, hover_color=DANGER_HOVER,
        )
        self.btn_stop.pack(side="left", padx=(0, 12))

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

        sep = ctk.CTkFrame(results_card, height=1, fg_color=SEPARATOR)
        sep.pack(fill="x", padx=14, pady=(0, 4))

        # Column headers
        header = ctk.CTkFrame(results_card, fg_color=BG_CARD_ALT, corner_radius=0)
        header.pack(fill="x", padx=14, pady=(0, 2))
        ctk.CTkLabel(header, text="", width=36).pack(side="left")
        ctk.CTkLabel(header, text="IP Address", width=140, font=FONT_SMALL_BOLD,
                      text_color=TEXT_DIM, anchor="w").pack(side="left")
        ctk.CTkLabel(header, text="MAC", width=150, font=FONT_SMALL_BOLD,
                      text_color=TEXT_DIM, anchor="w").pack(side="left")
        ctk.CTkLabel(header, text="Manufacturer", width=180, font=FONT_SMALL_BOLD,
                      text_color=TEXT_DIM, anchor="w").pack(side="left")
        ctk.CTkLabel(header, text="Open Ports", width=120, font=FONT_SMALL_BOLD,
                      text_color=TEXT_DIM, anchor="w").pack(side="left")
        ctk.CTkLabel(header, text="SSH Banner", width=240, font=FONT_SMALL_BOLD,
                      text_color=TEXT_DIM, anchor="w").pack(side="left")

        # Scrollable results
        self.results_scroll = ctk.CTkScrollableFrame(
            results_card, fg_color="transparent",
        )
        self.results_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        # ── Bottom actions ───────────────────────────────────
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=4, pady=(0, 4))

        ctk.CTkButton(
            bottom, text="Select All", command=self._select_all,
            width=90, height=32, font=FONT_LABEL,
            fg_color="transparent", hover_color=GHOST_HOVER,
            border_width=1, border_color=BORDER, text_color=TEXT_ON_CARD,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            bottom, text="Deselect All", command=self._deselect_all,
            width=100, height=32, font=FONT_LABEL,
            fg_color="transparent", hover_color=GHOST_HOVER,
            border_width=1, border_color=BORDER, text_color=TEXT_ON_CARD,
        ).pack(side="left", padx=(0, 6))

        self.var_only_ubnt = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            bottom, text="Only Ubiquiti", variable=self.var_only_ubnt,
            command=self._apply_filter, font=FONT_LABEL,
            checkbox_width=18, checkbox_height=18, text_color=TEXT_ON_CARD,
        ).pack(side="left", padx=(6, 12))

        ctk.CTkButton(
            bottom, text="Adopt Selected", command=self._adopt_selected,
            width=140, height=32, font=FONT_BTN_BOLD,
            fg_color=SUCCESS, hover_color=SUCCESS_HOVER, text_color=TEXT_ON_SUCCESS,
        ).pack(side="left")

    # ── Scan logic ───────────────────────────────────────────

    def _on_scan(self):
        subnet = self.var_subnet.get().strip()
        if not subnet:
            self.log("Enter a subnet to scan.")
            return

        self._clear_results()
        self.btn_scan.configure(state="disabled")
        self.scanner = NetworkScanner(log=self.log, max_workers=50)

        def on_found(result):
            self.after(0, lambda r=result: self._add_result(r))

        def on_progress(scanned, total):
            self.after(0, lambda s=scanned, t=total: self.var_progress.set(f"{s}/{t} scanned"))

        def worker():
            try:
                self.scanner.scan_subnet(
                    subnet, on_found=on_found, on_progress=on_progress,
                )
            except Exception as e:
                self.log(f"Scan error: {e}")
            finally:
                self.after(0, lambda: self.btn_scan.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_stop(self):
        if self.scanner:
            self.scanner.stop()

    def _clear_results(self):
        self.results = []
        self.check_vars = []
        self._row_widgets = []
        for widget in self.results_scroll.winfo_children():
            widget.destroy()
        self.var_progress.set("")

    def _add_result(self, result):
        self.results.append(result)
        var = ctk.BooleanVar(value=True)
        self.check_vars.append(var)

        idx = len(self.results) - 1
        bg = ROW_STRIPE if idx % 2 == 0 else "transparent"
        row = ctk.CTkFrame(self.results_scroll, fg_color=bg, corner_radius=4)
        row.pack(fill="x", pady=1)
        if not hasattr(self, "_row_widgets"):
            self._row_widgets = []
        self._row_widgets.append(row)

        ctk.CTkCheckBox(
            row, text="", variable=var, width=36,
            checkbox_width=18, checkbox_height=18,
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=result["ip"], width=140, font=FONT_LABEL, anchor="w",
            text_color=TEXT_ON_CARD,
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=result.get("mac", "") or "—",
            width=150, font=FONT_LABEL, anchor="w", text_color=TEXT_DIM,
        ).pack(side="left")
        vendor = result.get("vendor", "") or "—"
        # Highlight Ubiquiti hits
        is_ubnt = "ubiquiti" in vendor.lower()
        ctk.CTkLabel(
            row, text=vendor, width=180, font=FONT_LABEL, anchor="w",
            text_color=(SUCCESS if is_ubnt else TEXT_DIM),
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=", ".join(str(p) for p in result["ports"]),
            width=120, font=FONT_LABEL, anchor="w", text_color=TEXT_ON_CARD,
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=result.get("banner", "")[:60],
            width=240, font=FONT_SMALL, anchor="w", text_color=TEXT_DIM,
        ).pack(side="left")

        # Honor "Only Ubiquiti" filter if currently enabled
        if self.var_only_ubnt.get() and not is_ubnt:
            row.pack_forget()

    def _apply_filter(self):
        only_ubnt = self.var_only_ubnt.get()
        if not hasattr(self, "_row_widgets"):
            return
        for i, row in enumerate(self._row_widgets):
            vendor = (self.results[i].get("vendor") or "").lower()
            if only_ubnt and "ubiquiti" not in vendor:
                row.pack_forget()
            else:
                row.pack(fill="x", pady=1)

    def _select_all(self):
        for var in self.check_vars:
            var.set(True)

    def _deselect_all(self):
        for var in self.check_vars:
            var.set(False)

    def _adopt_selected(self):
        selected = [
            self.results[i]["ip"]
            for i, var in enumerate(self.check_vars)
            if var.get()
        ]
        if not selected:
            self.log("No devices selected.")
            return
        self.log(f"Sending {len(selected)} device(s) to SSH tab for adoption ...")
        if self.on_adopt_selected:
            self.on_adopt_selected(selected)
