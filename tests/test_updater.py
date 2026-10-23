import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

from shugotracker import updater as up


class FakeResp:
    def __init__(self, status=200, json_data=None, content=b"", text=""):
        self.status_code = status
        self._json = json_data
        self._content = content
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, n):
        for i in range(0, len(self._content), n):
            yield self._content[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.headers = {}

    def get(self, url, **kw):
        return self.routes[url]


def release(tag, new_exe, sha=None):
    base = "https://github.com/" + up.DEFAULT_REPO + "/releases/download/" + tag
    sha = sha or hashlib.sha256(new_exe).hexdigest()
    return {
        "https://api.github.com/repos/" + up.DEFAULT_REPO + "/releases/latest": FakeResp(json_data={
            "tag_name": tag, "html_url": "x",
            "assets": [{"name": up.EXE_ASSET, "browser_download_url": base + "/exe"},
                       {"name": up.SHA_ASSET, "browser_download_url": base + "/sha"}]}),
        base + "/exe": FakeResp(content=new_exe),
        base + "/sha": FakeResp(text=f"{sha}  ShugoTracker.exe\n"),
    }


class VersionTests(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(up.is_newer("v1.2.0", "1.1.9"))
        self.assertTrue(up.is_newer("v1.10", "1.9.3"))
        self.assertFalse(up.is_newer("v1.2.0", "1.2.0"))
        self.assertFalse(up.is_newer("v1.0.0", "0.0.0-dev"))  # dev builds never auto-update
        self.assertFalse(up.is_newer("nightly", "1.0.0"))


class UpdateFlowTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.exe = os.path.join(self.dir, "ShugoTracker.exe")
        with open(self.exe, "wb") as f:
            f.write(b"OLD")
        self.patches = [mock.patch.object(up, "FROZEN", True), mock.patch.object(sys, "executable", self.exe)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def make(self, routes, version="1.0.0"):
        u = up.Updater()
        u.current = version
        u._session = FakeSession(routes)
        return u

    def test_download_verify_and_swap(self):
        u = self.make(release("v1.1.0", b"NEW-EXE"))
        u.check_and_download()
        self.assertEqual(u.state, "ready")
        self.assertIn("v1.1.0", u.banner())
        with mock.patch.object(up.subprocess, "Popen") as popen:
            self.assertTrue(u.apply(restart=False))
            popen.assert_not_called()
        self.assertEqual(open(self.exe, "rb").read(), b"NEW-EXE")
        self.assertEqual(open(self.exe + ".old", "rb").read(), b"OLD")
        u._cleanup_old()
        self.assertFalse(os.path.exists(self.exe + ".old"))

    def test_bad_checksum_is_discarded(self):
        u = self.make(release("v1.1.0", b"NEW-EXE", sha="0" * 64))
        u.check_and_download()
        self.assertEqual(u.state, "error")
        self.assertFalse(os.path.exists(self.exe + ".new"))
        self.assertFalse(u.apply(restart=False))
        self.assertEqual(open(self.exe, "rb").read(), b"OLD")

    def test_up_to_date(self):
        u = self.make(release("v1.0.0", b"X"))
        u.check_and_download()
        self.assertEqual(u.state, "uptodate")
        self.assertIsNone(u.banner())

    def test_no_release_yet(self):
        u = self.make({"https://api.github.com/repos/" + up.DEFAULT_REPO + "/releases/latest": FakeResp(404)})
        u.check_and_download()
        self.assertEqual(u.state, "uptodate")


if __name__ == "__main__":
    unittest.main()
