"""Favorite characters, kept in favorites.json next to the app."""
from __future__ import annotations

import json
import os

from .aion2api import Character

_KEEP = ("char_id", "name", "race", "pc_id", "level", "server_id", "server_name", "region", "portrait", "legion")


class Favorites:
    def __init__(self, path: str | None, log=None):
        self.path = path
        self.log = log or (lambda s: None)
        self.last_error: str | None = None
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
        except (OSError, ValueError) as e:
            self.last_error = f"load: {e}"
            self.log(f"favorites: couldn't read {self.path}: {e}")
            # keep the unreadable file instead of overwriting it on the next save
            try:
                os.replace(self.path, self.path + ".broken")
            except OSError:
                pass

    def merge_from(self, path: str) -> int:
        """Add favorites from another favorites.json (keeps ours on conflicts). Returns how many were added."""
        other = Favorites(path)
        added = 0
        for k, d in other._items.items():
            if k not in self._items:
                self._items[k] = d
                added += 1
        return added

    def save(self) -> None:
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(list(self._items.values()), f, ensure_ascii=False, indent=1)
            for attempt in range(5):         # another program (antivirus, backup) may hold the file briefly
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    import time
                    time.sleep(0.1)
            self.last_error = None
        except (OSError, TypeError, ValueError) as e:
            self.last_error = f"save: {e}"
            self.log(f"favorites: couldn't save {self.path}: {e}")

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        # An empty list is still a real, saving favorites store: never let `favorites or ...` swap it out.
        return True

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
