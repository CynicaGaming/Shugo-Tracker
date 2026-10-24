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
        from .profile import EQUIPMENT_URL
        if url == EQUIPMENT_URL:
            time.sleep(random.uniform(0.2, 0.8) * self.slow)
            return _Resp(self._equipment(p["characterId"]))
        raise ValueError(url)

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
        gear = [{"slotPosName": s, "name": (f"Enraged Kromede's Ancient Ceremonial {s}" if s in ("Necklace", "Earring1") else f"Demo {s}"), "grade": r.choice(grades), "enchantLevel": r.randint(0, 15),
                 "exceedLevel": r.choice([0, 0, 1])} for s in GEAR_MAIN + GEAR_ACCESSORIES + GEAR_ARCANA]
        skills = [{"name": f"{cat} skill {i + 1}", "category": cat, "skillLevel": r.randint(0, 20),
                   "equip": int(r.random() < .5), "acquired": int(r.random() < .85), "needLevel": i}
                  for cat in ("Active", "Passive", "Dp") for i in range(6)]
        return {"equipment": {"equipmentList": gear,
                              "skinList": [{"slotPosName": s, "name": f"Demo outfit ({s})", "grade": "Legend"}
                                           for s in ("Helmet", "Torso", "Gloves", "Boots")]},
                "petwing": {"pet": {"name": "Crasaur", "level": 3}, "wing": {"name": "Forest Spirit Wings",
                                                                             "grade": "Unique"}},
                "skill": {"skillList": skills}}
