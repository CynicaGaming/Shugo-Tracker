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
        self.assertEqual(body["e"], {"search": 2, "profile": 1})
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
        self.assertEqual(cfg["usage_pending"], {"favorite": 1})
        u2, _cfg, sent2 = make(cfg)
        u2.send()
        self.assertEqual(sent2[0]["e"], {"favorite": 1})
        self.assertNotIn("usage_pending", cfg)

    def test_dev_builds_never_send(self):
        sent = []
        u = us.Usage({}, lambda: None, dict, post=lambda d: sent.append(d) or True, enabled_build=False)
        u.count("search")
        u.send()
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
