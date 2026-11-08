"""Rolling hashrate history for the dashboard graph.

Keeps a bounded series of ``[epoch_s, ths_20s, ths_avg, chip_temp_c]`` samples,
persisted to a small JSONL file so the graph survives a service restart. Pure
data: the dashboard samples it in the background and serves it to the page.
"""

import json
import os
import threading
import time
from collections import deque

HISTORY = os.path.expanduser("~/.config/sc5-flasher/history.jsonl")


def sample_from_snapshot(snap, now=None):
    """A compact ``[t, ths_20s, ths_avg, max_chip_temp]`` row from a snapshot.

    Returns None when there is no hashrate to record (e.g. the miner is
    unreachable), so a gap in the data is never stored as a fake zero.
    """
    su = (snap or {}).get("summary") or {}
    ths = su.get("ths_20s")
    if ths is None:
        return None
    avg = su.get("ths_avg")
    temps = [b.get("temp_chip_c") for b in (snap or {}).get("boards", [])]
    temps = [t for t in temps if t is not None]
    temp = max(temps) if temps else None
    t = int(now if now is not None else time.time())
    return [t, round(ths, 3),
            round(avg, 3) if avg is not None else None,
            round(temp, 1) if temp is not None else None]


class History:
    """Bounded, persisted series of samples. Thread-safe."""

    def __init__(self, path=HISTORY, maxlen=4320, min_gap=15):   # 24 h at 20 s
        self.path = path
        self.maxlen = maxlen
        self.min_gap = min_gap          # min seconds between stored samples
        # The in-memory ring is hard-capped at maxlen. The file is append-only
        # between rewrites; rewriting every maxlen//4 appends keeps it bounded to
        # ~1.25*maxlen lines (a few hundred KB at the default), so it can never
        # grow without limit.
        self._flush_every = max(1, maxlen // 4)
        self.buf = deque(maxlen=maxlen)
        self.lock = threading.Lock()
        self._appends = 0
        self._load()

    def _load(self):
        try:
            with open(self.path) as fh:
                rows = [json.loads(ln) for ln in fh if ln.strip()]
            for r in rows[-self.maxlen:]:
                self.buf.append(r)
        except (OSError, ValueError):
            pass

    def add(self, sample):
        """Append a sample unless it comes too soon after the last one."""
        if not sample:
            return False
        with self.lock:
            if self.buf and sample[0] - self.buf[-1][0] < self.min_gap:
                return False
            self.buf.append(sample)
            self._persist(sample)
            return True

    def _persist(self, sample):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a") as fh:
                fh.write(json.dumps(sample) + "\n")
            self._appends += 1
            if self._appends >= self._flush_every:   # keep the file bounded
                self._rewrite()
        except OSError:
            pass

    def _rewrite(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w") as fh:
                for r in self.buf:
                    fh.write(json.dumps(r) + "\n")
            os.replace(tmp, self.path)
            self._appends = 0
        except OSError:
            pass

    def samples(self):
        with self.lock:
            return list(self.buf)
