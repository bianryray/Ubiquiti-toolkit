import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Callable

from ..utils import SCAN_PORTS, SCAN_TIMEOUT, LogFn, noop_log
from .oui import get_mac_for_ip, lookup_vendor


def get_local_subnets() -> List[str]:
    """Detect local network subnets from interfaces.

    Returns a list of subnet strings like '192.168.1.0/24'.
    """
    subnets = []
    try:
        import ipaddress

        hostname = socket.gethostname()
        addrs = socket.getaddrinfo(hostname, None, socket.AF_INET)
        seen = set()
        for info in addrs:
            ip = info[4][0]
            if ip.startswith("127.") or ip in seen:
                continue
            seen.add(ip)
            # Assume /24 for simplicity
            network = ipaddress.ip_network(f"{ip}/24", strict=False)
            subnets.append(str(network))
    except Exception:
        pass
    return subnets or ["192.168.1.0/24"]


def scan_host(host: str, ports: List[int] = None, timeout: float = SCAN_TIMEOUT) -> Optional[Dict]:
    """Scan a single host for open ports. Returns result dict or None if no ports open."""
    ports = ports or SCAN_PORTS
    open_ports = []
    banner = ""

    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                open_ports.append(port)
                if port == 22:
                    try:
                        sock.settimeout(2)
                        banner = sock.recv(256).decode(errors="ignore").strip()
                    except Exception:
                        pass
        except Exception:
            continue

    if not open_ports:
        return None

    # Resolve MAC + vendor from the local ARP cache. Failures are fine --
    # remote devices or cross-subnet hosts won't have an ARP entry.
    mac = get_mac_for_ip(host) or ""
    vendor = lookup_vendor(mac) if mac else ""

    return {
        "ip": host,
        "ports": open_ports,
        "banner": banner,
        "mac": mac,
        "vendor": vendor,
        "status": "found",
    }


class NetworkScanner:
    """Scans a subnet for Ubiquiti devices using TCP port checks."""

    def __init__(
        self,
        log: LogFn = noop_log,
        max_workers: int = 50,
    ):
        self.log = log
        self.max_workers = max_workers
        self._stop_event = threading.Event()
        self.results: List[Dict] = []

    def stop(self):
        self._stop_event.set()

    def scan_subnet(
        self,
        subnet: str,
        ports: List[int] = None,
        on_found: Optional[Callable[[Dict], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[Dict]:
        """Scan all hosts in a subnet.

        Args:
            subnet: CIDR notation like '192.168.1.0/24'
            ports: List of ports to check
            on_found: Callback when a device is found
            on_progress: Callback with (scanned_count, total_count)
        """
        import ipaddress

        self._stop_event.clear()
        self.results = []
        ports = ports or SCAN_PORTS

        try:
            network = ipaddress.ip_network(subnet, strict=False)
            hosts = list(network.hosts())
        except ValueError as e:
            self.log(f"Invalid subnet: {e}")
            return []

        total = len(hosts)
        self.log(f"Scanning {total} hosts on {subnet} ...")
        scanned = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(scan_host, str(host), ports): str(host)
                for host in hosts
            }
            for future in as_completed(futures):
                if self._stop_event.is_set():
                    self.log("Scan stopped by user.")
                    pool.shutdown(wait=False, cancel_futures=True)
                    break

                scanned += 1
                try:
                    result = future.result()
                    if result:
                        self.results.append(result)
                        vendor = result.get("vendor") or ""
                        vendor_hint = f" vendor={vendor}" if vendor else ""
                        self.log(
                            f"  Found: {result['ip']} "
                            f"ports={result['ports']}{vendor_hint}"
                        )
                        if on_found:
                            on_found(result)
                except Exception:
                    pass

                if on_progress:
                    try:
                        on_progress(scanned, total)
                    except Exception:
                        pass

        self.log(
            f"Scan complete: {len(self.results)} device(s) found "
            f"out of {scanned} scanned."
        )
        return self.results
