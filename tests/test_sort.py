"""Card sorting (Search / Favorites / Nearby / Recent)."""
import unittest

try:
    from shugotracker.sorting import sort_chars
except ImportError as e:  # no tkinter on this machine
    sort_chars = None
    WHY = str(e)
from shugotracker.aion2api import Character


def ch(name, cp=None, level=45):
    c = Character(char_id=name, name=name, race=1, pc_id=10, level=level, server_id=1101, server_name="S",
                  region="nae")
    c.combat_power = cp
    return c


class SortTests(unittest.TestCase):
    def test_latest_newest_first_and_grouped(self):
        a, b, c = ch("Ann"), ch("Bob"), ch("Cid")
        when = {"Ann": 10, "Bob": 30, "Cid": 20}
        self.assertEqual([x.name for x in sort_chars([a, b, c], "latest", None, when)], ["Bob", "Cid", "Ann"])
        sides = {"Ann": "enemy", "Bob": "ally", "Cid": "enemy"}
        self.assertEqual([x.name for x in sort_chars([a, b, c], "latest", sides, when)], ["Cid", "Ann", "Bob"])

    def test_latest_without_times_keeps_order(self):
        a, b = ch("Bob"), ch("Ann")
        self.assertEqual([x.name for x in sort_chars([a, b], "latest", None, {})], ["Bob", "Ann"])

    def test_columns_and_reverse(self):
        a, b, c = ch("Ann", 5, level=40), ch("bob", None, level=45), ch("Cid", 9, level=42)
        self.assertEqual([x.name for x in sort_chars([c, b, a], "name")], ["Ann", "bob", "Cid"])
        self.assertEqual([x.name for x in sort_chars([c, b, a], "name", reverse=True)], ["Cid", "bob", "Ann"])
        self.assertEqual([x.name for x in sort_chars([a, b, c], "level")], ["bob", "Cid", "Ann"])
        # reversed numbers: smallest first, unknown still last
        self.assertEqual([x.name for x in sort_chars([a, b, c], "cp", reverse=True)], ["Ann", "Cid", "bob"])
        sides = {"Ann": "ally", "bob": "enemy", "Cid": "ally"}
        self.assertEqual([x.name for x in sort_chars([a, b, c], "cp", sides)], ["bob", "Cid", "Ann"])

    def test_numbers_unknown_last(self):
        a, b, c = ch("Ann", 5), ch("Bob", None), ch("Cid", 9)
        self.assertEqual([x.name for x in sort_chars([a, b, c], "cp")], ["Cid", "Ann", "Bob"])
