"""Network Tests (BETA) page: area check + three kinds of speed test."""

import socket
import threading

import customtkinter as ctk

from ..core import nettest as N
from ..core.ssh_manager import SSHManager
from ..utils import DEFAULT_SSH_PORT, SSHOptions, LogFn
from .. import theme as T

_STATUS = {
    "ok": ("●", T.SUCCESS),
    "warn": ("●", T.WARNING),
    "bad": ("●", T.DANGER),
    "info": ("●", T.TEXT_FAINT),
}
_DURATIONS = {"5 s": 5, "10 s": 10, "20 s": 20}


def _beta_chip(parent):
    chip = ctk.CTkLabel(parent, text=" BETA ", font=T.FONT_SMALL_BOLD, corner_radius=6,
                        fg_color=T.WARNING, text_color="#1a1200")
    return chip


class ResultBox(ctk.CTkFrame):
    """Area where a test writes its outcome (findings, speeds, errors)."""

    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self.pack(fill="x", pady=(12, 0))

    def clear(self):
        for w in self.winfo_children():
            w.destroy()

    def running(self, text):
        self.clear()
        T.label(self, text, dim=True).pack(anchor="w")

    def error(self, text):
        self.clear()
        f = ctk.CTkFrame(self, fg_color=("#fdecec", "#2a1518"), corner_radius=T.RADIUS_SM)
        f.pack(fill="x")
        T.label(f, text, wraplength=820).pack(anchor="w", padx=14, pady=10)

    def verdict(self, text, status):
        colors = {"ok": (("#e8f7ee", "#10261a"), T.SUCCESS),
                  "warn": (("#fff6e5", "#2a2110"), T.WARNING),
                  "bad": (("#fdecec", "#2a1518"), T.DANGER)}
        bg, accent = colors.get(status, colors["warn"])
        f = ctk.CTkFrame(self, fg_color=bg, corner_radius=T.RADIUS_SM,
                         border_width=1, border_color=accent)
        f.pack(fill="x", pady=(0, 10))
        T.label(f, text, bold=True, wraplength=820).pack(anchor="w", padx=14, pady=10)

    def finding(self, status, title, detail=""):
        dot, color = _STATUS.get(status, _STATUS["info"])
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=dot, width=18, font=T.FONT_LABEL, text_color=color).pack(
            side="left", anchor="n")
        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", fill="x", expand=True)
        T.label(col, title, bold=True).pack(anchor="w")
        if detail:
            T.label(col, detail, dim=True, small=True, wraplength=780).pack(anchor="w")

    def speeds(self, results, note=""):
        self.clear()
        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.pack(fill="x")
        for r in results:
            t = ctk.CTkFrame(tiles, fg_color=T.BG_CARD_ALT, corner_radius=T.RADIUS_SM,
                             border_width=1, border_color=T.BORDER)
            t.pack(side="left", padx=(0, 10))
            T.label(t, r.label, dim=True, small=True).pack(anchor="w", padx=16, pady=(12, 0))
            ctk.CTkLabel(t, text=f"{r.mbps:,.0f} Mbps", font=("Segoe UI", 24, "bold"),
                         text_color=T.TEXT, anchor="w").pack(anchor="w", padx=16)
            T.label(t, f"{r.megabytes:,.0f} MB in {r.seconds:.1f} s", dim=True, small=True).pack(
                anchor="w", padx=16, pady=(0, 12))
        if note:
            T.label(self, note, dim=True, small=True, wraplength=820).pack(anchor="w", pady=(8, 0))


class NetTestTab(ctk.CTkFrame):
    def __init__(self, parent, log_fn: LogFn, get_ssh_login=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.log = log_fn
        self.get_ssh_login = get_ssh_login
        self._busy = False
        self._stop = threading.Event()
        self._peer = None
        self._run_buttons = []
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        page = self.page = T.scroll_page(self)
        head = ctk.CTkFrame(page, fg_color="transparent")
        head.pack(fill="x", padx=4, pady=(2, 14))
        title = ctk.CTkFrame(head, fg_color="transparent")
        title.pack(fill="x")
        ctk.CTkLabel(title, text="Network Tests", font=T.FONT_PAGE_TITLE,
                     text_color=T.TEXT).pack(side="left")
        _beta_chip(title).pack(side="left", padx=(10, 0), pady=(4, 0))
        T.autowrap(T.label(head, "Find out why an area is slow and measure real throughput "
                                 "between your gear. Experimental - compare results against a "
                                 "known-good test before relying on them.", dim=True)).pack(
            fill="x", pady=(2, 0))

        # Login + settings
        login = T.card(page, "Device Login", "SSH login used for the devices below")
        g = ctk.CTkFrame(login, fg_color="transparent")
        g.pack(fill="x")
        self.var_user = ctk.StringVar(value="ubnt")
        self.var_pass = ctk.StringVar()
        self.var_port = ctk.StringVar(value=str(DEFAULT_SSH_PORT))
        T.field(g, 0, 0, "USERNAME", lambda c: T.entry(c, self.var_user, width=170))
        T.field(g, 0, 1, "PASSWORD", lambda c: T.entry(c, self.var_pass, width=170, show="•"))
        T.field(g, 0, 2, "SSH PORT", lambda c: T.entry(c, self.var_port, width=70))
        self.var_duration = ctk.StringVar(value="10 s")
        T.field(g, 0, 3, "TEST LENGTH",
                lambda c: T.segmented(c, list(_DURATIONS), var=self.var_duration))
        self.var_test_port = ctk.StringVar(value=str(N.DEFAULT_TEST_PORT))
        T.field(g, 0, 4, "TEST PORT", lambda c: T.entry(c, self.var_test_port, width=80))

        r = T.row(login)
        self.var_gw_login = ctk.BooleanVar(value=False)
        T.switch(r, "Gateway uses a different login", self.var_gw_login,
                 self._toggle_gw_login).pack(side="left")
        T.button(r, "Use SSH Adoption login", self._copy_login, kind="ghost",
                 text_color=T.ACCENT).pack(side="right")
        self.gw_login = ctk.CTkFrame(login, fg_color="transparent")
        self.var_gw_user = ctk.StringVar(value="root")
        self.var_gw_pass = ctk.StringVar()
        T.field(self.gw_login, 0, 0, "GATEWAY USERNAME",
                lambda c: T.entry(c, self.var_gw_user, width=170))
        T.field(self.gw_login, 0, 1, "GATEWAY PASSWORD",
                lambda c: T.entry(c, self.var_gw_pass, width=170, show="•"))

        # Area check
        area = T.card(
            page, "Area Check",
            "Run it on the AP that serves the slow area. Checks the AP's link back to the "
            "gateway, the internet, DNS, its uplink (cable speed or mesh signal), Wi-Fi channel "
            "congestion, client signal and load - then says which one is the likely cause.",
        )
        ar = T.row(area)
        self.var_area_ip = ctk.StringVar()
        T.label(ar, "AP IP", bold=True).pack(side="left", padx=(0, 10))
        T.entry(ar, self.var_area_ip, width=200).pack(side="left", padx=(0, 10))
        self._run_buttons.append(T.button(ar, "Run Area Check", self._on_area, kind="primary"))
        self._run_buttons[-1].pack(side="left")
        self.area_result = ResultBox(area)

        # AP <-> gateway
        apgw = T.card(
            page, "AP ↔ Gateway Speed",
            "iperf3 between the AP and the gateway (UDM / UXG / UDR) in both directions - "
            "tests the AP's real path back without your PC or Wi-Fi in the way. "
            "Needs iperf3 on both devices; the app checks first.",
        )
        g2 = ctk.CTkFrame(apgw, fg_color="transparent")
        g2.pack(fill="x")
        self.var_gw_ip = ctk.StringVar()
        T.field(g2, 0, 0, "GATEWAY IP", lambda c: T.entry(c, self.var_gw_ip, width=180),
                hint="Filled in by Area Check")
        T.field(g2, 0, 1, "AP IP", lambda c: T.entry(c, self.var_area_ip, width=180))
        self._run_buttons.append(T.button(apgw, "Run AP ↔ Gateway Test", self._on_apgw,
                                          kind="primary"))
        self._run_buttons[-1].pack(anchor="w")
        self.apgw_result = ResultBox(apgw)

        # PC <-> device
        pcd = T.card(
            page, "PC ↔ Device Speed",
            "This PC listens; the device sends to it and receives from it. Works on any UniFi "
            "device you can SSH into. Windows may ask to allow UniFi Toolbox through the "
            "firewall the first time - allow it on Private networks.",
        )
        pr = T.row(pcd)
        self.var_dev_ip = ctk.StringVar()
        T.label(pr, "Device IP", bold=True).pack(side="left", padx=(0, 10))
        T.entry(pr, self.var_dev_ip, width=200).pack(side="left", padx=(0, 10))
        self._run_buttons.append(T.button(pr, "Run PC ↔ Device Test", self._on_pc_device,
                                          kind="primary"))
        self._run_buttons[-1].pack(side="left")
        self.pcd_result = ResultBox(pcd)

        # PC <-> PC
        pcpc = T.card(
            page, "PC ↔ PC Speed",
            "Run UniFi Toolbox on two computers. On one, turn on Listen. On the other, enter "
            "the first PC's IP and run the test. The most accurate way to measure the network "
            "itself.",
        )
        lr = T.row(pcpc, pady=(0, 10))
        self.var_listen = ctk.BooleanVar(value=False)
        T.switch(lr, "Listen for tests from another PC", self.var_listen,
                 self._toggle_listen).pack(side="left")
        self.var_listen_status = ctk.StringVar(value="")
        ctk.CTkLabel(lr, textvariable=self.var_listen_status, font=T.FONT_SMALL_BOLD,
                     text_color=T.ACCENT).pack(side="left", padx=(16, 0))
        tr = T.row(pcpc)
        self.var_peer_ip = ctk.StringVar()
        T.label(tr, "Other PC IP", bold=True).pack(side="left", padx=(0, 10))
        T.entry(tr, self.var_peer_ip, width=200).pack(side="left", padx=(0, 10))
        self._run_buttons.append(T.button(tr, "Run PC ↔ PC Test", self._on_pc_pc,
                                          kind="primary"))
        self._run_buttons[-1].pack(side="left")
        self.pcpc_result = ResultBox(pcpc)

        # Stop
        stop_row = T.row(page, pady=(0, 12))
        self.btn_stop = T.button(stop_row, "Stop Test", self._on_stop, kind="danger-outline",
                                 state="disabled")
        self.btn_stop.pack(side="left", padx=4)

    # ── Helpers ──────────────────────────────────────────────────

    def _toggle_gw_login(self):
        if self.var_gw_login.get():
            self.gw_login.pack(fill="x", pady=(10, 0))
        else:
            self.gw_login.pack_forget()

    def _copy_login(self):
        if not self.get_ssh_login:
            return
        user, pwd, port = self.get_ssh_login()
        self.var_user.set(user or "ubnt")
        self.var_pass.set(pwd or "")
        self.var_port.set(str(port or DEFAULT_SSH_PORT))
        self.log("Network Tests: using the SSH Adoption login.")

    def _int(self, var, default):
        try:
            return int(var.get().strip())
        except ValueError:
            return default

    def _quiet_log(self, msg):
        if not msg.startswith("SSH connected"):
            self.log(msg)

    def _ssh(self, ip, gateway=False):
        ip = ip.strip()
        if not ip:
            raise N.TestError("Enter an IP address first.")
        if gateway and self.var_gw_login.get():
            user, pwd = self.var_gw_user.get().strip(), self.var_gw_pass.get()
        else:
            user, pwd = self.var_user.get().strip(), self.var_pass.get()
        if not user:
            raise N.TestError("Enter the SSH username in Device Login.")
        return SSHManager(ip, user, pwd, port=self._int(self.var_port, DEFAULT_SSH_PORT),
                          log=self._quiet_log, options=SSHOptions())

    def _duration(self):
        return _DURATIONS.get(self.var_duration.get(), 10)

    def _run(self, box: ResultBox, start_text: str, work, done):
        """Run `work()` in a thread; `done(result)` on the UI thread."""
        if self._busy:
            self.log("A test is already running.")
            return
        self._busy = True
        self._stop.clear()
        for b in self._run_buttons:
            b.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        box.running(start_text)

        def worker():
            try:
                result, err = work(), None
            except N.TestError as e:
                result, err = None, str(e)
            except Exception as e:  # unexpected; still report it
                result, err = None, f"Unexpected error: {e}"
            self.after(0, lambda: self._finish(box, result, err, done))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, box, result, err, done):
        self._busy = False
        for b in self._run_buttons:
            b.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        if err:
            box.error(err)
            self.log(f"Test failed: {err}")
        else:
            done(result)

    def _on_stop(self):
        self._stop.set()
        self.log("Stopping test after the current step ...")

    # ── Tests ────────────────────────────────────────────────────

    def _on_area(self):
        ip = self.var_area_ip.get()

        def work():
            return N.area_check(self._ssh(ip), log=self.log)

        def done(rep):
            box = self.area_result
            box.clear()
            worst = "bad" if any(f.status == "bad" for f in rep.findings) else (
                "warn" if any(f.status == "warn" for f in rep.findings) else "ok")
            box.verdict(rep.verdict, worst)
            for f in rep.findings:
                box.finding(f.status, f.title, f.detail)
            if rep.gateway_ip and not self.var_gw_ip.get().strip():
                self.var_gw_ip.set(rep.gateway_ip)
            self.log(f"Area check done: {rep.verdict}")

        self._run(self.area_result, f"Checking {ip.strip()} - about 15 seconds ...", work, done)

    def _on_apgw(self):
        gw_ip, ap_ip = self.var_gw_ip.get().strip(), self.var_area_ip.get().strip()
        d = self._duration()

        def work():
            if not gw_ip:
                raise N.TestError("Enter the gateway IP (or run Area Check to fill it in).")
            return N.iperf_between(self._ssh(gw_ip, gateway=True), gw_ip, self._ssh(ap_ip),
                                   duration=d, server_name="Gateway", client_name="AP",
                                   log=self.log)

        def done(res):
            self.apgw_result.speeds(
                res, "Gateway → AP is what devices in this area download through. "
                     "Far below the AP's link speed points at the cabling or mesh link.")
            for r in res:
                self.log(f"  {r}")

        self._run(self.apgw_result, f"Testing for {d * 2 + 6} seconds ...", work, done)

    def _on_pc_device(self):
        ip = self.var_dev_ip.get().strip()
        d, port = self._duration(), self._int(self.var_test_port, N.DEFAULT_TEST_PORT)

        def work():
            return N.pc_device_test(self._ssh(ip), ip, duration=d, port=port,
                                    log=self.log, stop=self._stop)

        def done(res):
            self.pcd_result.speeds(
                res, "APs and switches have small CPUs, so they can top out before the link "
                     "does - a lower number here doesn't always mean a bad cable. Your PC's "
                     "own connection (e.g. Wi-Fi) is part of this path too.")
            for r in res:
                self.log(f"  {r}")

        self._run(self.pcd_result, f"Testing for about {d * 2 + 4} seconds ...", work, done)

    def _on_pc_pc(self):
        host = self.var_peer_ip.get().strip()
        d, port = self._duration(), self._int(self.var_test_port, N.DEFAULT_TEST_PORT)

        def work():
            if not host:
                raise N.TestError("Enter the other PC's IP address.")
            return N.peer_test(host, port, duration=d, stop=self._stop)

        def done(res):
            self.pcpc_result.speeds(res)
            for r in res:
                self.log(f"  {r}")

        self._run(self.pcpc_result, f"Testing for about {d * 2 + 2} seconds ...", work, done)

    def _toggle_listen(self):
        if self.var_listen.get():
            port = self._int(self.var_test_port, N.DEFAULT_TEST_PORT)
            try:
                self._peer = N.PeerServer(port, log=self.log)
            except N.TestError as e:
                self.var_listen.set(False)
                self.log(str(e))
                return
            ip = _my_ip()
            self.var_listen_status.set(f"Listening on {ip} : {port}  -  enter {ip} on the other PC")
            self.log(f"Listening for PC tests on {ip}:{port}")
        else:
            if self._peer:
                self._peer.close()
                self._peer = None
            self.var_listen_status.set("")
            self.log("Stopped listening for PC tests.")


def _my_ip() -> str:
    try:
        return N.local_ip_for("192.0.2.1")  # any off-box address picks the LAN interface
    except OSError:
        return socket.gethostbyname(socket.gethostname())
