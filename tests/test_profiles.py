import unittest

from shugotracker.profiles import SLOTS, MyCharacters


def ch(name, cid, server=1101):
    return {"name": name, "char_id": cid, "server_id": server, "server_name": "Siel", "race": 1}


class SlotsTest(unittest.TestCase):
    def test_empty(self):
        cfg = {}
        m = MyCharacters(cfg)
        self.assertIsNone(m.active())
        self.assertEqual(cfg["my_characters"], [None] * SLOTS)
        self.assertNotIn("nearby_me", cfg)

    def test_old_setting_becomes_character_1(self):
        cfg = {"my_character": ch("Cynica", "a")}
        m = MyCharacters(cfg)
        self.assertEqual((m.active_slot, m.active()["name"]), (0, "Cynica"))
        self.assertEqual(cfg["nearby_me"], ["Cynica", 1101])

    def test_set_keeps_active_unless_none(self):
        cfg = {}
        m = MyCharacters(cfg)
        m.set(2, ch("Alt", "b"))
        self.assertEqual(m.active_slot, 2)              # first one set becomes active
        m.set(0, ch("Main", "a"))
        self.assertEqual(m.active()["name"], "Alt")     # setting another slot doesn't switch
        m.activate(0)
        self.assertEqual((cfg["my_active"], cfg["my_character"]["name"]), (0, "Main"))
        self.assertEqual(MyCharacters(cfg).active()["name"], "Main")   # survives a restart

    def test_replace_active_slot(self):
        m = MyCharacters({})
        m.set(0, ch("Main", "a"))
        m.set(0, ch("Other", "c"))
        self.assertEqual(m.active()["name"], "Other")

    def test_same_character_moves(self):
        m = MyCharacters({})
        m.set(0, ch("Main", "a"))
        m.set(3, ch("Main", "a"))
        self.assertIsNone(m.slots[0])
        self.assertEqual((m.active_slot, len(m.used())), (3, 1))

    def test_delete(self):
        cfg = {}
        m = MyCharacters(cfg)
        m.set(0, ch("Main", "a"))
        m.set(1, ch("Alt", "b"))
        m.delete(0)
        self.assertEqual(m.active()["name"], "Alt")     # falls to the next one set
        m.delete(1)
        self.assertIsNone(m.active())
        self.assertNotIn("my_character", cfg)

    def test_bad_config(self):
        m = MyCharacters({"my_characters": ["x", None, ch("A", "a")] + [None] * 9, "my_active": 9})
        self.assertEqual((len(m.slots), m.active_slot), (SLOTS, 2))


if __name__ == "__main__":
    unittest.main()
