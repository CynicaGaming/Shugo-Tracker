"""Your characters: up to five saved slots ("Set Profile → Set Character N"), one of them active.

The active character is who "My profile", Alt-compare and Nearby's sides use. Slots are only ever set by you
(right-click a player); the game's own traffic never changes them.
"""
from __future__ import annotations

SLOTS = 5
KEEP = ("char_id", "name", "race", "pc_id", "level", "server_id", "server_name", "region", "portrait")


class MyCharacters:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        raw = cfg.get("my_characters")
        if not isinstance(raw, list):
            old = cfg.get("my_character")                 # from before slots: becomes Character 1
            raw = [old] if isinstance(old, dict) and old.get("name") else []
        self.slots: list[dict | None] = [(d if isinstance(d, dict) and d.get("name") else None)
                                         for d in raw[:SLOTS]]
        self.slots += [None] * (SLOTS - len(self.slots))
        act = cfg.get("my_active", 0)
        self.active_slot = act if isinstance(act, int) and 0 <= act < SLOTS and self.slots[act] else None
        if self.active_slot is None:
            self.active_slot = self._first()
        self._save()

    def _first(self) -> int | None:
        return next((i for i, d in enumerate(self.slots) if d), None)

    def _save(self):
        self.cfg["my_characters"] = list(self.slots)
        self.cfg["my_active"] = self.active_slot if self.active_slot is not None else 0
        a = self.active()
        if a:                                             # read by older versions and by Nearby at start
            self.cfg["my_character"] = dict(a)
            self.cfg["nearby_me"] = [a["name"], a.get("server_id") or 0]
        else:
            self.cfg.pop("my_character", None)
            self.cfg.pop("nearby_me", None)

    def active(self) -> dict | None:
        return self.slots[self.active_slot] if self.active_slot is not None else None

    def used(self) -> list[tuple[int, dict]]:
        return [(i, d) for i, d in enumerate(self.slots) if d]

    def set(self, slot: int, char: dict) -> None:
        """Put a character in a slot (replacing whoever was there). It becomes active when nothing was, or when it
        replaced the active one; the same character already in another slot moves here."""
        if not 0 <= slot < SLOTS:
            raise IndexError(slot)
        entry = {k: char.get(k) for k in KEEP}
        key = (entry.get("server_id"), entry.get("char_id"))
        for i, d in enumerate(self.slots):
            if d and i != slot and (d.get("server_id"), d.get("char_id")) == key:
                self.slots[i] = None
                if self.active_slot == i:
                    self.active_slot = slot
        self.slots[slot] = entry
        if self.active_slot is None:
            self.active_slot = slot
        self._save()

    def activate(self, slot: int) -> None:
        if 0 <= slot < SLOTS and self.slots[slot]:
            self.active_slot = slot
            self._save()

    def delete(self, slot: int) -> None:
        if not 0 <= slot < SLOTS:
            return
        self.slots[slot] = None
        if self.active_slot == slot:
            self.active_slot = self._first()
        self._save()
