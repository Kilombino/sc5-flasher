"""Multi-point software fan curve for the SC5 Pro II.

The stock firmware's temperature target lives in a file we can't edit (SSH is
closed), so the service runs its own curve on the one safe lever we have — the
fan floor (fans-only; clock/voltage never touched).

The curve is a list of [chip_temp_C, fan_%] points. Between points the target
fan % is interpolated linearly; below the first point it holds the first %, above
the last it holds the last. A background supervisor reads the chip temperature,
rounds the target to `step` %, and sets the fan floor when it changes — so the
fans ramp up and down on their own, smoothly, without spamming the miner.

`interp()` / `target_pct()` are pure functions so the logic is unit-tested.
"""

import json
import os
import threading

from .control import FAN_MIN

CONFIG = os.path.expanduser("~/.config/sc5-flasher/curve.json")
DEFAULT = {
    "enabled": False,
    # progressive: 50% up to 70 C, ramping to 100% by 85 C
    "points": [[70, 50], [80, 75], [85, 100]],
    "step": 5,
}


def _clamp_points(points):
    out = []
    for t, p in points:
        t = max(50, min(95, int(round(t))))
        p = max(FAN_MIN, min(100, int(round(p))))
        out.append([t, p])
    out.sort(key=lambda tp: tp[0])
    # drop duplicate temps (keep the higher %), enforce non-decreasing %
    dedup = {}
    for t, p in out:
        dedup[t] = max(dedup.get(t, 0), p)
    pts = sorted([t, p] for t, p in dedup.items())
    best = FAN_MIN
    for tp in pts:
        best = tp[1] = max(best, tp[1])   # fans never drop as temp rises
    return pts or [[70, 50]]


def _clamp(cfg):
    cfg["enabled"] = bool(cfg.get("enabled"))
    cfg["step"] = max(1, min(10, int(cfg.get("step", 5))))
    cfg["points"] = _clamp_points(cfg.get("points") or DEFAULT["points"])
    return cfg


def load():
    cfg = dict(DEFAULT)
    try:
        with open(CONFIG) as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    cfg.pop("base", None)   # drop legacy single-point keys if present
    cfg.pop("trip", None)
    cfg.pop("hyst", None)
    cfg.pop("hot", None)
    return _clamp(cfg)


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


def interp(temp_c, points):
    """Linear interpolation of fan % at temp_c over sorted [temp, pct] points.
    Flat below the first point and above the last."""
    pts = sorted(points)
    if temp_c is None or not pts:
        return None
    if temp_c <= pts[0][0]:
        return float(pts[0][1])
    if temp_c >= pts[-1][0]:
        return float(pts[-1][1])
    for (t0, p0), (t1, p1) in zip(pts, pts[1:]):
        if t0 <= temp_c <= t1:
            if t1 == t0:
                return float(max(p0, p1))
            return p0 + (p1 - p0) * (temp_c - t0) / (t1 - t0)
    return float(pts[-1][1])


def target_pct(temp_c, cfg):
    """The fan % to apply: interpolated, rounded to `step`, clamped to [FAN_MIN,100]."""
    raw = interp(temp_c, cfg["points"])
    if raw is None:
        return None
    step = cfg.get("step", 5)
    pct = int(round(raw / step) * step)
    return max(FAN_MIN, min(100, pct))


def max_chip_temp(snapshot):
    temps = [b.get("temp_chip_c") for b in snapshot.get("boards", [])]
    temps = [t for t in temps if t is not None]
    return max(temps) if temps else None


class Supervisor:
    """Background thread that enforces the curve by setting fan floors.

    Only ever calls miner.do("fan", <pct>) — the allowlisted fans-only action.
    Writes only when the rounded target changes, so it does not spam the miner.
    """

    def __init__(self, miner, snapshot_fn, cfg=None, interval=10):
        self.miner = miner
        self.snapshot_fn = snapshot_fn
        self.cfg = cfg or load()
        self.interval = interval
        self.applied = None
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
            self.applied = None
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
                temp = max_chip_temp(self.snapshot_fn())
                target = target_pct(temp, cfg)
                with self._lock:
                    self.last_temp = temp
                if target is not None and target != self.applied:
                    self.miner.do("fan", target)
                    with self._lock:
                        self.applied = target
                        self.last_error = None
            except Exception as exc:
                with self._lock:
                    self.last_error = str(exc)
