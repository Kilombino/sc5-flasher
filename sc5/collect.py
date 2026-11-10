"""Gathers every read-only source into the raw dict that model.build_snapshot expects."""

from . import api
from .model import build_snapshot

CG = ("version", "summary", "devs", "pools")
WEB = {"status": "/mcb/status", "setting": "/mcb/setting",
       "algosetting": "/mcb/algosetting", "pools_web": "/mcb/pools"}


def collect(host):
    raw, errors = {}, []
    for cmd in CG:
        try:
            raw[cmd] = api.cgminer(host, cmd)
        except Exception as exc:  # one dead source must not hide the others
            errors.append(f"cgminer {cmd}: {exc}")
    for key, path in WEB.items():
        try:
            raw[key] = api.web_get(host, path)
        except Exception as exc:
            errors.append(f"web {path}: {exc}")
    snap = build_snapshot(raw)
    pw = snap.get("power") or {}
    snap["notes"] = []
    if pw.get("level") == 3 and not pw.get("manual"):
        # Idle: the firmware stops cgminer, so its API refusing connections is expected.
        cg = [e for e in errors if e.startswith("cgminer ")]
        if cg:
            errors = [e for e in errors if not e.startswith("cgminer ")]
            snap["notes"].append("En reposo el minero para cgminer: no hay lecturas de "
                                 "hashrate, temperatura ni ventiladores hasta elegir Hash o Eco.")
    snap["errors"] = errors
    return snap
