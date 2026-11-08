import json
import pathlib
import unittest
from unittest import mock

from sc5 import api, collect
from sc5.model import build_snapshot

FX = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    text = (FX / name).read_text()
    return api.parse_cgminer(text) if name.startswith("cg_") else json.loads(text)


class ReadOnlyGuards(unittest.TestCase):
    def test_write_commands_rejected(self):
        for cmd in ("restart", "quit", "addpool", "switchpool", "ascset", "pgaset", "enablepool"):
            with self.assertRaises(api.ReadOnlyViolation):
                api.cgminer("127.0.0.1", cmd)

    def test_write_paths_rejected(self):
        for path in ("/mcb/restart", "/mcb/facrst", "/mcb/uploadimage", "/mcb/protect",
                     "/mcb/defend", "/mcb/newpool", "/user/login", "/mcb/cmossetting"):
            with self.assertRaises(api.ReadOnlyViolation):
                api.web_get("127.0.0.1", path)

    def test_only_get_is_used(self):
        seen = []

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"{}"

        def fake_urlopen(req, timeout):
            seen.append(req.get_method())
            return Resp()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            for path in api.READ_PATHS:
                api.web_get("127.0.0.1", path)
        self.assertEqual(set(seen), {"GET"})


class Parsing(unittest.TestCase):
    def test_broken_stats_json_is_fixed(self):
        stats = load("cg_stats.json")
        self.assertIn("STATS", stats)

    def test_snapshot_from_fixtures(self):
        raw = {
            "version": load("cg_version.json"), "summary": load("cg_summary.json"),
            "devs": load("cg_devs.json"), "pools": load("cg_pools.json"),
            "status": load("web_status.json"), "setting": load("web_setting.json"),
            "algosetting": load("web_algosetting.json"), "pools_web": load("web_pools.json"),
        }
        s = build_snapshot(raw)
        self.assertEqual(s["device"]["board"], "MCB_V3_3")
        self.assertEqual(s["device"]["firmware"], "2.2.0")
        self.assertEqual(len(s["boards"]), 4)
        self.assertGreater(s["summary"]["ths_avg"], 10)
        self.assertEqual(s["algorithm"], "blake2b(SC)")
        # pool passwords from the web API never reach the snapshot
        self.assertNotIn('"pass"', json.dumps(s))

    def test_collect_survives_dead_sources(self):
        with mock.patch.object(api, "cgminer", side_effect=OSError("down")), \
             mock.patch.object(api, "web_get", side_effect=OSError("down")):
            s = collect.collect("127.0.0.1")
        self.assertEqual(s["boards"], [])
        self.assertTrue(s["errors"])


if __name__ == "__main__":
    unittest.main()
