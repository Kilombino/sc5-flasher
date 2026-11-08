import os
import tempfile
import unittest

from sc5.history import History, sample_from_snapshot

SNAP = {
    "summary": {"ths_20s": 13.84, "ths_avg": 14.1},
    "boards": [{"temp_chip_c": 70}, {"temp_chip_c": 83}, {"temp_chip_c": None}],
}


class SampleFromSnapshot(unittest.TestCase):
    def test_extracts_row(self):
        row = sample_from_snapshot(SNAP, now=1000)
        self.assertEqual(row, [1000, 13.84, 14.1, 83.0])  # temp = max chip

    def test_none_when_no_hashrate(self):
        self.assertIsNone(sample_from_snapshot({"summary": {}}, now=1))
        self.assertIsNone(sample_from_snapshot({}, now=1))

    def test_tolerates_missing_avg_and_temps(self):
        row = sample_from_snapshot({"summary": {"ths_20s": 5}, "boards": []}, now=2)
        self.assertEqual(row, [2, 5, None, None])


class HistoryBuffer(unittest.TestCase):
    def _hist(self, **kw):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return History(path=path, **kw), path

    def test_add_and_samples(self):
        h, _ = self._hist(min_gap=0)
        self.assertTrue(h.add([1, 10, 10, 70]))
        self.assertTrue(h.add([2, 11, 10, 71]))
        self.assertEqual(len(h.samples()), 2)

    def test_ignores_none_and_empty(self):
        h, _ = self._hist()
        self.assertFalse(h.add(None))
        self.assertFalse(h.add([]))
        self.assertEqual(h.samples(), [])

    def test_min_gap_drops_too_soon(self):
        h, _ = self._hist(min_gap=15)
        self.assertTrue(h.add([100, 10, 10, 70]))
        self.assertFalse(h.add([110, 11, 10, 70]))   # only 10s later
        self.assertTrue(h.add([120, 12, 10, 70]))    # 20s later
        self.assertEqual([r[0] for r in h.samples()], [100, 120])

    def test_maxlen_bounds(self):
        h, _ = self._hist(maxlen=3, min_gap=0)
        for i in range(6):
            h.add([i, i, i, 70])
        self.assertEqual([r[0] for r in h.samples()], [3, 4, 5])

    def test_persists_and_reloads(self):
        h, path = self._hist(min_gap=0)
        h.add([1, 10, 10, 70])
        h.add([2, 11, 10, 71])
        h2 = History(path=path, min_gap=0)
        self.assertEqual(h2.samples(), [[1, 10, 10, 70], [2, 11, 10, 71]])

    def test_rewrite_keeps_file_bounded(self):
        h, path = self._hist(maxlen=3, min_gap=0)
        for i in range(10):
            h.add([i, i, i, 70])
        with open(path) as fh:
            lines = [ln for ln in fh if ln.strip()]
        self.assertLessEqual(len(lines), 6)          # capped, not 10
        self.assertEqual([r[0] for r in h.samples()], [7, 8, 9])


if __name__ == "__main__":
    unittest.main()
