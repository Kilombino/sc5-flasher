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
                        "manualPowerplan": "700 MHz", "powerplans": []}
            return None

        m = Miner("127.0.0.1", password="x")
        with mock.patch.object(m, "_request", side_effect=fake_request):
            m.do("mode", "idle")

        writes = [c for c in calls if c[0] == "PUT"]
        self.assertEqual(len(writes), 1)
        method, path, body = writes[0]
        self.assertEqual(path, "/mcb/setting")           # only /mcb/setting is written
        self.assertEqual(body["select"], MODE_LEVELS["idle"])
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
                        "manualPowerplan": "700 MHz 11750 V 30 RPM 30 RPM PV 11900", "powerplans": []}
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


if __name__ == "__main__":
    unittest.main()
