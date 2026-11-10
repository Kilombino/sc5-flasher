import unittest

from sc5.curve import (interp, target_pct, max_chip_temp, _clamp_points, _clamp,
                       current_fan_pct, needs_write)

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

    def test_safe_max_forces_full_fans(self):
        # even a reckless "40% up to 95" curve goes 100% once the chip is hot
        cfg = {"points": [[95, 40]], "step": 5}
        self.assertEqual(target_pct(88, cfg), 100)
        self.assertEqual(target_pct(92, cfg), 100)
        self.assertEqual(target_pct(70, cfg), 40)


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


class CurveReboot(unittest.TestCase):
    def test_current_fan_pct(self):
        self.assertEqual(current_fan_pct({"power": {"fan_pct": 65}}), 65)
        self.assertIsNone(current_fan_pct({"power": {}}))
        self.assertIsNone(current_fan_pct({}))

    def test_reclaims_control_after_reboot(self):
        # miner rebooted back to a 50% preset; our last applied was 65.
        # Even though target (65) == cached applied (65), the REAL fan is 50,
        # so we must re-write 65. Without the fix this case would be missed.
        self.assertTrue(needs_write(target=65, actual=50, applied=65))

    def test_no_write_when_already_at_target(self):
        self.assertFalse(needs_write(target=65, actual=65, applied=50))
        self.assertFalse(needs_write(target=None, actual=50, applied=50))

    def test_falls_back_to_applied_when_fan_unreadable(self):
        self.assertTrue(needs_write(target=65, actual=None, applied=50))
        self.assertFalse(needs_write(target=65, actual=None, applied=65))


if __name__ == "__main__":
    unittest.main()


class DownHysteresisTests(unittest.TestCase):
    CFG = {"points": [[78, 68], [80, 72], [82, 78]], "step": 5, "down_hyst": 2}

    def test_boundary_does_not_saw_tooth(self):
        from sc5.curve import hold_target
        # 81 C -> 75 %; dropping back to 80 C (-> 70 %) must keep 75 %
        self.assertEqual(hold_target(81, self.CFG, 70), 75)
        self.assertEqual(hold_target(80, self.CFG, 75), 75)
        # only 2 C cooler than where 70 % applies does it come down
        self.assertEqual(hold_target(78, self.CFG, 75), 70)

    def test_up_is_immediate_and_none_passthrough(self):
        from sc5.curve import hold_target
        self.assertEqual(hold_target(82, self.CFG, 70), 80)
        self.assertEqual(hold_target(80, self.CFG, None), 70)
        self.assertIsNone(hold_target(None, self.CFG, 70))

    def test_zero_hyst_behaves_like_target(self):
        from sc5.curve import hold_target
        cfg = dict(self.CFG, down_hyst=0)
        self.assertEqual(hold_target(80, cfg, 75), 70)


class TargetModeTests(unittest.TestCase):
    CFG = {"points": [[70, 50], [80, 72], [84, 85], [88, 100]], "step": 1,
           "mode": "target", "target_c": 80, "adjust_s": 60}

    def test_holds_at_target(self):
        from sc5.curve import target_step
        self.assertEqual(target_step(80, self.CFG, 72, 999), (72, False))

    def test_one_percent_moves_rate_limited(self):
        from sc5.curve import target_step
        self.assertEqual(target_step(81, self.CFG, 72, 999), (73, True))
        self.assertEqual(target_step(79, self.CFG, 72, 999), (71, True))
        self.assertEqual(target_step(81, self.CFG, 72, 10), (72, False))

    def test_rescue_and_safety(self):
        from sc5.curve import target_step
        # 3 C over target: jump to the curve floor at once, ignoring the rate limit
        pct, adj = target_step(83, self.CFG, 60, 5)
        self.assertTrue(adj); self.assertGreaterEqual(pct, 81)
        self.assertEqual(target_step(88, self.CFG, 60, 5), (100, True))
        self.assertEqual(target_step(None, self.CFG, 60, 999), (60, False))

    def test_floor_and_start(self):
        from sc5.curve import target_step, FAN_MIN
        self.assertEqual(target_step(70, self.CFG, FAN_MIN, 999), (FAN_MIN, True))
        self.assertEqual(target_step(80, self.CFG, None, None), (72, True))
