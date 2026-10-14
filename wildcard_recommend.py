#!/usr/bin/env python3
"""Captain/bench recommendation for a manually-captured wildcard squad
(e.g. bacalhau-wildcard.js, shaaland-wildcard.js). The squad itself is
hand-updated from screenshots — FPL's API never exposes a provisional
squad before ITS OWN deadline, not even your own team's, so there's no
way to read an in-progress wildcard draft automatically — but the
recommendation on top of it is computed fresh every refresh cycle from
real bootstrap-static data, so captain/bench advice stays current as
form, fixtures and injury status change before the deadline.

Expected points come from the program's own model (ai_team.player_values: xG/xA
rates, minutes security, the next gameweek's fixture, availability) - NOT FPL's
ep_next, which currently just repeats a player's last-week form (a defender
with one big week showed as the best captain). Captain = highest expected points
among the fit starters; bench-swap suggestions flag a benched player who
out-projects a starter in the same position group. Injury/doubt flags reuse
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
from refresh import ET, deadline_state, fixture_scan, player_availability
import ai_team

ROOT = Path(__file__).resolve().parent
TEAM_IDS = {"Shaaland": 1360999, "Bacalhau": 1360920}
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

    `entry_prices` is a second, independent reference point: the price at
    the moment each currently-held name MOST RECENTLY joined the squad. A
    player added after the original baseline (e.g. swapped in later in the
    draft) would otherwise show baseline_cost/delta as permanently null —
    there'd be no way to see how that specific pick has moved since it was
    actually added, which defeats the point of tracking price changes for a
    profit-maximizing wildcard plan. Pruned the instant a name leaves the
    squad (not just left stale) so a sold-then-rebought player re-arms at
    the rebuy price rather than keeping a stale original entry.
    """
    prev = watch.get("worth_tracker") or {}
    current_prices = {p["name"]: p["cost"] for p in squad if p.get("cost") is not None}
    current_names = set(current_prices)
    current_total = round(sum(current_prices.values()), 1)

    baseline = prev.get("baseline") or {"date": today, "total_cost": current_total, "prices": dict(current_prices)}

    last = prev.get("current") or baseline
    last_prices = last.get("prices", {})
    last_names = set(last_prices)

    entry_prices = dict(prev.get("entry_prices") or {}) if prev else dict(current_prices)
    for name in current_names - last_names:
        entry_prices[name] = current_prices[name]
    for name in list(entry_prices):
        if name not in current_names:
            del entry_prices[name]

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

    # Baseline members are permanent fixtures here (their drift from the
    # original plan matters for the life of the plan); a non-baseline player
    # who's removed would otherwise vanish from this list the instant they
    # leave (never having been in `baseline["prices"]`) even though the log
    # just announced their removal — so also include `last_names` for one
    # extra run, giving a visible "removed" row instead of a silent drop.
    players = []
    for name in sorted(current_names | set(baseline["prices"]) | last_names):
        b, c = baseline["prices"].get(name), current_prices.get(name)
        e = entry_prices.get(name)
        status = "held" if (b is not None and c is not None) else ("removed" if c is None else "added")
        delta = round(c - b, 1) if (b is not None and c is not None) else None
        delta_since_added = round(c - e, 1) if (e is not None and c is not None) else None
        redundant = e is not None and b is not None and e == b  # held-since-baseline: nothing new to show
        players.append({
            "name": name, "baseline_cost": b, "current_cost": c, "delta": delta,
            "entry_cost": None if redundant else e,
            "delta_since_added": None if redundant else delta_since_added,
            "status": status,
        })
    players.sort(key=lambda p: (p["status"] != "held", -(p["delta"] or 0)))

    return {
        "baseline": baseline,
        "current": {"date": today, "total_cost": current_total, "prices": current_prices},
        "entry_prices": entry_prices,
        "total_delta": round(current_total - baseline["total_cost"], 1),
        "players": players,
        "log": log,
    }


def expected_points(boot, teams):
    """Model expected points for the next open gameweek, per player (same model as the AI team)."""
    ds = deadline_state(boot)
    target = ds.get("next_gw")
    if not target:
        return {"gw": None, "vals": {}}
    team_objs = {t["id"]: t for t in boot["teams"]}
    ids = {e["id"] for e in boot["events"]}
    fix1 = fixture_scan(target, team_objs)
    fix2 = fixture_scan(target + 1, team_objs) if target + 1 in ids else {}
    finished = sum(1 for e in boot["events"] if e.get("finished"))
    locked = ds.get("locked_gw")
    played = max(1, finished + (1 if locked and not next((e for e in boot["events"] if e["id"] == locked), {}).get("finished") else 0))
    return {"gw": target, "vals": ai_team.player_values(boot, fix1, fix2, played)}


def sync_confirmed_squad(watch, boot, teams):
    """The squad in a watch file is hand-captured while a wildcard is still a draft. Once that gameweek's
    deadline has passed FPL publishes the locked squad, so replace the draft with it (XI, bench order,
    chips played) - otherwise a stale 'provisional' draft sits here forever."""
    team_id = TEAM_IDS.get(watch.get("team"))
    gw = watch.get("gw")
    ev = next((e for e in boot["events"] if e["id"] == gw), None)
    if not (team_id and ev):
        return
    from fpl_common import parse_iso
    dl = parse_iso(ev.get("deadline_time"))
    if not dl or datetime.now(dl.tzinfo) < dl:
        return
    try:
        pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
        hist = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/history/")
    except Exception as e:
        print(f"warn: could not sync {watch.get('team')} GW{gw} squad: {e}")
        return
    picks = sorted(pk.get("picks") or [], key=lambda p: p.get("position") or 99)
    if len(picks) != 15:
        return
    els = {e["id"]: e for e in boot["elements"]}
    def row(p):
        el = els[p["element"]]
        return {"pos": ai_team.POS[el["element_type"]], "name": el["web_name"], "club": teams[el["team"]],
                "fixture": "", **({"captain": True} if p.get("is_captain") else {}), **({"vice": True} if p.get("is_vice_captain") else {})}
    watch["xi"] = [row(p) for p in picks if p["position"] <= 11]
    watch["bench"] = [row(p) for p in picks if p["position"] > 11]
    watch["status"] = "confirmed"
    watch["captured_at"] = datetime.now(ET).strftime("%Y-%m-%d")
    watch["note"] = f"Confirmed GW{gw} squad — the GW{gw} deadline has passed and this matches the lineup FPL locked in (synced from {watch.get('team')}'s picks every refresh)."
    chips = {}
    for c in hist.get("chips", []):
        chips[c["name"]] = f"played_gw{c['event']}"
    if chips:
        watch["chips"] = {k: chips.get(k, "available") for k in ("bboost", "3xc", "wildcard", "freehit")}


def main(watch_path=DEFAULT_WATCH_PATH):
    watch_path = Path(watch_path)
    watch = load_js_object(watch_path)
    if not watch:
        print(f"{watch_path.name} not found or empty — nothing to recommend on")
        return

    boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    sync_confirmed_squad(watch, boot, teams)
    model = expected_points(boot, teams)
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
        m = model["vals"].get(el["id"]) or {}
        return {**p, "ep_next": m.get("xp"), "fixture": m.get("fixture") or p.get("fixture"), "status": avail["kind"],
                "avail_label": avail["label"], "chance": avail["chance"], "cost": el["now_cost"] / 10}

    xi = [enrich(p) for p in watch.get("xi", [])]
    bench = [enrich(p) for p in watch.get("bench", [])]

    # show next gameweek's fixture for each player (the saved ones are from whenever the squad was captured)
    for saved, enriched in list(zip(watch.get("xi", []), xi)) + list(zip(watch.get("bench", []), bench)):
        if enriched.get("fixture"):
            saved["fixture"] = enriched["fixture"]

    fit_xi = [p for p in xi if p["ep_next"] is not None and p["status"] != "out"]
    # A real doubt (<75% to play) shouldn't wear the armband: FPL's ep_next only
    # partly discounts it. Fall back to them only if nobody safer is left.
    safe_xi = [p for p in fit_xi if p["status"] != "doubt" or (p.get("chance") or 0) >= 75]
    ranked = sorted(safe_xi if len(safe_xi) >= 2 else fit_xi, key=lambda p: -p["ep_next"])
    captain = ranked[0] if ranked else None
    vice = ranked[1] if len(ranked) > 1 else None

    # Bench-swap suggestions: a benched player who out-projects the WORST
    # starter in the same position group is worth reconsidering pre-deadline
    # — a pre-deadline "process" check, same framing as the season's bench
    # audit, just run forward instead of graded after the fact.
    swaps, claimed = [], set()
    # Best bench projection first; each starter is offered up only once, so two
    # bench players in one position group can't both point at the same starter.
    for bp in sorted((p for p in bench if p["ep_next"] is not None and p["status"] != "out"), key=lambda p: -p["ep_next"]):
        pool = [p for p in xi if p["pos"] == bp["pos"] and p["ep_next"] is not None and p["name"] not in claimed]
        if not pool:
            continue
        worst = min(pool, key=lambda p: p["ep_next"])  # an out bench player can't be swapped in
        if bp["ep_next"] > worst["ep_next"]:
            claimed.add(worst["name"])
            swaps.append({
                "bench": bp["name"], "bench_ep": bp["ep_next"],
                "starter": worst["name"], "starter_ep": worst["ep_next"],
            })
    swaps.sort(key=lambda s: -(s["bench_ep"] - s["starter_ep"]))

    # Auto-sub order: FPL fixes the spare keeper in slot 1; the outfield bench is
    # subbed in slot order, so the likeliest-to-play, highest-EP player goes first.
    def bench_key(p):
        rank = {"out": 2, "doubt": 1}.get(p["status"], 0)
        return (rank, -(p["ep_next"] if p["ep_next"] is not None else -1))
    gk_bench = [p for p in bench if p["pos"] == "GKP"]
    out_bench = sorted([p for p in bench if p["pos"] != "GKP"], key=bench_key)
    bench_order = [p["name"] for p in gk_bench + out_bench]
    your_order = [p["name"] for p in bench]

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
        "bench_order": bench_order,
        "bench_order_changed": bench_order != your_order,
        "availability_flags": flags,
        "xi_ep": [{"name": p["name"], "pos": p["pos"], "ep_next": p["ep_next"], "status": p["status"]} for p in xi],
        "bench_ep": [{"name": p["name"], "pos": p["pos"], "ep_next": p["ep_next"], "status": p["status"]} for p in bench],
    }

    today = datetime.now(ET).strftime("%Y-%m-%d")
    unmatched = [p["name"] for p in xi + bench if p.get("cost") is None]
    if unmatched:
        # A partial total would understate the baseline for good and log spurious removed/added rows.
        print(f"warn: {watch_path.name}: unmatched player(s) {unmatched} — skipping worth_tracker update this run")
    else:
        watch["worth_tracker"] = build_worth_tracker(watch, xi + bench, today)

    watch_path.write_text("window.FPL_WILDCARD_WATCH = " + json.dumps(watch, indent=2, ensure_ascii=False) + ";\n")
    cap = watch["recommend"]["captain"]
    wt = watch.get("worth_tracker")
    worth = f", worth £{wt['current']['total_cost']}m ({sign_str(wt['total_delta'])})" if wt and not unmatched else ""
    print(f"wildcard_recommend {watch_path.name}: captain={cap} ({watch['recommend']['captain_ep']}), {len(swaps)} bench-swap suggestion(s), {len(flags)} availability flag(s){worth}")


def sign_str(n):
    return f"+{n}" if n > 0 else str(n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(DEFAULT_WATCH_PATH))
    args = ap.parse_args()
    main(args.path)
