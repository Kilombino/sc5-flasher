import unittest
from unittest import mock

from sc5 import control
from sc5.control import Miner, ControlError, FORBIDDEN, MODE_LEVELS


class ControlGuards(unittest.TestCase):
    def test_unknown_action_rejected(self):
        m = Miner("127.0.0.1", password="x")
        for bad in ("flash", "facrst", "upload", "", None, "setting"):
            with self.assertRaises(ControlError):
                m.do(bad)

    def test_forbidden_paths_never_requested(self):
        m = Miner("127.0.0.1", password="x")
        for path in FORBIDDEN:
            with self.assertRaises(ControlError):
                m._request(path, method="PUT", body={}, token="t")

    def test_mode_is_read_modify_write_to_setting_only(self):
        calls = []

        def fake_request(path, method="GET", body=None, token=None):
            calls.append((method, path, body))
            if path.startswith("/user/login"):
                return {"JWT Token": "tok"}
            if path == "/mcb/setting" and method == "GET":
                return {"select": 0, "manual": False, "ledcontrol": False, "tempcontrol": True,
                        "manualPowerplan": "700 MHz", "powerplans": [{"info": "700 MHz", "level": 0}, {"info": "513 MHz", "level": 2}, {"info": "0 MHz", "level": 3}]}
            return None

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            m.do("mode", "idle")

        writes = [c for c in calls if c[0] == "PUT"]
        self.assertEqual(len(writes), 1)
        method, path, body = writes[0]
        self.assertEqual(path, "/mcb/setting")           # only /mcb/setting is written
        self.assertEqual(body["select"], 2)               # INDEX of the level-3 plan, not 3
        self.assertIs(body["manual"], False)              # factory preset, not custom tuning
        # nothing in the whole exchange ever touches firmware or factory reset
        self.assertFalse(any(p in ("/mcb/uploadimage", "/mcb/facrst") for _, p, _ in calls))

    def test_bad_mode_arg_rejected_before_any_write(self):
        calls = []

        def fake_request(path, method="GET", body=None, token=None):
            calls.append((method, path))
            if path.startswith("/user/login"):
                return {"JWT Token": "tok"}
            if path == "/mcb/setting":
                return {"select": 0}
            return None

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            with self.assertRaises(ControlError):
                m.do("mode", "turbo")
        self.assertFalse(any(meth == "PUT" for meth, _ in calls))

    def test_fan_max_changes_only_fan_digits(self):
        captured = {}

        def fake_request(path, method="GET", body=None, token=None):
            if path.startswith("/user/login"):
                return {"JWT Token": "tok"}
            if path == "/mcb/setting" and method == "GET":
                return {"select": 0, "manual": False,
                        "manualPowerplan": "700 MHz 11750 V 30 RPM 30 RPM PV 11900",
                        "ledcontrol": False, "tempcontrol": True, "powerplans": []}
            if path == "/mcb/setting" and method == "PUT":
                captured["body"] = body
            return None

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            m.do("fan", "max")
        plan = captured["body"]["manualPowerplan"]
        self.assertEqual(plan, "700 MHz 11750 V 100 RPM 100 RPM PV 11900")  # MHz/V untouched
        self.assertIn("700 MHz", plan)
        self.assertIn("11750 V", plan)
        self.assertTrue(captured["body"]["manual"])

    def test_fan_auto_restores_preset(self):
        captured = {}

        def fake_request(path, method="GET", body=None, token=None):
            if path.startswith("/user/login"):
                return {"JWT Token": "tok"}
            if path == "/mcb/setting" and method == "GET":
                return {"select": 0, "manual": True,
                        "manualPowerplan": "700 MHz 11750 V 100 RPM 100 RPM PV 11900", "powerplans": []}
            if path == "/mcb/setting" and method == "PUT":
                captured["body"] = body
            return None

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            m.do("fan", "auto")
        self.assertIs(captured["body"]["manual"], False)
        # "auto" must re-enable the firmware thermal ramp (safety backstop)
        self.assertIs(captured["body"]["tempcontrol"], True)

    def test_mode_enables_tempcontrol_backstop(self):
        captured = {}

        def fake_request(path, method="GET", body=None, token=None):
            if path.startswith("/user/login"):
                return {"JWT Token": "tok"}
            if path == "/mcb/setting" and method == "GET":
                return {"select": 0, "manual": True, "tempcontrol": False,
                        "manualPowerplan": "700 MHz 11750 V 30 RPM 30 RPM PV 11900", "powerplans": [{"info": "700 MHz", "level": 0}, {"info": "513 MHz", "level": 2}, {"info": "0 MHz", "level": 3}]}
            if path == "/mcb/setting" and method == "PUT":
                captured["body"] = body
            return None

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            m.do("mode", "hash")
        self.assertIs(captured["body"]["tempcontrol"], True)   # never a bare preset without ramp

    def test_fan_percent_step(self):
        captured = {}

        def fake_request(path, method="GET", body=None, token=None):
            if path.startswith("/user/login"):
                return {"JWT Token": "tok"}
            if path == "/mcb/setting" and method == "GET":
                return {"manual": False, "manualPowerplan": "700 MHz 11750 V 30 RPM 30 RPM PV 11900", "powerplans": []}
            if path == "/mcb/setting" and method == "PUT":
                captured["body"] = body
            return None

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            m.do("fan", 75)
        self.assertEqual(captured["body"]["manualPowerplan"], "700 MHz 11750 V 75 RPM 75 RPM PV 11900")

    def test_fan_bad_arg_rejected(self):
        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_login", return_value="tok"), \
             mock.patch.object(m, "_request", return_value={"manualPowerplan": "700 MHz 11750 V 30 RPM 30 RPM PV 11900"}):
            for bad in ("turbo", 30, 20, 0, 999):   # 30/20/0 would starve cooling
                with self.assertRaises(ControlError):
                    m.do("fan", bad)

    def test_reboot_puts_restart(self):
        calls = []

        def fake_request(path, method="GET", body=None, token=None):
            calls.append((method, path))
            if path.startswith("/user/login"):
                return {"JWT Token": "tok"}
            return None

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            out = m.do("reboot")
        self.assertTrue(out["ok"])
        self.assertIn(("PUT", "/mcb/restart"), calls)


def _pools():
    return [
        {"url": "stratum+tcp://a.example:1", "user": "wa", "pass": "pa", "legal": True,
         "active": True, "dragid": 0, "pool-priority": 0},
        {"url": "stratum+tcp://b.example:2", "user": "wb", "pass": "pb", "legal": True,
         "active": False, "dragid": 1, "pool-priority": 1},
        {"url": "stratum+tcp://c.example:3", "user": "wc", "pass": "pc", "legal": True,
         "active": False, "dragid": 2, "pool-priority": 2},
    ]


class PoolOrder(unittest.TestCase):
    def _run(self, arg, pools=None):
        calls = []
        src = _pools() if pools is None else pools

        def fake_request(path, method="GET", body=None, token=None):
            calls.append((method, path, body))
            if path.startswith("/user/login"):
                return {"JWT Token": "tok"}
            if path == "/mcb/pools" and method == "GET":
                return [dict(p) for p in src]
            return None

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            out = m.do("pool", arg)
        return out, [c for c in calls if c[0] == "PUT"]

    def test_move_to_top_reorders_and_renumbers(self):
        out, writes = self._run({"url": "stratum+tcp://c.example:3", "move": "top"})
        self.assertTrue(out["ok"])
        self.assertEqual([w[1] for w in writes], ["/mcb/pools", "/mcb/restart"])
        _, path, body = writes[0]
        self.assertEqual([p["url"][14] for p in body], ["c", "a", "b"])
        self.assertEqual([p["pool-priority"] for p in body], [0, 1, 2])

    def test_everything_but_priority_is_sent_back_unchanged(self):
        _, writes = self._run({"url": "stratum+tcp://b.example:2", "move": "down"})
        body = writes[0][2]
        original = {p["url"]: p for p in _pools()}
        for p in body:
            o = dict(original[p["url"]])
            o.pop("pool-priority")
            q = dict(p)
            q.pop("pool-priority")
            self.assertEqual(q, o)   # user, pass, dragid, flags byte-identical
        self.assertEqual(len(body), 3)  # nothing added or removed

    def test_up_and_bottom(self):
        _, w = self._run({"url": "stratum+tcp://b.example:2", "move": "up"})
        self.assertEqual([p["url"][14] for p in w[0][2]], ["b", "a", "c"])
        _, w = self._run({"url": "stratum+tcp://a.example:1", "move": "bottom"})
        self.assertEqual([p["url"][14] for p in w[0][2]], ["b", "c", "a"])

    def test_order_follows_priority_not_list_position(self):
        shuffled = list(reversed(_pools()))
        _, w = self._run({"url": "stratum+tcp://b.example:2", "move": "up"}, pools=shuffled)
        self.assertEqual([p["url"][14] for p in w[0][2]], ["b", "a", "c"])

    def test_no_write_when_already_there(self):
        out, writes = self._run({"url": "stratum+tcp://a.example:1", "move": "top"})
        self.assertTrue(out["ok"])
        self.assertEqual(writes, [])

    def test_bad_args_never_write(self):
        for arg in (None, "top", {"url": "stratum+tcp://a.example:1", "move": "delete"},
                    {"url": "stratum+tcp://nope:9", "move": "top"}, {"move": "top"}):
            with self.assertRaises(ControlError):
                self._run(arg)

    def test_duplicate_or_weird_lists_refused(self):
        dup = _pools() + [dict(_pools()[0], **{"pool-priority": 3})]
        with self.assertRaises(ControlError):
            self._run({"url": "stratum+tcp://a.example:1", "move": "down"}, pools=dup)
        with self.assertRaises(ControlError):
            self._run({"url": "x", "move": "top"}, pools=[])

class SelectIsIndexTests(unittest.TestCase):
    """/mcb/setting "select" is an index into powerplans (levels [0, 2, 3] on the SC5)."""
    CFG = {"powerplans": [{"level": 0}, {"level": 2}, {"level": 3}]}

    def test_plan_index(self):
        from sc5.control import plan_index
        self.assertEqual([plan_index(self.CFG, l) for l in (0, 2, 3)], [0, 1, 2])
        self.assertIsNone(plan_index(self.CFG, 1))

    def test_selected_level(self):
        from sc5.control import selected_level
        self.assertEqual(selected_level({**self.CFG, "select": 2}), 3)   # idle, not eco
        self.assertEqual(selected_level({**self.CFG, "select": 1}), 2)
        self.assertIsNone(selected_level({**self.CFG, "select": 3}))

    def test_eco_writes_index_1(self):
        captured = {}

        def fake_request(path, method="GET", body=None, token=None):
            if path.startswith("/user/login"):
                return {"JWT Token": "tok"}
            if path == "/mcb/setting" and method == "GET":
                return {"select": 0, "manual": False, "tempcontrol": True, **self.CFG}
            if method == "PUT":
                captured["body"] = body
            return None

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            m.do("mode", "eco")
        self.assertEqual(captured["body"]["select"], 1)

    def test_fixed_fan_refused_while_idle(self):
        writes = []

        def fake_request(path, method="GET", body=None, token=None):
            if path.startswith("/user/login"):
                return {"JWT Token": "tok"}
            if method == "PUT":
                writes.append(path)
            return {"select": 2, "manual": False, "manualPowerplan": "700 MHz 11750 V 65 RPM 65 RPM",
                    **self.CFG}

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            with self.assertRaises(ControlError):
                m.do("fan", 75)
        self.assertEqual(writes, [])

    def test_missing_plan_refuses_to_write(self):
        writes = []

        def fake_request(path, method="GET", body=None, token=None):
            if path.startswith("/user/login"):
                return {"JWT Token": "tok"}
            if method == "PUT":
                writes.append(path)
            return {"select": 0, "powerplans": [{"level": 0}]}

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            with self.assertRaises(ControlError):
                m.do("mode", "idle")
        self.assertEqual(writes, [])


if __name__ == "__main__":
    unittest.main()
