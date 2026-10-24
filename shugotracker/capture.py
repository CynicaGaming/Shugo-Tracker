"""
Passive capture of AION 2 server->client traffic through Npcap (via scapy).

The game's TCP connections are found in the Windows TCP table (psutil) by owning
process (AION2.exe), so the sniffer only ever looks at the game's own downstream
packets. Nothing is sent, modified or injected.
"""
from __future__ import annotations

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


def bpf_for(conns: set[tuple[str, int, str, int]]) -> str:
    parts = [f"(src host {rip} and src port {rport} and dst port {lport})"
             for (_lip, lport, rip, rport) in sorted(conns)]
    return "tcp and (" + " or ".join(parts) + ")"


def tcp_payload(ip, tcp) -> bytes:
    """
    The TCP segment's real data. Ethernet pads frames shorter than 60 bytes with zeros, and scapy hands that
    padding back as part of the payload: for a bare ACK that's 6 zero bytes at the next sequence number, which
    the reassembler would then keep instead of the real bytes. Cut to the length the IP header states.
    """
    raw = bytes(tcp.payload)
    try:
        header = int(tcp.dataofs or 5) * 4
        if getattr(ip, "version", 4) == 6:
            size = int(ip.plen) - header
        else:
            size = int(ip.len) - int(ip.ihl or 5) * 4 - header
    except (TypeError, ValueError, AttributeError):
        return raw
    return raw[:max(0, size)]


class GameCapture:
    """
    Calls on_bytes(flow, data, gap) with in-order server->client bytes.
    Restarts the sniffer whenever the game's set of connections changes.
    """

    def __init__(self, on_bytes: Callable[[FlowKey, bytes, bool], None],
                 ifaces: list[str] | None = None, log: Callable[[str], None] | None = None,
                 process_names: set[str] | None = None, poll_s: float = 3.0):
        self.on_bytes = on_bytes
        self.ifaces = ifaces
        self.log = log or print
        self.process_names = process_names or GAME_PROCESS_NAMES
        self.poll_s = poll_s
        self.streams: dict[FlowKey, TcpStream] = {}
        self.status = "starting"
        self._sniffer = None
        self._conns: set = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._stop_sniffer()

    # ───── internals ─────
    def _run(self) -> None:
        try:
            from scapy.all import conf  # noqa: F401  (import check)
        except Exception as e:  # pragma: no cover
            self.status = f"scapy missing: {e}"
            self.log(self.status)
            return
        while not self._stop.is_set():
            conns = find_game_connections(self.process_names)
            if conns != self._conns:
                self._conns = conns
                self._stop_sniffer()
                if conns:
                    self._start_sniffer(conns)
                    self.status = f"capturing {len(conns)} game connection(s)"
                else:
                    self.status = "waiting for AION2.exe"
                self.log(self.status)
            self._stop.wait(self.poll_s)

    def _ifaces(self) -> list | None:
        if self.ifaces:
            return self.ifaces
        from scapy.all import conf
        # Every adapter, including the Npcap loopback adapter (ExitLag & other ping reducers
        # route the game through 127.0.0.1).
        try:
            return [i for i in conf.ifaces.values() if getattr(i, "is_valid", lambda: True)()]
        except Exception:
            return None

    def _start_sniffer(self, conns) -> None:
        from scapy.all import AsyncSniffer
        flt = bpf_for(conns)
        attempts = [self._ifaces()]
        if attempts[0] is not None and not self.ifaces:
            attempts.append(None)  # fall back to scapy's default adapter if one of them won't open
        for ifaces in attempts:
            try:
                self._sniffer = AsyncSniffer(iface=ifaces, filter=flt, prn=self._on_packet, store=False)
                self._sniffer.start()
                time.sleep(1.0)  # adapters are opened on the sniffer's own thread
                thread = getattr(self._sniffer, "thread", None)
                if thread is None or thread.is_alive():
                    return
                raise RuntimeError("sniffer stopped while opening adapters")
            except Exception as e:
                self.status = f"capture error: {e}"
                self._sniffer = None
        self.log(self.status + "  (is Npcap installed and are you running as administrator?)")

    def _stop_sniffer(self) -> None:
        s = self._sniffer
        self._sniffer = None
        if s is not None:
            try:
                s.stop()
            except Exception:
                pass

    def _on_packet(self, pkt) -> None:
        from scapy.layers.inet import IP, TCP
        from scapy.layers.inet6 import IPv6
        if TCP not in pkt:
            return
        ip = pkt[IP] if IP in pkt else (pkt[IPv6] if IPv6 in pkt else None)
        if ip is None:
            return
        tcp = pkt[TCP]
        data = tcp_payload(ip, tcp)
        if not data:
            return
        key: FlowKey = (ip.src, int(tcp.sport), ip.dst, int(tcp.dport))
        st = self.streams.get(key)
        if st is None:
            st = self.streams[key] = TcpStream()
        out, gap = st.push(int(tcp.seq), data, time.time())
        if out:
            self.on_bytes(key, out, gap)


def replay_pcap(path: str, on_bytes: Callable[[FlowKey, bytes, bool], None],
                server_ports: set[int] | None = None, realtime: bool = False) -> int:
    """Feed a Wireshark capture (pcap/pcapng) through the same pipeline. Returns packets read."""
    from scapy.all import PcapReader
    from scapy.layers.inet import IP, TCP
    streams: dict[FlowKey, TcpStream] = {}
    count = 0
    t0 = wall0 = None
    with PcapReader(path) as reader:
        for pkt in reader:
            if TCP not in pkt or IP not in pkt:
                continue
            tcp, ip = pkt[TCP], pkt[IP]
            if server_ports and int(tcp.sport) not in server_ports:
                continue
            data = tcp_payload(ip, tcp)
            if not data:
                continue
            ts = float(pkt.time)
            if realtime:
                if t0 is None:
                    t0, wall0 = ts, time.time()
                delay = (ts - t0) - (time.time() - wall0)
                if delay > 0:
                    time.sleep(delay)
            key = (ip.src, int(tcp.sport), ip.dst, int(tcp.dport))
            st = streams.setdefault(key, TcpStream())
            out, gap = st.push(int(tcp.seq), data, ts)
            if out:
                on_bytes(key, out, gap)
            count += 1
    return count
