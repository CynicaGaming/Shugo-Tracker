"""Server id helpers. Global ids are race*1000 + region*100 + n."""
from __future__ import annotations

import re

from .server_table import SERVER_NAMES

ELYOS, ASMODIAN = 1, 2
FACTION_NAMES = {ELYOS: "Elyos", ASMODIAN: "Asmodian"}

# Region digit -> Shugo.GG sub-region slug prefix (Global).
REGION_PREFIX = {1: "nae", 2: "naw", 3: "eu", 4: "la", 5: "as"}
REGION_LABEL = {1: "NA-East", 2: "NA-West", 3: "EU", 4: "LatAm", 5: "Asia", 0: "KR/TW"}

KNOWN_SERVERS: set[int] = set(SERVER_NAMES)


def race_of(server: int) -> int:
    return server // 1000


def region_of(server: int) -> int:
    return server // 100 % 10


def name_of(server: int) -> str:
    return SERVER_NAMES.get(server, str(server))


def slug_of(server: int) -> str:
    return re.sub(r"[^a-z0-9]+", "", name_of(server).lower())


def shugo_server_path(server: int, kr_tw_region: str = "kr") -> str | None:
    """'global/nae-siel' for Global ids, 'kr/kochi' for region-0 (KR/TW) ids."""
    if server not in SERVER_NAMES:
        return None
    reg = region_of(server)
    if reg in REGION_PREFIX:
        return f"global/{REGION_PREFIX[reg]}-{slug_of(server)}"
    if reg == 0:
        return f"{kr_tw_region}/{slug_of(server)}"
    return None


def mirror_server(server: int) -> int | None:
    """The opposite-faction server with the same region and number (Siel 1101 <-> Israphel 2101)."""
    r = race_of(server)
    if r not in (ELYOS, ASMODIAN):
        return None
    other = (3 - r) * 1000 + server % 1000
    return other if other in SERVER_NAMES else None


def parse_server(text: str | int | None) -> int | None:
    """Accept 1101, '1101', 'nae-siel', 'NAE Siel' or 'naw-israphel'."""
    if text is None or text == "":
        return None
    if isinstance(text, int):
        return text if text in SERVER_NAMES else None
    t = str(text).strip().lower()
    if t.isdigit():
        v = int(t)
        return v if v in SERVER_NAMES else None
    m = re.match(r"^(nae|naw|eu|la|as)[\s\-_/]+(.+)$", t)
    if not m:
        return None
    region = {v: k for k, v in REGION_PREFIX.items()}[m.group(1)]
    slug = re.sub(r"[^a-z0-9]+", "", m.group(2))
    for sid, name in SERVER_NAMES.items():
        if region_of(sid) == region and re.sub(r"[^a-z0-9]+", "", name.lower()) == slug:
            return sid
    return None


def label(server: int | None) -> str:
    if server is None:
        return "?"
    return f"{name_of(server)} ({REGION_LABEL.get(region_of(server), '?')})"
