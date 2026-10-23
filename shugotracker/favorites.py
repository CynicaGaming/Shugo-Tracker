"""Favorite characters, kept in favorites.json next to the app."""
from __future__ import annotations

import json
import os

from .aion2api import Character

_KEEP = ("char_id", "name", "race", "pc_id", "level", "server_id", "server_name", "region", "portrait", "legion")


class Favorites:
    def __init__(self, path: str | None):
        self.path = path
        self._items: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            for d in data if isinstance(data, list) else []:
                if isinstance(d, dict) and d.get("char_id") and d.get("server_id"):
                    self._items[f"{d['server_id']}:{d['char_id']}"] = {k: d.get(k) for k in _KEEP}
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(list(self._items.values()), f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def toggle(self, c: Character) -> bool:
        """Add or remove; returns True if c is now a favorite."""
        if c.key in self._items:
            del self._items[c.key]
            self.save()
            return False
        self._items[c.key] = {k: getattr(c, k) for k in _KEEP}
        self.save()
        return True

    def update(self, c: Character) -> None:
        """Keep a favorite's stored name/level/portrait current."""
        if c.key in self._items:
            self._items[c.key] = {k: getattr(c, k) for k in _KEEP}

    def characters(self) -> list[Character]:
        return [Character(**{k: d.get(k) for k in _KEEP}) for d in self._items.values()]
