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
import sys
import threading
from dataclasses import dataclass

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


def describe(skill_id: int, level: int) -> SkillText | None:
    """The description at this skill level (level 0 = not learned: shows level 1; above the data's max, as from
    Daevanion nodes: shows the max). None when the skill isn't in the data."""
    e = _load().get(str(skill_id)) if skill_id else None
    texts = (e or {}).get("text") or []
    if not texts:
        return None
    i = max(1, min(int(level or 1), len(texts))) - 1
    pick = lambda key: ((e.get(key) or [""] * len(texts)) + [""] * len(texts))[i] or ""  # noqa: E731
    return SkillText(name=e.get("name") or "", text=texts[i], level=i + 1, max_level=len(texts),
                     cooldown=str(pick("cd")), mp=str(pick("mp")), url=e.get("url") or "")


def count() -> int:
    return len(_load())
