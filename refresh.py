#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from league_tactics import build_tactics
from lab_audit import add_roll_rows
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

def get(url):
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
    return local.strftime("%Y-%m-%d %-I:%M %p ET").replace("AM", "AM").replace("PM", "PM")

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
    intel_gw = next_gw or (nxt or {}).get("id") or ((current_gw or 0) + 1)
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

def format_pick_squad(picks, elements, teams):
    """XI + bench + captain from an entry event picks payload."""
    xi, bench = [], []
    captain = vice = None
    chip = None
    for p in sorted(picks or [], key=lambda x: x.get("position") or 99):
        el = elements.get(p["element"])
        if not el:
            continue
        name = el["web_name"]
        pos = POS[el["element_type"]]
        club = teams[el["team"]]["short_name"]
        item = {"id": p["element"], "name": name, "pos": pos, "club": club, "mult": p.get("multiplier") or 0}
        if p.get("is_captain"):
            captain = name
            item["captain"] = True
        if p.get("is_vice_captain"):
            vice = name
            item["vice"] = True
        if (p.get("position") or 99) <= 11:
            xi.append(item)
        else:
            bench.append(item)
    return {"xi": xi, "bench": bench, "captain": captain, "vice": vice}

def fixture_map(event_id, teams):
    fx = get(f"https://fantasy.premierleague.com/api/fixtures/?event={event_id}")
    out = {}
    for f in fx:
        h, a = f["team_h"], f["team_a"]
        out[h] = {"side": "H", "opp": teams[a]["short_name"], "fdr": f.get("team_h_difficulty")}
        out[a] = {"side": "A", "opp": teams[h]["short_name"], "fdr": f.get("team_a_difficulty")}
    return out

def fixture_scan(event_id, teams):
    """Like fixture_map, but keeps EVERY fixture per team instead of one —
    fixture_map's dict overwrites a team's earlier entry on a double gameweek,
    which is fine for the single-fixture Plan tab but hides blanks/doubles,
    exactly the signal chip-timing strategy needs."""
    fx = get(f"https://fantasy.premierleague.com/api/fixtures/?event={event_id}")
    out = {}
    for f in fx:
        h, a = f["team_h"], f["team_a"]
        out.setdefault(h, []).append({"side": "H", "opp": teams[a]["short_name"], "fdr": f.get("team_h_difficulty")})
        out.setdefault(a, []).append({"side": "A", "opp": teams[h]["short_name"], "fdr": f.get("team_a_difficulty")})
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

def recommend(pos, fdr, cost, minutes, avail=None):
    if avail and avail.get("kind") == "out":
        return "OUT"
    if avail and avail.get("kind") == "doubt":
        ch = avail.get("chance")
        if ch is not None and ch < 50:
            return "OUT"
        return "DOUBT"
    if fdr is None: return "BLANK"
    if minutes < 30: return "SIT"
    if minutes < 60 and cost < 5.5: return "SIT"
    if pos == "GKP": return "START" if fdr <= 3 else "SIT"
    if pos == "DEF":
        if fdr >= 5 or (fdr >= 4 and cost < 5.5): return "SIT"
        return "START"
    if pos == "MID" and ((fdr >= 5 and cost < 8) or (fdr >= 4 and cost < 6.5)): return "SIT"
    if pos == "FWD" and fdr >= 5 and cost < 8: return "SIT"
    return "START"

def bare(name):
    return name.split(" (")[0]

def score(pos, fdr, form, minutes, cost, avail=None):
    if avail and avail.get("kind") == "out":
        return -99
    if fdr is None: return -99
    if minutes < 30: return -40 + form
    base = form * 2 + (6 - int(fdr)) * 2.2 + min(minutes, 270) / 90 + (0.4 if cost >= 9 else 0)
    if avail and avail.get("kind") == "doubt":
        ch = avail.get("chance")
        # Scale by chance and add a flat penalty so fit players win ties.
        factor = (ch / 100.0) if ch is not None else 0.5
        return base * factor - 8
    return base

def pick_lineup(players, gw_key):
    ranked = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in players:
        info = p["gws"].get(gw_key) or {}
        ranked[p["pos"]].append((info.get("score", -99), p))
    for pos in ranked:
        ranked[pos].sort(key=lambda x: x[0], reverse=True)
    picked, counts = [], {k: 0 for k in MINN}
    def take(p, tag=""):
        picked.append(p["name"] + tag)
        counts[p["pos"]] += 1
    started = lambda: {bare(x) for x in picked}
    if ranked["GKP"]:
        take(ranked["GKP"][0][1])
    for pos, n in MINN.items():
        if pos == "GKP":
            continue
        for _s, p in ranked[pos]:
            if counts[pos] >= n:
                break
            if p["name"] in started():
                continue
            take(p, " (C)" if pos == "FWD" and counts[pos] == 0 else "")
    pool = []
    for pos in ("DEF", "MID", "FWD"):
        for s, p in ranked[pos]:
            if p["name"] not in started():
                pool.append((s, p))
    pool.sort(key=lambda x: x[0], reverse=True)
    for s, p in pool:
        if len(picked) >= 11:
            break
        if counts[p["pos"]] >= MAXX[p["pos"]]:
            continue
        take(p)
    if picked and not any(x.endswith(" (C)") for x in picked):
        picked[0] = picked[0] + " (C)"
    if picked and not any(" (VC)" in x for x in picked):
        for i, name in enumerate(picked):
            if not name.endswith(" (C)"):
                picked[i] = name + " (VC)"
                break
    rest_gk = [p["name"] for _s, p in ranked["GKP"] if p["name"] not in started()]
    rest_of = [p["name"] for _s, p in sorted([(_s, p) for pos in ("DEF", "MID", "FWD") for _s, p in ranked[pos] if p["name"] not in started()], key=lambda x: x[0], reverse=True)]
    return picked[:11], (rest_gk + rest_of)[:4]

def free_transfers_for_next(hist):
    """Free transfers banked heading into the next deadline. FPL raised the
    max bankable amount from 2 to 5 partway through 2023/24 — capping at 2
    here undercounted anyone who'd rolled 3+ times. A Wildcard/Free Hit week
    lets you make unlimited transfers for free, so its event_transfers must
    NOT be subtracted from the bank (only genuine paid hits should reduce
    it), which a normal week with a real transfer count can't be told apart
    from without knowing which GWs were chip weeks."""
    chip_gws = {c["event"] for c in hist.get("chips", []) if c.get("name") in ("wildcard", "freehit")}
    ft = 0
    for row in hist.get("current", []):
        ft = min(5, ft + 1)
        if row.get("event") not in chip_gws:
            ft = max(0, ft - int(row.get("event_transfers") or 0))
    return min(5, ft + 1)

def build_plan(boot, team_id, hist=None, chips_used=None):
    teams = {t["id"]: t for t in boot["teams"]}
    elements = {e["id"]: e for e in boot["elements"]}
    events = sorted(boot["events"], key=lambda e: e["id"])
    finished = [e for e in events if e.get("finished")]
    upcoming = [e for e in events if not e.get("finished")][:2]
    last_fin = finished[-1] if finished else None
    picks, picks_gw, skipped_fh = [], None, None
    fh_gw = (chips_used or {}).get("freehit")
    for ev in reversed(events):
        if ev["id"] > (last_fin["id"] if last_fin else 0) + 1: continue
        try:
            payload = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{ev['id']}/picks/")
            chip = payload.get("active_chip")
            if chip == "freehit" or ev["id"] == fh_gw:
                skipped_fh = ev["id"]
                continue
            picks = payload.get("picks") or []
            if picks:
                picks_gw = ev["id"]; break
        except Exception as e:
            _warn(f"build_plan: could not load GW{ev['id']} picks: {e}")
            continue
    if not picks:
        return {"note": "Could not load squad picks.", "upcoming": [], "rows": []}
    maps, headers = {}, []
    now = datetime.now(timezone.utc)
    for ev in upcoming:
        maps[ev["id"]] = fixture_map(ev["id"], teams)
        dl = ev.get("deadline_time") or ""
        dl_dt = parse_deadline(dl)
        headers.append({
            "gw": ev["id"],
            "deadline": fmt_deadline_et(dl) if dl else "",
            "deadline_utc": dl,
            "deadline_passed": bool(dl_dt and now >= dl_dt),
        })
    players, rows, availability = [], [], {}
    for pick in sorted(picks, key=lambda p: (elements[p["element"]]["element_type"], p["element"])):
        el = elements[pick["element"]]
        avail = player_availability(el)
        pos, form, mins, cost = POS[el["element_type"]], float(el.get("form") or 0), int(el.get("minutes") or 0), el["now_cost"] / 10
        gws, row = {}, [pos, el["web_name"], teams[el["team"]]["short_name"]]
        for ev in upcoming:
            info = maps[ev["id"]].get(el["team"])
            fdr = info["fdr"] if info else None
            cell = {
                "fixture": fmt_fix(info),
                "fdr": fdr,
                "call": recommend(pos, fdr, cost, mins, avail),
                "score": round(score(pos, fdr, form, mins, cost, avail), 2),
                "avail": avail["kind"],
                "avail_label": avail["label"],
            }
            gws[f"gw{ev['id']}"] = cell
            row.extend([cell["fixture"], fdr if fdr is not None else "-", cell["call"]])
        players.append({"name": el["web_name"], "pos": pos, "gws": gws, "cost": cost, "avail": avail})
        if avail["kind"] != "ok":
            availability[el["web_name"]] = avail
        rows.append(row)
    xis = {}
    for ev in upcoming:
        key = f"gw{ev['id']}"
        xi, bn = pick_lineup(players, key)
        xis[key] = {"xi": xi, "bench": bn}
    for i, ev in enumerate(upcoming):
        started = {bare(n) for n in xis[f"gw{ev['id']}"]["xi"]}
        for r in rows:
            fix = r[3 + i * 3]
            name = r[1]
            avail = availability.get(name) or {}
            if fix == "Blank":
                r[5 + i * 3] = "BLANK"
            elif avail.get("kind") == "out":
                r[5 + i * 3] = "OUT"
            elif avail.get("kind") == "doubt" and name not in started:
                r[5 + i * 3] = "DOUBT"
            else:
                r[5 + i * 3] = "START" if name in started else "SIT"
        for p in players:
            cell = p["gws"].get(f"gw{ev['id']}") or {}
            avail = p.get("avail") or {}
            if cell.get("fixture") == "Blank":
                cell["call"] = "BLANK"
            elif avail.get("kind") == "out":
                cell["call"] = "OUT"
            elif avail.get("kind") == "doubt" and p["name"] not in started:
                cell["call"] = "DOUBT"
            else:
                cell["call"] = "START" if p["name"] in started else "SIT"
    ft = free_transfers_for_next(hist or {})
    fh_used = bool((chips_used or {}).get("freehit"))
    bench_calls = []
    for ev in upcoming:
        key = f"gw{ev['id']}"
        sits = []
        for p in players:
            cell = p["gws"].get(key) or {}
            if cell.get("call") not in ("SIT", "BLANK", "OUT", "DOUBT"):
                continue
            avail = p.get("avail") or {}
            sits.append({
                "player": p["name"],
                "fixture": cell.get("fixture"),
                "fdr": cell.get("fdr"),
                "call": cell.get("call"),
                "avail": avail.get("kind"),
                "news": avail.get("news") or "",
            })
        def sit_key(x):
            # Prioritise injured/out, then doubtful, then hardest fixtures.
            pri = 0 if x.get("avail") == "out" else (1 if x.get("avail") == "doubt" else 2)
            return (pri, -(x["fdr"] or 0))
        sits.sort(key=sit_key)
        top = sits[0] if sits else None
        if top and top.get("avail") in ("out", "doubt"):
            why = f"{top['player']} {top.get('call')} · {(top.get('news') or top.get('fixture') or '').strip()}"
        elif top:
            why = f"{top['player']} {top['fixture']} FDR {top['fdr']}"
        else:
            why = "No sit"
        bench_calls.append({"gw": ev["id"], "sit": xis[key]["bench"], "worst": top["player"] if top else None, "why": why})
    who = "Shaaland" if team_id == 1360999 else "the original squad"
    action, move, reason = "ROLL", None, f"You have {ft} FT. " + (f"FH unused — roll so the FT returns with {who}." if not fh_used else "No forced move. Bank it.")
    note = f"GW{picks_gw} squad. Last finished {(last_fin or {}).get('id')}."
    if skipped_fh:
        note = f"GW{picks_gw} squad (GW{skipped_fh} was Free Hit; reverted). Last finished {(last_fin or {}).get('id')}."
    # Intel targets the next GW whose deadline has not passed (not stale locked GW themes)
    ds = deadline_state(boot, now)
    intel_gw = ds["intel_gw"]
    # Clear signal for UI: after GW N deadline, do not treat GW N news/X as current Plan advice
    return {
        "note": note,
        "last_finished": (last_fin or {}).get("id"),
        "squad_from_gw": picks_gw,
        "upcoming": headers,
        "rows": rows,
        "xis": xis,
        "bench_calls": bench_calls,
        "availability": availability,
        "transfer": {"ft_available": ft, "action": action, "reason": reason, "move": move, "fh_unused": not fh_used},
        "deadline_passed": ds["deadline_passed"],
        "locked_gw": ds["locked_gw"],
        "next_gw": ds["next_gw"],
        "intel_gw": intel_gw,
        # UI clears Plan themes when news/x gw < intel_gw (locked-GW consensus is stale)
        "intel_clear": False,
        "intel_note": (
            f"Waiting for GW{intel_gw} intel — GW{ds['locked_gw']} deadline has passed."
            if ds["deadline_passed"] and ds["locked_gw"]
            else None
        ),
    }

def captain_audit(boot, team_id):
    names = {e["id"]: e["web_name"] for e in boot["elements"]}
    out = []
    for ev in boot["events"]:
        if not ev.get("finished"): continue
        gw = ev["id"]
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
            live = get(f"https://fantasy.premierleague.com/api/event/{gw}/live/")
        except Exception as e:
            _warn(f"captain_audit: could not load GW{gw} picks/live: {e}")
            continue
        pts = {el["id"]: el["stats"]["total_points"] for el in live.get("elements", [])}
        cap = next((p for p in pk.get("picks", []) if p.get("is_captain")), None)
        vc = next((p for p in pk.get("picks", []) if p.get("is_vice_captain")), None)
        if not cap: continue
        cap_raw = pts.get(cap["element"], 0)
        vc_raw = pts.get(vc["element"], 0) if vc else 0
        mult = cap.get("multiplier") or 2
        best_id, best_raw = cap["element"], cap_raw
        for p in pk.get("picks", []):
            raw = pts.get(p["element"], 0)
            if raw > best_raw:
                best_id, best_raw = p["element"], raw
        got = cap_raw * mult
        out.append({"gw": gw, "chip": pk.get("active_chip"), "captain": names.get(cap["element"], "?"), "captain_raw": cap_raw, "got": got, "vc": names.get(vc["element"], "?") if vc else "-", "vc_raw": vc_raw, "best": names.get(best_id, "?"), "best_raw": best_raw, "vs_vc": got - vc_raw * mult, "vs_best": got - best_raw * mult})
    return out

def _best_xi(squad):
    """Best legal XI by final points, with the actual captain pinned first —
    same rule _process_xi uses. Bench-audit's "hindsight" is meant to isolate
    the LINEUP decision (who started vs. who was benched), not captaincy,
    which is a separate call graded elsewhere (captain_audit). Without
    pinning, this would silently re-captain to whoever scored highest in the
    chosen XI, so a blank captain week showed up as a "bench miss" here even
    when the actual bench/lineup was fine — bench points have nothing to do
    with captain points."""
    cap_name = next((p["name"] for p in squad if p.get("captain")), None)
    by = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in squad:
        by[p["pos"]].append(p)
    for pos in by:
        by[pos].sort(key=lambda x: (x["name"] != cap_name, -x["pts"]))
    picked, counts = [], {k: 0 for k in MINN}
    if by["GKP"]:
        picked.append(by["GKP"][0]); counts["GKP"] = 1
    have = lambda: {p["name"] for p in picked}
    for pos, n in MINN.items():
        if pos == "GKP":
            continue
        for p in by[pos]:
            if counts[pos] >= n:
                break
            if p["name"] in have():
                continue
            picked.append(p); counts[pos] += 1
    pool = [p for pos in ("DEF", "MID", "FWD") for p in by[pos] if p["name"] not in have()]
    pool.sort(key=lambda x: (x["name"] != cap_name, -x["pts"]))
    for p in pool:
        if len(picked) >= 11:
            break
        if counts[p["pos"]] >= MAXX[p["pos"]]:
            continue
        picked.append(p); counts[p["pos"]] += 1
    return picked

def _process_xi(squad, mins_key="mins"):
    """Best legal XI judged only by minutes, not final points: a bench player only
    displaces a starter here if they played strictly more minutes by `mins_key` — a
    call you could make without knowing the final scoreline. The real captain is
    pinned first so the multiplier isn't re-litigated by this heuristic.

    `mins_key` selects WHICH minutes decide who was "nailed on": the default,
    "mins", is that gameweek's own actual minutes (used by the Free Hit audit,
    which asks "how would this exact squad's real GW have gone"). bench_audit
    instead passes "trail_mins" — minutes from the GWs BEFORE the one being
    judged — since a genuine process call has to be based on what was knowable
    heading into the deadline, not on minutes that only exist after kickoff."""
    cap_name = next((p["name"] for p in squad if p.get("captain")), None)
    by = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in squad:
        by[p["pos"]].append(p)
    for pos in by:
        by[pos].sort(key=lambda x: (x["name"] != cap_name, -x[mins_key], not x["started"]))
    picked, counts = [], {k: 0 for k in MINN}
    if by["GKP"]:
        picked.append(by["GKP"][0]); counts["GKP"] = 1
    have = lambda: {p["name"] for p in picked}
    for pos, n in MINN.items():
        if pos == "GKP":
            continue
        for p in by[pos]:
            if counts[pos] >= n:
                break
            if p["name"] in have():
                continue
            picked.append(p); counts[pos] += 1
    pool = [p for pos in ("DEF", "MID", "FWD") for p in by[pos] if p["name"] not in have()]
    pool.sort(key=lambda x: (x["name"] != cap_name, -x[mins_key], not x["started"]))
    for p in pool:
        if len(picked) >= 11:
            break
        if counts[p["pos"]] >= MAXX[p["pos"]]:
            continue
        picked.append(p); counts[p["pos"]] += 1
    return picked

def build_bench_audit(boot, team_id, lookback=3):
    """`process` grades your bench call against what was knowable BEFORE the
    deadline, not against what happened in the gameweek itself: a player's
    "process" minutes are their trailing minutes from the `lookback` finished
    GWs before the one being judged (a true pre-deadline signal — reusing the
    gameweek's OWN actual minutes would grade the decision on its outcome,
    which is exactly the outcome-bias process-vs-outcome is meant to avoid).
    Early gameweeks with no/short history fall back to fewer prior GWs, and
    with zero history _process_xi's minutes-tie falls through to whichever
    player you actually started — the only defensible "process" call when
    there's no track record yet."""
    names = {e["id"]: e["web_name"] for e in boot["elements"]}
    pmap = {e["id"]: POS[e["element_type"]] for e in boot["elements"]}
    finished_gws = sorted(e["id"] for e in boot["events"] if e.get("finished"))
    live_cache = {}
    def live_for(g):
        if g not in live_cache:
            try:
                live_cache[g] = get(f"https://fantasy.premierleague.com/api/event/{g}/live/").get("elements", [])
            except Exception as e:
                _warn(f"build_bench_audit: could not load GW{g} live data: {e}")
                live_cache[g] = []
        return live_cache[g]

    out = {}
    for gw in finished_gws:
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
        except Exception as e:
            _warn(f"build_bench_audit: could not load GW{gw} picks: {e}")
            continue
        if pk.get("active_chip") == "bboost":
            # Bench Boost makes the whole audit meaningless: every one of the
            # 15 counts toward "you" regardless of bench position, so there
            # was no actual start/sit decision to grade that week — comparing
            # that bench-boosted real score against an 11-man-only process/
            # hindsight XI is an apples-to-oranges number, not a real miss.
            continue
        live_elems = live_for(gw)
        pts = {el["id"]: el["stats"]["total_points"] for el in live_elems}
        mins = {el["id"]: el["stats"].get("minutes", 0) for el in live_elems}
        prior_gws = [g for g in finished_gws if g < gw][-lookback:]
        trail_mins = {}
        for g in prior_gws:
            for el in live_for(g):
                trail_mins[el["id"]] = trail_mins.get(el["id"], 0) + int(el["stats"].get("minutes") or 0)
        cap = next((p for p in pk.get("picks", []) if p.get("is_captain")), None)
        mult = (cap or {}).get("multiplier") or 2
        squad, bench = [], []
        for p in pk.get("picks", []):
            item = {
                "name": names.get(p["element"], "?"),
                "pos": pmap.get(p["element"], "MID"),
                "pts": pts.get(p["element"], 0),
                "mins": mins.get(p["element"], 0),
                "trail_mins": trail_mins.get(p["element"], 0),
                "started": p["position"] <= 11,
                "captain": bool(p.get("is_captain")),
            }
            squad.append(item)
            if p["position"] > 11:
                bench.append([item["name"], item["pts"]])
        best = _best_xi(squad)
        started = {p["name"] for p in best}
        you = (pk.get("entry_history") or {}).get("points")
        raw = sum(p["pts"] for p in best)
        # Actual captain's own points, not a virtual re-captain to whoever
        # scored highest — hindsight is meant to grade the lineup only, and
        # _best_xi already guarantees the real captain is in `best`.
        best_cap_pts = next((p["pts"] for p in best if p["captain"]), 0)
        hindsight = raw + best_cap_pts * (mult - 1)
        proc_xi = _process_xi(squad, mins_key="trail_mins")
        proc_started = {p["name"] for p in proc_xi}
        proc_cap_pts = next((p["pts"] for p in proc_xi if p["captain"]), 0)
        process = sum(p["pts"] for p in proc_xi) + proc_cap_pts * (mult - 1)
        # "Should have benched" is judged by PROCESS (who was nailed on
        # trailing minutes heading into this GW), not pure outcome — a
        # starter who was clearly a fixture but had a quiet points day (e.g.
        # a nailed captain blanking) isn't a bench mistake, so flagging them
        # via hindsight's points-only best XI was misleading. `better` now
        # lists actual starters process XI wouldn't have started, i.e. it
        # wanted a currently-benched player (by trailing minutes) instead.
        better = [[p["name"], p["pts"]] for p in squad if p["name"] not in proc_started]
        # Per-bench-player verdict, auto-derived instead of hand-typed per GW:
        # "process" = minutes said they should've started (a real misread),
        # "variance" = not a nailed-minutes starter, but scored well enough
        # that hindsight's best XI (`started`) still wanted them anyway (bad
        # luck, not a mistake), "ok" = correctly left out either way — i.e. in
        # `better`/`better_names`, hindsight's own worst scorers, which is
        # what "correctly benched" actually looks like.
        bench_tags = {}
        for name, _pts in bench:
            if name in proc_started:
                bench_tags[name] = "process"
            elif name in started:
                bench_tags[name] = "variance"
            else:
                bench_tags[name] = "ok"
        out[f"gw{gw}"] = {"you": you, "process": process, "hindsight": hindsight, "your_bench": bench, "better_bench": better[:4], "bench_tags": bench_tags}
    return out

def build_chip_net(chips_used, caps, bench_audit):
    """Auto-compute each played chip's net points vs not using it, from data
    already gathered for captain_audit/bench_audit — no per-chip hand-typed
    numbers to keep updating. Wildcard has no well-defined "net vs no chip"
    (it changes your whole squad), so it's intentionally left out."""
    out = {}
    bboost_gw = chips_used.get("bboost")
    if bboost_gw:
        bench = (bench_audit.get(f"gw{bboost_gw}") or {}).get("your_bench") or []
        out["bboost"] = {
            "net": sum(pts for _name, pts in bench),
            "note": " + ".join(f"{name} {pts}" for name, pts in bench) or None,
        }
    xc_gw = chips_used.get("3xc")
    if xc_gw:
        row = next((c for c in caps if c.get("gw") == xc_gw), None)
        if row:
            extra = row.get("captain_raw") or 0  # 3xc's only gain over a normal (C) is the 3rd multiple
            out["3xc"] = {
                "net": extra,
                "note": f"{row.get('captain')} {extra} raw. Triple gave {extra * 3} instead of {extra * 2}.",
            }
    return out


def build_fh_audit(boot, team_id, chips_used):
    """Auto-compute the Free Hit process/outcome audit: the FH XI that was
    actually played vs. the best process-based XI from the squad you'd have
    had if you'd rolled instead (FPL guarantees the squad reverts exactly, so
    the prior gameweek's picks are that "original" squad — see
    score_original_squad for why it's re-optimized rather than replayed
    as-started). Replaces the one-off hand-written fh.js, which only ever
    covers whichever GW someone last wrote it for."""
    fh_gw = chips_used.get("freehit")
    if not fh_gw:
        return None
    elements = {e["id"]: e for e in boot["elements"]}
    try:
        fh_pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{fh_gw}/picks/")
        live = get(f"https://fantasy.premierleague.com/api/event/{fh_gw}/live/")
    except Exception as e:
        _warn(f"build_fh_audit: could not load GW{fh_gw} FH picks/live: {e}")
        return None
    orig_gw = fh_gw - 1
    orig_pk = {}
    if orig_gw >= 1:
        try:
            orig_pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{orig_gw}/picks/")
        except Exception as e:
            _warn(f"build_fh_audit: could not load GW{orig_gw} original picks: {e}")
    if not orig_pk.get("picks"):
        return None
    pts = {el["id"]: el["stats"]["total_points"] for el in live.get("elements", [])}
    mins = {el["id"]: el["stats"]["minutes"] for el in live.get("elements", [])}

    def score_fh_squad(pk):
        """The FH squad's own multiplier/position fields already reflect what
        actually happened in fh_gw (FPL's picks API applies real autosubs and
        captain/VC fallback to the returned multiplier) — safe to trust as-is."""
        total, xi = 0, []
        for p in pk.get("picks") or []:
            el = elements.get(p["element"])
            if not el:
                continue
            mult = p.get("multiplier") or 0
            if not mult:
                continue  # bench, or subbed out
            raw = pts.get(p["element"], 0)
            total += raw * mult
            item = {"name": el["web_name"], "pos": POS[el["element_type"]], "got": raw * mult}
            if mult != 1:
                item["mult"] = mult
            if p.get("is_captain"):
                item["captain"] = True
            xi.append(item)
        return total, xi

    def score_original_squad(pk):
        """Best process-based XI from the full 15-man squad you'd have carried
        into fh_gw, scored against fh_gw's results — reusing _process_xi (same
        "best legal XI by minutes played, captain pinned" rule the bench audit
        uses) rather than just replaying whatever was literally started/benched
        in orig_gw, since that start/bench split was made for a different
        gameweek's team news and isn't the comparison worth making here."""
        squad = []
        for p in pk.get("picks") or []:
            el = elements.get(p["element"])
            if not el:
                continue
            squad.append({
                "name": el["web_name"],
                "pos": POS[el["element_type"]],
                "pts": pts.get(p["element"], 0),
                "mins": mins.get(p["element"], 0),
                "started": (p.get("position") or 99) <= 11,
                "captain": bool(p.get("is_captain")),
            })
        xi = _process_xi(squad)
        cap_name = next((p["name"] for p in squad if p["captain"]), None)
        total, out_xi = 0, []
        for p in xi:
            mult = 2 if p["name"] == cap_name else 1
            total += p["pts"] * mult
            item = {"name": p["name"], "pos": p["pos"], "got": p["pts"] * mult}
            if mult != 1:
                item["mult"] = mult
            if p["name"] == cap_name:
                item["captain"] = True
            out_xi.append(item)
        return total, out_xi, cap_name

    fh_points, fh_xi = score_fh_squad(fh_pk)
    fh_cap_pick = next((p for p in (fh_pk.get("picks") or []) if p.get("is_captain")), None)
    fh_cap = elements.get((fh_cap_pick or {}).get("element"), {}).get("web_name")
    orig_points, orig_xi, orig_cap = score_original_squad(orig_pk)
    net = fh_points - orig_points
    return {
        "gw": fh_gw,
        "fh_points": fh_points,
        "original_points": orig_points,
        "net": net,
        "process": "ok",  # a played Free Hit is always a legal, deliberate reset — not a process error by definition
        "outcome": "won" if net > 0 else ("lost" if net < 0 else "even"),
        "original_cap": orig_cap,
        "fh_cap": fh_cap,
        "original_xi": orig_xi,
        "fh_xi": fh_xi,
        "why": f"FH scored {fh_points} vs {orig_points} for the reverted squad's best process XI — net {'+' if net >= 0 else ''}{net}.",
    }


def build_transfers(boot, team_id):
    names = {e["id"]: e["web_name"] for e in boot["elements"]}
    try:
        rows = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/transfers/")
    except Exception as e:
        _warn(f"build_transfers: could not load transfers list: {e}")
        return []
    live_cache, out = {}, []
    for t in rows:
        gw = t.get("event")
        if gw not in live_cache:
            try:
                live_cache[gw] = {el["id"]: el["stats"]["total_points"] for el in get(f"https://fantasy.premierleague.com/api/event/{gw}/live/").get("elements", [])}
            except Exception as e:
                _warn(f"build_transfers: could not load GW{gw} live data: {e}")
                live_cache[gw] = {}
        inn, outp = names.get(t["element_in"], "?"), names.get(t["element_out"], "?")
        pin, pout = live_cache[gw].get(t["element_in"], 0), live_cache[gw].get(t["element_out"], 0)
        net = pin - pout
        verdict = "Good that GW" if net > 1 else ("Lost that GW" if net < -1 else "Even that GW")
        out.append({"gw": gw, "out": outp, "inn": inn, "net": ("+" if net > 0 else "") + str(net), "verdict": verdict})
    out.sort(key=lambda x: x["gw"] or 0)
    return out

CHIP_LABEL = {"wildcard": "Wildcard", "freehit": "Free Hit", "bboost": "Bench Boost", "3xc": "Triple Captain"}

def build_strategy(boot, team_id, hist, gameweeks, transfers, picks_gw, horizon=8):
    """Chip-timing and free-transfer strategy signals for the Strategy tab:
    - chips remaining: each of the 4 chips is usable TWICE a season (once in
      each half) since FPL's 2023-24+ rules — boot['chips'] gives the exact
      GW window for each half, which beats hardcoding a cutoff GW that moves
      year to year.
    - a fixture-swing scan across the next `horizon` gameweeks for your
      CURRENT squad's clubs, flagging blank/double gameweeks and the
      easiest/hardest upcoming run — the standard real-world signal for when
      to wildcard, free hit, bench boost, or triple captain.
    - whether hits taken this season have actually paid for themselves, using
      the same per-transfer net figures already shown on the Transfers tab.
    """
    teams = {t["id"]: t for t in boot["teams"]}
    elements = {e["id"]: e for e in boot["elements"]}
    chip_history = hist.get("chips", [])  # every use this season (a list, unlike the "latest per name" dict used elsewhere)

    # boot['chips']'s own "number" field is always 1 on every entry (confirmed live —
    # it's not a per-half indicator), so derive window order from start_event instead:
    # each chip type's two entries sort into "window 1" (earlier half) and "window 2".
    windows_by_chip = {}
    for c in (boot.get("chips") or []):
        name = c.get("name")
        if not name:
            continue
        windows_by_chip.setdefault(name, []).append({"start": c.get("start_event"), "stop": c.get("stop_event")})
    for ws in windows_by_chip.values():
        ws.sort(key=lambda w: w["start"] or 0)
        for i, w in enumerate(ws, start=1):
            w["number"] = i

    current_gw = max((e["id"] for e in boot["events"] if e.get("finished")), default=1)
    chip_status = []
    for name, windows in windows_by_chip.items():
        entry = {"chip": name, "label": CHIP_LABEL.get(name, name), "windows": []}
        for w in windows:
            used = next((u for u in chip_history if u.get("name") == name and w["start"] <= (u.get("event") or 0) <= w["stop"]), None)
            if used:
                status = "used"
            elif current_gw + 1 < w["start"]:
                status = "upcoming"
            elif current_gw >= w["stop"]:
                status = "expired"
            else:
                status = "open"
            entry["windows"].append({"number": w["number"], "start": w["start"], "stop": w["stop"], "used_gw": (used or {}).get("event"), "status": status})
        chip_status.append(entry)
    chip_status.sort(key=lambda e: e["chip"])

    tr_by_gw = {}
    for t in transfers or []:
        tr_by_gw.setdefault(t.get("gw"), []).append(t)
    hit_rows, total_hit_cost, total_moves_net = [], 0, 0
    for g in gameweeks or []:
        cost = g.get("hits") or 0
        if not cost:
            continue
        moves = [t for t in tr_by_gw.get(g["gw"], []) if t.get("inn") != "ROLL"]
        gw_net = sum(int(str(t.get("net", "0")).replace("+", "")) for t in moves)
        total_hit_cost += cost
        total_moves_net += gw_net
        hit_rows.append({"gw": g["gw"], "cost": cost, "moves_net": gw_net, "paid_off": gw_net > cost})
    hits_summary = {"total_cost": total_hit_cost, "total_moves_net": total_moves_net, "net_after_cost": total_moves_net - total_hit_cost, "rows": hit_rows}

    squad_clubs = []
    if picks_gw:
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
            squad_clubs = sorted({elements[p["element"]]["team"] for p in pk.get("picks", []) if p.get("element") in elements})
        except Exception as e:
            _warn(f"build_strategy: could not load GW{picks_gw} squad for fixture scan: {e}")

    upcoming_events = sorted((e for e in boot["events"] if not e.get("finished")), key=lambda e: e["id"])[:horizon]
    fixture_rows = []
    for ev in upcoming_events:
        try:
            fx = fixture_scan(ev["id"], teams)
        except Exception as e:
            _warn(f"build_strategy: could not load GW{ev['id']} fixtures: {e}")
            continue
        fdrs, blanks, doubles = [], [], []
        for cid in squad_clubs:
            fixtures = fx.get(cid) or []
            club = teams[cid]["short_name"]
            if not fixtures:
                blanks.append(club)
            else:
                if len(fixtures) > 1:
                    doubles.append(club)
                fdrs.extend(f["fdr"] for f in fixtures if f.get("fdr") is not None)
        avg_fdr = round(sum(fdrs) / len(fdrs), 2) if fdrs else None
        fixture_rows.append({"gw": ev["id"], "avg_fdr": avg_fdr, "blanks": blanks, "doubles": doubles})

    rated = [r for r in fixture_rows if r["avg_fdr"] is not None]
    easiest = min(rated, key=lambda r: r["avg_fdr"], default=None)
    hardest = max(rated, key=lambda r: r["avg_fdr"], default=None)
    first_blank = next((r for r in fixture_rows if r["blanks"]), None)
    first_double = next((r for r in fixture_rows if r["doubles"]), None)

    return {
        "chips": chip_status,
        "free_transfers": free_transfers_for_next(hist or {}),
        "hits": hits_summary,
        "fixtures": {"horizon": horizon, "rows": fixture_rows, "easiest": easiest, "hardest": hardest, "first_blank": first_blank, "first_double": first_double},
    }

def build_xg_signal(boot, team_id, picks_gw, min_minutes=180, threshold=2.0):
    """Flag your own squad's players as over/underperforming their underlying
    numbers — a concrete "due for a dry patch" (sell-high) or "still getting
    the chances, patience/buy-low" signal, using FPL's own expected-goals
    data (already in bootstrap-static, no new scraping needed) instead of a
    gut read on "good form". Defenders/keepers also get a goals-conceded vs
    expected-goals-conceded check, since clean-sheet luck is the bigger swing
    for that position than attacking returns."""
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}
    if not picks_gw:
        return None
    try:
        pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
    except Exception as e:
        _warn(f"build_xg_signal: could not load GW{picks_gw} squad: {e}")
        return None

    def to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    rows = []
    for p in pk.get("picks") or []:
        el = elements.get(p["element"])
        if not el:
            continue
        mins = int(el.get("minutes") or 0)
        if mins < min_minutes:
            continue  # too small a sample for xG/xA to mean anything
        pos = POS[el["element_type"]]
        goals, assists = int(el.get("goals_scored") or 0), int(el.get("assists") or 0)
        xg, xa = to_float(el.get("expected_goals")) or 0.0, to_float(el.get("expected_assists")) or 0.0
        xgi = to_float(el.get("expected_goal_involvements"))
        if xgi is None:
            xgi = xg + xa
        gi = goals + assists
        diff = round(gi - xgi, 2)
        tag = "overperforming" if diff >= threshold else ("underperforming" if diff <= -threshold else "on_track")
        row = {
            "name": el["web_name"], "pos": pos, "club": teams[el["team"]]["short_name"], "minutes": mins,
            "goals": goals, "assists": assists, "xg": round(xg, 2), "xa": round(xa, 2),
            "xgi": round(xgi, 2), "gi": gi, "diff": diff, "tag": tag,
        }
        if pos in ("DEF", "GKP"):
            xgc = to_float(el.get("expected_goals_conceded"))
            if xgc is not None:
                gc = int(el.get("goals_conceded") or 0)
                gc_diff = round(xgc - gc, 2)  # positive = conceding FEWER than expected (riding luck)
                row.update({"goals_conceded": gc, "xgc": round(xgc, 2), "gc_diff": gc_diff,
                            "gc_tag": "riding_luck" if gc_diff >= threshold else ("unlucky" if gc_diff <= -threshold else "on_track")})
        rows.append(row)
    rows.sort(key=lambda r: -abs(r["diff"]))
    notable = [r for r in rows if r["tag"] != "on_track" or r.get("gc_tag") not in (None, "on_track")]
    return {"threshold": threshold, "min_minutes": min_minutes, "rows": rows, "notable": notable}

def build_form_fdr(boot, next_fixture_map, min_minutes=90, top_n=10):
    """Every qualifying player's recent form (FPL's own rolling average
    points over their last 30 days) against how hard their very next
    fixture is — one number that separates "in form AND an easy game" from
    "in form but walking into a tough one", instead of reading the two
    signals apart. League-wide (like build_value_board), not squad-scoped,
    so it doubles as a scouting list rather than just auditing your own 15.
    Blank-gameweek players (no next_fixture_map entry) get no ratio, since
    dividing by a missing fixture isn't meaningful."""
    teams = {t["id"]: t for t in boot["teams"]}
    rows = []
    for el in boot["elements"]:
        mins = int(el.get("minutes") or 0)
        if mins < min_minutes:
            continue  # too little game time for "form" to mean anything yet
        try:
            form = float(el.get("form") or 0)
        except (TypeError, ValueError):
            form = 0.0
        info = next_fixture_map.get(el["team"]) if next_fixture_map else None
        fdr = info["fdr"] if info else None
        fixture = f"{info['opp']} ({info['side']})" if info else "Blank"
        ratio = round(form / fdr, 2) if fdr else None
        rows.append({
            "name": el["web_name"], "pos": POS[el["element_type"]], "club": teams[el["team"]]["short_name"],
            "cost": el["now_cost"] / 10, "owned_pct": float(el.get("selected_by_percent") or 0),
            "form": form, "fdr": fdr, "fixture": fixture, "ratio": ratio,
        })
    rows.sort(key=lambda r: (r["ratio"] is None, -(r["ratio"] or 0)))
    by_pos = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for r in rows:
        if len(by_pos[r["pos"]]) < top_n:
            by_pos[r["pos"]].append(r)
    return {"min_minutes": min_minutes, "top_n": top_n, "by_pos": by_pos}


DEFCON_THRESHOLD = {"DEF": 10, "MID": 12, "FWD": 12}

def build_defcon(boot, team_id, picks_gw, min_minutes=180):
    """FPL's 2025-26+ Defensive Contribution rule awards 2 pts in any match
    where a player's combined defensive actions clear a position threshold:
    10 (clearances+blocks+interceptions+tackles) for defenders, 12 (the same
    four plus ball recoveries) for midfielders/forwards. bootstrap-static's
    own defensive_contribution_per_90 field is already computed with the
    correct position-specific combination (confirmed against FPL's own field
    docs), so this reuses it directly instead of re-deriving it from the raw
    per-stat counts and risking a wrong recombination. Goalkeepers don't have
    a defensive contribution rule and are skipped."""
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}
    if not picks_gw:
        return None
    try:
        pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
    except Exception as e:
        _warn(f"build_defcon: could not load GW{picks_gw} squad: {e}")
        return None

    def to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    rows = []
    for p in pk.get("picks") or []:
        el = elements.get(p["element"])
        if not el:
            continue
        pos = POS[el["element_type"]]
        if pos == "GKP":
            continue
        mins = int(el.get("minutes") or 0)
        per90 = to_float(el.get("defensive_contribution_per_90"))
        if mins < min_minutes or per90 is None:
            continue
        threshold = DEFCON_THRESHOLD[pos]
        margin = round(per90 - threshold, 2)
        tag = "reliable" if per90 >= threshold else ("borderline" if per90 >= threshold * 0.75 else "unlikely")
        rows.append({
            "name": el["web_name"], "pos": pos, "club": teams[el["team"]]["short_name"], "minutes": mins,
            "threshold": threshold, "per90": round(per90, 2), "season_total": to_float(el.get("defensive_contribution")),
            "margin": margin, "tag": tag,
        })
    rows.sort(key=lambda r: -r["margin"])
    return {"min_minutes": min_minutes, "rows": rows}

def build_rotation_risk(boot, team_id, picks_gw, lookback=3, start_mins=60):
    """Minutes trend over the last few finished GWs for each squad player —
    catches a player sliding out of the XI while it's still happening,
    instead of only after the fact via a bench-audit miss the week it costs
    you points. Uses real-world minutes from each GW's live feed,
    independent of who owned the player in FPL that week.

    Cross-referenced against FPL's own injury/suspension status
    (player_availability) so a falling/declining trend is labelled either
    "injury" (status explains the drop) or "rested" (fit per FPL, dropped by
    the manager's own choice — the one that's easy to miss) — and a player
    who's still nailed on by minutes but freshly flagged gets caught too."""
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}
    if not picks_gw:
        return None
    finished = sorted(e["id"] for e in boot.get("events") or [] if e.get("finished"))
    recent_gws = finished[-lookback:]
    if len(recent_gws) < 2:
        return None  # too early in the season for a trend to mean anything
    try:
        pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
    except Exception as e:
        _warn(f"build_rotation_risk: could not load GW{picks_gw} squad: {e}")
        return None

    minutes_by_gw = {}
    for gw in recent_gws:
        try:
            minutes_by_gw[gw] = {el["id"]: int(el["stats"].get("minutes") or 0) for el in get(f"https://fantasy.premierleague.com/api/event/{gw}/live/").get("elements", [])}
        except Exception as e:
            _warn(f"build_rotation_risk: could not load GW{gw} live data: {e}")
            minutes_by_gw[gw] = {}

    rows = []
    for p in pk.get("picks") or []:
        el = elements.get(p["element"])
        if not el:
            continue
        mins = [minutes_by_gw[gw].get(el["id"], 0) for gw in recent_gws]
        first, last = mins[0], mins[-1]
        earlier_avg = sum(mins[:-1]) / len(mins[:-1])
        if last < start_mins and earlier_avg >= start_mins:
            tag, note = "falling", "was starting, now fringe/bench minutes"
        elif last >= start_mins and first < start_mins:
            tag, note = "rising", "breaking into the side"
        elif all(m >= start_mins for m in mins):
            tag = "declining" if (first - last) >= 20 and mins == sorted(mins, reverse=True) else "starter"
            note = "starts getting shorter each week" if tag == "declining" else "nailed on across the window"
        elif all(m < 20 for m in mins):
            tag, note = "fringe", "fringe involvement across the window"
        else:
            tag, note = "mixed", "minutes bouncing around, no clear trend"
        avail = player_availability(el)
        reason = None
        if tag in ("falling", "declining"):
            reason = "injury" if avail["kind"] in ("out", "doubt") else "rested"
        elif avail["kind"] in ("out", "doubt"):
            reason = "injury"  # still nailed by recent minutes, but freshly flagged
        rows.append({
            "name": el["web_name"], "pos": POS[el["element_type"]], "club": teams[el["team"]]["short_name"],
            "minutes": mins, "trend": tag, "note": note,
            "avail_kind": avail["kind"], "avail_label": avail["label"], "news": avail["news"], "reason": reason,
        })
    def sort_key(r):
        pri = 0 if r["reason"] is not None else (1 if r["trend"] == "rising" else 2)
        return (pri, r["minutes"][-1] - r["minutes"][0])
    rows.sort(key=sort_key)
    notable = [r for r in rows if r["reason"] is not None or r["trend"] == "rising"]
    return {"gws": recent_gws, "start_mins": start_mins, "rows": rows, "notable": notable}

def build_value_board(boot, min_minutes=180, top_n=10):
    """Best points-per-money across the WHOLE player pool, split by position
    (comparing a £4m defender against a £15m forward on raw value isn't a
    fair scouting comparison) — league-wide, not scoped to your squad or
    ownership, since this is a "who's efficient right now" reference, not a
    transfer-target list. Recomputed from current total_points/now_cost on
    every refresh, so it moves with real returns and price changes rather
    than being a one-time snapshot — a player's price rise or a big haul
    shows up here on the next run, same as everywhere else in this app.
    min_minutes filters out small-sample flukes (e.g. a nailed-on cheap
    player who returned big off a single start)."""
    elements = boot["elements"]
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    by_pos = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for el in elements:
        mins = int(el.get("minutes") or 0)
        cost = el["now_cost"] / 10
        if mins < min_minutes or cost <= 0:
            continue
        pts = int(el.get("total_points") or 0)
        row = {
            "name": el["web_name"], "club": teams.get(el["team"], "?"), "cost": cost,
            "points": pts, "minutes": mins, "owned_pct": float(el.get("selected_by_percent") or 0),
            "value_per_1m": round(pts / cost, 2),
        }
        by_pos[POS[el["element_type"]]].append(row)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda r: -r["value_per_1m"])
        by_pos[pos] = by_pos[pos][:top_n]
    return {"min_minutes": min_minutes, "top_n": top_n, "by_pos": by_pos}

def build_price_radar(boot, team_id, picks_gw, top_n=8):
    """Approximate price-change momentum from FPL's own transfer-volume
    fields: transfers_in_event/transfers_out_event (net transfers so far
    today) and cost_change_event/cost_change_start (price change already
    applied today / this season). FPL has never published its exact
    price-change algorithm, so "momentum" here — net transfers today as a
    % of the player's own current owner base (selected_by_percent% of
    total_players) — is a relative signal (a swing on a low-ownership
    player moves the needle far more than the same raw swing on a template
    player), not a guaranteed prediction of tonight's change."""
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}
    total_players = boot.get("total_players") or 0

    def row_of(el):
        inn, out = int(el.get("transfers_in_event") or 0), int(el.get("transfers_out_event") or 0)
        net = inn - out
        owned = float(el.get("selected_by_percent") or 0)
        owners = owned / 100 * total_players
        momentum = round(net / owners * 100, 1) if owners >= 1 else 0.0  # % of the player's own current owners, not a raw count
        season_change = (el.get("cost_change_start") or 0) / 10
        # FPL only ever moves a price by exactly £0.1m in a single change, so
        # "expected" is a direction call off today's momentum sign, not a
        # probability — the size of the move (if one happens) is fixed by
        # the rule itself, not something this needs to estimate.
        expected_change = 0.1 if net > 0 else (-0.1 if net < 0 else 0.0)
        return {
            "name": el["web_name"], "pos": POS[el["element_type"]], "club": teams[el["team"]]["short_name"],
            "cost": el["now_cost"] / 10, "owned_pct": owned, "net_transfers_today": net, "momentum": momentum,
            "changed_today": (el.get("cost_change_event") or 0) != 0,
            "cost_change_today": (el.get("cost_change_event") or 0) / 10,
            "season_change": season_change,
            "expected_change": expected_change,
            "expected_season_change": round(season_change + expected_change, 1),
        }

    squad_ids = set()
    if picks_gw:
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
            squad_ids = {p["element"] for p in pk.get("picks") or [] if p.get("element") in elements}
        except Exception as e:
            _warn(f"build_price_radar: could not load GW{picks_gw} squad: {e}")

    squad_rows = sorted((row_of(elements[eid]) for eid in squad_ids), key=lambda r: -abs(r["momentum"]))
    all_rows = [row_of(el) for el in elements.values()]
    rising = sorted((r for r in all_rows if r["net_transfers_today"] > 0), key=lambda r: -r["momentum"])[:top_n]
    falling = sorted((r for r in all_rows if r["net_transfers_today"] < 0), key=lambda r: r["momentum"])[:top_n]
    return {"squad": squad_rows, "rising": rising, "falling": falling}

def build_transfer_targets(boot, team_id, picks_gw, top_n=8, min_minutes=180):
    """Scouting lists for the Plan tab: players you DON'T currently own with
    strong underlying attacking numbers (xG+xA per 90) or a reliable
    Defensive Contribution rate — the same underlying-stats signals already
    used to audit your own squad (build_xg_signal / build_defcon), applied
    league-wide and filtered to non-owned players, as concrete transfer
    targets rather than just a read on your existing 15."""
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}

    def to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    squad_ids = set()
    if picks_gw:
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
            squad_ids = {p["element"] for p in pk.get("picks") or [] if p.get("element") in elements}
        except Exception as e:
            _warn(f"build_transfer_targets: could not load GW{picks_gw} squad: {e}")

    xg_rows, defcon_rows = [], []
    for el in elements.values():
        if el["id"] in squad_ids:
            continue
        mins = int(el.get("minutes") or 0)
        if mins < min_minutes:
            continue
        pos = POS[el["element_type"]]
        club = teams[el["team"]]["short_name"]
        cost, owned = el["now_cost"] / 10, float(el.get("selected_by_percent") or 0)
        p90 = mins / 90

        if pos != "GKP":
            xgi = to_float(el.get("expected_goal_involvements"))
            if xgi is None:
                xgi = (to_float(el.get("expected_goals")) or 0.0) + (to_float(el.get("expected_assists")) or 0.0)
            xg_rows.append({
                "name": el["web_name"], "pos": pos, "club": club, "cost": cost, "owned_pct": owned,
                "goals": int(el.get("goals_scored") or 0), "assists": int(el.get("assists") or 0),
                "xgi": round(xgi, 2), "xgi_p90": round(xgi / p90, 2) if p90 else 0.0,
            })

        if pos in DEFCON_THRESHOLD:
            per90 = to_float(el.get("defensive_contribution_per_90"))
            threshold = DEFCON_THRESHOLD[pos]
            if per90 is not None and per90 >= threshold:
                defcon_rows.append({
                    "name": el["web_name"], "pos": pos, "club": club, "cost": cost, "owned_pct": owned,
                    "per90": round(per90, 2), "threshold": threshold, "margin": round(per90 - threshold, 2),
                })

    xg_rows.sort(key=lambda r: -r["xgi_p90"])
    defcon_rows.sort(key=lambda r: -r["margin"])
    return {"min_minutes": min_minutes, "xg": xg_rows[:top_n], "defcon": defcon_rows[:top_n]}

def target_rival_entries(rows, team_id, limit_top=2, spread=1):
    """Entry ids for the small, bounded set of rivals the Leagues tab actually
    compares against: the top of the table (limit_top) and whoever's within
    `spread` ranks of you either side — a superset of whatever build_tactics()
    ends up calling "first"/"second"/"neighbor_above"/"neighbor_below", so it
    doesn't need to duplicate that exact tie-break logic here."""
    sorted_rows = sorted(rows, key=lambda r: (r.get("rank") is None, r.get("rank") or 10**9))
    me_idx = next((i for i, r in enumerate(sorted_rows) if r.get("entry") == team_id), None)
    picked = list(sorted_rows[:limit_top])
    if me_idx is not None:
        lo, hi = max(0, me_idx - spread), min(len(sorted_rows), me_idx + spread + 1)
        picked.extend(sorted_rows[lo:hi])
    seen, out = set(), []
    for r in picked:
        eid = r.get("entry")
        if eid is None or eid == team_id or eid in seen:
            continue
        seen.add(eid)
        out.append(eid)
    return out


def rival_context(entries, last_fin_gw, my_last_gw_pts, member_squads_by_entry, elements, next_fixture_map):
    """Small, targeted extra fetches (season history only, no per-GW picks) for a
    bounded set of rivals: chips used this season, how much ground moved last GW,
    and — once picks are public — their squad's average fixture difficulty for
    the next GW. Only for the handful of rows the Leagues tab's comparisons
    actually use, not the whole league."""
    ctx = {}
    for eid in entries:
        try:
            h = get(f"https://fantasy.premierleague.com/api/entry/{eid}/history/")
        except Exception as e:
            _warn(f"rival_context: could not load history for entry {eid}: {e}")
            continue
        chips = {c["name"]: c["event"] for c in h.get("chips", [])}
        gap_trend = None
        if my_last_gw_pts is not None and last_fin_gw is not None:
            row = next((r for r in h.get("current", []) if r.get("event") == last_fin_gw), None)
            if row and row.get("points") is not None:
                gap_trend = my_last_gw_pts - row["points"]
        fixture = None
        squad = member_squads_by_entry.get(eid)
        if squad and next_fixture_map:
            fdrs = []
            for p in squad.get("xi", []):
                el = elements.get(p.get("id"))
                info = next_fixture_map.get(el["team"]) if el else None
                if info and info.get("fdr") is not None:
                    fdrs.append(info["fdr"])
            if fdrs:
                avg = sum(fdrs) / len(fdrs)
                fixture = {"avg_fdr": round(avg, 1), "label": "Tough" if avg >= 3.6 else ("Easy" if avg <= 2.4 else "Mixed")}
        ctx[eid] = {"chips": chips, "gap_trend": gap_trend, "fixture": fixture}
    return ctx


def analyze_leagues(boot, entry, team_id, picks_gw, deadline_passed=False, my_last_gw_pts=None, last_fin_gw=None, next_fixture_map=None):
    teams = {t["id"]: t for t in boot["teams"]}
    elements = {e["id"]: e for e in boot["elements"]}
    classic = entry.get("leagues", {}).get("classic") or []
    tracked_ids = TRACKED_BY_TEAM.get(team_id, TRACKED_LEAGUES)
    my_picks = set()
    my_squad = None
    try:
        my_pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
        my_picks = {p["element"] for p in my_pk.get("picks") or []}
        if deadline_passed and my_pk.get("picks"):
            my_squad = format_pick_squad(my_pk.get("picks"), elements, teams)
            my_squad["chip"] = my_pk.get("active_chip")
    except Exception as e:
        _warn(f"analyze_leagues: could not load own GW{picks_gw} picks: {e}")
    leagues = []
    tracked = [x for x in classic if x.get("id") in tracked_ids]
    tracked.sort(key=lambda x: 0 if x.get("id") == 125784 else 1)
    for L in tracked:
        try:
            rows = (get(f"https://fantasy.premierleague.com/api/leagues-classic/{L['id']}/standings/?page_standings=1").get("standings") or {}).get("results") or []
        except Exception as e:
            _warn(f"analyze_leagues: could not load standings for league {L['id']}: {e}")
            continue
        table = [{"rank": r.get("rank"), "team": r.get("entry_name"), "pts": r.get("total"), "me": r.get("entry") == team_id, "entry": r.get("entry")} for r in rows[:15]]
        counts, n, owned_by, cap_by = {}, 0, {}, {}
        member_squads = []
        picks_available = 0
        if len(rows) >= 2:
            for r in rows:
                try:
                    pk = get(f"https://fantasy.premierleague.com/api/entry/{r['entry']}/event/{picks_gw}/picks/")
                except Exception as e:
                    _warn(f"analyze_leagues: could not load picks for entry {r.get('entry')}: {e}")
                    continue
                picks = pk.get("picks") or []
                if not picks:
                    continue
                picks_available += 1
                n += 1
                eid = r.get("entry")
                owned = set()
                for p in picks:
                    pid = p["element"]
                    counts[pid] = counts.get(pid, 0) + 1
                    owned.add(pid)
                    if p.get("is_captain"):
                        cap_by[pid] = cap_by.get(pid, 0) + 1
                if eid is not None:
                    owned_by[eid] = owned
                if deadline_passed:
                    squad = format_pick_squad(picks, elements, teams)
                    squad.update({
                        "entry": eid,
                        "team": r.get("entry_name"),
                        "manager": r.get("player_name"),
                        "rank": r.get("rank"),
                        "pts": r.get("total"),
                        "me": eid == team_id,
                        "chip": pk.get("active_chip"),
                    })
                    member_squads.append(squad)
        # Adaptive, not a flat 40%/25%: in a 6-team league 40% is ~2 people, barely
        # a signal. Same scaling build_tactics() already uses for its own template.
        tmpl_thresh = max(3, (n + 1) // 2) if n else None
        diff_thresh = max(1, n // 4) if n else None
        template, diffs = [], []
        if n:
            for pid, c in sorted(counts.items(), key=lambda x: -x[1]):
                el = elements.get(pid)
                if not el: continue
                pct = round(100 * c / n)
                item = {"name": el["web_name"], "club": teams[el["team"]]["short_name"], "own": pct, "count": c, "n": n}
                if c >= tmpl_thresh and pid not in my_picks: template.append(item)
                if pid in my_picks and c <= diff_thresh: diffs.append(item)
        member_squads_by_entry = {s["entry"]: s for s in member_squads}
        target_entries = target_rival_entries(rows, team_id)
        rival_ctx = rival_context(target_entries, last_fin_gw, my_last_gw_pts, member_squads_by_entry, elements, next_fixture_map) if target_entries else {}
        tactics = build_tactics(rows, team_id, L, n, counts, owned_by, cap_by, my_picks, elements, teams, rival_ctx=rival_ctx)
        league_obj = {
            "id": L["id"],
            "name": L.get("name"),
            "rank": L.get("entry_rank"),
            "last_rank": L.get("entry_last_rank"),
            "size": len(rows),
            "table": table,
            "template": template[:8],
            "diffs": diffs[:8],
            "tactics": tactics,
            "picks_gw": picks_gw,
            "deadline_passed": bool(deadline_passed),
            "picks_unlocked": bool(deadline_passed and picks_available > 0),
        }
        if deadline_passed:
            # Prefer rank order for display
            member_squads.sort(key=lambda s: (s.get("rank") is None, s.get("rank") or 999))
            league_obj["member_squads"] = member_squads
            if picks_available == 0:
                league_obj["picks_note"] = "Picks unlock after deadline (API empty)."
        else:
            league_obj["picks_note"] = "Picks unlock after deadline."
        leagues.append(league_obj)
    overall_template, overall_diffs = [], []
    for el in boot["elements"]:
        sel = float(el.get("selected_by_percent") or 0)
        item = {"name": el["web_name"], "club": teams[el["team"]]["short_name"], "own": sel}
        if my_picks:
            if sel >= 25 and el["id"] not in my_picks: overall_template.append(item)
            if el["id"] in my_picks and sel <= 12: overall_diffs.append(item)
    overall_template.sort(key=lambda x: -x["own"])
    overall_diffs.sort(key=lambda x: x["own"])
    overall = next((L for L in classic if L.get("id") == 314), None)
    public = [{"id": 314, "name": "Overall", "rank": overall.get("entry_rank"), "last_rank": overall.get("entry_last_rank")}] if overall else []
    out = {
        "mini": leagues,
        "public": public,
        "overall_template": overall_template[:8],
        "overall_diffs": overall_diffs[:8],
        "picks_gw": picks_gw,
        "deadline_passed": bool(deadline_passed),
        "picks_unlocked": bool(deadline_passed),
    }
    if my_squad and deadline_passed:
        out["my_squad"] = {**my_squad, "entry": team_id, "me": True, "picks_gw": picks_gw}
    return out


def main(team_id=TEAM_ID, out_path=None):
    data_file = Path(out_path) if out_path else ROOT / "data.js"
    existing = {}
    if data_file.exists():
        raw = data_file.read_text(); s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            try:
                existing = json.loads(raw[s:e+1])
            except Exception:
                existing = {}
    boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
    entry = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/")
    hist = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/history/")
    avg = {e["id"]: e.get("average_entry_score") for e in boot["events"]}
    field_avg = dict(existing.get("field_avg_known") or {})
    chips_used = {c["name"]: c["event"] for c in hist.get("chips", [])}
    gws = []
    for row in hist.get("current", []):
        gw = row["event"]; fa = field_avg.get(gw) or avg.get(gw)
        if fa: field_avg[gw] = fa
        gws.append({"gw": gw, "points": row["points"], "bench": row["points_on_bench"], "transfers": row["event_transfers"], "hits": row["event_transfers_cost"], "rank": row["overall_rank"], "field_avg": fa, "delta": (row["points"] - fa) if fa else None, "chip": next((n for n, ev in chips_used.items() if ev == gw), None)})
    plan = build_plan(boot, team_id, hist, chips_used)
    ds = deadline_state(boot)
    last_fin = max((e["id"] for e in boot["events"] if e.get("finished")), default=1)
    # After deadline: league picks for the locked GW. Before: ownership from provisional/latest squad GW.
    league_picks_gw = ds["locked_gw"] if ds["deadline_passed"] and ds["locked_gw"] else (plan.get("squad_from_gw") or last_fin)
    my_last_gw_pts = next((r["points"] for r in hist.get("current", []) if r.get("event") == last_fin), None)
    teams_by_id = {t["id"]: t for t in boot["teams"]}
    next_fixture_map = fixture_map(ds["next_gw"], teams_by_id) if ds["next_gw"] else None
    leagues = analyze_leagues(boot, entry, team_id, league_picks_gw, deadline_passed=bool(ds["deadline_passed"]),
                               my_last_gw_pts=my_last_gw_pts, last_fin_gw=last_fin, next_fixture_map=next_fixture_map)
    caps = captain_audit(boot, team_id)
    data = existing or {}
    # Recomputed every run rather than cached off `existing`: both only cover finished
    # GWs (whose points never change), so recomputing is cheap and safe, whereas a
    # "skip if already present" cache would silently freeze once a new GW finishes.
    data["transfers"] = add_roll_rows(build_transfers(boot, team_id), hist, chips_used)
    data["bench_audit"] = build_bench_audit(boot, team_id)
    data["chip_net"] = build_chip_net(chips_used, caps, data["bench_audit"])
    data["fh_audit"] = build_fh_audit(boot, team_id, chips_used)
    data["strategy"] = build_strategy(boot, team_id, hist, gws, data["transfers"], plan.get("squad_from_gw"))
    data["xg_signal"] = build_xg_signal(boot, team_id, plan.get("squad_from_gw"))
    data["defcon"] = build_defcon(boot, team_id, plan.get("squad_from_gw"))
    data["rotation_risk"] = build_rotation_risk(boot, team_id, plan.get("squad_from_gw"))
    data["form_fdr"] = build_form_fdr(boot, next_fixture_map)
    data["price_radar"] = build_price_radar(boot, team_id, plan.get("squad_from_gw"))
    data["value_board"] = build_value_board(boot)
    data["transfer_targets"] = build_transfer_targets(boot, team_id, plan.get("squad_from_gw"))
    now = datetime.now(timezone.utc)
    data.update({
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "generated_at_et": fmt_generated_et(now),
        "timezone": "America/Toronto",
        "deadline": {
            "passed": ds["deadline_passed"],
            "locked_gw": ds["locked_gw"],
            "next_gw": ds["next_gw"],
            "intel_gw": ds["intel_gw"],
            "current_gw": ds["current_gw"],
            "picks_unlocked": ds["picks_unlocked"],
        },
        "team": {**(existing.get("team") or {}), "id": entry["id"], "name": entry["name"], "manager": f"{entry.get('player_first_name','')} {entry.get('player_last_name','')}".strip(), "overall_points": entry.get("summary_overall_points"), "overall_rank": entry.get("summary_overall_rank"), "bank": entry.get("last_deadline_bank", 0) / 10, "value": entry.get("last_deadline_value", 0) / 10},
        "history": hist.get("past", []),
        "chips_official": {"bboost": chips_used.get("bboost"), "3xc": chips_used.get("3xc"), "freehit": chips_used.get("freehit"), "wildcard": chips_used.get("wildcard")},
        "gameweeks": gws,
        "field_avg_known": field_avg,
        "plan": plan,
        "leagues": leagues,
        "captain_audit": caps,
    })
    data_file.write_text("window.FPL_DATA = " + json.dumps(data, indent=2) + ";\n")
    print("Updated", data_file.name, entry.get("name"), [u["gw"] for u in plan.get("upcoming", [])])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", type=int, default=TEAM_ID)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    main(args.team, args.out)
