"""Tests for the search/details client, using response shapes captured from the live endpoints."""
import threading
import time
import unittest

from shugotracker import aion2api as a

SEARCH_JSON = {
    "list": [
        {"characterId": "t-k7XTs1Enuf9yA5YNUAgbj7FzhhqKMbeuhHNemWLaM%3D", "name": "<strong>Luna</strong>", "race": 1,
         "pcId": 6, "level": 1, "serverId": 1109, "serverName": "Hithanya",
         "profileImageUrl": "/game_profile_images/aion2global/images?gameServerKey=1109&charKey=312155749172397810",
         "region": "nae"},
        {"characterId": "F0Ubce33Dq_LpNdYg_lVavO_-GjY11B-Q4kqxiWG-ok%3D", "name": "<strong>Luna</strong>", "race": 2,
         "pcId": 36, "level": 45, "serverId": 2101, "serverName": "Israphel",
         "profileImageUrl": "/game_profile_images/aion2global/images?gameServerKey=2101&charKey=591378926069485316",
         "region": "nae"},
        {"characterId": "92X7SfUFq7_lLkb-CUiaD5IjyJT4z1PfVuXt_5NeJnk%3D", "name": "A<strong>luna</strong>", "race": 2,
         "pcId": 32, "level": 45, "serverId": 2108, "serverName": "Beritra", "profileImageUrl": None, "region": "nae"},
    ],
    "pagination": {"page": 1, "size": 3, "total": 3049, "endPage": 1017},
}

INFO_JSON = {
    "profile": {"characterId": "F0Ubce33Dq_LpNdYg_lVavO_-GjY11B-Q4kqxiWG-ok=", "characterLevel": 45,
                "characterName": "Luna", "className": "Chanter", "combatPower": 50566, "pcId": 36, "raceId": 2,
                "serverId": 2101, "serverName": "Israphel", "titleName": "Saint of Altgard",
                "profileImage": "https://profileimg.plaync.com/game_profile_images/aion2global/images?x=1"},
    "stat": {"statList": [{"name": "Might", "type": "STR", "value": 34},
                          {"name": "아이템레벨", "type": "ItemLevel", "value": 972}]},
}


class FakeResp:
    def __init__(self, data, status=200, headers=None):
        self._data, self.status_code, self.headers = data, status, headers or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.headers = {}
        self.calls = []
        self.lock = threading.Lock()

    def get(self, url, params=None, timeout=None):
        with self.lock:
            self.calls.append((url, dict(params or {})))
        return self.handler(url, params or {})


def default_handler(url, params):
    if url == a.SEARCH_URL:
        return FakeResp(SEARCH_JSON if params["region"] == "nae" else {"list": [], "pagination": {"total": 0}})
    if url == a.INFO_URL:
        return FakeResp(INFO_JSON)
    raise AssertionError(url)


class ParseTests(unittest.TestCase):
    def test_search(self):
        chars, total = a.parse_search(SEARCH_JSON)
        self.assertEqual(total, 3049)
        luna = chars[1]
        self.assertEqual(luna.name, "Luna")
        self.assertEqual(luna.char_id, "F0Ubce33Dq_LpNdYg_lVavO_-GjY11B-Q4kqxiWG-ok=")
        self.assertEqual((luna.class_name, luna.faction, luna.level), ("Chanter", "Asmodian", 45))
        self.assertTrue(luna.portrait.startswith("https://profileimg.plaync.com/"))
        self.assertEqual(luna.shugo_url, "https://shugo.gg/character/global/nae-israphel/Luna")
        self.assertEqual(chars[0].class_name, "Gladiator")  # pcId 5-8
        self.assertEqual(chars[2].name, "Aluna")
        self.assertIsNone(chars[2].portrait)

    def test_info(self):
        d = a.parse_info(INFO_JSON)
        self.assertEqual((d["combat_power"], d["gear_score"], d["title"]), (50566, 972, "Saint of Altgard"))

    def test_rank(self):
        chars, _ = a.parse_search(SEARCH_JSON)
        ranked = a.rank(chars, "luna")
        self.assertEqual([c.name for c in ranked], ["Luna", "Luna", "Aluna"])
        self.assertEqual(ranked[0].level, 45)               # exact matches, highest level first


class ApiTests(unittest.TestCase):
    def make(self, handler=default_handler, **kw):
        sess = FakeSession(handler)
        api = a.Api(session=sess, rate=1000, **kw)
        self.addCleanup(api.close)
        return api, sess

    def search_all(self, api, name):
        got, done = {}, threading.Event()

        def on_done(region, chars, total, err):
            got[region] = (chars, total, err)
            if len(got) == len(a.SUB_REGIONS):
                done.set()
        api.search(name, a.SUB_REGIONS, on_done=on_done)
        self.assertTrue(done.wait(5))
        return got

    def test_parallel_search_and_lazy_details(self):
        api, sess = self.make()
        got = self.search_all(api, "Luna")
        self.assertEqual(got["nae"][1], 3049)
        self.assertEqual(sorted(p["region"] for u, p in sess.calls if u == a.SEARCH_URL), sorted(a.SUB_REGIONS))
        luna = got["nae"][0][1]
        self.assertEqual(luna.status, "none")
        self.assertFalse(any(u == a.INFO_URL for u, _ in sess.calls))   # nothing fetched until asked

        done = threading.Event()
        api.want(luna, lambda c: done.set())
        api.want(luna, lambda c: None)                                   # duplicate request ignored
        self.assertTrue(done.wait(5))
        self.assertEqual((luna.status, luna.combat_power, luna.gear_score), ("ok", 50566, 972))
        info_calls = [p for u, p in sess.calls if u == a.INFO_URL]
        self.assertEqual(len(info_calls), 1)
        self.assertEqual(info_calls[0]["characterId"], "F0Ubce33Dq_LpNdYg_lVavO_-GjY11B-Q4kqxiWG-ok=")
        self.assertEqual(info_calls[0]["serverId"], 2101)

        # A later search for the same character is answered from cache, with no extra request.
        again = self.search_all(api, "Luna")["nae"][0][1]
        self.assertEqual((again.status, again.combat_power), ("ok", 50566))
        self.assertEqual(len([1 for u, _ in sess.calls if u == a.INFO_URL]), 1)

    def test_new_search_drops_queued_details(self):
        gate = threading.Event()

        def slow(url, params):
            if url == a.INFO_URL:
                gate.wait(5)
            return default_handler(url, params)

        api, sess = self.make(slow, workers=1)
        chars, _ = a.parse_search(SEARCH_JSON)
        for c in chars:
            api.want(c, lambda c: None)
        time.sleep(0.1)          # the single worker is now blocked on the newest request
        api.new_generation()     # user typed a new search
        gate.set()
        time.sleep(0.3)
        self.assertEqual(len([1 for u, _ in sess.calls if u == a.INFO_URL]), 1)
        self.assertEqual(sum(c.status == "none" for c in chars), 2)  # the rest were dropped, not fetched

    def test_rate_limit_backoff(self):
        n = {"i": 0}

        def flaky(url, params):
            n["i"] += 1
            if n["i"] == 1:
                return FakeResp({}, status=429, headers={"Retry-After": "0.1"})
            return default_handler(url, params)

        api, _ = self.make(flaky)
        before = api.limiter.rate
        chars, total = api.search_region("Luna", "nae")
        self.assertEqual(total, 3049)
        self.assertLess(api.limiter.rate, before)

    def test_errors_are_reported(self):
        def broken(url, params):
            return FakeResp({}, status=403)

        api, _ = self.make(broken)
        got = self.search_all(api, "Luna")
        self.assertTrue(all(err for _, _, err in got.values()))


if __name__ == "__main__":
    unittest.main()


class CachingTests(unittest.TestCase):
    def make(self):
        sess = FakeSession(default_handler)
        api = a.Api(session=sess, rate=1000)
        self.addCleanup(api.close)
        return api, sess

    def test_repeat_search_is_served_from_memory(self):
        api, sess = self.make()
        api.search_region("Luna", "nae")
        api.search_region("luna", "nae")                 # same search, different case
        self.assertEqual(len([1 for u, _ in sess.calls if u == a.SEARCH_URL]), 1)
        api.search_region("Luna", "nae", page=2)
        self.assertEqual(len([1 for u, _ in sess.calls if u == a.SEARCH_URL]), 2)

    def test_stale_numbers_show_instantly_then_refresh(self):
        api, sess = self.make()
        chars, _ = a.parse_search(SEARCH_JSON)
        luna = chars[1]
        api._cache[luna.key] = {"combat_power": 111, "gear_score": 222, "legion": None,
                                "ts": time.time() - a.DETAILS_FRESH_S - 60}
        chars, _ = api.search_region("Luna", "nae")      # the search applies the cache
        luna = chars[1]
        self.assertEqual((luna.status, luna.combat_power, luna.stale), ("ok", 111, True))
        done = threading.Event()
        api.want(luna, lambda c: done.set())             # card is on screen: refresh quietly
        self.assertEqual(luna.status, "ok")               # numbers stay visible meanwhile
        self.assertTrue(done.wait(5))
        self.assertEqual((luna.combat_power, luna.stale), (50566, False))

    def test_fresh_numbers_are_not_refetched(self):
        api, sess = self.make()
        chars, _ = a.parse_search(SEARCH_JSON)
        luna = chars[1]
        api._cache[luna.key] = {"combat_power": 111, "gear_score": 222, "legion": None, "ts": time.time()}
        api.want(luna, lambda c: None)
        time.sleep(0.2)
        self.assertEqual(luna.combat_power, 111)
        self.assertFalse(any(u == a.INFO_URL for u, _ in sess.calls))

    def test_very_old_cache_is_ignored(self):
        api, _ = self.make()
        chars, _ = a.parse_search(SEARCH_JSON)
        luna = chars[1]
        api._cache[luna.key] = {"combat_power": 111, "gear_score": 222, "legion": None,
                                "ts": time.time() - a.DETAILS_KEEP_S - 60}
        done = threading.Event()
        api.want(luna, lambda c: done.set())
        self.assertEqual(luna.status, "loading")          # too old to show: skeleton, then real numbers
        self.assertTrue(done.wait(5))
        self.assertEqual(luna.combat_power, 50566)
