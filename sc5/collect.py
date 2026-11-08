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
    snap["errors"] = errors
    return snap
