import threading

import customtkinter as ctk

from ..core.discovery import NetworkScanner, get_local_subnets
from ..utils import LogFn

# Shared palette
_CARD = "#2a2a3e"
_ACCENT = "#0f3460"
_GREEN = "#00b894"
_GREEN_HOVER = "#00a381"
_RED = "#e94560"
_RED_HOVER = "#c73e54"
_DIM = "#8a8a9a"
_LABEL_FONT = ("Segoe UI", 12)
_HEADING_FONT = ("Segoe UI", 13, "bold")


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
        ctrl_card = _section(self, "Network Scan")
        row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(row, text="Subnet", font=_LABEL_FONT).pack(side="left", padx=(0, 8))
        self.var_subnet = ctk.StringVar()
        subnets = get_local_subnets()
        if subnets:
            self.var_subnet.set(subnets[0])
        ctk.CTkEntry(
            row, textvariable=self.var_subnet, width=200, height=32,
        ).pack(side="left", padx=(0, 8))

        self.btn_scan = ctk.CTkButton(
            row, text="Scan", command=self._on_scan,
            width=80, height=32, font=("Segoe UI", 12, "bold"),
            fg_color=_GREEN, hover_color=_GREEN_HOVER, text_color="#1a1a2e",
        )
        self.btn_scan.pack(side="left", padx=(0, 8))

        self.btn_stop = ctk.CTkButton(
            row, text="Stop", command=self._on_stop,
            width=80, height=32, font=_LABEL_FONT,
            fg_color=_RED, hover_color=_RED_HOVER,
        )
        self.btn_stop.pack(side="left", padx=(0, 12))

        self.var_progress = ctk.StringVar(value="")
        ctk.CTkLabel(
            row, textvariable=self.var_progress,
            font=("Segoe UI", 11), text_color=_DIM,
        ).pack(side="left")

        # ── Results ──────────────────────────────────────────
        results_card = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=8)
        results_card.pack(fill="both", expand=True, padx=4, pady=(0, 8))

        results_header = ctk.CTkFrame(results_card, fg_color="transparent")
        results_header.pack(fill="x", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            results_header, text="Discovered Devices", font=_HEADING_FONT,
            text_color="#ffffff",
        ).pack(side="left")

        sep = ctk.CTkFrame(results_card, height=1, fg_color="#3a3a4e")
        sep.pack(fill="x", padx=14, pady=(0, 4))

        # Column headers
        header = ctk.CTkFrame(results_card, fg_color="#222236", corner_radius=0)
        header.pack(fill="x", padx=14, pady=(0, 2))
        ctk.CTkLabel(header, text="", width=36).pack(side="left")
        ctk.CTkLabel(header, text="IP Address", width=160, font=("Segoe UI", 11, "bold"),
                      text_color=_DIM, anchor="w").pack(side="left")
        ctk.CTkLabel(header, text="Open Ports", width=160, font=("Segoe UI", 11, "bold"),
                      text_color=_DIM, anchor="w").pack(side="left")
        ctk.CTkLabel(header, text="SSH Banner", width=320, font=("Segoe UI", 11, "bold"),
                      text_color=_DIM, anchor="w").pack(side="left")

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
            width=90, height=32, font=_LABEL_FONT,
            fg_color="transparent", hover_color="#3a3a4e",
            border_width=1, border_color="#4a4a5e",
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            bottom, text="Deselect All", command=self._deselect_all,
            width=100, height=32, font=_LABEL_FONT,
            fg_color="transparent", hover_color="#3a3a4e",
            border_width=1, border_color="#4a4a5e",
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            bottom, text="Adopt Selected", command=self._adopt_selected,
            width=140, height=32, font=("Segoe UI", 12, "bold"),
            fg_color=_GREEN, hover_color=_GREEN_HOVER, text_color="#1a1a2e",
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
        for widget in self.results_scroll.winfo_children():
            widget.destroy()
        self.var_progress.set("")

    def _add_result(self, result):
        self.results.append(result)
        var = ctk.BooleanVar(value=True)
        self.check_vars.append(var)

        idx = len(self.results) - 1
        bg = "#282840" if idx % 2 == 0 else "transparent"
        row = ctk.CTkFrame(self.results_scroll, fg_color=bg, corner_radius=4)
        row.pack(fill="x", pady=1)

        ctk.CTkCheckBox(
            row, text="", variable=var, width=36,
            checkbox_width=18, checkbox_height=18,
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=result["ip"], width=160, font=_LABEL_FONT, anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=", ".join(str(p) for p in result["ports"]),
            width=160, font=_LABEL_FONT, anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=result.get("banner", "")[:60],
            width=320, font=("Segoe UI", 11), anchor="w", text_color=_DIM,
        ).pack(side="left")

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
