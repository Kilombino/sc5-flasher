import unittest

from sc5.curve import interp, target_pct, max_chip_temp, _clamp_points, _clamp

CFG = {"points": [[70, 50], [80, 75], [85, 100]], "step": 5}


class CurveInterp(unittest.TestCase):
    def test_flat_below_first_and_above_last(self):
        self.assertEqual(interp(60, CFG["points"]), 50)
        self.assertEqual(interp(90, CFG["points"]), 100)
        self.assertEqual(interp(70, CFG["points"]), 50)
        self.assertEqual(interp(85, CFG["points"]), 100)

    def test_linear_between_points(self):
        self.assertAlmostEqual(interp(75, CFG["points"]), 62.5)   # midway 50->75
        self.assertAlmostEqual(interp(82.5, CFG["points"]), 87.5)  # midway 75->100

    def test_target_rounds_to_step_and_floors(self):
        self.assertEqual(target_pct(60, CFG), 50)
        self.assertEqual(target_pct(75, CFG), 60)   # 62.5 -> nearest 5 (banker's)
        self.assertEqual(target_pct(90, CFG), 100)
        self.assertIsNone(target_pct(None, CFG))

    def test_target_never_below_floor(self):
        cfg = {"points": [[70, 40]], "step": 5}
        self.assertEqual(target_pct(50, cfg), 40)   # FAN_MIN


class CurveClamp(unittest.TestCase):
    def test_points_sorted_and_monotonic(self):
        pts = _clamp_points([[85, 100], [70, 75], [78, 60]])
        self.assertEqual([t for t, _ in pts], sorted(t for t, _ in pts))
        pcts = [p for _, p in pts]
        self.assertEqual(pcts, sorted(pcts))        # fans never drop as temp rises

    def test_values_bounded(self):
        pts = _clamp_points([[10, 10], [200, 999]])
        for t, p in pts:
            self.assertTrue(50 <= t <= 95)
            self.assertTrue(40 <= p <= 100)

    def test_clamp_defaults_and_enabled(self):
        c = _clamp({"enabled": 1, "points": [[70, 50], [85, 100]], "step": 99})
        self.assertIs(c["enabled"], True)
        self.assertLessEqual(c["step"], 10)

    def test_max_chip_temp(self):
        snap = {"boards": [{"temp_chip_c": 70}, {"temp_chip_c": 83}, {"temp_chip_c": None}]}
        self.assertEqual(max_chip_temp(snap), 83)
        self.assertIsNone(max_chip_temp({"boards": []}))


if __name__ == "__main__":
    unittest.main()
