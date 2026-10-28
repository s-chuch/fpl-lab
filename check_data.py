"""Sanity checks on the generated data files, run by refresh.yml as its last step (after the data has
been committed, so a failure turns the run red and emails you without blocking the refresh).
They guard against the quiet kind of failure - a section that exists but has stopped telling you
anything - e.g. a chip you have played with no result, or an AI plan for the wrong gameweek.

    python check_data.py [data.js bacalhau-data.js]      exit 1 if anything is wrong"""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
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


MIN_ROWS = {"transfers": 1, "targets": 1, "injury_watch": 1}      # sections that must hold rows, not just exist


def _age_hours(stamp):
    """Hours since a 'YYYY-MM-DD HH:MM UTC' or ISO timestamp (None if unreadable)."""
    try:
        t = datetime.fromisoformat(str(stamp).replace(" UTC", "").replace("Z", "+00:00").replace(" ", "T", 1))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600
    except Exception:
        return None


def check_ai_squad(name, d):
    """The AI team must always hold a legal squad: 15 players in the right positions, at most 3 per club,
    a bank that is not negative and a total that fits the budget."""
    ai = d.get("ai_team") or {}
    plan = ai.get("plan") or {}
    squad = plan.get("squad") or []
    out = []
    if not squad:
        return out
    if len(squad) != 15:
        out.append(f"{name}: AI team squad has {len(squad)} players")
    per_pos = {}
    per_club = {}
    for p in squad:
        per_pos[p["pos"]] = per_pos.get(p["pos"], 0) + 1
        per_club[p["club"]] = per_club.get(p["club"], 0) + 1
    if per_pos != {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}:
        out.append(f"{name}: AI team squad shape is {per_pos}")
    over = [c for c, n in per_club.items() if n > 3]
    if over:
        out.append(f"{name}: AI team has more than 3 players from {', '.join(over)}")
    if (plan.get("bank") or 0) < -0.001:
        out.append(f"{name}: AI team bank is negative ({plan.get('bank')})")
    budget = ai.get("budget")
    # Sell value plus bank can pass the starting money only by price rises (the AI keeps half of any profit), so allow a few percent of
    # headroom; anything beyond that means the money was invented.
    if budget is not None and plan.get("sell_value") is not None and round(plan["sell_value"] + (plan.get("bank") or 0), 1) > round(budget, 1) + max(0.15, 0.04 * budget):
        out.append(f"{name}: AI team holds more money than it has ({plan['sell_value']} + {plan.get('bank')} > {budget})")
    return out


def check(name, d):
    problems = check_watch(name, d)
    for k in REQUIRED:
        if d.get(k) in (None, [], {}):
            problems.append(f"{name}: section '{k}' is missing or empty")
    for k, n in MIN_ROWS.items():
        v = d.get(k)
        rows = v if isinstance(v, list) else ((v or {}).get("rows") or (v or {}).get("horizons") or [])
        if len(rows) < n:
            problems.append(f"{name}: section '{k}' has no rows")
    age = _age_hours(d.get("generated_at"))
    if age is not None and age > 30:
        problems.append(f"{name}: data was generated {age:.0f}h ago - scheduled refreshes may have stopped")
    for sec, h in (d.get("_health") or {}).items():
        if not h.get("ok"):
            problems.append(f"{name}: section '{sec}' failed since {h.get('since')}: {h.get('error')}")
    problems += check_ai_squad(name, d)
    # points reconciliation: the gameweek rows must add up to FPL's overall points (hits are taken off)
    gws = d.get("gameweeks") or []
    total = (d.get("team") or {}).get("overall_points")
    if gws and total is not None:
        net = sum(g["points"] - (g.get("hits") or 0) for g in gws)
        locked = (d.get("deadline") or {}).get("locked_gw")
        live = bool(gws and gws[-1].get("gw") == locked and not gws[-1].get("points"))    # the gameweek in play is not in the rows yet
        if (net - total > 2) if live else (abs(net - total) > 2):
            problems.append(f"{name}: gameweek points add up to {net} but FPL reports {total} overall")
    # a finished gameweek must have a graded track record
    vl = d.get("volume_log") or {}
    fin_events = (d.get("deadline") or {}).get("locked_gw")
    for k, e in vl.items():
        if e.get("graded") is False and e.get("gw") is not None and fin_events and e["gw"] < fin_events - 1:
            problems.append(f"{name}: xG/xA track record for GW{e['gw']} was never graded")
    for hp in ((d.get("ai_team") or {}).get("history") or {}).values():
        r = hp.get("result") or {}
        if not r.get("final") and hp.get("gw") is not None and hp["gw"] < (fin_events or 0) - 1:
            problems.append(f"{name}: AI result for GW{hp['gw']} is still not final")
    for sec, maxh in (("team_recovery", 8),):
        a = _age_hours((d.get(sec) or {}).get("fetched_at"))
        if a is None:
            problems.append(f"{name}: '{sec}' has no fetch time (the feed has never answered)")
        elif a > maxh:
            problems.append(f"{name}: '{sec}' was fetched {a:.0f}h ago")
    official, net = d.get("chips_official") or {}, d.get("chip_net") or {}
    audit = d.get("fh_audit") or {}
    for chip, gw in official.items():
        if not gw:
            continue
        have = net.get(chip) or ({"net": audit.get("net"), "note": audit.get("why")} if chip == "freehit" else None)
        if not have or not (have.get("note") or have.get("compare")):
            problems.append(f"{name}: chip '{chip}' was played in GW{gw} but has no result line")
        elif have.get("net") is None:
            problems.append(f"{name}: chip '{chip}' (GW{gw}) has no points result")
    ai, nxt = d.get("ai_team") or {}, (d.get("deadline") or {}).get("next_gw")
    plan = ai.get("plan") or {}
    if nxt and plan.get("gw") != nxt:
        problems.append(f"{name}: AI team plan is for GW{plan.get('gw')} but the next open gameweek is GW{nxt}")
    pa = _age_hours(plan.get("computed_at")) if plan and not plan.get("locked") else None
    if pa is not None and pa > 12:
        problems.append(f"{name}: the unlocked AI plan was last computed {pa:.0f}h ago")
    for k in ("decisions_error",):
        if plan.get(k):
            problems.append(f"{name}: AI plan {k}: {plan[k]}")
    if ai.get("review_error"):
        problems.append(f"{name}: AI review failed: {ai['review_error']}")
    if plan and len(plan.get("xi", [])) != 11:
        problems.append(f"{name}: AI team XI has {len(plan.get('xi', []))} players")
    return problems


def check_age_only(files):
    """Watchdog: runs on its own schedule, so it still fires when the refresh workflow itself has stopped."""
    problems = []
    for f in files:
        try:
            a = _age_hours(load(ROOT / f).get("generated_at"))
        except Exception as e:
            problems.append(f"{f}: could not be read ({e})"); continue
        if a is None or a > 30:
            problems.append(f"{f}: data is {'of unknown age' if a is None else f'{a:.0f}h old'} - scheduled refreshes have stopped")
    for p in problems:
        print("::error::" + p)
    print("age check:", "OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def check_exa_news():
    """exa-news.js (display-only Exa team news) is optional: a missing file is fine, a corrupt one is only a warning -
    the page hides the block and the next refresh rewrites it. Never fails the run."""
    path = ROOT / "exa-news.js"
    if not path.is_file():
        return
    try:
        raw = path.read_text()
        d = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        n = len(d.get("items") or [])
        age = _age_hours(d.get("generated_at"))
        print(f"exa-news.js: {n} items, {'?' if age is None else round(age, 1)}h old, {(d.get('month_usage') or {}).get('searches', '?')} searches this month")
    except Exception as e:
        print(f"::warning::exa-news.js unreadable ({e}) - the page hides the block until the next refresh")


def main(argv):
    if argv and argv[0] == "--age-only":
        return check_age_only(argv[1:] or ["data.js", "bacalhau-data.js"])
    files = argv or ["data.js", "bacalhau-data.js"]
    problems = []
    for f in files:
        try:
            problems += check(f, load(ROOT / f))
        except Exception as e:
            problems.append(f"{f}: could not be read ({e})")
    for p in problems:
        print("::error::" + p)
    check_exa_news()
    print("data checks:", "OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
