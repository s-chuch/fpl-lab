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
from datetime import datetime
from pathlib import Path

from fpl_common import get, load_js_object
from refresh import ET, player_availability

ROOT = Path(__file__).resolve().parent
DEFAULT_WATCH_PATH = ROOT / "bacalhau-wildcard.js"


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_worth_tracker(watch, squad, today):
    """Track the wildcard target squad's total cost and per-player price
    moves across refreshes, so a profit-maximizing wildcard plan has a
    running log instead of only ever showing today's snapshot. FPL exposes
    no per-player price history, so this is built up incrementally, refresh
    over refresh, by diffing against what this function itself wrote back
    into the watch file last time.

    `baseline` is set once, the first time a squad is captured, and never
    moves — it's "what it would have cost to assemble this plan when you
    first drafted it." `current` is last run's snapshot, used only to spot
    what changed since then. total_delta compares current cost to assemble
    the (possibly edited) plan against that original baseline cost — the
    plan's net drift, whether from price moves on held names or swaps to
    different-priced targets.
    """
    prev = watch.get("worth_tracker") or {}
    current_prices = {p["name"]: p["cost"] for p in squad if p.get("cost") is not None}
    current_names = set(current_prices)
    current_total = round(sum(current_prices.values()), 1)

    baseline = prev.get("baseline") or {"date": today, "total_cost": current_total, "prices": dict(current_prices)}

    last = prev.get("current") or baseline
    last_prices = last.get("prices", {})
    last_names = set(last_prices)

    log = list(prev.get("log") or [])
    if not prev:
        log.append({"date": today, "event": "captured", "detail": f"Initial target squad captured — {len(current_names)} players, £{current_total}m."})

    for name in sorted(current_names & last_names):
        old, new = last_prices[name], current_prices[name]
        if abs(new - old) >= 0.05:
            log.append({"date": today, "event": "price_change", "player": name, "from": old, "to": new, "delta": round(new - old, 1)})
    for name in sorted(last_names - current_names):
        log.append({"date": today, "event": "removed", "player": name, "price_at_change": last_prices[name]})
    for name in sorted(current_names - last_names):
        log.append({"date": today, "event": "added", "player": name, "price_at_change": current_prices[name]})
    log = log[-40:]  # bound file growth across a long season

    players = []
    for name in sorted(current_names | set(baseline["prices"])):
        b, c = baseline["prices"].get(name), current_prices.get(name)
        status = "held" if (b is not None and c is not None) else ("removed" if c is None else "added")
        players.append({
            "name": name, "baseline_cost": b, "current_cost": c,
            "delta": round(c - b, 1) if (b is not None and c is not None) else None,
            "status": status,
        })
    players.sort(key=lambda p: (p["status"] != "held", -(p["delta"] or 0)))

    return {
        "baseline": baseline,
        "current": {"date": today, "total_cost": current_total, "prices": current_prices},
        "total_delta": round(current_total - baseline["total_cost"], 1),
        "players": players,
        "log": log,
    }


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
            return {**p, "ep_next": None, "status": "unmatched", "chance": None, "unmatched": True, "cost": None}
        avail = player_availability(el)
        return {**p, "ep_next": to_float(el.get("ep_next")), "status": avail["kind"], "avail_label": avail["label"], "chance": avail["chance"], "cost": el["now_cost"] / 10}

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

    today = datetime.now(ET).strftime("%Y-%m-%d")
    watch["worth_tracker"] = build_worth_tracker(watch, xi + bench, today)

    watch_path.write_text("window.FPL_WILDCARD_WATCH = " + json.dumps(watch, indent=2, ensure_ascii=False) + ";\n")
    cap = watch["recommend"]["captain"]
    wt = watch["worth_tracker"]
    print(f"wildcard_recommend {watch_path.name}: captain={cap} ({watch['recommend']['captain_ep']}), {len(swaps)} bench-swap suggestion(s), {len(flags)} availability flag(s), worth £{wt['current']['total_cost']}m ({sign_str(wt['total_delta'])})")


def sign_str(n):
    return f"+{n}" if n > 0 else str(n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(DEFAULT_WATCH_PATH))
    args = ap.parse_args()
    main(args.path)
