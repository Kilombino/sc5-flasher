"""sc5: dashboard and control tools for the Goldshell SC5 Pro II.

  python3 -m sc5 status 192.168.1.50          one-shot report
  python3 -m sc5 status 192.168.1.50 --json   same, as JSON
  python3 -m sc5 serve 192.168.1.50           local dashboard on http://127.0.0.1:8099
"""

import argparse
import json
import sys

from .collect import collect


def fmt_report(s):
    d = s["device"]
    out = [f"{d.get('model')}  hw {d.get('hardware')}  board {d.get('board')}  fw {d.get('firmware')}  ({d.get('miner')})"]
    su = s["summary"]
    up = su["uptime_s"] or 0
    out.append(f"Hashrate {su['ths_20s']:.2f} TH/s (avg {su['ths_avg']:.2f})  uptime {int(up // 3600)}h{int(up % 3600 // 60):02d}m  "
               f"HW {su['hw_pct']}%  rejected {su['reject_pct']}%  algo {s.get('algorithm')}")
    out.append(f"Power plan: {s['power']['plan']}  temp control {s['power']['temp_control']}")
    for b in s["boards"]:
        temps = "/".join(f"{t:.0f}" for t in b["temps_c"])
        out.append(f"  board {b['id']}: {b['status']:5}  {b['ths_20s']:.2f} TH/s  {b['clock_mhz']:.0f} MHz  "
                   f"{(b['voltage_mv'] or 0) / 1000:.2f} V  {temps} °C  fans {b['fans_rpm']}  HW {b['hw_pct']}%")
    for p in s["pools"]:
        mark = "*" if p["active"] else " "
        out.append(f" {mark}pool {p['priority']}: {p['status']:5} {p['url']}  user {p['user']}  acc {p['accepted']} rej {p['rejected']}")
    for w in s["warnings"]:
        out.append(f"! {w}")
    for e in s.get("errors", []):
        out.append(f"x {e}")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sc5", description="Read-only tools for the Goldshell SC5 Pro II")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", help="print a one-shot report")
    st.add_argument("host")
    st.add_argument("--json", action="store_true")
    sv = sub.add_parser("serve", help="local dashboard (read-only unless --control)")
    sv.add_argument("host")
    sv.add_argument("--bind", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8099)
    sv.add_argument("--control", action="store_true",
                    help="enable allowlisted controls (mode/LED/temp/reboot); needs the password in ~/.config/sc5-flasher/secrets.env")
    a = ap.parse_args(argv)

    if a.cmd == "status":
        snap = collect(a.host)
        print(json.dumps(snap, indent=2, ensure_ascii=False) if a.json else fmt_report(snap))
        return 0 if not snap.get("errors") else 1
    if a.cmd == "serve":
        from .dashboard import serve
        serve(a.host, a.bind, a.port, control=a.control)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
