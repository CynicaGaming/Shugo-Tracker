"""Minimal one-direction TCP reassembly (server -> client)."""
from __future__ import annotations

import time

MOD = 1 << 32


def _diff(a: int, b: int) -> int:
    """Signed distance a - b in sequence space."""
    d = (a - b) % MOD
    return d - MOD if d >= MOD // 2 else d


class TcpStream:
    """
    Delivers bytes in order. Out-of-order segments wait in a small buffer; if a gap
    is not filled within `gap_timeout_s` (lost capture), the stream skips ahead and
    reports a discontinuity so the decoder can resync.
    """

    def __init__(self, gap_timeout_s: float = 1.5, max_pending: int = 2_000_000):
        self.next_seq: int | None = None
        self.pending: dict[int, bytes] = {}
        self.pending_bytes = 0
        self.gap_since: float | None = None
        self.gap_timeout_s = gap_timeout_s
        self.max_pending = max_pending

    def push(self, seq: int, data: bytes, now: float | None = None) -> tuple[bytes, bool]:
        """Returns (in-order bytes now available, discontinuity happened)."""
        now = now or time.time()
        if not data:
            return b"", False
        if self.next_seq is None:
            self.next_seq = seq
        d = _diff(seq, self.next_seq)
        if d < 0:  # retransmit / overlap
            if -d >= len(data):
                return self._drain(now)
            data = data[-d:]
            seq = self.next_seq
        if seq != self.next_seq:
            if seq not in self.pending:
                self.pending[seq] = data
                self.pending_bytes += len(data)
            if self.gap_since is None:
                self.gap_since = now
            return self._drain(now)
        out = bytearray(data)
        self.next_seq = (seq + len(data)) % MOD
        more, gap = self._drain(now)
        out += more
        return bytes(out), gap

    def _drain(self, now: float) -> tuple[bytes, bool]:
        out = bytearray()
        gap = False
        while True:
            progressed = False
            for s in list(self.pending):
                d = _diff(s, self.next_seq)
                if d <= 0:
                    seg = self.pending.pop(s)
                    self.pending_bytes -= len(seg)
                    if -d < len(seg):
                        seg = seg[-d:] if d < 0 else seg
                        out += seg
                        self.next_seq = (self.next_seq + len(seg)) % MOD
                    progressed = True
            if progressed:
                continue
            if not self.pending:
                self.gap_since = None
                break
            timed_out = self.gap_since is not None and now - self.gap_since > self.gap_timeout_s
            if timed_out or self.pending_bytes > self.max_pending:
                # give up on the hole: jump to the earliest pending segment
                self.next_seq = min(self.pending, key=lambda s: _diff(s, self.next_seq))
                gap = True
                self.gap_since = now
                continue
            break
        return bytes(out), gap
