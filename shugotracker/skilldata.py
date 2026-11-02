"""Skill descriptions bundled with the app (shugotracker/data/skills.json.gz, made by tools/fetch_skills.py).

The text comes from MetaBot.GG, which reads it from the AION 2 Global client. Their terms let apps show it as long
as each skill credits MetaBot.GG with a link to the page it came from, so every entry keeps that page's URL and
the Skills tab opens it on click.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass, field

log = logging.getLogger(__name__)
SOURCE = "MetaBot.GG"
_lock = threading.Lock()
_skills: dict[str, dict] | None = None


def _path() -> str:
    base = getattr(sys, "_MEIPASS", None)                 # inside the exe (PyInstaller unpacks data here)
    if base:
        return os.path.join(base, "shugotracker", "data", "skills.json.gz")
    return os.path.join(os.path.dirname(__file__), "data", "skills.json.gz")


def _load() -> dict[str, dict]:
    global _skills
    with _lock:
        if _skills is None:
            try:
                with gzip.open(_path(), "rt", encoding="utf-8") as f:
                    _skills = json.load(f).get("skills") or {}
            except (OSError, ValueError) as e:
                log.info("no skill descriptions: %s", e)
                _skills = {}
        return _skills


@dataclass
class SkillText:
    name: str
    text: str
    level: int          # the level the text is for (the character's, within what the data has)
    max_level: int
    cooldown: str
    mp: str
    url: str
    spans: list[tuple[int, int]] = field(default_factory=list)   # (start, end) of the numbers to highlight

# A number as the game writes it: 1,234 / 12.5% / a range like 170–187
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?(?:\s*[–~]\s*\d[\d,]*(?:\.\d+)?)?%?")


def scaling_spans(texts: list[str], i: int) -> list[tuple[int, int]]:
    """Where texts[i]'s numbers that change with skill level are, so they can be highlighted like the game does
    (Move Speed 12.5% is gold, the fixed 15% chance isn't). Numbers are compared by position across all levels;
    if the levels don't line up number for number, every number is highlighted."""
    per_level = [list(_NUMBER.finditer(t)) for t in texts]
    mine = per_level[i]
    if len({len(m) for m in per_level}) != 1:
        return [m.span() for m in mine]
    return [m.span() for k, m in enumerate(mine) if len({lv[k].group() for lv in per_level}) > 1]


def _find(skill_id: int, name: str, cls: str) -> dict | None:
    skills = _load()
    if skill_id and str(skill_id) in skills:
        return skills[str(skill_id)]
    if not name:
        return None
    if cls and f"name:{cls}:{name}" in skills:            # entries MetaBot had no ID for
        return skills[f"name:{cls}:{name}"]
    return None


def describe(skill_id: int, level: int, name: str = "", cls: str = "") -> SkillText | None:
    """The description at this skill level (level 0 = not learned: shows level 1; above the data's max, as from
    Daevanion nodes: shows the max). Found by the game's skill ID, else by class + name. None when not in the data."""
    e = _find(skill_id, name, cls)
    texts = (e or {}).get("text") or []
    if not texts:
        return None
    i = max(1, min(int(level or 1), len(texts))) - 1
    pick = lambda key: ((e.get(key) or [""] * len(texts)) + [""] * len(texts))[i] or ""  # noqa: E731
    return SkillText(name=e.get("name") or "", text=texts[i], level=i + 1, max_level=len(texts),
                     cooldown=str(pick("cd")), mp=str(pick("mp")), url=e.get("url") or "",
                     spans=scaling_spans(texts, i))


def count() -> int:
    return len(_load())
