#!/usr/bin/env python3
from __future__ import annotations
import json, urllib.request
from datetime import datetime, timezone
from pathlib import Path

TEAM_ID = 1360999
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data.js"
POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
NEED = {"GKP": 1, "DEF": 3, "MID": 4, "FWD": 3}

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ShaalandFPLLab/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

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

def recommend(pos, fdr, cost, minutes):
    if fdr is None: return "BLANK"
    if minutes < 60 and cost < 5.5: return "SIT"
    if pos == "GKP": return "START" if fdr <= 3 else "SIT"
    if pos == "DEF":
        if fdr >= 5 or (fdr >= 4 and cost < 5.5): return "SIT"
        return "START"
    if pos == "MID" and ((fdr >= 5 and cost < 8) or (fdr >= 4 and cost < 6.5)): return "SIT"
    if pos == "FWD" and fdr >= 5 and cost < 8: return "SIT"
    return "START"

def score(pos, fdr, form, minutes, cost):
    if fdr is None: return -99
    return form * 2 + (6 - int(fdr)) * 2.2 + min(minutes, 270) / 90 + (0.4 if cost >= 9 else 0)

def pick_lineup(players, gw_key):
    ranked = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in players:
        info = p["gws"].get(gw_key) or {}
        ranked[p["pos"]].append((info.get("score", -99), p))
    for pos in ranked: ranked[pos].sort(key=lambda x: x[0], reverse=True)
    xi, bn = [], []
    for pos, n in NEED.items():
        for i, (_s, p) in enumerate(ranked[pos]):
            tag = " (C)" if pos == "FWD" and i == 0 else ""
            (xi if i < n else bn).append(p["name"] + tag)
    if xi and not any(" (VC)" in x for x in xi):
        for i, name in enumerate(xi):
            if not name.endswith(" (C)"):
                xi[i] = name + " (VC)"; break
    return xi, bn[:4]

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
    picks, picks_gw = [], None
    for ev in reversed(events):
        if ev["id"] > (last_fin["id"] if last_fin else 0) + 1: continue
        try:
            payload = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{ev['id']}/picks/")
            picks = payload.get("picks") or []
            if picks:
                picks_gw = ev["id"]; break
        except Exception:
            continue
    if not picks:
        return {"note": "Could not load squad picks.", "upcoming": [], "rows": []}
    maps, headers = {}, []
    for ev in upcoming:
        maps[ev["id"]] = fixture_map(ev["id"], teams)
        dl = ev.get("deadline_time") or ""
        headers.append({"gw": ev["id"], "deadline": dl.replace("T", " ")[:16] + " UTC" if dl else ""})
    players, rows = [], []
    for pick in sorted(picks, key=lambda p: (elements[p["element"]]["element_type"], p["element"])):
        el = elements[pick["element"]]
        pos, form, mins, cost = POS[el["element_type"]], float(el.get("form") or 0), int(el.get("minutes") or 0), el["now_cost"] / 10
        gws, row = {}, [pos, el["web_name"], teams[el["team"]]["short_name"]]
        for ev in upcoming:
            info = maps[ev["id"]].get(el["team"])
            fdr = info["fdr"] if info else None
            cell = {"fixture": fmt_fix(info), "fdr": fdr, "call": recommend(pos, fdr, cost, mins), "score": round(score(pos, fdr, form, mins, cost), 2)}
            gws[f"gw{ev['id']}"] = cell
            row.extend([cell["fixture"], fdr if fdr is not None else "-", cell["call"]])
        players.append({"name": el["web_name"], "pos": pos, "gws": gws, "cost": cost})
        rows.append(row)
    xis = {}
    for ev in upcoming:
        key = f"gw{ev['id']}"
        xi, bn = pick_lineup(players, key)
        xis[key] = {"xi": xi, "bench": bn}
    ft = free_transfers_for_next(hist or {})
    fh_used = bool((chips_used or {}).get("freehit"))
    bench_calls = []
    for ev in upcoming:
        key = f"gw{ev['id']}"
        sits = [{"player": p["name"], "fixture": (p["gws"].get(key) or {}).get("fixture"), "fdr": (p["gws"].get(key) or {}).get("fdr")} for p in players if (p["gws"].get(key) or {}).get("call") in ("SIT", "BLANK")]
        sits.sort(key=lambda x: -(x["fdr"] or 0))
        top = sits[0] if sits else None
        bench_calls.append({"gw": ev["id"], "sit": xis[key]["bench"], "worst": top["player"] if top else None, "why": f"{top['player']} {top['fixture']} FDR {top['fdr']}" if top else "No sit"})
    action, move, reason = "ROLL", None, f"You have {ft} FT. " + ("FH unused — roll so the FT returns with Shaaland." if not fh_used else "No forced move. Bank it.")
    return {"note": f"GW{picks_gw} squad. Last finished {(last_fin or {}).get('id')}.", "last_finished": (last_fin or {}).get("id"), "squad_from_gw": picks_gw, "upcoming": headers, "rows": rows, "xis": xis, "bench_calls": bench_calls, "transfer": {"ft_available": ft, "action": action, "reason": reason, "move": move, "fh_unused": not fh_used}}

def analyze_leagues(boot, entry, team_id, picks_gw):
    teams = {t["id"]: t for t in boot["teams"]}
    elements = {e["id"]: e for e in boot["elements"]}
    classic = entry.get("leagues", {}).get("classic") or []
    my_picks = set()
    try:
        my_picks = {p["element"] for p in get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/").get("picks") or []}
    except Exception:
        pass
    leagues = []
    for L in [x for x in classic if x.get("league_type") == "x"]:
        try:
            rows = (get(f"https://fantasy.premierleague.com/api/leagues-classic/{L['id']}/standings/?page_standings=1").get("standings") or {}).get("results") or []
        except Exception:
            continue
        table = [{"rank": r.get("rank"), "team": r.get("entry_name"), "pts": r.get("total"), "me": r.get("entry") == team_id} for r in rows[:15]]
        counts, n = {}, 0
        if len(rows) >= 2:
            for r in rows:
                try:
                    pk = get(f"https://fantasy.premierleague.com/api/entry/{r['entry']}/event/{picks_gw}/picks/")
                except Exception:
                    continue
                n += 1
                for p in pk.get("picks") or []:
                    counts[p["element"]] = counts.get(p["element"], 0) + 1
        template, diffs = [], []
        if n:
            for pid, c in sorted(counts.items(), key=lambda x: -x[1]):
                el = elements.get(pid)
                if not el: continue
                pct = round(100 * c / n)
                item = {"name": el["web_name"], "club": teams[el["team"]]["short_name"], "own": pct, "count": c, "n": n}
                if pct >= 40 and pid not in my_picks: template.append(item)
                if pid in my_picks and pct <= 25: diffs.append(item)
        leagues.append({"id": L["id"], "name": L.get("name"), "rank": L.get("entry_rank"), "last_rank": L.get("entry_last_rank"), "size": len(rows), "table": table, "template": template[:8], "diffs": diffs[:8], "picks_gw": picks_gw})
    overall_template, overall_diffs = [], []
    for el in boot["elements"]:
        sel = float(el.get("selected_by_percent") or 0)
        item = {"name": el["web_name"], "club": teams[el["team"]]["short_name"], "own": sel}
        if my_picks:
            if sel >= 25 and el["id"] not in my_picks: overall_template.append(item)
            if el["id"] in my_picks and sel <= 12: overall_diffs.append(item)
    overall_template.sort(key=lambda x: -x["own"])
    overall_diffs.sort(key=lambda x: x["own"])
    public = [{"id": L.get("id"), "name": L.get("name"), "rank": L.get("entry_rank"), "last_rank": L.get("entry_last_rank")} for L in classic if L.get("id") in (15, 59, 314)]
    return {"mini": leagues, "public": public, "overall_template": overall_template[:8], "overall_diffs": overall_diffs[:8], "picks_gw": picks_gw}

def main():
    existing = {}
    if DATA.exists():
        raw = DATA.read_text(); s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1: existing = json.loads(raw[s:e+1])
    boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
    entry = get(f"https://fantasy.premierleague.com/api/entry/{TEAM_ID}/")
    hist = get(f"https://fantasy.premierleague.com/api/entry/{TEAM_ID}/history/")
    avg = {e["id"]: e.get("average_entry_score") for e in boot["events"]}
    field_avg = dict(existing.get("field_avg_known") or {1: 50, 2: 81, 3: 51})
    chips_used = {c["name"]: c["event"] for c in hist.get("chips", [])}
    gws = []
    for row in hist.get("current", []):
        gw = row["event"]; fa = field_avg.get(gw) or avg.get(gw)
        if fa: field_avg[gw] = fa
        gws.append({"gw": gw, "points": row["points"], "bench": row["points_on_bench"], "transfers": row["event_transfers"], "hits": row["event_transfers_cost"], "rank": row["overall_rank"], "field_avg": fa, "delta": (row["points"] - fa) if fa else None, "chip": next((n for n, ev in chips_used.items() if ev == gw), None)})
    plan = build_plan(boot, TEAM_ID, hist, chips_used)
    last_fin = max((e["id"] for e in boot["events"] if e.get("finished")), default=1)
    leagues = analyze_leagues(boot, entry, TEAM_ID, plan.get("squad_from_gw") or last_fin)
    data = existing or {}
    data.update({"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "team": {**(existing.get("team") or {}), "id": entry["id"], "name": entry["name"], "manager": f"{entry.get('player_first_name','')} {entry.get('player_last_name','')}".strip(), "overall_points": entry.get("summary_overall_points"), "overall_rank": entry.get("summary_overall_rank"), "bank": entry.get("last_deadline_bank", 0) / 10, "value": entry.get("last_deadline_value", 0) / 10}, "history": hist.get("past", []), "chips_official": {"bboost": chips_used.get("bboost"), "3xc": chips_used.get("3xc"), "freehit": chips_used.get("freehit"), "wildcard": chips_used.get("wildcard")}, "gameweeks": gws, "field_avg_known": field_avg, "plan": plan, "leagues": leagues})
    DATA.write_text("window.FPL_DATA = " + json.dumps(data, indent=2) + ";\n")
    print("Updated", [u["gw"] for u in plan.get("upcoming", [])], "leagues", len(leagues.get("mini", [])))

if __name__ == "__main__":
    main()
