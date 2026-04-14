"""MAC address discovery + OUI (manufacturer) lookup.

Why: a lot of unlabeled rows in the Discovery tab are actually printers, TVs,
phones, etc. Showing the manufacturer helps filter the real Ubiquiti devices
from everything else on the subnet.

Strategy:
  1. Once a host is confirmed up (at least one open TCP port), ping it to
     force an ARP-cache entry, then shell out to the OS `arp` tool to read
     the MAC. This works on Windows / macOS / Linux without any elevated
     privileges and without extra dependencies.
  2. Look up the first 3 bytes of the MAC (OUI) against a small bundled
     table. The table is Ubiquiti-heavy but also covers the usual suspects
     you'd see scanning a home / SMB network.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Optional

# -- Built-in OUI table -----------------------------------------------------
# First 6 hex chars of the MAC (uppercase, no separators) -> vendor name.
# Not exhaustive -- this is a pragmatic list for Ubiquiti networks. Users can
# still see "Unknown" for devices we don't recognise, which is fine.
_OUI_TABLE: dict[str, str] = {
    # ---- Ubiquiti (many ranges over the years) ----
    "002722": "Ubiquiti Networks",
    "00156D": "Ubiquiti Networks",
    "0418D6": "Ubiquiti Networks",
    "0CEA14": "Ubiquiti Networks",
    "18E829": "Ubiquiti Networks",
    "245A4C": "Ubiquiti Networks",
    "24A43C": "Ubiquiti Networks",
    "28704E": "Ubiquiti Networks",
    "44D9E7": "Ubiquiti Networks",
    "4C5E0C": "Ubiquiti Networks",
    "68725B": "Ubiquiti Networks",
    "68D79A": "Ubiquiti Networks",
    "702A0B": "Ubiquiti Networks",
    "74ACB9": "Ubiquiti Networks",
    "7483C2": "Ubiquiti Networks",
    "788A20": "Ubiquiti Networks",
    "802AA8": "Ubiquiti Networks",
    "9024E8": "Ubiquiti Networks",
    "942A6F": "Ubiquiti Networks",
    "B4FBE4": "Ubiquiti Networks",
    "DC9FDB": "Ubiquiti Networks",
    "E063DA": "Ubiquiti Networks",
    "E4383C": "Ubiquiti Networks",
    "F09FC2": "Ubiquiti Networks",
    "F492BF": "Ubiquiti Networks",
    "F4E2C6": "Ubiquiti Networks",
    "FCECDA": "Ubiquiti Networks",
    # ---- Common infrastructure ----
    "001B17": "Cisco",
    "0023DC": "Cisco",
    "0024F7": "Cisco",
    "001560": "Aruba / HPE",
    "001A1E": "Aruba / HPE",
    "6CF37F": "Aruba / HPE",
    "2CFDA1": "Aruba / HPE",
    "9C1C12": "Juniper",
    "001E79": "Mikrotik",
    "48A98A": "Mikrotik",
    "B869F4": "Mikrotik",
    "CC2DE0": "Mikrotik",
    "6C3B6B": "Mikrotik",
    # ---- TP-Link ----
    "001DAA": "TP-Link",
    "001D0F": "TP-Link",
    "144D67": "TP-Link",
    "30B5C2": "TP-Link",
    "50C7BF": "TP-Link",
    "6C5AB0": "TP-Link",
    "A42BB0": "TP-Link",
    "AC84C6": "TP-Link",
    "C0C9E3": "TP-Link",
    "E8DE27": "TP-Link",
    "F4F26D": "TP-Link",
    # ---- Netgear ----
    "000FB5": "Netgear",
    "001B2F": "Netgear",
    "0024B2": "Netgear",
    "20E52A": "Netgear",
    "28C68E": "Netgear",
    "30469A": "Netgear",
    "44A56E": "Netgear",
    "9C3DCF": "Netgear",
    "A040A0": "Netgear",
    # ---- ASUS ----
    "001FC6": "ASUS",
    "04D4C4": "ASUS",
    "0C9D92": "ASUS",
    "305A3A": "ASUS",
    "386077": "ASUS",
    "50465D": "ASUS",
    "704D7B": "ASUS",
    "AC220B": "ASUS",
    "E0CB4E": "ASUS",
    # ---- Apple ----
    "0003FF": "Apple",
    "0016CB": "Apple",
    "001B63": "Apple",
    "001EC2": "Apple",
    "002312": "Apple",
    "002332": "Apple",
    "002608": "Apple",
    "002500": "Apple",
    "003065": "Apple",
    "0050E4": "Apple",
    "080007": "Apple",
    "14109F": "Apple",
    "1CE62B": "Apple",
    "24A074": "Apple",
    "3C0754": "Apple",
    "406C8F": "Apple",
    "60334B": "Apple",
    "7014A6": "Apple",
    "78CA39": "Apple",
    "90840D": "Apple",
    "A4B197": "Apple",
    "B8C111": "Apple",
    "BC926B": "Apple",
    "D0034B": "Apple",
    "E0ACCB": "Apple",
    "F4F951": "Apple",
    # ---- Samsung ----
    "001377": "Samsung",
    "0023D6": "Samsung",
    "002454": "Samsung",
    "00265D": "Samsung",
    "08ECA9": "Samsung",
    "0C8910": "Samsung",
    "0CDFA4": "Samsung",
    "14F42A": "Samsung",
    "30CDA7": "Samsung",
    "84A466": "Samsung",
    "A81DE0": "Samsung",
    "B43A28": "Samsung",
    "E8508B": "Samsung",
    "F4428F": "Samsung",
    # ---- Google / Nest ----
    "001A11": "Google",
    "18B430": "Nest Labs / Google",
    "1CF29A": "Google",
    "6466B3": "Google",
    "7CD1C3": "Google",
    "F4F5D8": "Google",
    # ---- Amazon ----
    "0832B8": "Amazon",
    "181994": "Amazon",
    "34D270": "Amazon",
    "444602": "Amazon",
    "68DBF5": "Amazon",
    "F0272D": "Amazon",
    "FC65DE": "Amazon",
    # ---- Roku / media ----
    "0C1724": "Roku",
    "8C49B6": "Roku",
    "AC3A7A": "Roku",
    "B0A737": "Roku",
    "B83E59": "Roku",
    # ---- Printers ----
    "0011B3": "HP",
    "001279": "HP",
    "001A4B": "HP",
    "002655": "HP",
    "6C3BE5": "HP",
    "B499BA": "HP",
    "001B78": "HP",
    "00065B": "Brother",
    "008092": "Brother",
    # ---- Raspberry Pi (default Eth, WiFi) ----
    "B827EB": "Raspberry Pi Foundation",
    "DCA632": "Raspberry Pi Foundation",
    "E45F01": "Raspberry Pi Foundation",
    "D83ADD": "Raspberry Pi Foundation",
    "28CDC1": "Raspberry Pi Foundation",
    # ---- Intel NICs ----
    "001E67": "Intel",
    "0022FA": "Intel",
    "3C970E": "Intel",
    "50B7C3": "Intel",
    "7C5CF8": "Intel",
    "A0A8CD": "Intel",
    "A4C494": "Intel",
    "C03FD5": "Intel",
    # ---- Realtek / generic ----
    "001E58": "Realtek",
    "52540": "QEMU / KVM (virt)",
    # ---- Synology / QNAP ----
    "0011322": "Synology",
    "245EBE": "QNAP",
}


_MAC_RE = re.compile(
    r"([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}"
    r"[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})"
)


def _normalize(mac: str) -> str:
    """Uppercase hex, no separators."""
    return re.sub(r"[^0-9A-Fa-f]", "", mac).upper()


def lookup_vendor(mac: str) -> str:
    """Return vendor name for a MAC, or 'Unknown' if not in the table."""
    if not mac:
        return ""
    n = _normalize(mac)
    if len(n) < 6:
        return ""
    oui = n[:6]
    return _OUI_TABLE.get(oui, "Unknown")


def format_mac(mac: str) -> str:
    """Normalize to aa:bb:cc:dd:ee:ff format for display."""
    n = _normalize(mac)
    if len(n) < 12:
        return mac
    return ":".join(n[i:i + 2] for i in range(0, 12, 2)).lower()


def _ping_once(ip: str, timeout_ms: int = 500) -> None:
    """Fire a single ping so the OS populates its ARP cache for `ip`.
    Errors are swallowed -- ping may not be installed or may require privs."""
    try:
        if sys.platform.startswith("win"):
            # -n 1 -w <ms>  (count, timeout in ms)
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
        else:
            # -c 1 -W <s>   (count, timeout in seconds)
            cmd = ["ping", "-c", "1", "-W", "1", ip]
        subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout_ms / 1000 + 1,
        )
    except Exception:
        pass


def get_mac_for_ip(ip: str) -> Optional[str]:
    """Look up the MAC address for `ip` via the OS ARP cache.

    Returns a normalized `aa:bb:cc:dd:ee:ff` string, or None if we couldn't
    find a MAC (remote host on a different L2 segment, ARP blocked, etc).
    """
    if not ip:
        return None
    # Force ARP cache entry if the TCP probe alone didn't leave one.
    _ping_once(ip)
    try:
        creation_flags = 0
        if sys.platform.startswith("win"):
            # Avoid opening a visible console window when bundled by PyInstaller.
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            ["arp", "-a", ip] if sys.platform.startswith("win") else ["arp", "-n", ip],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=2, text=True, creationflags=creation_flags,
        )
        out = (result.stdout or "") + "\n" + (result.stderr or "")
    except Exception:
        # Some Linux distros don't ship `arp`; try `ip neigh` as fallback.
        try:
            result = subprocess.run(
                ["ip", "neigh", "show", ip],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=2, text=True,
            )
            out = result.stdout or ""
        except Exception:
            return None

    for line in out.splitlines():
        # We only want the line that actually references this IP.
        if ip not in line:
            continue
        m = _MAC_RE.search(line)
        if m:
            mac = m.group(1)
            # Filter incomplete/placeholder entries.
            if mac.lower() in ("00-00-00-00-00-00", "00:00:00:00:00:00",
                               "ff-ff-ff-ff-ff-ff", "ff:ff:ff:ff:ff:ff"):
                return None
            return format_mac(mac)
    return None
