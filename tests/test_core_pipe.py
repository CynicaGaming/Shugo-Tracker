"""The pipe between Electron and the core: UTF-8 in, ASCII-safe JSON out, whatever Windows' code page is."""
import json
import os
import subprocess
import sys
import tempfile
import unittest


class PipeTests(unittest.TestCase):
    def test_non_latin_names_survive_a_cp1252_console(self):
        # Nov 2026: a player named with a Chinese character made every Nearby message fail ("'charmap' codec
        # can't encode character"), freezing the list.
        name = "乙彡강해린"
        lines = [{"id": 1, "method": "config.set", "params": {"key": "probe", "value": name}},
                 {"id": 2, "method": "init", "params": {}}, {"method": "quit"}]
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
            out = subprocess.run([sys.executable, "-m", "shugotracker.core", "--root", root, "--demo"],
                                 input="".join(json.dumps(m, ensure_ascii=False) + "\n" for m in lines).encode("utf-8"),
                                 capture_output=True, env=env, timeout=60,
                                 cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        raw = out.stdout
        self.assertTrue(all(b < 128 for b in raw), "the pipe carries plain ASCII")
        msgs = [json.loads(ln) for ln in raw.decode("ascii").splitlines() if ln.strip()]
        init = next(m for m in msgs if m.get("id") == 2)
        self.assertEqual(init["result"]["config"]["probe"], name)


if __name__ == "__main__":
    unittest.main()
