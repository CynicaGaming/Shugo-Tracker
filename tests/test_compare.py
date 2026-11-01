import unittest

from shugotracker.profile import ItemDetail, fmt_delta, stat_deltas, stat_number


class CompareTest(unittest.TestCase):
    def test_stat_number(self):
        self.assertEqual(stat_number("1,234"), 1234)
        self.assertEqual(stat_number("12.5%"), 12.5)
        self.assertEqual(stat_number("+24"), 24)
        self.assertIsNone(stat_number(""))

    def test_deltas(self):
        theirs = ItemDetail(item_level=320, main_stats=[("Attack", "442", "146"), ("Crit", "5%", "")],
                            exceed_stats=[("Attack", "24")])
        mine = ItemDetail(item_level=300, main_stats=[("Attack", "400", "100"), ("Crit", "5%", "")])
        d = stat_deltas(mine, theirs)
        self.assertEqual(d["Attack"], (112, False))      # 612 vs 500, exceed counted in
        self.assertEqual(d["Item Level"], (20, False))
        self.assertNotIn("Crit", d)                      # equal: no arrow

    def test_missing_stat_counts_as_zero(self):
        theirs = ItemDetail(main_stats=[("Block", "200", "")])
        self.assertEqual(stat_deltas(ItemDetail(), theirs), {"Block": (200, False)})
        self.assertEqual(stat_deltas(None, theirs), {"Block": (200, False)})

    def test_fmt(self):
        self.assertEqual(fmt_delta(12), "▲12")
        self.assertEqual(fmt_delta(-3.5, True), "▼3.5%")
        self.assertEqual(fmt_delta(1500), "▲1,500")


if __name__ == "__main__":
    unittest.main()
