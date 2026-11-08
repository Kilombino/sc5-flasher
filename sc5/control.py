"""Write actions for the Goldshell SC5 Pro II — strictly allowlisted and reversible.

Design: the browser never sends a miner path or a raw payload. It sends an action
name from ACTIONS and, at most, one simple argument. This module maps that to a
fixed operation. There is NO code path to /mcb/facrst (factory reset) or
/mcb/uploadimage (firmware), so the panel cannot brick the miner.

Every setting change is read-modify-write: we read the device's own config object
and send it back with a single field changed, exactly as the stock UI does.

The web password is read from ~/.config/sc5-flasher/secrets.env, never from the
browser and never committed.
"""

import json
import os
import re
import threading
import urllib.parse
import urllib.request

# Power-plan levels the stock firmware ships (from /mcb/setting -> powerplans).
# Only factory presets: no custom clock/voltage, which is where tuning can overheat.
MODE_LEVELS = {"hash": 0, "eco": 2, "idle": 3}

# Paths this module is ever allowed to touch. Writes only here; nothing else.
_READ = "/mcb/setting"
_WRITE_SETTING = "/mcb/setting"
_WRITE_RESTART = "/mcb/restart"

# Actions the panel may request. Each is a fixed, reversible operation.
ACTIONS = {
    "mode",          # arg: "hash" | "eco" | "idle"  -> set power-plan level
    "fan",           # arg: "max" | "auto"            -> fan % only, clock/voltage untouched
    "led",           # arg: bool                      -> identification LED
    "tempcontrol",   # arg: bool                      -> temperature-based fan control
    "reboot",        # no arg                         -> PUT /mcb/restart
}

# Paths that must never be reachable from here, as a second line of defence.
FORBIDDEN = {"/mcb/facrst", "/mcb/uploadimage", "/mcb/newpool", "/mcb/delpool",
             "/mcb/cmossetting", "/mcb/ip", "/mcb/wifisetting"}

TIMEOUT = 15
SECRETS = os.path.expanduser("~/.config/sc5-flasher/secrets.env")


class ControlError(RuntimeError):
    pass


def load_password():
    try:
        with open(SECRETS) as fh:
            for line in fh:
                if line.startswith("SC5_WEB_PASSWORD="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    raise ControlError(f"No password in {SECRETS} (set SC5_WEB_PASSWORD=…, chmod 600).")


class Miner:
    """Holds the host and a cached login token; serialises writes."""

    def __init__(self, host, password=None):
        self.host = host
        self._password = password
        self._token = None
        self._lock = threading.Lock()

    def _opener(self):
        # Stock API is plain HTTP. Refuse redirects, ignore system proxies.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def _request(self, path, method="GET", body=None, token=None):
        if path in FORBIDDEN:
            raise ControlError(f"Refusing forbidden path {path}")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://{self.host}{path}", data=data,
                                     headers=headers, method=method)
        with self._opener().open(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else None

    def _login(self):
        if self._token:
            return self._token
        pw = self._password or load_password()
        q = urllib.parse.urlencode({"username": "admin", "password": pw})
        out = self._request(f"/user/login?{q}", method="GET")
        token = (out or {}).get("JWT Token")
        if not token:
            raise ControlError("Login rejected: check the dashboard password.")
        self._token = token
        return token

    def do(self, action, arg=None):
        if action not in ACTIONS:
            raise ControlError(f"Unknown action {action!r}")
        with self._lock:
            token = self._login()
            if action == "reboot":
                self._request(_WRITE_RESTART, method="PUT", body={}, token=token)
                self._token = None  # miner reboots; token will be reissued next time
                return {"ok": True, "note": "Reinicio enviado; vuelve en ~1-2 min."}

            cfg = self._request(_READ, method="GET", token=token)
            if not isinstance(cfg, dict):
                raise ControlError("Could not read current settings.")

            if action == "mode":
                if arg not in MODE_LEVELS:
                    raise ControlError(f"mode must be one of {sorted(MODE_LEVELS)}")
                cfg["select"] = MODE_LEVELS[arg]
                cfg["manual"] = False  # use the factory preset, not custom tuning
            elif action == "fan":
                # Raise/lower ONLY the fan %, keeping clock and voltage byte-identical
                # to the active plan. More cooling can't brick; we never touch MHz/V.
                if arg not in ("max", "auto"):
                    raise ControlError("fan must be 'max' or 'auto'")
                if arg == "auto":
                    cfg["manual"] = False  # fans follow the selected preset + temp control
                else:
                    plan = cfg.get("manualPowerplan") or ""
                    # replace the two "<n> RPM <n> RPM" fan fields with 100; leave the
                    # rest (MHz, V, PV) exactly as-is. Refuse if the shape is unexpected.
                    new_plan, n = re.subn(r"\d+\s*RPM\s+\d+\s*RPM", "100 RPM 100 RPM", plan, count=1)
                    if n != 1:
                        raise ControlError(f"Unexpected power-plan format: {plan!r}")
                    cfg["manualPowerplan"] = new_plan
                    cfg["manual"] = True
            elif action == "led":
                cfg["ledcontrol"] = bool(arg)
            elif action == "tempcontrol":
                cfg["tempcontrol"] = bool(arg)

            self._request(_WRITE_SETTING, method="PUT", body=cfg, token=token)
            return {"ok": True, "applied": action, "arg": arg}
