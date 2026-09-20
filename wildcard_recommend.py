#!/usr/bin/env python3
"""Captain/bench recommendation for a manually-captured wildcard squad
(e.g. bacalhau-wildcard.js, shaaland-wildcard.js). The squad itself is
hand-updated from screenshots — FPL's API never exposes a provisional
squad before ITS OWN deadline, not even your own team's, so there's no
way to read an in-progress wildcard draft automatically — but the
recommendation on top of it is computed fresh every refresh cycle from
real bootstrap-static data, so captain/bench advice stays current as
form, fixtures and injury status change before the deadline.

Uses FPL's own ep_next field ("expected points next gameweek" — the
platform's own form+fixture-blended prediction) rather than re-deriving
a competing points model: captain = highest ep_next among the fit
starters; bench-swap suggestions flag a benched player whose ep_next
beats a starter in the same position group. Injury/doubt flags reuse
refresh.py's player_availability so the same status rules apply
everywhere in the app.

Reads the squad (xi/bench) from the given watch file as input and writes
a "recommend" block back into the same file — hand-editing the squad
there (a newer screenshot) and re-running this just recomputes advice
against the new squad; nothing else in the file is touched.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from fpl_common import get, load_js_object
from refresh import player_availability

ROOT = Path(__file__).resolve().parent
DEFAULT_WATCH_PATH = ROOT / "bacalhau-wildcard.js"


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main(watch_path=DEFAULT_WATCH_PATH):
    watch_path = Path(watch_path)
    watch = load_js_object(watch_path)
    if not watch:
        print(f"{watch_path.name} not found or empty — nothing to recommend on")
        return

    boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    by_name_club, by_name = {}, {}
    for el in boot["elements"]:
        name = el.get("web_name")
        club = teams.get(el["team"])
        by_name_club[(name, club)] = el
        by_name.setdefault(name, el)  # fallback if a club code doesn't line up exactly

    def enrich(p):
        el = by_name_club.get((p["name"], p.get("club"))) or by_name.get(p["name"])
        if not el:
            return {**p, "ep_next": None, "status": "unmatched", "chance": None, "unmatched": True}
        avail = player_availability(el)
        return {**p, "ep_next": to_float(el.get("ep_next")), "status": avail["kind"], "avail_label": avail["label"], "chance": avail["chance"]}

    xi = [enrich(p) for p in watch.get("xi", [])]
    bench = [enrich(p) for p in watch.get("bench", [])]

    fit_xi = [p for p in xi if p["ep_next"] is not None and p["status"] != "out"]
    ranked = sorted(fit_xi, key=lambda p: -p["ep_next"])
    captain = ranked[0] if ranked else None
    vice = ranked[1] if len(ranked) > 1 else None

    # Bench-swap suggestions: a benched player who out-projects the WORST
    # starter in the same position group is worth reconsidering pre-deadline
    # — a pre-deadline "process" check, same framing as the season's bench
    # audit, just run forward instead of graded after the fact.
    swaps = []
    for b in bench:
        if b["ep_next"] is None:
            continue
        same_pos = [p for p in xi if p["pos"] == b["pos"] and p["ep_next"] is not None]
        if not same_pos:
            continue
        worst = min(same_pos, key=lambda p: p["ep_next"])
        if b["ep_next"] > worst["ep_next"]:
            swaps.append({
                "bench": b["name"], "bench_ep": b["ep_next"],
                "starter": worst["name"], "starter_ep": worst["ep_next"],
            })
    swaps.sort(key=lambda s: -(s["bench_ep"] - s["starter_ep"]))

    flags = [
        {"name": p["name"], "label": p.get("avail_label"), "chance": p.get("chance")}
        for p in xi + bench if p["status"] in ("out", "doubt")
    ]

    watch["recommend"] = {
        "captain": captain["name"] if captain else None,
        "captain_ep": captain["ep_next"] if captain else None,
        "vice": vice["name"] if vice else None,
        "vice_ep": vice["ep_next"] if vice else None,
        "bench_swaps": swaps,
        "availability_flags": flags,
        "xi_ep": [{"name": p["name"], "pos": p["pos"], "ep_next": p["ep_next"], "status": p["status"]} for p in xi],
        "bench_ep": [{"name": p["name"], "pos": p["pos"], "ep_next": p["ep_next"], "status": p["status"]} for p in bench],
    }

    watch_path.write_text("window.FPL_WILDCARD_WATCH = " + json.dumps(watch, indent=2, ensure_ascii=False) + ";\n")
    cap = watch["recommend"]["captain"]
    print(f"wildcard_recommend {watch_path.name}: captain={cap} ({watch['recommend']['captain_ep']}), {len(swaps)} bench-swap suggestion(s), {len(flags)} availability flag(s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(DEFAULT_WATCH_PATH))
    args = ap.parse_args()
    main(args.path)
