#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from league_tactics import build_tactics

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
    req = urllib.request.Request(url, headers={"User-Agent": "ShaalandFPLLab/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


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
    ft = 0
    for row in hist.get("current", []):
        ft = min(2, ft + 1)
        ft = max(0, ft - int(row.get("event_transfers") or 0))
    return min(2, ft + 1)

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
        except Exception:
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
        except Exception:
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
    by = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in squad:
        by[p["pos"]].append(p)
    for pos in by:
        by[pos].sort(key=lambda x: -x["pts"])
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
    pool.sort(key=lambda x: -x["pts"])
    for p in pool:
        if len(picked) >= 11:
            break
        if counts[p["pos"]] >= MAXX[p["pos"]]:
            continue
        picked.append(p); counts[p["pos"]] += 1
    return picked

def _process_xi(squad):
    """Best legal XI judged only by minutes played, not final points: a bench player
    only displaces a starter here if they played strictly more minutes — a call you
    could make without knowing the final scoreline. The real captain is pinned first
    so the multiplier isn't re-litigated by this heuristic."""
    cap_name = next((p["name"] for p in squad if p.get("captain")), None)
    by = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in squad:
        by[p["pos"]].append(p)
    for pos in by:
        by[pos].sort(key=lambda x: (x["name"] != cap_name, -x["mins"], not x["started"]))
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
    pool.sort(key=lambda x: (x["name"] != cap_name, -x["mins"], not x["started"]))
    for p in pool:
        if len(picked) >= 11:
            break
        if counts[p["pos"]] >= MAXX[p["pos"]]:
            continue
        picked.append(p); counts[p["pos"]] += 1
    return picked

def build_bench_audit(boot, team_id):
    names = {e["id"]: e["web_name"] for e in boot["elements"]}
    pmap = {e["id"]: POS[e["element_type"]] for e in boot["elements"]}
    out = {}
    for ev in boot["events"]:
        if not ev.get("finished"):
            continue
        gw = ev["id"]
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
            live = get(f"https://fantasy.premierleague.com/api/event/{gw}/live/")
        except Exception:
            continue
        pts = {el["id"]: el["stats"]["total_points"] for el in live.get("elements", [])}
        mins = {el["id"]: el["stats"].get("minutes", 0) for el in live.get("elements", [])}
        cap = next((p for p in pk.get("picks", []) if p.get("is_captain")), None)
        mult = (cap or {}).get("multiplier") or 2
        squad, bench = [], []
        for p in pk.get("picks", []):
            item = {
                "name": names.get(p["element"], "?"),
                "pos": pmap.get(p["element"], "MID"),
                "pts": pts.get(p["element"], 0),
                "mins": mins.get(p["element"], 0),
                "started": p["position"] <= 11,
                "captain": bool(p.get("is_captain")),
            }
            squad.append(item)
            if p["position"] > 11:
                bench.append([item["name"], item["pts"]])
        best = _best_xi(squad)
        started = {p["name"] for p in best}
        better = [[p["name"], p["pts"]] for p in squad if p["name"] not in started]
        you = (pk.get("entry_history") or {}).get("points")
        raw = sum(p["pts"] for p in best)
        top = max((p["pts"] for p in best), default=0)
        hindsight = raw + top * (mult - 1)
        proc_xi = _process_xi(squad)
        proc_cap_pts = next((p["pts"] for p in proc_xi if p["captain"]), 0)
        process = sum(p["pts"] for p in proc_xi) + proc_cap_pts * (mult - 1)
        out[f"gw{gw}"] = {"you": you, "process": process, "hindsight": hindsight, "your_bench": bench, "better_bench": better[:4]}
    return out

def build_transfers(boot, team_id):
    names = {e["id"]: e["web_name"] for e in boot["elements"]}
    try:
        rows = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/transfers/")
    except Exception:
        return []
    live_cache, out = {}, []
    for t in rows:
        gw = t.get("event")
        if gw not in live_cache:
            try:
                live_cache[gw] = {el["id"]: el["stats"]["total_points"] for el in get(f"https://fantasy.premierleague.com/api/event/{gw}/live/").get("elements", [])}
            except Exception:
                live_cache[gw] = {}
        inn, outp = names.get(t["element_in"], "?"), names.get(t["element_out"], "?")
        pin, pout = live_cache[gw].get(t["element_in"], 0), live_cache[gw].get(t["element_out"], 0)
        net = pin - pout
        verdict = "Good that GW" if net > 1 else ("Lost that GW" if net < -1 else "Even that GW")
        out.append({"gw": gw, "out": outp, "inn": inn, "net": ("+" if net > 0 else "") + str(net), "verdict": verdict})
    out.sort(key=lambda x: x["gw"] or 0)
    return out

def analyze_leagues(boot, entry, team_id, picks_gw, deadline_passed=False):
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
    except Exception:
        pass
    leagues = []
    tracked = [x for x in classic if x.get("id") in tracked_ids]
    tracked.sort(key=lambda x: 0 if x.get("id") == 125784 else 1)
    for L in tracked:
        try:
            rows = (get(f"https://fantasy.premierleague.com/api/leagues-classic/{L['id']}/standings/?page_standings=1").get("standings") or {}).get("results") or []
        except Exception:
            continue
        table = [{"rank": r.get("rank"), "team": r.get("entry_name"), "pts": r.get("total"), "me": r.get("entry") == team_id, "entry": r.get("entry")} for r in rows[:15]]
        counts, n, owned_by, cap_by = {}, 0, {}, {}
        member_squads = []
        picks_available = 0
        if len(rows) >= 2:
            for r in rows:
                try:
                    pk = get(f"https://fantasy.premierleague.com/api/entry/{r['entry']}/event/{picks_gw}/picks/")
                except Exception:
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
        template, diffs = [], []
        if n:
            for pid, c in sorted(counts.items(), key=lambda x: -x[1]):
                el = elements.get(pid)
                if not el: continue
                pct = round(100 * c / n)
                item = {"name": el["web_name"], "club": teams[el["team"]]["short_name"], "own": pct, "count": c, "n": n}
                if pct >= 40 and pid not in my_picks: template.append(item)
                if pid in my_picks and pct <= 25: diffs.append(item)
        tactics = build_tactics(rows, team_id, L, n, counts, owned_by, cap_by, my_picks, elements, teams)
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
    leagues = analyze_leagues(boot, entry, team_id, league_picks_gw, deadline_passed=bool(ds["deadline_passed"]))
    caps = captain_audit(boot, team_id)
    data = existing or {}
    # Recomputed every run rather than cached off `existing`: both only cover finished
    # GWs (whose points never change), so recomputing is cheap and safe, whereas a
    # "skip if already present" cache would silently freeze once a new GW finishes.
    data["transfers"] = build_transfers(boot, team_id)
    data["bench_audit"] = build_bench_audit(boot, team_id)
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
