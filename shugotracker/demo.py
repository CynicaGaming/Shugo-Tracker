"""Offline stand-in for the AION 2 endpoints: --demo shows the search window with made-up characters."""
from __future__ import annotations

import random
import threading
import time
from urllib.parse import quote

from . import aion2api as a
from . import servers as sv

_SYL = ["ka", "ri", "mor", "vel", "dra", "nyx", "sa", "lo", "thi", "gr", "ae", "zu", "kel", "en", "lu", "na"]
_PCIDS = [6, 10, 14, 18, 22, 26, 30, 34]
_REGION_DIGIT = {"nae": 1, "naw": 2, "eu": 3, "la": 4, "as": 5}


class _Resp:
    def __init__(self, data):
        self._data, self.status_code, self.headers = data, 200, {}

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class DemoSession:
    """Answers search/info calls with deterministic fake data and realistic delays."""

    def __init__(self, slow: float = 1.0):
        self.headers = {}
        self.slow = slow
        self._lock = threading.Lock()

    def _rnd(self, *key):
        return random.Random("|".join(map(str, key)))

    def get(self, url, params=None, timeout=None):
        p = params or {}
        if url == a.SEARCH_URL:
            time.sleep(self._rnd(p.get("region"), p.get("page")).uniform(0.2, 0.7) * self.slow)
            return _Resp(self._search(p["keyword"], p["region"], int(p["page"]), int(p["size"])))
        if url == a.INFO_URL:
            time.sleep(random.uniform(0.15, 0.9) * self.slow)
            return _Resp(self._info(p["characterId"]))
        from .profile import EQUIPMENT_URL, ITEM_URL
        if url == ITEM_URL:
            time.sleep(random.uniform(0.1, 0.4) * self.slow)
            return _Resp(self._item(p))
        if url == EQUIPMENT_URL:
            time.sleep(random.uniform(0.2, 0.8) * self.slow)
            return _Resp(self._equipment(p["characterId"]))
        raise ValueError(url)

    def _item(self, p):
        r = self._rnd(p.get("characterId"), p.get("slotPos"))
        slot = int(p.get("slotPos") or 0)
        if slot >= 41:                            # an Arcana card: linked skills and a set
            return {"level": 80, "categoryName": "Arcana", "mainStats": [{"name": "Time [Siel]", "value": "20", "extra": "3"}],
                    "subSkills": [{"name": n, "level": r.randint(1, 3)} for n in ("Judgment", "Insulting Roar", "Pummel")],
                    "set": {"name": "Primal Vigor", "equippedCount": 4, "items": [{}] * 5,
                            "bonuses": [{"degree": 2, "descriptions": ["+60 PvE Attack when HP is 70% or more"]},
                                        {"degree": 4, "descriptions": ["+150 PvE Attack when HP is 70% or more"]}]}}
        stones = [{"name": r.choice(["HP", "MP", "Attack", "Accuracy"]), "value": f"+{r.choice([15, 30, 60])}",
                   "grade": r.choice(["Common", "Rare"]), "slotPos": i} for i in range(r.randint(1, 4))]
        return {"level": r.randint(60, 90), "categoryName": "Longsword", "equipLevel": 45, "maxEnchantLevel": 15,
                "maxExceedEnchantLevel": 5, "magicStoneSlotCount": 4, "godStoneSlotCount": 1,
                "mainStats": [{"name": "Attack", "value": str(r.randint(300, 450)), "extra": str(r.randint(50, 150))},
                              {"name": "Accuracy", "value": "150", "extra": "0"}],
                "subStats": [{"name": "Might", "value": "30"}, {"name": "Combat Speed", "value": "11.9%"}],
                "magicStoneStat": stones,
                "godStoneStat": [{"name": "Freezing Strike", "desc": "Chance to freeze the target on hit"}]
                if r.random() < 0.5 else []}

    def _search(self, kw, region, page, size):
        r = self._rnd(kw.lower(), region)
        total = r.randint(4, 140)
        items = []
        for i in range((page - 1) * size, min(page * size, total)):
            ri = self._rnd(kw.lower(), region, i)
            race = ri.choice([1, 2])
            n = ri.randint(1, 20)
            server = race * 1000 + _REGION_DIGIT[region] * 100 + n
            name = kw.capitalize() if i < 3 else (
                ri.choice(["", kw.capitalize()]) + "".join(ri.choice(_SYL) for _ in range(ri.randint(1, 2)))
                + ("" if ri.random() < .5 else kw.lower())).capitalize()
            cid = f"demo-{region}-{i}-{kw.lower()}="
            items.append({"characterId": quote(cid), "name": name.replace(kw.capitalize(), f"<strong>{kw.capitalize()}</strong>"),
                          "race": race, "pcId": ri.choice(_PCIDS), "level": ri.choice([45, 45, 45, 44, 38, 21, 1]),
                          "serverId": server, "serverName": sv.name_of(server), "profileImageUrl": None,
                          "region": region})
        return {"list": items, "pagination": {"page": page, "size": size, "total": total}}

    def _info(self, char_id):
        r = self._rnd(char_id)
        stats = [{"type": t, "name": n, "value": r.randint(0, 80), "statSecondList": [f"{n} bonus +{r.randint(1, 8)}%"]}
                 for t, n in [("STR", "Might"), ("DEX", "Dexterity"), ("INT", "Intelligence"), ("CON", "Constitution"),
                              ("AGI", "Precision"), ("WIS", "Willpower"), ("Justice", "Justice [Nezekan]"),
                              ("Freedom", "Freedom [Vaizel]"), ("Time", "Time [Siel]"), ("Space", "Space [Israphel]")]]
        stats.append({"type": "ItemLevel", "name": "Item level", "value": r.randint(600, 2900)})
        return {"profile": {"combatPower": r.randint(20_000, 230_000), "titleName": "Saint of Verteron",
                            "regionName": r.choice(["Power", "Valor", "Ember"])},
                "stat": {"statList": stats},
                "title": {"ownedCount": r.randint(20, 290), "totalCount": 297,
                          "titleList": [{"name": "Golden Glow", "equipCategory": "Attack", "grade": "Unique",
                                         "ownedPercent": 70, "equipStatList": [{"desc": "Critical Attack +45"}],
                                         "statList": [{"desc": "Critical Attack +3"}]}]},
                "daevanion": {"boardList": [{"name": n, "openNodeCount": r.randint(0, tot), "totalNodeCount": tot}
                                            for n, tot in [("Nezekan", 88), ("Zikel", 88), ("Vaizel", 88),
                                                           ("Triniel", 116), ("Azphel", 152)]]}}

    def _equipment(self, char_id):
        r = self._rnd(char_id, "eq")
        from .profile import GEAR_ACCESSORIES, GEAR_ARCANA, GEAR_MAIN
        grades = ["Unique", "Unique", "Legend", "Epic", "Special"]
        pos = {"MainHand": 1, "SubHand": 2, "Helmet": 3, "Shoulder": 4, "Torso": 5, "Pants": 6, "Gloves": 7, "Boots": 8,
               "Necklace": 10, "Earring1": 11, "Earring2": 12, "Ring1": 13, "Ring2": 14, "Bracelet1": 15, "Bracelet2": 16,
               "Belt": 17, "Cape": 19, "Amulet": 22, "Rune1": 23, "Rune2": 24,
               **{f"Arcana{i}": 40 + i for i in range(1, 11)}}
        slots = GEAR_MAIN + GEAR_ACCESSORIES + GEAR_ARCANA[:7]           # 7 of the 10 Arcana slots filled
        gear = [{"slotPosName": s, "slotPos": pos.get(s, 0), "id": 100000 + pos.get(s, 0),
                 "name": (f"Enraged Kromede's Ancient Ceremonial {s}" if s in ("Necklace", "Earring1") else f"Demo {s}"),
                 "grade": r.choice(grades), "enchantLevel": r.randint(0, 15),
                 "exceedLevel": r.choice([0, 0, 1])} for s in slots]
        skills = [{"name": f"{cat} skill {i + 1}", "category": cat, "skillLevel": r.randint(0, 20),
                   "equip": int(r.random() < .5), "acquired": int(r.random() < .85), "needLevel": i}
                  for cat in ("Active", "Passive", "Dp") for i in range(6)]
        return {"equipment": {"equipmentList": gear,
                              "skinList": [{"slotPosName": s, "name": f"Demo outfit ({s})", "grade": "Legend"}
                                           for s in ("Helmet", "Torso", "Gloves", "Boots")]},
                "petwing": {"pet": {"name": "Crasaur", "level": 3}, "wing": {"name": "Forest Spirit Wings",
                                                                             "grade": "Unique"}},
                "skill": {"skillList": skills}}


# ───── nearby (made-up game traffic, decoded by the real decoder) ─────
DEMO_NEARBY = [("Kraeg", 2101, 6), ("Vexa", 2101, 26), ("Morrow", 2102, 18), ("Sable", 2101, 34),
               ("Aria", 1101, 10), ("Tamsin", 1102, 22), ("Oren", 1101, 46), ("Ilsa", 1101, 14)]
def _frame(body: bytes) -> bytes:
    from .protocol import encode_varint
    return encode_varint(len(body) + 4) + body


def _name(name: str) -> bytes:
    b = name.encode()
    return bytes([0x01, len(b)]) + b


def feed_nearby(service) -> None:
    import struct
    from .protocol import encode_varint
    frames = [b"\x33\x36" + encode_varint(100) + b"\x00" * 4 + _name("Luna") + struct.pack("<HIBI", 1101, 30, 0, 45)
              + b"\x00" * 24]
    people = DEMO_NEARBY
    for i, (nm, server, cls) in enumerate(people):
        eid = 200 + i
        frames.append(b"\x45\x36" + encode_varint(eid) + b"\x10\x00\x00\x00" + _name(nm) + struct.pack("<I", cls))
        nb = nm.encode()
        frames.append(b"\x04\x8d" + encode_varint(5000 + i) + b"\x01\x02\x03\x04" + encode_varint(eid)
                      + struct.pack("<H", server) + bytes([len(nb)]) + nb + b"\x00" * 4)
    # Kraeg is hitting you
    frames.append(b"\x04\x38" + encode_varint(100) + encode_varint(0x05) + encode_varint(0) + encode_varint(200)
                  + struct.pack("<I", 12010000) + b"\x00" * 20)
    service.on_bytes(("demo", 0, "demo", 0), b"".join(_frame(f) for f in frames), False)


def feed_teleport(service) -> None:
    """--demo: you load into a new area; the old crowd moves to Recent."""
    import struct
    from .protocol import encode_varint
    for dec in service._decoders.values():
        dec._self_at.clear()
    frames = [b"\x33\x36" + encode_varint(100) + b"\x00" * 4 + _name("Luna") + struct.pack("<HIBI", 1101, 30, 0, 45)
              + b"\x00" * 24]
    for i, (nm, server, cls) in enumerate([("Aria", 1101, 10), ("Kraeg", 2101, 6)]):
        eid = 900 + i
        frames.append(b"\x45\x36" + encode_varint(eid) + b"\x10\x00\x00\x00" + _name(nm) + struct.pack("<I", cls))
    service.on_bytes(("demo", 0, "demo", 0), b"".join(_frame(f) for f in frames), False)


def find_nearby(session):
    """find_by_name for --demo: like NCSOFT, the exact name in that region."""
    import random
    from .aion2api import Character, class_pc_ids
    from . import servers as sv
    home = {n: srv for n, srv, _ in DEMO_NEARBY}
    home["Luna"] = 1101

    def find(name: str, region: str, classes=None, pc_ids=None, race=None):
        srv = home.get(name)
        if srv is None or sv.REGION_PREFIX.get(sv.region_of(srv)) != region:
            return []
        r = random.Random(name)
        cls = r.choice(["Gladiator", "Templar", "Ranger", "Assassin", "Spiritmaster", "Sorcerer", "Cleric",
                        "Chanter", "Brawler"])
        return [Character(char_id=f"demo-{name}", name=name, race=sv.race_of(srv), pc_id=class_pc_ids([cls])[0],
                          level=45, server_id=srv, server_name=sv.name_of(srv), region=region)]
    return find
