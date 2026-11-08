"""Software fan curve for the SC5 Pro II.

The stock firmware's temperature target lives in a file we can't edit (SSH is
closed). So we run our own curve on top of the one safe lever we have — the fan
floor (fans-only, clock/voltage never touched). The supervisor watches the chip
temperature and, with hysteresis, keeps the fan floor at `base` %, bumping it to
`hot` when the chip reaches `trip` °C and letting it drop back once it cools to
`trip - hyst`.

`decide()` is a pure function so the logic is unit-tested without a miner.
"""

import json
import os
import threading
import time

CONFIG = os.path.expanduser("~/.config/sc5-flasher/curve.json")
DEFAULT = {"enabled": False, "base": 75, "trip": 80, "hyst": 4, "hot": 100}


def load():
    cfg = dict(DEFAULT)
    try:
        with open(CONFIG) as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return cfg


def _clamp(cfg):
    cfg["base"] = max(40, min(100, int(cfg["base"])))
    cfg["hot"] = max(cfg["base"], min(100, int(cfg["hot"])))  # hot >= base
    cfg["trip"] = max(60, min(95, int(cfg["trip"])))
    cfg["hyst"] = max(1, min(15, int(cfg["hyst"])))
    cfg["enabled"] = bool(cfg["enabled"])
    return cfg


def save(cfg):
    merged = dict(DEFAULT)
    merged.update(cfg)
    merged = _clamp(merged)
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(merged, fh)
    os.replace(tmp, CONFIG)
    return merged


def decide(temp_c, applied, cfg):
    """Return the fan floor % to apply, given the chip temp and what we applied
    last time. Hysteresis: go `hot` at/above `trip`, back to `base` at/below
    `trip - hyst`, and hold the current value in between. None temp → no change."""
    base, trip, hyst, hot = cfg["base"], cfg["trip"], cfg["hyst"], cfg["hot"]
    if temp_c is None:
        return applied if applied is not None else base
    if temp_c >= trip:
        return hot
    if temp_c <= trip - hyst:
        return base
    return applied if applied is not None else base


def max_chip_temp(snapshot):
    temps = [b.get("temp_chip_c") for b in snapshot.get("boards", [])]
    temps = [t for t in temps if t is not None]
    return max(temps) if temps else None


class Supervisor:
    """Background thread that enforces the software curve by setting fan floors.

    It only ever calls miner.do("fan", <pct>) — the same allowlisted, fans-only
    action the buttons use. It writes only when the target floor changes, so it
    does not spam the miner.
    """

    def __init__(self, miner, snapshot_fn, cfg=None, interval=10):
        self.miner = miner
        self.snapshot_fn = snapshot_fn
        self.cfg = cfg or load()
        self.interval = interval
        self.applied = None          # last fan % we set
        self.last_temp = None
        self.last_error = None
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def state(self):
        with self._lock:
            return {"cfg": dict(self.cfg), "applied": self.applied,
                    "last_temp": self.last_temp, "last_error": self.last_error,
                    "running": bool(self._thread and self._thread.is_alive())}

    def update(self, cfg):
        with self._lock:
            self.cfg = save({**self.cfg, **cfg})
            self.applied = None  # force re-evaluation on next tick
        if self.cfg.get("enabled"):
            self.start()
        else:
            self.stop()
        return self.state()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(0 if self.applied is None else self.interval):
            if self._stop.is_set():
                break
            try:
                with self._lock:
                    cfg = dict(self.cfg)
                if not cfg.get("enabled"):
                    break
                snap = self.snapshot_fn()
                temp = max_chip_temp(snap)
                target = decide(temp, self.applied, cfg)
                with self._lock:
                    self.last_temp = temp
                if target is not None and target != self.applied:
                    self.miner.do("fan", target)
                    with self._lock:
                        self.applied = target
                        self.last_error = None
            except Exception as exc:  # keep the loop alive; surface the error
                with self._lock:
                    self.last_error = str(exc)
