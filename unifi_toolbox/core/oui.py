"""MAC address discovery + manufacturer (OUI) lookup.

Strategy:
  1. Once a host is confirmed up (at least one open TCP port), ping it to
     force an ARP-cache entry, then shell out to the OS `arp` tool to read
     the MAC. Works on Windows / macOS / Linux without elevated privileges.
  2. Look the MAC up in the full IEEE registry (MA-L / MA-M / MA-S, ~54k
     prefixes) bundled at unifi_toolbox/data/oui.txt.gz, longest prefix
     first. "Update manufacturer list" in the Discovery tab downloads a
     fresh copy into the user's config folder, which then takes priority.
  3. MACs with the locally-administered bit set are not in any registry --
     they're phones / laptops using private (randomized) Wi-Fi addresses,
     VMs, containers, etc. -- so they're labelled as such instead of "Unknown".
"""

from __future__ import annotations

import gzip
import os
import re
import socket
import subprocess
import sys
import threading
from datetime import datetime
from typing import Dict, Optional

from .oui_sources import load_table

_BUNDLED_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "oui.txt.gz",
)

# Friendlier display names for a few registry entries.
_ALIASES = {
    "Routerboard.com": "MikroTik (Routerboard)",
    "IEEE Registration Authority": "Unknown (IEEE block)",
}

_db: Optional[Dict[str, str]] = None
_db_source = ""
_db_lock = threading.Lock()


def user_db_path() -> str:
    """Downloaded copy in %APPDATA%/UniFiToolbox (or ~/.config/UniFiToolbox)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))
    folder = os.path.join(base, "UniFiToolbox")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "oui.txt.gz")


def _built_date(path: str) -> str:
    """Date from the file's '# ... built YYYY-MM-DD' header line. (File mtime
    is useless in the packaged .exe: it's the extraction time.)"""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            m = re.search(r"\d{4}-\d{2}-\d{2}", f.readline())
        if m:
            return m.group(0)
    except OSError:
        pass
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")


def _load_db() -> Dict[str, str]:
    global _db, _db_source
    with _db_lock:
        if _db is not None:
            return _db
        # Prefer whichever copy is newer: a later app release may bundle a
        # fresher list than one the user downloaded months ago.
        candidates = [(_built_date(p), label, p) for p, label in
                      ((user_db_path(), "downloaded"), (_BUNDLED_DB, "built-in"))
                      if os.path.exists(p)]
        for built, label, path in sorted(candidates, reverse=True):
            table = load_table(path)
            if table:
                _db, _db_source = table, f"{label}, {len(table):,} prefixes, {built}"
                return _db
        _db, _db_source = {}, "missing"
        return _db


def reload_db() -> str:
    """Drop the cached table (after an update) and load again. Returns info."""
    global _db
    with _db_lock:
        _db = None
    _load_db()
    return _db_source


def db_info() -> str:
    _load_db()
    return _db_source


_MAC_RE = re.compile(
    r"([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}"
    r"[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})"
)


def _normalize(mac: str) -> str:
    """Uppercase hex, no separators."""
    return re.sub(r"[^0-9A-Fa-f]", "", mac).upper()


def lookup_vendor(mac: str) -> str:
    """Return the manufacturer for a MAC, or a descriptive fallback."""
    if not mac:
        return ""
    n = _normalize(mac)
    if len(n) < 6:
        return ""
    db = _load_db()
    for length in (9, 7, 6):  # MA-S, MA-M, MA-L: most specific first
        name = db.get(n[:length])
        if name:
            return _ALIASES.get(name, name)
    if n.startswith("525400"):
        return "QEMU / KVM virtual NIC"
    if int(n[1], 16) & 0x2:  # locally-administered bit
        return "Private / randomized MAC"
    return "Unknown"


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


def get_hostname(ip: str, timeout: float = 2.0) -> str:
    """Reverse-DNS / NetBIOS name for `ip` (Windows resolves both through
    gethostbyaddr). Returns '' when the device has no name or the lookup
    takes longer than `timeout` -- NetBIOS misses can stall for seconds."""
    result = []

    def lookup():
        try:
            result.append(socket.gethostbyaddr(ip)[0])
        except (OSError, UnicodeError):
            pass

    t = threading.Thread(target=lookup, daemon=True)
    t.start()
    t.join(timeout)
    name = result[0] if result else ""
    return "" if name == ip else name
