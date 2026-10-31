"""Server time (US Eastern, what the NA servers show as ST) and local time, for the footer clock.

US Eastern is worked out by hand (EST/EDT, second Sunday of March to first Sunday of November) so the packaged
app needs no time-zone database (Windows has none for Python's zoneinfo)."""
from __future__ import annotations

import datetime as dt
import time

_UTC = dt.timezone.utc


def _nth_sunday(year: int, month: int, n: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def eastern_offset(utc: dt.datetime) -> dt.timedelta:
    """UTC-4 during US daylight saving time, else UTC-5."""
    y = utc.year
    start = dt.datetime.combine(_nth_sunday(y, 3, 2), dt.time(7), _UTC)    # 2:00 EST
    end = dt.datetime.combine(_nth_sunday(y, 11, 1), dt.time(6), _UTC)     # 2:00 EDT
    return dt.timedelta(hours=-4 if start <= utc < end else -5)


def server_now(now: float | None = None) -> dt.datetime:
    utc = dt.datetime.fromtimestamp(time.time() if now is None else now, _UTC)
    return (utc + eastern_offset(utc)).replace(tzinfo=None)


def local_now(now: float | None = None) -> dt.datetime:
    return dt.datetime.fromtimestamp(time.time() if now is None else now)


def clock_text(mode: str, now: float | None = None) -> str:
    """'ST' (server) or 'LT' (local): date and time like the game shows them, MM/DD/YYYY HH:MM."""
    t = server_now(now) if mode == "ST" else local_now(now)
    return t.strftime("%m/%d/%Y %H:%M")
