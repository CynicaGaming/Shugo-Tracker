"""LZ4 block decoding. Uses the `lz4` package when installed, else a pure-Python decoder."""
from __future__ import annotations

try:  # pragma: no cover - optional speed-up
    import lz4.block as _lz4

    def decompress(src: bytes, size: int) -> bytes:
        return _lz4.decompress(src, uncompressed_size=size)
except ImportError:  # pragma: no cover
    _lz4 = None

    def decompress(src: bytes, size: int) -> bytes:
        return decompress_py(src, size)


def decompress_py(src: bytes, size: int) -> bytes:
    out = bytearray()
    i = 0
    n = len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                if i >= n:
                    raise ValueError("truncated literal length")
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        if i + lit > n:
            raise ValueError("truncated literals")
        out += src[i:i + lit]
        i += lit
        if i >= n:
            break  # last sequence carries literals only
        if i + 2 > n:
            raise ValueError("truncated offset")
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(out):
            raise ValueError("bad offset")
        mlen = token & 0x0F
        if mlen == 15:
            while True:
                if i >= n:
                    raise ValueError("truncated match length")
                b = src[i]
                i += 1
                mlen += b
                if b != 255:
                    break
        mlen += 4
        start = len(out) - offset
        if mlen <= offset:
            out += out[start:start + mlen]
        else:  # overlapping copy
            for k in range(mlen):
                out.append(out[start + k])
        if len(out) > size:
            raise ValueError("output overrun")
    return bytes(out)


def compress_literals(data: bytes) -> bytes:
    """A valid (uncompressed) LZ4 block holding `data` as literals - used by tests."""
    n = len(data)
    out = bytearray()
    if n < 15:
        out.append(n << 4)
    else:
        out.append(0xF0)
        rest = n - 15
        while rest >= 255:
            out.append(255)
            rest -= 255
        out.append(rest)
    out += data
    return bytes(out)
