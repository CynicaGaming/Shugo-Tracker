"""
Passive capture of AION 2 server->client traffic through Windows raw sockets (SIO_RCVALL).

Nothing to install: Windows hands a raw socket a copy of every IPv4 packet on an adapter once the app runs as
administrator. The game's TCP connections are found in the Windows TCP table (psutil) by owning process
(AION2.exe); one socket listens on each local address the game uses, and only the game servers' downstream
packets are kept. Nothing is sent, modified or injected.
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from typing import Callable

import psutil

from .reassembly import TcpStream

GAME_PROCESS_NAMES = {"aion2.exe"}

FlowKey = tuple[str, int, str, int]  # src ip, src port, dst ip, dst port


def find_game_connections(process_names: set[str] = GAME_PROCESS_NAMES) -> set[tuple[str, int, str, int]]:
    """(local ip, local port, remote ip, remote port) of every established game TCP connection."""
    pids = set()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info["name"] or "").lower() in process_names:
                pids.add(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not pids:
        return set()
    conns = set()
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.pid in pids and c.raddr and c.status == psutil.CONN_ESTABLISHED:
                conns.add((c.laddr.ip, c.laddr.port, c.raddr.ip, c.raddr.port))
    except psutil.AccessDenied:
        pass
    return conns


COMMON_PORTS = {80, 443}


class PacketFilter:
    """
    Which packets count: everything from the game's server ports (any host), so a connection the game opens
    later (entering Shugo or the arena, a channel change: a new server on the same port) is heard from its very
    first packet, without waiting for the next poll. Ordinary web ports (80/443) are only taken from the exact
    hosts the game is talking to.
    """

    def __init__(self, conns: set[tuple[str, int, str, int]]):
        self.ports = frozenset(rport for (_l, _lp, _r, rport) in conns if rport not in COMMON_PORTS)
        self.exact = frozenset((rip, rport, lport) for (_l, lport, rip, rport) in conns if rport in COMMON_PORTS)

    def __eq__(self, other):
        return isinstance(other, PacketFilter) and (self.ports, self.exact) == (other.ports, other.exact)

    def __hash__(self):
        return hash((self.ports, self.exact))

    def __bool__(self):
        return bool(self.ports or self.exact)

    def wants(self, src: str, sport: int, dport: int) -> bool:
        return sport in self.ports or (src, sport, dport) in self.exact


def parse_ipv4_tcp(pkt: bytes) -> tuple[str, int, str, int, int, bytes] | None:
    """(src, sport, dst, dport, seq, payload) of an IPv4 TCP packet, else None. The payload is cut to the length
    the IP header states, so link-layer padding never becomes data; a length of 0 or past the end (segments
    the network card coalesced) means 'the rest of the packet'."""
    if len(pkt) < 40 or pkt[0] >> 4 != 4 or pkt[9] != 6:
        return None
    ihl = (pkt[0] & 0x0F) * 4
    total, frag = struct.unpack_from("!H2xH", pkt, 2)
    if frag & 0x3FFF:                     # an IP fragment (TCP practically never is): skip
        return None
    if not total or total > len(pkt):
        total = len(pkt)
    if total < ihl + 20:
        return None
    sport, dport, seq = struct.unpack_from("!HHI", pkt, ihl)
    data_at = ihl + (pkt[ihl + 12] >> 4) * 4
    return (socket.inet_ntoa(bytes(pkt[12:16])), sport, socket.inet_ntoa(bytes(pkt[16:20])), dport, seq,
            bytes(pkt[data_at:total]) if data_at < total else b"")


class _Listener:
    """One raw socket on one local IPv4 address, reading on its own thread."""

    def __init__(self, ip: str, on_packet: Callable[[bytes], None]):
        self.ip = ip
        self.on_packet = on_packet
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32 * 1024 * 1024)
        except OSError:
            pass
        self.sock.bind((ip, 0))
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        self.sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        self.sock.settimeout(0.5)
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"capture-{ip}", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        buf = bytearray(65535)
        view = memoryview(buf)
        while not self._stop.is_set():
            try:
                n = self.sock.recv_into(buf)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                time.sleep(0.2)
                continue
            if n:
                self.on_packet(view[:n])

    def stop(self) -> None:
        self._stop.set()
        try:
            self.sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class GameCapture:
    """
    Calls on_bytes(flow, data, gap) with in-order server->client bytes.
    Follows the game's connections: a raw socket per local address the game uses, opened before the old ones
    close, and a packet filter swapped in place (no restart) when the game's servers change.
    """

    def __init__(self, on_bytes: Callable[[FlowKey, bytes, bool], None],
                 log: Callable[[str], None] | None = None,
                 process_names: set[str] | None = None, poll_s: float = 3.0):
        self.on_bytes = on_bytes
        self.log = log or print
        self.process_names = process_names or GAME_PROCESS_NAMES
        self.poll_s = poll_s
        self.streams: dict[FlowKey, TcpStream] = {}
        self.status = "starting"
        self._filter = PacketFilter(set())
        self._listeners: dict[str, _Listener] = {}
        self._conns: set = set()
        self._stop = threading.Event()
        self._lock = threading.Lock()          # listeners on several adapters feed the same streams
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        for ln in list(self._listeners.values()):
            ln.stop()
        self._listeners.clear()

    # ───── internals ─────
    def _run(self) -> None:
        last = None
        while not self._stop.is_set():
            conns = find_game_connections(self.process_names)
            self._conns = conns
            self._filter = PacketFilter(conns)
            ips = {lip for (lip, _lp, _r, _rp) in conns if "." in lip and ":" not in lip}
            failed = self._listen_on(ips)
            if not conns:
                status = "waiting for AION2.exe"
            elif not self._listeners:
                status = f"capture error: couldn't listen on {', '.join(sorted(failed)) or 'any address'}"
            else:
                status = f"capturing {len(conns)} game connection(s)"
            if status != last:
                self.status = last = status
                self.log(status)
            self._stop.wait(self.poll_s)

    def _listen_on(self, ips: set[str]) -> dict[str, str]:
        """Open sockets for new addresses before closing ones the game no longer uses. Returns failures."""
        failed = {}
        for ip in ips - set(self._listeners):
            try:
                self._listeners[ip] = _Listener(ip, self._on_packet)
                self.log(f"listening on {ip}")
            except OSError as e:
                failed[ip] = str(e)
                self.log(f"capture error on {ip}: {e}")
        for ip in set(self._listeners) - ips:
            if ips:                            # keep the last sockets while the game is between connections
                self._listeners.pop(ip).stop()
        return failed

    def _on_packet(self, pkt) -> None:
        p = parse_ipv4_tcp(pkt)
        if p is None:
            return
        src, sport, dst, dport, seq, data = p
        if not data or not self._filter.wants(src, sport, dport):
            return
        key: FlowKey = (src, sport, dst, dport)
        with self._lock:
            st = self.streams.get(key)
            if st is None:
                st = self.streams[key] = TcpStream()
            out, gap = st.push(seq, data, time.time())
            if out:
                self.on_bytes(key, out, gap)


# ───── Wireshark captures (development: --replay) ─────
def read_pcap(path: str):
    """Yield (timestamp, IPv4 packet bytes) from a pcap or pcapng file (Ethernet, raw IP or loopback links)."""
    with open(path, "rb") as f:
        data = f.read()

    def strip(link: int, frame: bytes) -> bytes | None:
        if link == 1:                                     # Ethernet (with an optional VLAN tag)
            off, etype = 14, struct.unpack_from("!H", frame, 12)[0]
            if etype == 0x8100:
                off, etype = 18, struct.unpack_from("!H", frame, 16)[0]
            return frame[off:] if etype == 0x0800 else None
        if link in (101, 228, 12, 14):                    # raw IPv4
            return frame
        if link in (0, 108):                              # BSD loopback: 4-byte family header
            return frame[4:]
        if link == 113:                                   # Linux cooked
            return frame[16:]
        return None

    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        e = "<" if magic[0] in (0xD4, 0x4D) else ">"
        nano = magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
        link = struct.unpack_from(e + "I", data, 20)[0]
        pos = 24
        while pos + 16 <= len(data):
            sec, frac, incl, _orig = struct.unpack_from(e + "IIII", data, pos)
            frame = data[pos + 16: pos + 16 + incl]
            pos += 16 + incl
            ip = strip(link, frame)
            if ip:
                yield sec + frac / (1e9 if nano else 1e6), ip
        return
    if magic != b"\x0a\x0d\x0d\x0a":
        raise ValueError("not a pcap or pcapng file")
    e, links, pos = "<", [], 0
    while pos + 12 <= len(data):
        btype = struct.unpack_from(e + "I", data, pos)[0]
        if btype == 0x0A0D0D0A:                           # section header: byte order
            e = "<" if data[pos + 8: pos + 12] == b"\x4d\x3c\x2b\x1a" else ">"
            links = []
        blen = struct.unpack_from(e + "I", data, pos + 4)[0]
        if blen < 12:
            break
        if btype == 1:                                    # interface description
            links.append(struct.unpack_from(e + "H", data, pos + 8)[0])
        elif btype == 6:                                  # enhanced packet
            iface, hi, lo, incl = struct.unpack_from(e + "IIII", data, pos + 8)
            frame = data[pos + 28: pos + 28 + incl]
            ip = strip(links[iface] if iface < len(links) else 1, frame)
            if ip:
                yield ((hi << 32) | lo) / 1e6, ip
        pos += blen


def replay_pcap(path: str, on_bytes: Callable[[FlowKey, bytes, bool], None],
                server_ports: set[int] | None = None, realtime: bool = False) -> int:
    """Feed a Wireshark capture (pcap/pcapng) through the same pipeline. Returns packets read."""
    streams: dict[FlowKey, TcpStream] = {}
    count = 0
    t0 = wall0 = None
    for ts, pkt in read_pcap(path):
        p = parse_ipv4_tcp(pkt)
        if p is None:
            continue
        src, sport, dst, dport, seq, data = p
        if (server_ports and sport not in server_ports) or not data:
            continue
        if realtime:
            if t0 is None:
                t0, wall0 = ts, time.time()
            delay = (ts - t0) - (time.time() - wall0)
            if delay > 0:
                time.sleep(delay)
        key = (src, sport, dst, dport)
        st = streams.setdefault(key, TcpStream())
        out, gap = st.push(seq, data, ts)
        if out:
            on_bytes(key, out, gap)
        count += 1
    return count
