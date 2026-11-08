"""Turns raw API replies into one snapshot dict. Pure functions, easy to test."""

import re
import time

KNOWN_MODEL = "Goldshell-SC5Pro"  # status.model starts with this ("Goldshell-SC5ProⅡ")
KNOWN_BOARDS = {"MCB_V3_3"}
TESTED_FIRMWARE = {"2.2.0"}


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_snapshot(raw):
    """raw: {"version","summary","devs","pools","status","setting","pools_web",...}
    Missing parts are tolerated; the snapshot just has fewer fields."""
    snap = {"taken_at": int(time.time()), "warnings": []}

    status = raw.get("status") or {}
    snap["device"] = {
        "model": status.get("model"),
        "hardware": status.get("hardware"),
        "board": status.get("mcbversion"),
        "firmware": status.get("firmware"),
    }
    model = status.get("model") or ""
    if model and not model.startswith(KNOWN_MODEL):
        snap["warnings"].append(f"Unknown model {model!r}: this tool was written for the SC5 Pro II.")
    if status.get("mcbversion") and status["mcbversion"] not in KNOWN_BOARDS:
        snap["warnings"].append(f"Untested board {status['mcbversion']!r}.")
    if status.get("firmware") and status["firmware"] not in TESTED_FIRMWARE:
        snap["warnings"].append(f"Untested firmware {status['firmware']!r}.")

    version = (raw.get("version") or {}).get("VERSION") or [{}]
    snap["device"]["miner"] = version[0].get("Miner")

    summary = ((raw.get("summary") or {}).get("SUMMARY") or [{}])[0]
    snap["summary"] = {
        "uptime_s": _num(summary.get("Elapsed")),
        "ths_avg": (_num(summary.get("MHS av"), 0) or 0) / 1e6,
        "ths_20s": (_num(summary.get("MHS 20s"), 0) or 0) / 1e6,
        "accepted": summary.get("Accepted"),
        "rejected": summary.get("Rejected"),
        "hw_errors": summary.get("Hardware Errors"),
        "hw_pct": _num(summary.get("Device Hardware%")),
        "reject_pct": _num(summary.get("Pool Rejected%")),
        "best_share": _num(summary.get("Best Share")),
    }

    boards = []
    for d in (raw.get("devs") or {}).get("DEVS") or []:
        # tstemp-0/1 are the two chip (ASIC) zones; tstemp-2 is the cooler board
        # sensor. The stock panel shows only tstemp-2, which is why it reads lower.
        chip_temps = [_num(d.get(k)) for k in ("tstemp-0", "tstemp-1")]
        chip_temps = [t for t in chip_temps if t is not None]
        board_temp = _num(d.get("tstemp-2"))
        temps = [t for t in (_num(d.get("tstemp-0")), _num(d.get("tstemp-1")), board_temp) if t is not None]
        board = {
            "id": d.get("ID"),
            "status": d.get("Status"),
            "ths_avg": (_num(d.get("MHS av"), 0) or 0) / 1e6,
            "ths_20s": (_num(d.get("MHS 20s"), 0) or 0) / 1e6,
            "clock_mhz": _num(d.get("clock")),
            "voltage_mv": _num(d.get("voltage")),
            "fans_rpm": [d.get(f"fan{i}") for i in range(4) if d.get(f"fan{i}") is not None],
            "temps_c": temps,
            "temp_chip_c": max(chip_temps) if chip_temps else None,  # the hot one
            "temp_board_c": board_temp,                              # what stock shows
            "temp_max_c": max(temps) if temps else None,
            "overheat": d.get("overheat"),
            "hw_pct": _num(d.get("Device Hardware%")),
            "reboots": d.get("rebootcnt"),
        }
        boards.append(board)
        if board["status"] != "Alive":
            snap["warnings"].append(f"Board {board['id']} status {board['status']!r}.")
        if board["overheat"]:
            snap["warnings"].append(f"Board {board['id']} reports overheat.")
        if board["temp_max_c"] is not None and board["temp_max_c"] >= 90:
            snap["warnings"].append(f"Board {board['id']} at {board['temp_max_c']:.0f} °C.")
    snap["boards"] = boards

    pools = []
    for p in (raw.get("pools") or {}).get("POOLS") or []:
        pools.append({
            "priority": p.get("Priority"),
            "url": p.get("URL"),
            "user": p.get("User"),
            "status": p.get("Status"),
            "active": bool(p.get("Stratum Active")),
            "accepted": p.get("Accepted"),
            "rejected": p.get("Rejected"),
            "last_share": p.get("Last Share Time"),
        })
    snap["pools"] = pools

    setting = raw.get("setting") or {}
    plan = setting.get("manualPowerplan") or ""
    fan_m = re.search(r"(\d+)\s*RPM", plan)
    snap["power"] = {
        "plan": setting.get("manualPowerplan"),
        "manual": setting.get("manual"),
        "select": setting.get("select"),
        "fan_pct": int(fan_m.group(1)) if fan_m else None,  # fan % baked into the plan
        "led": setting.get("ledcontrol"),
        "temp_control": setting.get("tempcontrol"),
        "plans": [pl.get("info") for pl in setting.get("powerplans") or []],
    }
    algo = raw.get("algosetting") or {}
    algos = {a.get("id"): a.get("name") for a in algo.get("algos") or []}
    snap["algorithm"] = algos.get(algo.get("algo_select"))

    if raw.get("pools_web") is not None:
        # The stock web API serves pool passwords without authentication.
        snap["warnings"].append("Stock web API exposes pool settings without a password (LAN only!).")
    return snap
