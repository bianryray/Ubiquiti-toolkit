"""Network tests (BETA): throughput tests and an "area check" for an AP.

Throughput tests
  * PC <-> device: this PC listens on a TCP port; over SSH the device is told
    to stream zeros to us (download) or to read what we send (upload) using
    the `nc` / `dd` tools every UniFi device ships. The device always makes
    the outbound connection, so nothing has to listen on the device.
  * Device <-> device: `iperf3` server on one device, client on the other
    (e.g. gateway <-> AP). Needs iperf3 on both.
  * PC <-> PC: two copies of UniFi Toolbox; one listens (PeerServer), the
    other runs peer_test().

Timing: the first second of every transfer is ignored (TCP ramp-up), and an
upload is only counted as finished once the receiver has drained everything
and closed the connection, so socket buffering doesn't inflate the result.

Area check: from the AP serving a bad area, measure latency/loss to the
gateway and to the internet, DNS, the AP's uplink (wired link speed / mesh
signal), Wi-Fi channel utilisation, client signal and CPU load -- then say
in plain words which part looks responsible.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..utils import LogFn, noop_log

DEFAULT_TEST_PORT = 50555
WARMUP = 1.0           # seconds ignored at the start of each transfer
_CHUNK = 256 * 1024
_ZEROS = bytes(_CHUNK)


class TestError(Exception):
    """A test couldn't run; the message is shown to the user as-is."""


@dataclass
class Speed:
    label: str
    mbps: float
    seconds: float
    megabytes: float

    def __str__(self):
        return f"{self.label}: {self.mbps:,.0f} Mbps ({self.megabytes:,.0f} MB in {self.seconds:.1f}s)"


@dataclass
class Finding:
    status: str        # "ok" | "warn" | "bad" | "info"
    title: str
    detail: str = ""


@dataclass
class AreaReport:
    findings: List[Finding] = field(default_factory=list)
    verdict: str = ""
    gateway_ip: str = ""
    raw: Dict = field(default_factory=dict)

    def add(self, status, title, detail=""):
        self.findings.append(Finding(status, title, detail))


# ── Helpers ─────────────────────────────────────────────────────────

def local_ip_for(target: str) -> str:
    """The address of this PC on the interface that reaches `target`."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target, 9))  # no packet is sent for UDP connect
        return s.getsockname()[0]
    finally:
        s.close()


def _listener(port: int) -> socket.socket:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("0.0.0.0", port))
    except OSError as e:
        srv.close()
        raise TestError(f"Can't listen on port {port} ({e}). Pick another port.")
    srv.listen(2)
    return srv


def _accept_from(srv: socket.socket, expect_ip: str, wait: float) -> socket.socket:
    deadline = time.monotonic() + wait
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TestError(
                "The device never connected back to this PC. Usually Windows "
                "Firewall is blocking UniFi Toolbox - allow it (Private networks) "
                "when Windows asks, or add an inbound rule for the test port."
            )
        srv.settimeout(left)
        try:
            conn, addr = srv.accept()
        except socket.timeout:
            continue
        if expect_ip and addr[0] != expect_ip:
            conn.close()  # someone else; ignore
            continue
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        return conn


def _receive(conn: socket.socket, duration: float, label: str,
             stop: Optional[threading.Event] = None) -> Speed:
    """Count bytes for `duration` seconds after the warm-up, then hang up."""
    conn.settimeout(10)
    start = counted_from = None
    counted = 0
    try:
        while True:
            data = conn.recv(_CHUNK)
            now = time.monotonic()
            if not data:
                break
            if start is None:
                start = now
            if counted_from is None and now - start >= WARMUP:
                counted_from = now
            elif counted_from is not None:
                counted += len(data)
                if now - counted_from >= duration or (stop and stop.is_set()):
                    break
    except socket.timeout:
        pass
    finally:
        conn.close()
    if not counted_from or not counted:
        raise TestError(f"{label}: no data arrived (or the stream stopped within the first second).")
    secs = time.monotonic() - counted_from
    return Speed(label, counted * 8 / secs / 1e6, secs, counted / 1e6)


def _send(conn: socket.socket, duration: float, label: str,
          stop: Optional[threading.Event] = None) -> Speed:
    """Send for warm-up + `duration`.

    Counting starts after the warm-up, when the send buffer is already full,
    so in steady state bytes accepted == bytes delivered. If the receiver
    then closes within a few seconds we use that (exact) end time; some
    `nc` builds keep the connection open, in which case the moment we
    stopped sending is used instead.
    """
    conn.settimeout(15)
    start = time.monotonic()
    counted_from = sent_end = None
    counted = 0
    try:
        while True:
            n = conn.send(_ZEROS)
            now = time.monotonic()
            if counted_from is None:
                if now - start >= WARMUP:
                    counted_from = now
            else:
                counted += n
                if now - counted_from >= duration or (stop and stop.is_set()):
                    break
        sent_end = time.monotonic()
        conn.shutdown(socket.SHUT_WR)
        conn.settimeout(5)
        try:
            while conn.recv(4096):
                pass
            sent_end = time.monotonic()   # receiver drained everything and closed
        except socket.timeout:
            pass
    except OSError as e:
        if not counted:
            raise TestError(f"{label}: connection failed ({e}).")
        sent_end = sent_end or time.monotonic()
    finally:
        conn.close()
    secs = (sent_end - counted_from) if counted_from and sent_end else 0
    if secs <= 0 or not counted:
        raise TestError(f"{label}: nothing could be sent.")
    return Speed(label, counted * 8 / secs / 1e6, secs, counted / 1e6)


def _run_bg(ssh, cmd: str, timeout: int):
    """Run an SSH command in a thread; returns (thread, result_holder)."""
    box = {}

    def go():
        box["result"] = ssh.run(cmd, timeout=timeout)

    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t, box


_NC = 'NC=$(command -v nc 2>/dev/null || echo "busybox nc"); '


# ── PC <-> device ───────────────────────────────────────────────────

def pc_device_test(ssh, device_ip: str, duration: int = 10, port: int = DEFAULT_TEST_PORT,
                   log: LogFn = noop_log, stop: Optional[threading.Event] = None) -> List[Speed]:
    """Download (device -> PC) then upload (PC -> device)."""
    pc_ip = local_ip_for(device_ip)
    results = []
    # Bound the device side even if this PC vanishes: enough for a 10 Gbps
    # link for the whole test, so the cap never ends a real test early.
    blocks = int(10e9 / 8 * (duration + WARMUP + 5) / 65536)

    # Download: device streams zeros to us.
    srv = _listener(port)
    try:
        log(f"Download: asking {device_ip} to send to {pc_ip}:{port} ...")
        t, box = _run_bg(ssh, _NC + f"dd if=/dev/zero bs=65536 count={blocks} 2>/dev/null"
                                    f" | $NC {pc_ip} {port}", timeout=duration + 30)
        conn = _accept_from(srv, device_ip, wait=20)
        results.append(_receive(conn, duration, "Device → PC (download)", stop))
    except TestError:
        _explain_ssh_failure(box, t)
        raise
    finally:
        srv.close()

    if stop and stop.is_set():
        return results

    # Upload: device connects and discards what we send.
    srv = _listener(port)
    try:
        log(f"Upload: sending from {pc_ip} to {device_ip} ...")
        t, box = _run_bg(ssh, _NC + f"$NC {pc_ip} {port} > /dev/null", timeout=duration + 30)
        conn = _accept_from(srv, device_ip, wait=20)
        results.append(_send(conn, duration, "PC → Device (upload)", stop))
    except TestError:
        _explain_ssh_failure(box, t)
        raise
    finally:
        srv.close()
        # Some nc builds linger after we hang up; don't leave them running.
        ssh.run(f"pkill -f '[n]c {pc_ip} {port}' 2>/dev/null; true", timeout=15)
    return results


def _explain_ssh_failure(box, thread):
    """If the SSH side already failed, surface that instead of a timeout."""
    if thread is not None:
        thread.join(0.5)
    ok, out, err = box.get("result", (True, "", ""))
    if not ok and err:
        if "not found" in (err + out):
            raise TestError("The device has no `nc` tool, so this test can't run on it.")
        raise TestError(err.strip().splitlines()[-1] if err.strip() else "SSH command failed.")


# ── Device <-> device (iperf3) ─────────────────────────────────────

def has_iperf3(ssh) -> bool:
    ok, out, _ = ssh.run("command -v iperf3", timeout=15)
    return ok and "iperf3" in out


def _iperf_mbps(out: str) -> float:
    try:
        data = json.loads(out[out.index("{"):])
    except (ValueError, json.JSONDecodeError):
        raise TestError("iperf3 gave no readable result:\n" + out[-300:])
    if data.get("error"):
        raise TestError(f"iperf3: {data['error']}")
    end = data.get("end", {})
    summary = end.get("sum_received") or end.get("sum") or {}
    bps = summary.get("bits_per_second")
    if not bps:
        raise TestError("iperf3 finished but reported no throughput.")
    return bps / 1e6


def iperf_between(server_ssh, server_ip: str, client_ssh, duration: int = 10,
                  port: int = 5201, server_name: str = "Gateway", client_name: str = "AP",
                  log: LogFn = noop_log) -> List[Speed]:
    """Run iperf3 both ways between two devices (server <- client, then reverse)."""
    for ssh, name in ((server_ssh, server_name), (client_ssh, client_name)):
        if not has_iperf3(ssh):
            raise TestError(f"{name} ({ssh.host}) doesn't have iperf3, so this test can't "
                            "run on it. Try the PC ↔ Device test instead.")
    results = []
    try:
        for reverse in (False, True):
            label = (f"{server_name} → {client_name}" if reverse
                     else f"{client_name} → {server_name}")
            log(f"iperf3: {label} for {duration}s ...")
            ok, out, err = server_ssh.run(
                f"iperf3 -s -1 -D -p {port} >/dev/null 2>&1; sleep 1; echo ready", timeout=20)
            if not ok:
                raise TestError(f"Couldn't start iperf3 on {server_name}: {err.strip()}")
            ok, out, err = client_ssh.run(
                f"iperf3 -c {server_ip} -p {port} -t {duration} -O 1 -J {'-R' if reverse else ''}",
                timeout=duration + 30)
            mbps = _iperf_mbps(out or err)
            results.append(Speed(label, mbps, float(duration), mbps * duration / 8))
    finally:
        server_ssh.run(f"pkill -f 'iperf3 -s -1 -D -p {port}' 2>/dev/null; true", timeout=15)
    return results


# ── PC <-> PC ──────────────────────────────────────────────────────

class PeerServer:
    """Listener for PC <-> PC tests. Protocol: client sends
    'UTBX1 <up|down> <seconds>\\n'; 'up' = client sends, we discard;
    'down' = we send for warm-up + seconds."""

    def __init__(self, port: int = DEFAULT_TEST_PORT, log: LogFn = noop_log):
        self.port = port
        self.log = log
        self._srv = _listener(port)
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def close(self):
        self._stop.set()
        try:
            self._srv.close()
        except OSError:
            pass

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._srv.settimeout(1)
                conn, addr = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn, addr), daemon=True).start()

    def _serve(self, conn, addr):
        try:
            conn.settimeout(10)
            header = b""
            while not header.endswith(b"\n") and len(header) < 64:
                b = conn.recv(1)
                if not b:
                    return
                header += b
            parts = header.decode(errors="ignore").split()
            if len(parts) != 3 or parts[0] != "UTBX1":
                return
            secs = min(max(int(parts[2]), 1), 120)
            if parts[1] == "down":
                self.log(f"PC test: sending to {addr[0]} for {secs}s")
                end = time.monotonic() + WARMUP + secs + 0.5
                while time.monotonic() < end:
                    conn.sendall(_ZEROS)
            elif parts[1] == "up":
                self.log(f"PC test: receiving from {addr[0]}")
                while conn.recv(_CHUNK):
                    pass
        except (OSError, ValueError):
            pass
        finally:
            conn.close()


def peer_test(host: str, port: int = DEFAULT_TEST_PORT, duration: int = 10,
              stop: Optional[threading.Event] = None) -> List[Speed]:
    results = []
    for direction, label in (("down", "Other PC → this PC"), ("up", "This PC → other PC")):
        try:
            conn = socket.create_connection((host, port), timeout=5)
        except OSError as e:
            raise TestError(f"Couldn't reach {host}:{port} ({e}). Is the other PC listening, "
                            "and is it allowed through its firewall?")
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        conn.sendall(f"UTBX1 {direction} {duration}\n".encode())
        if direction == "down":
            results.append(_receive(conn, duration, label, stop))
        else:
            results.append(_send(conn, duration, label, stop))
        if stop and stop.is_set():
            break
    return results


# ── Area check ─────────────────────────────────────────────────────

_PING_LOSS = re.compile(r"(\d+(?:\.\d+)?)% packet loss")
_PING_RTT = re.compile(r"(?:round-trip|rtt)[^=]*=\s*([\d.]+)/([\d.]+)/([\d.]+)")


def parse_ping(out: str) -> Optional[Dict[str, float]]:
    loss = _PING_LOSS.search(out)
    if not loss:
        return None
    rtt = _PING_RTT.search(out)
    res = {"loss": float(loss.group(1))}
    if rtt:
        res.update(min=float(rtt.group(1)), avg=float(rtt.group(2)), max=float(rtt.group(3)))
    return res


def _ping_finding(rep: AreaReport, name: str, p: Optional[Dict], warn_ms: float, bad_ms: float):
    if not p:
        rep.add("bad", f"{name}: no reply", "Ping got no answer at all.")
        return
    avg, mx, loss = p.get("avg"), p.get("max"), p["loss"]
    detail = f"{loss:g}% loss" + (f", avg {avg:.1f} ms, worst {mx:.1f} ms" if avg is not None else "")
    if loss >= 5 or (avg is not None and avg >= bad_ms):
        rep.add("bad", f"{name}: poor", detail)
    elif loss > 0 or (avg is not None and (avg >= warn_ms or mx >= bad_ms * 2)):
        rep.add("warn", f"{name}: unstable", detail)
    else:
        rep.add("ok", f"{name}: good", detail)


def _num(d, *keys):
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def analyze_stats(rep: AreaReport, stats: Dict) -> Dict[str, bool]:
    """Turn `mca-dump` JSON into findings. Field names vary by model and
    firmware, so every lookup is optional. Returns flags for the verdict."""
    flags = {"uplink_bad": False, "wifi_busy": False, "weak_clients": False, "cpu_high": False}

    up = stats.get("uplink") or {}
    if isinstance(up, dict) and up:
        utype = str(up.get("type", "")).lower()
        if utype in ("wireless", "mesh"):
            sig = _num(up, "signal", "rssi")
            if sig is not None and sig > 0:   # some firmwares report RSSI (higher = better)
                sig = sig - 95
            if sig is None:
                rep.add("info", "Uplink: wireless mesh", "Mesh link signal not reported.")
            elif sig < -75:
                flags["uplink_bad"] = True
                rep.add("bad", f"Uplink: weak mesh signal ({sig:.0f} dBm)",
                        "This AP connects back over Wi-Fi with a weak link - everything in "
                        "this area is limited by it. Move it closer to its parent AP or run a cable.")
            elif sig < -65:
                rep.add("warn", f"Uplink: fair mesh signal ({sig:.0f} dBm)",
                        "Mesh link is usable but will cut speed noticeably.")
            else:
                rep.add("ok", f"Uplink: mesh signal good ({sig:.0f} dBm)")
        else:
            speed = _num(up, "speed")
            duplex = up.get("full_duplex")
            if speed:
                if speed < 1000:
                    flags["uplink_bad"] = True
                    rep.add("bad", f"Uplink: cable linked at only {speed:.0f} Mbps",
                            "A gigabit port linking at 100 Mbps almost always means a bad "
                            "cable, a bad termination, or a damaged switch port.")
                elif duplex is False:
                    flags["uplink_bad"] = True
                    rep.add("bad", "Uplink: half duplex", "Duplex mismatch - check the cable and switch port.")
                else:
                    rep.add("ok", f"Uplink: wired at {speed:.0f} Mbps")

    radios = stats.get("radio_table_stats") or []
    for r in radios if isinstance(radios, list) else []:
        name = r.get("name") or r.get("radio") or "radio"
        band = {"ng": "2.4 GHz", "na": "5 GHz", "6e": "6 GHz"}.get(r.get("radio"), name)
        cu = _num(r, "cu_total")
        stas = _num(r, "num_sta", "user-num_sta")
        chan = r.get("channel")
        bits = []
        if chan:
            bits.append(f"channel {chan}")
        if stas is not None:
            bits.append(f"{stas:.0f} clients")
        if cu is None:
            continue
        bits.insert(0, f"{cu:.0f}% airtime used")
        detail = ", ".join(bits)
        if cu >= 70:
            flags["wifi_busy"] = True
            rep.add("bad", f"Wi-Fi {band}: channel congested", detail +
                    ". Interference or too many devices - try another channel or lower width.")
        elif cu >= 50:
            flags["wifi_busy"] = True
            rep.add("warn", f"Wi-Fi {band}: channel busy", detail)
        else:
            rep.add("ok", f"Wi-Fi {band}: channel clear", detail)

    weak, total = [], 0
    for vap in stats.get("vap_table") or []:
        for sta in vap.get("sta_table") or [] if isinstance(vap, dict) else []:
            total += 1
            sig = _num(sta, "signal")
            if sig is None:
                rssi = _num(sta, "rssi")
                sig = rssi - 95 if rssi is not None else None
            if sig is not None and sig < -72:
                weak.append((sig, sta.get("hostname") or sta.get("mac") or "?"))
    if total:
        if weak:
            flags["weak_clients"] = True
            names = ", ".join(f"{n} ({s:.0f} dBm)" for s, n in sorted(weak)[:5])
            rep.add("warn" if len(weak) * 3 < total else "bad",
                    f"Clients: {len(weak)} of {total} have weak signal",
                    f"Weakest: {names}. These devices are too far from the AP or behind walls.")
        else:
            rep.add("ok", f"Clients: all {total} have good signal")

    sysst = stats.get("system-stats") or {}
    cpu = _num(sysst, "cpu")
    mem = _num(sysst, "mem")
    if cpu is not None:
        if cpu >= 85:
            flags["cpu_high"] = True
            rep.add("warn", f"AP load: CPU {cpu:.0f}%", "The AP itself is struggling; a reboot or firmware update may help.")
        else:
            rep.add("ok", f"AP load: CPU {cpu:.0f}%" + (f", memory {mem:.0f}%" if mem is not None else ""))
    return flags


def area_check(ssh, log: LogFn = noop_log, ping_count: int = 10) -> AreaReport:
    rep = AreaReport()
    ok, out, err = ssh.run("ip route 2>/dev/null | awk '/^default/ {print $3; exit}'; "
                           "route -n 2>/dev/null | awk '$1==\"0.0.0.0\" {print $2; exit}'",
                           timeout=20)
    if not ok and "connection failed" in err.lower():
        raise TestError(err.strip())
    gw = next((ln.strip() for ln in out.splitlines() if re.match(r"\d+\.\d+\.\d+\.\d+$", ln.strip())), "")
    rep.gateway_ip = gw

    # Pings to the gateway and the internet run in parallel (separate SSH sessions).
    log(f"Area check: pinging gateway {gw or '?'} and the internet ({ping_count} pings each) ...")
    jobs = {}
    if gw:
        jobs["gw"] = _run_bg(ssh, f"ping -c {ping_count} {gw} 2>&1", timeout=ping_count + 20)
    jobs["net"] = _run_bg(ssh, f"ping -c {ping_count} 1.1.1.1 2>&1", timeout=ping_count + 20)
    jobs["dns"] = _run_bg(ssh, "nslookup ui.com 2>&1 | tail -n +3", timeout=20)
    jobs["stats"] = _run_bg(ssh, "mca-dump 2>/dev/null", timeout=30)
    for t, _box in jobs.values():
        t.join(ping_count + 25)

    def out_of(key):
        return (jobs[key][1].get("result") or (False, "", ""))[1] if key in jobs else ""

    gw_ping = parse_ping(out_of("gw")) if gw else None
    net_ping = parse_ping(out_of("net"))
    if gw:
        _ping_finding(rep, f"AP → gateway ({gw})", gw_ping, warn_ms=5, bad_ms=20)
    else:
        rep.add("warn", "Gateway: couldn't find the AP's default gateway")
    _ping_finding(rep, "AP → internet (1.1.1.1)", net_ping, warn_ms=40, bad_ms=100)

    dns_out = out_of("dns")
    if re.search(r"Address[^:]*:\s*\d", dns_out) and "can't" not in dns_out.lower():
        rep.add("ok", "DNS: working")
    else:
        rep.add("bad", "DNS: failed", "Names don't resolve from this AP - websites will fail "
                "even though the connection is up. Check the DNS servers on the gateway.")

    stats = {}
    raw = out_of("stats").strip()
    if raw.startswith("{"):
        try:
            stats = json.loads(raw)
        except json.JSONDecodeError:
            stats = {}
    rep.raw = stats
    flags = analyze_stats(rep, stats) if stats else {}
    if not stats:
        rep.add("info", "Wi-Fi details unavailable",
                "This device didn't return its statistics (mca-dump), so channel, uplink "
                "and client signal couldn't be checked.")

    rep.verdict = _verdict(gw_ping, net_ping, flags, dns_ok=not any(
        f.title.startswith("DNS: failed") for f in rep.findings))
    return rep


def _bad_ping(p, bad_ms):
    return p is None or p["loss"] >= 5 or (p.get("avg") or 0) >= bad_ms


def _verdict(gw_ping, net_ping, flags, dns_ok) -> str:
    if flags.get("uplink_bad"):
        return ("Most likely cause: this AP's own connection back to the network (cable or "
                "mesh link). Fix that first - nothing else in this area can be faster than it.")
    if gw_ping is not None and _bad_ping(gw_ping, 20):
        return ("Most likely cause: the path between this AP and the gateway (cabling, "
                "switch, or mesh link) is dropping packets or slow.")
    if _bad_ping(net_ping, 100):
        return ("The local network looks fine, but the internet connection itself is poor "
                "from here - this is probably the ISP/WAN, not this area.")
    if not dns_ok:
        return "Connection is fine but DNS is failing - fix the DNS settings on the gateway."
    if flags.get("wifi_busy"):
        return ("Most likely cause: Wi-Fi congestion or interference on this AP's channel. "
                "Try a different channel, a narrower channel width, or add an AP.")
    if flags.get("weak_clients"):
        return ("Network path is healthy; devices here have weak Wi-Fi signal. Coverage is "
                "the problem - move or add an AP closer to where people are.")
    if flags.get("cpu_high"):
        return "The AP itself is overloaded - try a reboot or firmware update."
    return ("Nothing wrong found from the AP's side. If it's still slow here, run the "
            "AP ↔ Gateway speed test, and check the device itself (its Wi-Fi, VPN, etc).")
