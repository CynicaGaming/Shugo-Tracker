"""How the result table sorts (no Tk here, so it's testable anywhere)."""
from __future__ import annotations

SIDE_ORDER = {"enemy": 0, "ally": 1}
# column key -> (what to sort by, biggest/newest first by default)
SORTS = {
    "default": (None, False),
    "latest": (None, True),
    "name": (lambda c: c.name.casefold(), False),
    "class": (lambda c: (c.class_name or "").casefold() or None, False),
    "level": (lambda c: c.level or None, True),
    "server": (lambda c: ((c.region or ""), (c.server_name or "").casefold()) if c.server_name else None, False),
    "gs": (lambda c: c.gear_score, True),
    "cp": (lambda c: c.combat_power, True),
}


def sort_chars(chars: list, key: str, side_of: dict | None = None, when: dict | None = None,
               reverse: bool = False) -> list:
    """Sort table rows. side_of (name -> 'enemy'/'ally') keeps sides grouped, enemies first; when (key or name
    -> time) drives 'latest'. Each column has a natural direction (numbers biggest first, text A–Z); reverse
    flips it. Rows with nothing to sort by go last either way; with no sort at all, order is kept."""
    when = when or {}
    if key == "latest" and when:
        value = lambda c: when.get(c.key, when.get(c.name))             # noqa: E731
        desc = True
    else:
        value, desc = SORTS.get(key, (None, False))
    out = list(chars)
    if value is not None:
        known = [c for c in out if value(c) is not None]
        unknown = [c for c in out if value(c) is None]
        known.sort(key=value, reverse=desc != reverse)
        out = known + unknown
    if side_of is not None:
        out.sort(key=lambda c: SIDE_ORDER.get(side_of.get(c.name), 2))   # stable: keeps the order within a side
    return out
