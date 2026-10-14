"""Sanity checks on the generated data files, run by refresh.yml as its last step (after the data has
been committed, so a failure turns the run red and emails you without blocking the refresh).
They guard against the quiet kind of failure - a section that exists but has stopped telling you
anything - e.g. a chip you have played with no result, or an AI plan for the wrong gameweek.

    python check_data.py [data.js bacalhau-data.js]      exit 1 if anything is wrong"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = ["team", "gameweeks", "plan", "transfers", "chips_official", "chip_net", "xg_signal", "rotation_risk",
            "ai_team", "daily_check", "deadline", "strategy"]


def load(path):
    raw = Path(path).read_text()
    return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])


WATCH = {"data.js": "shaaland-wildcard.js", "bacalhau-data.js": "bacalhau-wildcard.js"}


def check_watch(name, d):
    """The wildcard watch file is a hand-captured draft until its gameweek locks; after that it must have
    been replaced by the confirmed squad (wildcard_recommend.sync_confirmed_squad)."""
    path = ROOT / WATCH.get(name, "")
    if not path.is_file():
        return []
    w = load(path)
    locked = (d.get("deadline") or {}).get("locked_gw") or 0
    problems = []
    if w.get("gw") and w["gw"] <= locked and w.get("status") != "confirmed":
        problems.append(f"{path.name}: GW{w['gw']} has locked but the squad is still '{w.get('status')}' (captured {w.get('captured_at')})")
    if not (w.get("recommend") or {}).get("captain"):
        problems.append(f"{path.name}: no captain recommendation")
    return problems


def check(name, d):
    problems = check_watch(name, d)
    for k in REQUIRED:
        if d.get(k) in (None, [], {}):
            problems.append(f"{name}: section '{k}' is missing or empty")
    official, net = d.get("chips_official") or {}, d.get("chip_net") or {}
    audit = d.get("fh_audit") or {}
    for chip, gw in official.items():
        if not gw:
            continue
        have = net.get(chip) or ({"net": audit.get("net"), "note": audit.get("why")} if chip == "freehit" else None)
        if not have or not have.get("note"):
            problems.append(f"{name}: chip '{chip}' was played in GW{gw} but has no result line")
        elif chip != "wildcard" and have.get("net") is None:
            problems.append(f"{name}: chip '{chip}' (GW{gw}) has no points result")
    ai, nxt = d.get("ai_team") or {}, (d.get("deadline") or {}).get("next_gw")
    plan = ai.get("plan") or {}
    if nxt and plan.get("gw") != nxt:
        problems.append(f"{name}: AI team plan is for GW{plan.get('gw')} but the next open gameweek is GW{nxt}")
    if plan and len(plan.get("xi", [])) != 11:
        problems.append(f"{name}: AI team XI has {len(plan.get('xi', []))} players")
    return problems


def main(argv):
    files = argv or ["data.js", "bacalhau-data.js"]
    problems = []
    for f in files:
        try:
            problems += check(f, load(ROOT / f))
        except Exception as e:
            problems.append(f"{f}: could not be read ({e})")
    for p in problems:
        print("::error::" + p)
    print("data checks:", "OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
