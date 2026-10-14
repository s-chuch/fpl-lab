"""Shared base for the refresh: logging, constants, the memoised FPL GET, deadline state, fixtures."""
from __future__ import annotations
import copy, sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import fpl_common

def _warn(msg):
    """Surface a skipped-item failure in the Action log instead of swallowing it."""
    print(f"[refresh.py] WARNING: {msg}", file=sys.stderr)

ET = ZoneInfo("America/Toronto")

TEAM_ID = 1360999

TRACKED_BY_TEAM = {
    1360999: {125784, 494594},
    1360920: {125784, 494595},
}

TRACKED_LEAGUES = {125784, 494594}

ROOT = Path(__file__).resolve().parent

POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

MINN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}

MAXX = {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}

# Within one run the same per-GW endpoints are read by several builders (bench audit, captain
# audit/board, transfers, ...). Memoise the ones that don't change during a run.
_MEMO_PARTS = ("/live/", "/picks/", "/element-summary/", "/transfers/")

_memo = {}

def get(url):
    if any(p in url for p in _MEMO_PARTS):
        if url not in _memo:
            _memo[url] = fpl_common.get(url, timeout=30)
        return copy.deepcopy(_memo[url])  # callers may mutate what they get
    return fpl_common.get(url, timeout=30)

def parse_deadline(raw):
    """Parse FPL deadline_time (UTC ISO) to aware datetime, or None."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None

def fmt_deadline_et(raw):
    """User-facing deadline string in America/Toronto (labeled ET)."""
    dt = parse_deadline(raw)
    if not dt:
        return ""
    local = dt.astimezone(ET)
    # e.g. 2026-09-18 1:30 PM ET
    return local.strftime("%Y-%m-%d %-I:%M %p ET")

def fmt_generated_et(dt=None):
    dt = dt or datetime.now(timezone.utc)
    local = dt.astimezone(ET)
    return local.strftime("%Y-%m-%d %-I:%M %p ET")

def deadline_state(boot, now=None):
    """Compute locked vs next GW from FPL deadline_time (UTC).

    - locked_gw: highest event whose deadline has passed (picks public)
    - next_gw: first event whose deadline has not passed (intel / planning target)
    - current_gw: FPL is_current, else locked_gw if mid-GW, else next_gw
    - deadline_passed: True when the FPL current event's deadline has passed
      (or when locked_gw >= current unfinished matchweek)
    """
    now = now or datetime.now(timezone.utc)
    events = sorted(boot.get("events") or [], key=lambda e: e["id"])
    locked_gw = None
    next_gw = None
    by_id = {}
    for e in events:
        by_id[e["id"]] = e
        dl = parse_deadline(e.get("deadline_time"))
        if dl and now >= dl:
            locked_gw = e["id"]
        elif next_gw is None and dl and now < dl:
            next_gw = e["id"]
        elif next_gw is None and not dl:
            next_gw = e["id"]
    cur = next((e for e in events if e.get("is_current")), None)
    nxt = next((e for e in events if e.get("is_next")), None)
    unfinished = [e for e in events if not e.get("finished")]
    current_gw = (cur or (unfinished[0] if unfinished else None) or {}).get("id")
    if current_gw is None:
        current_gw = locked_gw or next_gw
    # Planning / intel target: next deadline that has not passed
    intel_gw = next_gw or (nxt or {}).get("id")
    if intel_gw is None and not (events and current_gw == events[-1]["id"]):
        intel_gw = (current_gw or 0) + 1  # no GW after the last event (season over)
    cur_dl = parse_deadline((by_id.get(current_gw) or {}).get("deadline_time"))
    deadline_passed = bool(cur_dl and now >= cur_dl)
    # Picks unlock for the locked GW (usually = current after deadline, else last finished)
    picks_gw = locked_gw or (unfinished[0]["id"] if unfinished else current_gw)
    return {
        "now_utc": now.isoformat(),
        "locked_gw": locked_gw,
        "next_gw": next_gw,
        "intel_gw": intel_gw,
        "current_gw": current_gw,
        "deadline_passed": deadline_passed,
        "picks_unlocked": bool(deadline_passed and locked_gw),
        "picks_gw": picks_gw if deadline_passed else None,
    }

_fixtures_cache = {}

def _fixtures_for(event_id):
    """Every fixture of one gameweek, from a single whole-season request made once per run (the
    per-gameweek form of the endpoint was being called 19 times)."""
    if "all" not in _fixtures_cache:
        try:
            _fixtures_cache["all"] = get("https://fantasy.premierleague.com/api/fixtures/")
        except Exception as e:
            _warn(f"fixtures: whole-season request failed, using per-gameweek requests: {e}")
            _fixtures_cache["all"] = None
    allfx = _fixtures_cache["all"]
    if allfx is None:
        return get(f"https://fantasy.premierleague.com/api/fixtures/?event={event_id}")
    return [f for f in allfx if f.get("event") == event_id]

def fixture_map(event_id, teams):
    """One entry per team. A double gameweek is combined (opponents joined with "+", FDR averaged, "double"
    set) rather than the second fixture overwriting the first; a blank team simply has no entry."""
    multi = fixture_scan(event_id, teams)
    out = {}
    for tid, fl in multi.items():
        fdrs = [f["fdr"] for f in fl if f.get("fdr") is not None]
        out[tid] = {"side": fl[0]["side"], "opp": "+".join(f["opp"] for f in fl),
                    "fdr": (round(sum(fdrs) / len(fdrs), 1) if len(fl) > 1 else (fdrs[0] if fdrs else None)),
                    **({"double": True} if len(fl) > 1 else {})}
    return out

# Bookmaker odds per upcoming fixture ({gw: {team_id: [{opp, side, xg_for, xg_against, cs, p_win}]}}, odds.by_team), registered
# once per run by ai_run.setup_odds. fixture_scan merges them into the fixtures it returns, so every consumer of fixtures
# (the xP model, the planner, the AI team, the Plan XI) sees them; with no odds the fixtures are exactly as before.
ODDS = {}


def set_odds(by_gw):
    ODDS.clear()
    ODDS.update(by_gw or {})


def fixture_scan(event_id, teams):
    """Like fixture_map, but keeps EVERY fixture per team instead of one —
    fixture_map's dict overwrites a team's earlier entry on a double gameweek,
    which is fine for the single-fixture Plan tab but hides blanks/doubles,
    exactly the signal chip-timing strategy needs."""
    fx = _fixtures_for(event_id)
    out = {}
    for f in fx:
        h, a = f["team_h"], f["team_a"]
        out.setdefault(h, []).append({"side": "H", "opp": teams[a]["short_name"], "fdr": f.get("team_h_difficulty")})
        out.setdefault(a, []).append({"side": "A", "opp": teams[h]["short_name"], "fdr": f.get("team_a_difficulty")})
    for tid, fxs in out.items():
        for entry in (ODDS.get(event_id) or {}).get(tid, []):
            for fx in fxs:
                if fx["opp"] == entry["opp"] and fx["side"] == entry["side"]:
                    fx.update({k: entry[k] for k in ("xg_for", "xg_against", "cs", "p_win") if entry.get(k) is not None})
    return out

def fmt_fix(info):
    return "Blank" if not info else f"{info['side']} {info['opp']}"

def player_availability(el):
    """Map FPL element status/chance/news into a plan availability record."""
    status = (el.get("status") or "a").lower()
    chance = el.get("chance_of_playing_next_round")
    if chance is None:
        chance = el.get("chance_of_playing_this_round")
    news = (el.get("news") or "").strip()
    if status in ("i", "s", "u") or chance == 0:
        label = {"i": "INJ", "s": "SUS", "u": "OUT"}.get(status, "OUT")
        return {"status": status, "chance": chance, "news": news, "kind": "out", "label": label}
    if status == "d" or (chance is not None and chance < 100):
        label = f"DOUBT {chance}%" if chance is not None else "DOUBT"
        return {"status": status, "chance": chance, "news": news, "kind": "doubt", "label": label}
    return {"status": status, "chance": chance, "news": news, "kind": "ok", "label": None}

def bare(name):
    return name.split(" (")[0]
