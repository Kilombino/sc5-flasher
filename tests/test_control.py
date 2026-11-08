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
