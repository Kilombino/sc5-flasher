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
import time

from .control import FAN_MIN

CONFIG = os.path.expanduser("~/.config/sc5-flasher/curve.json")

# Hard safety: whatever curve the user sets, at/above this chip temp we force
# 100% fans. This can't be edited away, so a gentle curve can never let the
# chip climb with the fans low. The miner also protects itself independently
# (firmware shuts the board down on overheat, cutoff 105 C chip / 89 C board).
SAFE_MAX_C = 88

DEFAULT = {
    "enabled": False,
    # progressive, several intermediate steps
    "points": [[62, 45], [70, 52], [76, 62], [80, 72], [84, 85], [88, 100]],
    "step": 5,
    # Lower the fan only once the chip is this many degrees below the point
    # where the lower % would apply. Without it a chip sitting on a rounding
    # boundary (e.g. 80/81 C) flips 70%<->75% every few seconds: a saw tooth.
    "down_hyst": 2,
    # "curve": follow the points. "target": hold the chip at target_c by nudging
    # the fan 1 % at a time (at most every adjust_s seconds); the curve stays as
    # an emergency floor 3 C above the target.
    "mode": "curve",
    "target_c": 80,
    "adjust_s": 60,
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
    cfg["down_hyst"] = max(0, min(5, int(cfg.get("down_hyst", 2))))
    cfg["mode"] = "target" if cfg.get("mode") == "target" else "curve"
    cfg["target_c"] = max(65, min(85, int(cfg.get("target_c", 80))))
    cfg["adjust_s"] = max(20, min(600, int(cfg.get("adjust_s", 60))))
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
    """The fan % to apply: interpolated, rounded to `step`, clamped to [FAN_MIN,100].
    Above SAFE_MAX_C the fans are forced to 100% whatever the curve says."""
    raw = interp(temp_c, cfg["points"])
    if raw is None:
        return None
    if temp_c is not None and temp_c >= SAFE_MAX_C:
        return 100
    step = cfg.get("step", 5)
    pct = int(round(raw / step) * step)
    return max(FAN_MIN, min(100, pct))


def hold_target(temp_c, cfg, current):
    """`target_pct` with downward hysteresis: going UP is immediate (safety),
    going DOWN from `current` only if the chip is also `down_hyst` degrees
    cooler. Otherwise keep `current`."""
    target = target_pct(temp_c, cfg)
    if target is None or current is None or target >= current:
        return target
    hyst = cfg.get("down_hyst", 2)
    if hyst and target_pct(temp_c + hyst, cfg) >= current:
        return current
    return target


TARGET_RESCUE_C = 3   # this far above target, jump straight to the curve


LEARNED = os.path.expanduser("~/.config/sc5-flasher/learned.json")
LEARN_BAND_C = 1        # within this many degrees of the target counts as "holding it"
LEARN_AFTER_S = 300     # held that long at the same fan % -> remember that %
FAST_DOWN_PCT = 3       # far below target: drop this many % per step instead of 1


def load_learned(target_c):
    """The fan % that last held the chip at target_c, or None."""
    try:
        with open(LEARNED) as f:
            v = json.load(f).get(str(int(target_c)))
        return int(v) if v is not None else None
    except (OSError, ValueError, TypeError):
        return None


def save_learned(target_c, pct):
    try:
        with open(LEARNED) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data[str(int(target_c))] = int(pct)
    tmp = LEARNED + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, LEARNED)


START_PCT_AT_82 = 60    # fan % to start from when the thermostat is switched on
START_PCT_PER_C = 4     # each degree of target below 82 C starts 4 % higher (and above, lower)


def start_pct(target_c):
    """Where the thermostat starts when it is switched on: 60 % for a 82 C target,
    proportionally more fan for a cooler target and less for a warmer one."""
    return max(FAN_MIN, min(100, START_PCT_AT_82 + START_PCT_PER_C * (82 - int(target_c))))


def target_step(temp_c, cfg, current, since_adjust, learned=None):
    """Thermostat mode: returns (pct, adjusted). Holds `current` while the chip
    sits at target_c; +1 % if hotter, -1 % if cooler, at most once every
    adjust_s seconds. Never below the curve once the chip is TARGET_RESCUE_C
    over target; TARGET_RESCUE_C under target it drops straight to the curve's
    value for the target. 100 % at SAFE_MAX_C."""
    if temp_c is None:
        return current, False
    if temp_c >= SAFE_MAX_C:
        return 100, True
    if current is None:
        return target_pct(temp_c, cfg), True
    tgt = cfg.get("target_c", 80)
    if temp_c >= tgt + TARGET_RESCUE_C:
        floor = target_pct(temp_c, cfg) or current
        if floor > current:
            return min(100, floor), True
    if temp_c <= tgt - TARGET_RESCUE_C:
        # far too cold (e.g. just after a rescue or a reboot): jump down to the fan %
        # that last held the target (learned), else to what the curve says for it,
        # instead of creeping 1 %/min for half an hour
        guess = learned if learned is not None else target_pct(tgt, cfg)
        if guess is not None and guess < current:
            return max(FAN_MIN, guess), True
    if since_adjust is not None and since_adjust < cfg.get("adjust_s", 60):
        return current, False
    if temp_c <= tgt - TARGET_RESCUE_C:
        # still far below after that jump: come down faster than 1 %
        return max(FAN_MIN, current - FAST_DOWN_PCT), True
    if temp_c > tgt:
        return min(100, current + 1), True
    if temp_c < tgt:
        return max(FAN_MIN, current - 1), True
    return current, False


def max_chip_temp(snapshot):
    temps = [b.get("temp_chip_c") for b in snapshot.get("boards", [])]
    temps = [t for t in temps if t is not None]
    return max(temps) if temps else None


def current_fan_pct(snapshot):
    """The fan % the miner is actually running right now (parsed from its live
    power plan). Used so the curve drives toward the target from the miner's
    REAL state, not from what we last think we set — so it reclaims control
    after a miner reboot (which reverts the plan to a factory preset)."""
    return (snapshot.get("power") or {}).get("fan_pct")


def keeps_curve(action, arg):
    """Whether a manual control leaves the software curve switched on.

    A fixed fan % is an explicit override, so it switches the curve off. A mode
    change does not: Hash and Idle keep it (in Idle the supervisor just waits),
    so the fans are never left on the Hash preset's fixed 30 %. Eco is the
    exception: the curve drives the fan through the custom plan, which mines at
    700 MHz, so leaving it on would silently undo Eco."""
    if action == "fan":
        return False
    if action == "mode":
        return arg in ("hash", "idle")
    return True


def overheat_guard(snapshot, curve_enabled):
    """True when the panel itself must force 100 % fans: the curve is off, the
    miner runs the Hash preset or the custom plan (both 700 MHz, so a fan write
    changes nothing else) and a chip is at/above SAFE_MAX_C with the fans below
    100 %. The firmware's own ramp has been seen to hold 30 % up to 93 C."""
    if curve_enabled:
        return False
    pw = (snapshot or {}).get("power") or {}
    if not pw.get("manual") and pw.get("level") != 0:
        return False
    temp = max_chip_temp(snapshot or {})
    if temp is None or temp < SAFE_MAX_C:
        return False
    return pw.get("fan_pct") != 100


def needs_write(target, actual, applied):
    """True if we must set the fan to `target`. Compared against the miner's
    REAL fan (`actual`) when we could read it, else our last `applied` value.
    This is what makes the curve reclaim control after a reboot: the miner
    comes back at a preset %, actual != target, so we re-assert the curve."""
    if target is None:
        return False
    ref = actual if actual is not None else applied
    return target != ref


class Supervisor:
    """Background thread that enforces the curve by setting fan floors.

    Only ever calls miner.do("fan", <pct>) — the allowlisted fans-only action.
    Each loop it compares the target against the miner's REAL current fan % and
    writes only when they differ, so it does not spam the miner yet still
    reclaims control after a reboot (which reverts the fan to a factory preset).
    """

    def __init__(self, miner, snapshot_fn, cfg=None, interval=10):
        self.miner = miner
        self.snapshot_fn = snapshot_fn
        self.cfg = cfg or load()
        self.interval = interval
        self.applied = None
        self.last_temp = None
        self.last_error = None
        self._last_adjust = None
        self._hold_since = None
        self._hold_pct = None
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
            self._last_adjust = None
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
                pw = (snap or {}).get("power") or {}
                if not pw.get("manual") and pw.get("level") == 3:
                    self._stop.wait(self.interval)   # avoid a busy loop when applied is None
                    continue   # idle: fans are already 100% and a fan write would wake it
                temp = max_chip_temp(snap)
                actual = current_fan_pct(snap)
                ref = actual if actual is not None else self.applied
                if cfg.get("mode") == "target":
                    now = time.monotonic()
                    since = None if self._last_adjust is None else now - self._last_adjust
                    tgt_c = cfg.get("target_c", 80)
                    if self.applied is None and temp is not None and temp < SAFE_MAX_C:
                        # just switched on (or the panel restarted): start from the
                        # proportional value for this target, then regulate from there
                        target, adjusted = start_pct(tgt_c), True
                    else:
                        target, adjusted = target_step(temp, cfg, ref, since, load_learned(tgt_c))
                    if adjusted:
                        self._last_adjust = now
                    # Learn the fan % that holds the target: the chip within
                    # LEARN_BAND_C of it for LEARN_AFTER_S at the same fan %.
                    if temp is not None and ref is not None and abs(temp - tgt_c) <= LEARN_BAND_C:
                        if self._hold_pct != ref:
                            self._hold_pct, self._hold_since = ref, now
                        elif now - self._hold_since >= LEARN_AFTER_S:
                            if load_learned(tgt_c) != ref:
                                save_learned(tgt_c, ref)
                            self._hold_since = now
                    else:
                        self._hold_pct = self._hold_since = None
                else:
                    target = hold_target(temp, cfg, ref)
                with self._lock:
                    self.last_temp = temp
                if target is not None:
                    # Drive toward the target from the miner's REAL fan %, not a
                    # cached value — so a reboot that reset the fan is corrected.
                    if needs_write(target, actual, self.applied):
                        self.miner.do("fan", target)
                        with self._lock:
                            self.last_error = None
                    with self._lock:
                        self.applied = target
            except Exception as exc:
                with self._lock:
                    self.last_error = str(exc)
