"""Result-table column layout."""
import unittest

from shugotracker.columns import layout_columns


class ColumnTests(unittest.TestCase):
    def test_drops_in_order_and_grows(self):
        keys = lambda w: list(layout_columns(w)["spans"])                        # noqa: E731
        self.assertEqual(keys(900), ["name", "legion", "class", "level", "server", "gs", "cp"])
        self.assertNotIn("server", keys(540))
        self.assertIn("legion", keys(540))
        self.assertEqual(keys(400), ["name", "class", "level", "gs", "cp"])
        wide, narrow = layout_columns(900)["spans"], layout_columns(600)["spans"]
        self.assertGreater(wide["name"][1] - wide["name"][0], narrow["name"][1] - narrow["name"][0])

    def test_no_overlap_and_inside(self):
        for w in range(300, 1400, 37):
            k = layout_columns(w)
            spans = list(k["spans"].values())
            for (a0, a1, _), (b0, b1, _) in zip(spans, spans[1:]):
                self.assertLessEqual(a1, b0)
            self.assertLessEqual(spans[-1][1], k["star"] - 10)


if __name__ == "__main__":
    unittest.main()
