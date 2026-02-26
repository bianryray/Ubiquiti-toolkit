import re
from typing import Callable, Optional
from dataclasses import dataclass, field

# Constants
DEFAULT_SSH_PORT = 22
SSH_TIMEOUT = 15
HTTP_TIMEOUT = 20
SCAN_PORTS = [22, 443, 8080, 8443]
SCAN_TIMEOUT = 1.5

# Console model detection pattern
CONSOLE_KEYWORDS = re.compile(r"(udm|udr|udm-?pro|uxg|uxg-?pro|udw|ucg)", re.I)

# Logging
LogFn = Callable[[str], None]


def noop_log(msg: str) -> None:
    pass


def build_inform_url(controller_url: str) -> str:
    if not controller_url:
        return ""
    return (
        controller_url
        if controller_url.endswith("/inform")
        else controller_url.rstrip("/") + "/inform"
    )


def parse_ip_targets(raw: str):
    """Parse a string of IP targets into a list of IPs.

    Supports:
      - Comma-separated: 192.168.1.1, 192.168.1.2
      - Range: 192.168.1.1-50  (last octet range)
      - CIDR: 192.168.1.0/24
      - Newline-separated
    """
    import ipaddress

    targets = []
    raw = raw.strip()
    if not raw:
        return targets

    # Split on commas and newlines
    parts = re.split(r"[,\n]+", raw)
    for part in parts:
        part = part.strip()
        if not part:
            continue

        # CIDR notation
        if "/" in part:
            try:
                network = ipaddress.ip_network(part, strict=False)
                for host in network.hosts():
                    targets.append(str(host))
            except ValueError:
                pass
            continue

        # Range notation: 192.168.1.1-50
        range_match = re.match(
            r"^(\d+\.\d+\.\d+)\.(\d+)\s*-\s*(\d+)$", part
        )
        if range_match:
            prefix = range_match.group(1)
            start = int(range_match.group(2))
            end = int(range_match.group(3))
            for i in range(start, end + 1):
                if 0 <= i <= 255:
                    targets.append(f"{prefix}.{i}")
            continue

        # Plain IP
        try:
            ipaddress.ip_address(part)
            targets.append(part)
        except ValueError:
            pass

    return targets


@dataclass
class SSHOptions:
    accept_unknown_host_key: bool = True
    try_keyboard_interactive: bool = True
    use_pkey: bool = False
    pkey_path: Optional[str] = None
    pkey_passphrase: Optional[str] = None
    banner_timeout: int = 60
    auth_timeout: int = 60
