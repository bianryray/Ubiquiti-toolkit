import threading

import customtkinter as ctk

from ..core.discovery import NetworkScanner, get_local_subnets
from ..utils import LogFn


class DiscoveryTab(ctk.CTkFrame):
    """Network discovery tab — scan for Ubiquiti devices on the LAN."""

    def __init__(self, parent, log_fn: LogFn, on_adopt_selected=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.log = log_fn
        self.on_adopt_selected = on_adopt_selected
        self.scanner = None
        self.results = []
        self.check_vars = []
        self._build_ui()

    def _build_ui(self):
        # --- Scan controls ---
        ctrl_frame = ctk.CTkFrame(self)
        ctrl_frame.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkLabel(ctrl_frame, text="Network Discovery", font=("", 14, "bold")).pack(
            anchor="w", padx=10, pady=(5, 0)
        )

        row = ctk.CTkFrame(ctrl_frame)
        row.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(row, text="Subnet:").pack(side="left", padx=5)
        self.var_subnet = ctk.StringVar()
        subnets = get_local_subnets()
        if subnets:
            self.var_subnet.set(subnets[0])
        self.ent_subnet = ctk.CTkEntry(row, textvariable=self.var_subnet, width=200)
        self.ent_subnet.pack(side="left", padx=5)

        self.btn_scan = ctk.CTkButton(row, text="Scan", command=self._on_scan, width=80,
                                       fg_color="#2b7a0b", hover_color="#1e5a08")
        self.btn_scan.pack(side="left", padx=5)
        self.btn_stop = ctk.CTkButton(row, text="Stop", command=self._on_stop, width=80,
                                       fg_color="#a31515", hover_color="#7a1010")
        self.btn_stop.pack(side="left", padx=5)

        # Progress
        self.var_progress = ctk.StringVar(value="")
        ctk.CTkLabel(row, textvariable=self.var_progress, font=("", 11)).pack(side="left", padx=10)

        # --- Results table ---
        results_frame = ctk.CTkFrame(self)
        results_frame.pack(fill="both", expand=True, padx=10, pady=5)
        ctk.CTkLabel(results_frame, text="Discovered Devices", font=("", 14, "bold")).pack(
            anchor="w", padx=10, pady=(5, 0)
        )

        # Header
        header = ctk.CTkFrame(results_frame)
        header.pack(fill="x", padx=10, pady=(5, 0))
        ctk.CTkLabel(header, text="", width=30).pack(side="left")
        ctk.CTkLabel(header, text="IP Address", width=150, font=("", 12, "bold")).pack(side="left")
        ctk.CTkLabel(header, text="Open Ports", width=150, font=("", 12, "bold")).pack(side="left")
        ctk.CTkLabel(header, text="SSH Banner", width=300, font=("", 12, "bold")).pack(side="left")

        # Scrollable results
        self.results_scroll = ctk.CTkScrollableFrame(results_frame, height=250)
        self.results_scroll.pack(fill="both", expand=True, padx=10, pady=5)

        # Bottom actions
        bottom = ctk.CTkFrame(self)
        bottom.pack(fill="x", padx=10, pady=(5, 10))

        ctk.CTkButton(bottom, text="Select All", command=self._select_all, width=90).pack(side="left", padx=5)
        ctk.CTkButton(bottom, text="Deselect All", command=self._deselect_all, width=100).pack(side="left", padx=5)
        ctk.CTkButton(
            bottom, text="Adopt Selected", command=self._adopt_selected,
            fg_color="#2b7a0b", hover_color="#1e5a08", width=130
        ).pack(side="left", padx=5)

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
                    subnet, on_found=on_found, on_progress=on_progress
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

        row = ctk.CTkFrame(self.results_scroll)
        row.pack(fill="x", pady=1)

        ctk.CTkCheckBox(row, text="", variable=var, width=30).pack(side="left")
        ctk.CTkLabel(row, text=result["ip"], width=150).pack(side="left")
        ctk.CTkLabel(row, text=", ".join(str(p) for p in result["ports"]), width=150).pack(side="left")
        ctk.CTkLabel(row, text=result.get("banner", "")[:60], width=300).pack(side="left")

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
