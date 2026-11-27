"""Anonymous usage statistics: what is sent, when nothing is, and what survives a restart."""
import json
import unittest

from shugotracker import usage as us


def make(cfg=None, ok=True):
    sent = []
    cfg = {} if cfg is None else cfg

    def post(data):
        sent.append(json.loads(data))
        return ok
    u = us.Usage(cfg, lambda: None, lambda: {"nearby": True, "favorites": 2, "my_chars": 1}, post=post,
                 platform_name="windows", os_name="Windows 11", lang="en-US", enabled_build=True)
    return u, cfg, sent


class UsageTests(unittest.TestCase):
    def test_sends_counts_and_nothing_personal(self):
        u, cfg, sent = make()
        u.count("search"); u.count("search"); u.count("profile"); u.count("bogus")
        self.assertTrue(u.send())
        body = sent[0]
        self.assertEqual(set(body), {"id", "v", "p", "os", "l", "e", "s"})
        self.assertEqual(body["e"], {"session": 1, "search": 2, "profile": 1})
        self.assertEqual((body["p"], body["os"]), ("windows", "Windows 11"))
        self.assertRegex(body["id"], r"^[0-9a-f-]{36}$")
        self.assertEqual(cfg["usage_id"], body["id"])                      # the same id every time
        u.send()
        self.assertEqual(sent[1]["e"], {})                                   # counted once
        self.assertEqual(sent[1]["id"], body["id"])

    def test_off_sends_nothing_and_forgets(self):
        u, cfg, sent = make({"usage_stats": False})
        u.count("search")
        u.send()
        self.assertEqual(sent, [])
        u, cfg, sent = make()
        u.count("search")
        cfg["usage_stats"] = False
        u.changed()
        cfg["usage_stats"] = True
        u.send()
        self.assertEqual(sent[0]["e"], {})

    def test_failed_send_keeps_counts_and_quitting_keeps_them_for_next_time(self):
        u, cfg, sent = make(ok=False)
        u.count("favorite")
        self.assertFalse(u.send())
        u.stop()
        self.assertEqual(cfg["usage_pending"], {"session": 1, "favorite": 1})
        u2, _cfg, sent2 = make(cfg)
        u2.send()
        self.assertEqual(sent2[0]["e"], {"session": 2, "favorite": 1})
        self.assertNotIn("usage_pending", cfg)

    def test_timings_and_minutes_open(self):
        u, cfg, sent = make()
        u.time("search_ms", 850); u.time("search_ms", 150); u.time("bogus_ms", 5); u.time("profile_ms", 10 ** 9)
        u._clock -= 125                                                   # open 2 minutes (and change)
        u.extra = {"screen": "2560x1440"}
        u.send()
        e = sent[0]["e"]
        self.assertEqual((e["search_ms"], e["search_n"], e["minutes"]), (1000, 2, 2))
        self.assertNotIn("profile_ms", e)
        self.assertEqual(sent[0]["s"]["screen"], "2560x1440")
        u.send()
        self.assertNotIn("minutes", sent[1]["e"])                         # counted once

    def test_dev_builds_never_send(self):
        sent = []
        u = us.Usage({}, lambda: None, dict, post=lambda d: sent.append(d) or True, enabled_build=False)
        u.count("search")
        u.send()
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
