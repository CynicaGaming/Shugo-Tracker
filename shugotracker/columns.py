"""Result-table column layout: which columns fit a list this wide, and how wide each one is (no Tk here)."""
from __future__ import annotations

GAP = 10
STAR_W = 24        # the favorite star, right of CP
# key, min width, max width, share of spare room, text anchor, drop order when narrow (1 goes first; 0 never)
SPEC = [
    ("name", 130, 10 ** 6, 3, "w", 0),
    ("legion", 56, 170, 2, "w", 2),
    ("class", 70, 112, 1, "w", 3),
    ("level", 24, 24, 0, "e", 0),
    ("server", 90, 200, 2, "w", 1),
    ("gs", 44, 52, 0, "e", 0),
    ("cp", 60, 72, 0, "e", 0),
    ("seen", 64, 96, 0, "w", 2),
]
SPEC_BY_KEY = {c[0]: c for c in SPEC}
LABELS = {"name": "Name", "legion": "Legion", "class": "Class", "level": "Lv", "server": "Server", "gs": "GS",
          "cp": "CP", "seen": "Last seen"}
MENU_LABELS = {**LABELS, "level": "Level", "gs": "Gear score", "cp": "Combat power"}
DEFAULT_COLUMNS = ["legion", "class", "level", "server", "gs", "cp", "seen"]   # Name always comes first


def clean_columns(cols) -> list[str]:
    """A saved column list, made safe: known keys, no repeats, no Name (it's always there)."""
    if not isinstance(cols, list):
        return list(DEFAULT_COLUMNS)
    out = []
    for k in cols:
        if k in SPEC_BY_KEY and k != "name" and k not in out:
            out.append(k)
    return out


def layout_columns(width: int, keys: list[str] | None = None) -> dict:
    """{"x1": right edge, "star": star centre x, "spans": {key: (left, right, anchor)}} for a list `width` wide,
    showing Name then `keys` in that order. Columns grow with the window (each by its share, up to its max;
    Name takes the rest) and drop out in order (Server, then Legion / Last seen, then Class) when it's narrow."""
    x1 = width - 6
    left, right = 8, x1 - STAR_W
    avail = right - left
    keys = DEFAULT_COLUMNS[:-1] if keys is None else keys
    cols = [SPEC_BY_KEY["name"]] + [SPEC_BY_KEY[k] for k in keys if k in SPEC_BY_KEY and k != "name"]

    def need(cs):
        return sum(c[1] for c in cs) + GAP * (len(cs) - 1)

    for drop in (1, 2, 3):
        if need(cols) <= avail:
            break
        cols = [c for c in cols if c[5] != drop]
    widths = {c[0]: float(c[1]) for c in cols}
    spare = avail - need(cols)
    if spare < 0:                                  # still too narrow: the name gives way (down to a stub)
        widths["name"] = max(40.0, widths["name"] + spare)
    while spare > 0.5:
        flex = [c for c in cols if c[3] and widths[c[0]] < c[2]]
        if not flex:
            break
        total = sum(c[3] for c in flex)
        used = 0.0
        for c in flex:
            add = min(spare * c[3] / total, c[2] - widths[c[0]])
            widths[c[0]] += add
            used += add
        spare -= used
        if used < 0.5:
            break
    spans, x = {}, float(left)
    for c in cols:
        spans[c[0]] = (round(x), round(x + widths[c[0]]), c[4])
        x += widths[c[0]] + GAP
    return {"x1": x1, "star": x1 - 11, "spans": spans}
