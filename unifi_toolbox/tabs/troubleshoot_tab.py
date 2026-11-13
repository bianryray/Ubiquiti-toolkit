"""Troubleshooting tab -- run common diagnostic commands per device type.

Keeps it simple: pick a device type, click a button for the command you want
to run. Results go to the shared log panel. Includes a 'Run via telnet
localhost' option since some Ubiquiti config commands only work from inside
the local CLI session.
"""

import threading
from typing import List, Tuple

import customtkinter as ctk

from ..core.ssh_manager import SSHManager
from ..utils import DEFAULT_SSH_PORT, SSHOptions, LogFn
from .. import theme as T


# -- Command catalog per device type ---------------------------------------
# Each entry is (button label, command, needs_telnet_wrap).
# A row with an empty command is rendered as a section divider label.

CONSOLE_CMDS: List[Tuple[str, str, bool]] = [
    ("Device Info",             "info",                                        False),
    ("UniFi OS Info",           "ubnt-device-info summary",                    False),
    ("Network Interfaces",      "ip -br addr",                                 False),
    ("Routing Table",           "ip route show",                               False),
    ("ARP / Neighbors",         "ip neigh show",                               False),
    ("DNS Config",              "cat /etc/resolv.conf",                        False),
    ("UniFi Service Status",    "systemctl status unifi --no-pager",           False),
    ("Server Log (tail 60)",    "tail -n 60 /var/log/unifi/server.log",        False),
    ("Kernel Log (tail)",       "dmesg | tail -n 40",                          False),
    ("CPU / Memory",            "top -b -n 1 | head -n 20",                    False),
    ("Disk Usage",              "df -h",                                       False),
    ("— CLI commands (via telnet localhost) —", "", False),
    ("Show Firewall All",       "show firewall all",                           True),
    ("Show Interfaces",         "show interfaces",                             True),
    ("Show VPN IPsec Status",   "show vpn ipsec status",                       True),
    ("Show Configuration",      "show configuration",                          True),
    ("Show DHCP Leases",        "show dhcp leases",                            True),
    ("Ping 8.8.8.8",            "ping 8.8.8.8 count 4",                        True),
]

AP_CMDS: List[Tuple[str, str, bool]] = [
    ("Device Info",             "info",                                        False),
    ("Adoption Status",         "cat /proc/ubnthal/status",                    False),
    ("Connected Stations",      "stainfo",                                     False),
    ("Wireless (iwconfig)",     "iwconfig 2>&1",                               False),
    ("Radio Info (iwinfo)",     "iwinfo",                                      False),
    ("Bridges",                 "brctl show",                                  False),
    ("Interfaces",              "ifconfig -a",                                 False),
    ("ARP Table",               "arp -a",                                      False),
    ("System Log (tail)",       "tail -n 60 /var/log/messages 2>/dev/null || "
                                "logread | tail -n 60",                        False),
    ("Ping Gateway",            "gw=$(ip route | awk '/default/ {print $3; "
                                "exit}'); ping -c 4 \"$gw\"",                  False),
    ("Ping 8.8.8.8",            "ping -c 4 8.8.8.8",                           False),
    ("Uptime / Load",           "uptime",                                      False),
    ("Memory",                  "free -m 2>/dev/null || cat /proc/meminfo "
                                "| head",                                       False),
]

SWITCH_CMDS: List[Tuple[str, str, bool]] = [
    ("Device Info",             "info",                                        False),
    ("Adoption Status",         "cat /proc/ubnthal/status",                    False),
    ("Port Status",             "swctrl port show 2>&1",                       False),
    ("PoE Status",              "swctrl poe show 2>&1",                        False),
    ("VLAN Config",             "swctrl vlan show 2>&1",                       False),
    ("Bridges",                 "brctl show",                                  False),
    ("Interfaces",              "ifconfig -a",                                 False),
    ("ARP Table",               "arp -a",                                      False),
    ("System Log (tail)",       "tail -n 60 /var/log/messages 2>/dev/null || "
                                "logread | tail -n 60",                        False),
    ("Ping Gateway",            "gw=$(ip route | awk '/default/ {print $3; "
                                "exit}'); ping -c 4 \"$gw\"",                  False),
    ("Uptime / Load",           "uptime",                                      False),
]

CATALOG = {
    "Console (UDM / UDR / UXG)": CONSOLE_CMDS,
    "Access Point (UAP)":        AP_CMDS,
    "Switch (USW)":              SWITCH_CMDS,
}


def wrap_with_telnet(cmd: str) -> str:
    """Feed a command into the local telnet session non-interactively.

    Ubiquiti devices often expose their config/CLI shell via
    `telnet localhost`. We pipe the command in, give it a moment to respond,
    then `exit`.
    """
    safe = cmd.replace("'", "'\\''")
    return (
        "(sleep 1; echo '" + safe + "'; sleep 2; echo exit; sleep 1) "
        "| telnet localhost 2>&1"
    )


class TroubleshootTab(ctk.CTkFrame):
    """Tab with one-click diagnostic commands grouped by device type."""

    def __init__(self, parent, log_fn: LogFn, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.log = log_fn
        self._build_ui()

    def _build_ui(self):
        page = T.scroll_page(self)
        T.page_header(
            page, "Troubleshoot",
            "One-click diagnostics over SSH. Output goes to the activity log.",
        )

        # ── Connection ──────────────────────────────────────
        conn = T.card(page, "Device")
        g = ctk.CTkFrame(conn, fg_color="transparent")
        g.pack(fill="x")
        self.var_ip = ctk.StringVar()
        self.var_user = ctk.StringVar(value="ubnt")
        self.var_pass = ctk.StringVar()
        self.var_port = ctk.StringVar(value=str(DEFAULT_SSH_PORT))
        T.field(g, 0, 0, "DEVICE IP", lambda c: T.entry(c, self.var_ip, width=200))
        self.ent_user = T.field(g, 0, 1, "USERNAME",
                                lambda c: T.entry(c, self.var_user, width=170)).input
        self.ent_pass = T.field(g, 0, 2, "PASSWORD",
                                lambda c: T.entry(c, self.var_pass, width=170, show="\u2022")).input
        T.field(g, 0, 3, "SSH PORT", lambda c: T.entry(c, self.var_port, width=80))
        self.var_default_creds = ctk.BooleanVar(value=False)
        T.switch(conn, "Use default ubnt / ubnt", self.var_default_creds,
                 self._on_toggle_default_creds).pack(anchor="w")

        # ── Commands ────────────────────────────────────────
        cmds, cmds_actions = T.card(page, "Diagnostic Commands",
                                    "Pick the device type, then click a command", actions=True)
        self.var_dtype = ctk.StringVar(value="Console (UDM / UDR / UXG)")
        T.segmented(
            cmds_actions, list(CATALOG.keys()),
            var=self.var_dtype, command=self._on_dtype_change,
        ).pack(side="right")
        self.cmds_frame = ctk.CTkFrame(cmds, fg_color="transparent")
        self.cmds_frame.pack(fill="x")
        self._render_buttons(self.var_dtype.get())

        # ── Custom command ──────────────────────────────────
        custom = T.card(
            page, "Custom Command",
            "The config CLI (show interfaces, show configuration, ...) lives behind "
            "`telnet localhost` - tick the box to pipe your command into it.",
        )
        crow = T.row(custom)
        self.var_custom = ctk.StringVar(value="")
        ce = T.entry(crow, self.var_custom, width=420, mono=True)
        ce.pack(side="left", padx=(0, 10))
        ce.bind("<Return>", lambda e: self._on_run_custom())
        self.var_telnet = ctk.BooleanVar(value=False)
        T.checkbox(crow, "Run via telnet localhost", self.var_telnet).pack(side="left", padx=(0, 12))
        T.button(crow, "Run", self._on_run_custom, kind="primary", width=80).pack(side="left")

    # ── Helpers ────────────────────────────────────────────

    def _on_toggle_default_creds(self):
        if self.var_default_creds.get():
            self.var_user.set("ubnt")
            self.var_pass.set("ubnt")
            self.ent_user.configure(state="disabled")
            self.ent_pass.configure(state="disabled")
        else:
            self.ent_user.configure(state="normal")
            self.ent_pass.configure(state="normal")

    def _on_dtype_change(self, _value):
        self._render_buttons(self.var_dtype.get())

    def _render_buttons(self, dtype: str):
        for w in self.cmds_frame.winfo_children():
            w.destroy()

        grid = ctk.CTkFrame(self.cmds_frame, fg_color="transparent")
        grid.pack(fill="x")
        col_count = 3
        for c in range(col_count):
            grid.columnconfigure(c, weight=1, uniform="cmd")

        col = row = 0
        for label, cmd, telnet in CATALOG.get(dtype, []):
            if not cmd:  # divider row
                if col:
                    row, col = row + 1, 0
                T.label(grid, label.strip("— ").upper(), dim=True, small=True,
                        bold=True).grid(row=row, column=0, columnspan=col_count,
                                        sticky="w", pady=(12, 4))
                row += 1
                continue
            T.button(
                grid, label,
                lambda c=cmd, t=telnet, l=label: self._on_run_cmd(l, c, t),
                kind="secondary", anchor="w",
            ).grid(row=row, column=col, padx=(0, 8), pady=4, sticky="ew")
            col += 1
            if col >= col_count:
                col, row = 0, row + 1

    def _get_port(self) -> int:
        try:
            return int(self.var_port.get().strip())
        except ValueError:
            return DEFAULT_SSH_PORT

    def _make_ssh(self) -> SSHManager:
        ip = self.var_ip.get().strip()
        user = self.var_user.get().strip()
        pwd = self.var_pass.get()
        if not ip or not user:
            raise ValueError("Device IP and username are required.")
        return SSHManager(
            ip, user, pwd,
            port=self._get_port(),
            log=self.log,
            options=SSHOptions(),
        )

    def _on_run_cmd(self, label: str, cmd: str, telnet: bool):
        final = wrap_with_telnet(cmd) if telnet else cmd

        def worker():
            try:
                ssh = self._make_ssh()
            except Exception as e:
                self.log(f"Error: {e}")
                return
            self.log(f"\n--- {label} ---")
            ssh.run_visible(final)

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_custom(self):
        cmd = self.var_custom.get().strip()
        if not cmd:
            self.log("Enter a command.")
            return
        final = wrap_with_telnet(cmd) if self.var_telnet.get() else cmd

        def worker():
            try:
                ssh = self._make_ssh()
            except Exception as e:
                self.log(f"Error: {e}")
                return
            self.log(f"\n--- custom: {cmd} ---")
            ssh.run_visible(final)

        threading.Thread(target=worker, daemon=True).start()
