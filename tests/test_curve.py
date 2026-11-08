import unittest

from sc5.curve import decide, max_chip_temp, _clamp

CFG = {"base": 75, "trip": 80, "hyst": 4, "hot": 100}


class CurveDecision(unittest.TestCase):
    def test_bumps_to_hot_at_trip(self):
        self.assertEqual(decide(80, 75, CFG), 100)
        self.assertEqual(decide(85, 75, CFG), 100)

    def test_back_to_base_below_release(self):
        self.assertEqual(decide(76, 100, CFG), 75)   # 80-4=76 -> release
        self.assertEqual(decide(60, 100, CFG), 75)

    def test_hysteresis_band_holds(self):
        # between 77 and 79 it holds whatever is applied
        self.assertEqual(decide(78, 100, CFG), 100)
        self.assertEqual(decide(78, 75, CFG), 75)

    def test_no_temp_keeps_applied(self):
        self.assertEqual(decide(None, 100, CFG), 100)
        self.assertEqual(decide(None, None, CFG), 75)

    def test_max_chip_temp(self):
        snap = {"boards": [{"temp_chip_c": 70}, {"temp_chip_c": 83}, {"temp_chip_c": None}]}
        self.assertEqual(max_chip_temp(snap), 83)
        self.assertIsNone(max_chip_temp({"boards": []}))

    def test_clamp_keeps_safe_bounds(self):
        c = _clamp({"base": 10, "hot": 5, "trip": 200, "hyst": 99, "enabled": 1})
        self.assertEqual(c["base"], 40)          # floor
        self.assertGreaterEqual(c["hot"], c["base"])
        self.assertLessEqual(c["trip"], 95)
        self.assertTrue(c["enabled"] is True)


if __name__ == "__main__":
    unittest.main()
