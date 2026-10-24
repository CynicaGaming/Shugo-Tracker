"""Full character profile: parsed from the info + equipment endpoints (the same data Shugo.GG's profile shows)."""
from __future__ import annotations

from dataclasses import dataclass, field

EQUIPMENT_URL = "https://aion2.plaync.com/api/character/equipment"

# Display groups for the gear tab, in the order the game's character window uses.
GEAR_MAIN = ["MainHand", "SubHand", "Helmet", "Shoulder", "Torso", "Pants", "Gloves", "Boots", "Cape", "Belt"]
GEAR_ACCESSORIES = ["Necklace", "Earring1", "Earring2", "Ring1", "Ring2", "Bracelet1", "Bracelet2",
                    "Amulet", "Rune1", "Rune2"]
GEAR_ARCANA = ["Arcana1", "Arcana2", "Arcana3", "Arcana4", "Arcana5"]
SLOT_LABELS = {
    "MainHand": "Main hand", "SubHand": "Off hand", "Earring1": "Earring", "Earring2": "Earring",
    "Ring1": "Ring", "Ring2": "Ring", "Bracelet1": "Bracelet", "Bracelet2": "Bracelet",
    "Rune1": "Rune", "Rune2": "Rune", "Cape": "Cloak", "Torso": "Chest", "Pants": "Legs",
    "SwordMain": "Weapon", "Arcana1": "Arcana", "Arcana2": "Arcana", "Arcana3": "Arcana",
    "Arcana4": "Arcana", "Arcana5": "Arcana",
}
SKILL_CATEGORIES = [("Active", "Active"), ("Passive", "Passive"), ("Dp", "Stigma")]
PRIMARY_STATS = ["STR", "DEX", "INT", "CON", "AGI", "WIS"]


@dataclass
class Item:
    slot: str
    name: str
    grade: str
    enchant: int = 0
    exceed: int = 0
    icon: str | None = None
    item_id: int = 0
    level: int | None = None   # pets

    @property
    def slot_label(self) -> str:
        return SLOT_LABELS.get(self.slot, self.slot)


@dataclass
class Skill:
    name: str
    category: str
    level: int
    equipped: bool
    acquired: bool
    icon: str | None = None
    need_level: int = 0


@dataclass
class Stat:
    type: str
    name: str
    value: int
    effects: list[str] = field(default_factory=list)

    @property
    def per_point(self) -> list[str]:
        """What one point of this stat adds, e.g. ["Attack increase +0.1%"] (empty for unknown stats)."""
        return [f"{label} {sign}{STAT_PER_POINT:g}%" for label, sign in STAT_BONUSES.get(self.type, ())]


# Every point of a stat adds 0.1% to each of its bonuses (checked against ~50 live characters; the API only
# lists bonuses for stats that have points, so this lets empty stats show what they would give).
STAT_PER_POINT = 0.1
STAT_BONUSES: dict[str, list[tuple[str, str]]] = {
    "STR": [("Attack increase", "+")],
    "DEX": [("Evasion increase", "+"), ("Block increase", "+"), ("Critical Hit Resist increase", "+")],
    "AGI": [("Accuracy increase", "+"), ("Critical Hit increase", "+")],
    "CON": [("HP increase", "+")],
    "INT": [("Status Effect Chance", "+")],
    "WIS": [("Status Effect Resist", "+")],
    "Justice": [("Defense increase", "+"), ("Perfect Chance", "+")],
    "Freedom": [("Accuracy increase", "+"), ("Evasion increase", "+")],
    "Illusion": [("Cooldown", "-"), ("Endurance Penetration", "+")],
    "Life": [("HP increase", "+"), ("Regeneration", "+")],
    "Time": [("Combat Speed", "+"), ("Double Resist", "+")],
    "Destruction": [("Attack increase", "+"), ("Perfect Resist", "+")],
    "Death": [("Critical Hit increase", "+"), ("Regeneration Penetration", "+")],
    "Wisdom": [("Double Chance", "+"), ("MP Cost", "-")],
    "Destiny": [("MP increase", "+"), ("Endurance", "+")],
    "Space": [("Move Speed", "+"), ("Block increase", "+")],
}


@dataclass
class Board:
    name: str
    opened: int
    total: int
    icon: str | None = None
    game_percent: int | None = None   # the game's own rounding

    @property
    def percent(self) -> int:
        if self.game_percent is not None:
            return self.game_percent
        return int(100 * self.opened / self.total + 0.5) if self.total else 0


@dataclass
class Title:
    name: str
    category: str
    grade: str
    effects: list[str] = field(default_factory=list)
    owned_percent: int | None = None


@dataclass
class Profile:
    name: str = ""
    class_name: str = ""
    level: int = 0
    race: int = 0
    server_id: int = 0
    server_name: str = ""
    legion: str | None = None
    title: str | None = None
    gender: str | None = None
    combat_power: int | None = None
    gear_score: int | None = None
    portrait: str | None = None
    stats: list[Stat] = field(default_factory=list)
    gear: dict[str, Item] = field(default_factory=dict)
    skins: list[Item] = field(default_factory=list)
    wing: Item | None = None
    wing_skin: Item | None = None
    pet: Item | None = None
    skills: list[Skill] = field(default_factory=list)
    boards: list[Board] = field(default_factory=list)
    titles: list[Title] = field(default_factory=list)
    titles_owned: int | None = None
    titles_total: int | None = None
    equipment_error: str | None = None
    equipment_pending: bool = False   # info arrived, gear/skills/cosmetics still loading
    cached_at: float | None = None    # set when this copy came from the cache

    def skills_in(self, category: str) -> list[Skill]:
        out = [s for s in self.skills if s.category == category]
        return sorted(out, key=lambda s: (not s.equipped, not s.acquired, -s.level, s.need_level))

    @property
    def primary_stats(self) -> list[Stat]:
        return [s for s in self.stats if s.type in PRIMARY_STATS]

    @property
    def deity_stats(self) -> list[Stat]:
        return [s for s in self.stats if s.type not in PRIMARY_STATS and s.type != "ItemLevel"]


def _item(d: dict | None, slot: str | None = None) -> Item | None:
    # NCSOFT sends an empty placeholder (no name, no icon) for things a character doesn't have
    if not d or not (d.get("name") or d.get("icon")):
        return None
    return Item(slot=slot or d.get("slotPosName") or "", name=d.get("name") or "?", grade=d.get("grade") or "Common",
                enchant=int(d.get("enchantLevel") or 0), exceed=int(d.get("exceedLevel") or 0),
                icon=d.get("icon"), item_id=int(d.get("id") or 0),
                level=int(d["level"]) if d.get("level") is not None else None)


def parse_profile(info: dict, equipment: dict | None) -> Profile:
    prof = info.get("profile") or {}
    p = Profile(
        name=prof.get("characterName") or "",
        class_name=prof.get("className") or "",
        level=int(prof.get("characterLevel") or 0),
        race=int(prof.get("raceId") or 0),
        server_id=int(prof.get("serverId") or 0),
        server_name=prof.get("serverName") or "",
        legion=prof.get("regionName") or None,     # the API calls the legion "regionName"
        title=prof.get("titleName") or None,
        gender=prof.get("genderName") or None,
        combat_power=int(prof["combatPower"]) if prof.get("combatPower") is not None else None,
        portrait=prof.get("profileImage") or None,
    )
    if p.class_name == "Elementalist":
        p.class_name = "Spiritmaster"
    for st in (info.get("stat") or {}).get("statList") or []:
        if st.get("type") == "ItemLevel":
            p.gear_score = int(st.get("value") or 0) or None
            continue
        p.stats.append(Stat(type=st.get("type") or "", name=st.get("name") or "", value=int(st.get("value") or 0),
                            effects=list(st.get("statSecondList") or [])))
    for b in (info.get("daevanion") or {}).get("boardList") or []:
        p.boards.append(Board(name=b.get("name") or "", opened=int(b.get("openNodeCount") or 0),
                              total=int(b.get("totalNodeCount") or 0), icon=b.get("icon"),
                              game_percent=int(b["openPercent"]) if b.get("openPercent") is not None else None))
    tinfo = info.get("title") or {}
    p.titles_owned, p.titles_total = tinfo.get("ownedCount"), tinfo.get("totalCount")
    for t in tinfo.get("titleList") or []:
        p.titles.append(Title(name=t.get("name") or "", category=t.get("equipCategory") or "",
                              grade=t.get("grade") or "", owned_percent=t.get("ownedPercent"),
                              effects=[e.get("desc", "") for e in (t.get("equipStatList") or [])]
                              + [e.get("desc", "") for e in (t.get("statList") or [])]))
    if equipment:
        eq = equipment.get("equipment") or {}
        for d in eq.get("equipmentList") or []:
            it = _item(d)
            if it:
                p.gear[it.slot] = it
        p.skins = [i for i in (_item(d) for d in eq.get("skinList") or []) if i]
        pw = equipment.get("petwing") or {}
        p.wing, p.wing_skin, p.pet = _item(pw.get("wing"), "Wings"), _item(pw.get("wingSkin"), "Wing skin"), \
            _item(pw.get("pet"), "Pet")
        if p.pet:
            p.pet.grade = p.pet.grade or "Common"
        for s in (equipment.get("skill") or {}).get("skillList") or []:
            p.skills.append(Skill(name=s.get("name") or "", category=s.get("category") or "",
                                  level=int(s.get("skillLevel") or 0), equipped=bool(s.get("equip")),
                                  acquired=bool(s.get("acquired")), icon=s.get("icon"),
                                  need_level=int(s.get("needLevel") or 0)))
    return p
