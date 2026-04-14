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

# Shared palette (match other tabs)
_CARD = "#2a2a3e"
_ACCENT = "#0f3460"
_ACCENT_HOVER = "#1a4a70"
_DIM = "#8a8a9a"
_LABEL_FONT = ("Segoe UI", 12)
_HEADING_FONT = ("Segoe UI", 13, "bold")
_SMALL = ("Segoe UI", 11)
_ENTRY_W = 240


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
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # ── Connection ──────────────────────────────────────
        conn = _section(scroll, "Connection")
        grid = ctk.CTkFrame(conn, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 10))
        grid.columnconfigure(1, weight=1)

        ctk.CTkLabel(grid, text="Device IP", font=_LABEL_FONT, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_ip = ctk.StringVar()
        ctk.CTkEntry(grid, textvariable=self.var_ip, width=_ENTRY_W, height=32).grid(
            row=0, column=1, sticky="w", pady=4)

        ctk.CTkLabel(grid, text="Username", font=_LABEL_FONT, anchor="e").grid(
            row=1, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_user = ctk.StringVar(value="ubnt")
        self.ent_user = ctk.CTkEntry(grid, textvariable=self.var_user,
                                     width=_ENTRY_W, height=32)
        self.ent_user.grid(row=1, column=1, sticky="w", pady=4)

        ctk.CTkLabel(grid, text="Password", font=_LABEL_FONT, anchor="e").grid(
            row=2, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_pass = ctk.StringVar()
        self.ent_pass = ctk.CTkEntry(
            grid, textvariable=self.var_pass, show="*",
            width=_ENTRY_W, height=32,
        )
        self.ent_pass.grid(row=2, column=1, sticky="w", pady=4)

        self.var_default_creds = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            grid, text="Use default ubnt / ubnt",
            variable=self.var_default_creds,
            command=self._on_toggle_default_creds,
            font=_SMALL, checkbox_width=18, checkbox_height=18,
        ).grid(row=2, column=2, sticky="w", padx=(16, 0), pady=4)

        ctk.CTkLabel(grid, text="SSH Port", font=_LABEL_FONT, anchor="e").grid(
            row=3, column=0, sticky="e", padx=(0, 10), pady=4)
        self.var_port = ctk.StringVar(value=str(DEFAULT_SSH_PORT))
        ctk.CTkEntry(grid, textvariable=self.var_port, width=80, height=32).grid(
            row=3, column=1, sticky="w", pady=4)

        # ── Device type ─────────────────────────────────────
        dtype_card = _section(scroll, "Device Type")
        dtype_row = ctk.CTkFrame(dtype_card, fg_color="transparent")
        dtype_row.pack(fill="x", padx=14, pady=(0, 10))

        self.var_dtype = ctk.StringVar(value="Console (UDM / UDR / UXG)")
        self.dtype_menu = ctk.CTkSegmentedButton(
            dtype_row, values=list(CATALOG.keys()),
            variable=self.var_dtype, command=self._on_dtype_change,
            font=_LABEL_FONT,
        )
        self.dtype_menu.pack(fill="x")

        # ── Command buttons ─────────────────────────────────
        self.cmds_card = _section(scroll, "Diagnostic Commands")
        self.cmds_frame = ctk.CTkFrame(self.cmds_card, fg_color="transparent")
        self.cmds_frame.pack(fill="x", padx=14, pady=(0, 10))

        self._render_buttons(self.var_dtype.get())

        # ── Custom command ──────────────────────────────────
        custom = _section(scroll, "Custom Command")
        crow = ctk.CTkFrame(custom, fg_color="transparent")
        crow.pack(fill="x", padx=14, pady=(0, 10))

        self.var_custom = ctk.StringVar(value="")
        ctk.CTkEntry(
            crow, textvariable=self.var_custom, width=420, height=32,
            placeholder_text="e.g. show interfaces",
        ).pack(side="left", padx=(0, 8))

        self.var_telnet = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            crow, text="Run via telnet localhost", variable=self.var_telnet,
            font=_SMALL, checkbox_width=18, checkbox_height=18,
        ).pack(side="left", padx=(0, 12))

        ctk.CTkButton(
            crow, text="Run", command=self._on_run_custom,
            width=80, height=32, font=_LABEL_FONT,
            fg_color=_ACCENT, hover_color=_ACCENT_HOVER,
        ).pack(side="left")

        # ── Help note ───────────────────────────────────────
        help_note = ctk.CTkFrame(scroll, fg_color="transparent")
        help_note.pack(fill="x", padx=4, pady=(4, 0))
        ctk.CTkLabel(
            help_note,
            text=(
                "Tip: on Ubiquiti devices the config CLI (show firewall, "
                "show interfaces, show configuration, etc.) is a separate "
                "shell you get to via `telnet localhost` after SSHing in. "
                "Check 'Run via telnet localhost' to pipe the command into "
                "that shell automatically."
            ),
            font=_SMALL, text_color=_DIM, wraplength=900, justify="left",
        ).pack(anchor="w")

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

        entries = CATALOG.get(dtype, [])
        grid = ctk.CTkFrame(self.cmds_frame, fg_color="transparent")
        grid.pack(fill="x")
        col_count = 3

        col = 0
        row = 0
        for label, cmd, telnet in entries:
            # Divider rows
            if not cmd:
                if col != 0:
                    row += 1
                    col = 0
                ctk.CTkLabel(
                    grid, text=label, font=_SMALL, text_color=_DIM, anchor="w",
                ).grid(row=row, column=0, columnspan=col_count,
                       sticky="w", padx=4, pady=(10, 4))
                row += 1
                continue

            ctk.CTkButton(
                grid, text=label,
                command=lambda c=cmd, t=telnet, l=label: self._on_run_cmd(l, c, t),
                width=230, height=32, font=_LABEL_FONT,
                fg_color=_ACCENT, hover_color=_ACCENT_HOVER,
            ).grid(row=row, column=col, padx=4, pady=4, sticky="w")
            col += 1
            if col >= col_count:
                col = 0
                row += 1

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
