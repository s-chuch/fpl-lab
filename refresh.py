#!/usr/bin/env python3
"""Refresh Shaaland dashboard from the official FPL API."""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TEAM_ID = 1360999
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data.js"
POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
NEED = {"GKP": 1, "DEF": 3, "MID": 4, "FWD": 3}


def get(url: str):
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
    if not info:
        return "Blank"
    return f"{info['side']} {info['opp']}"


def recommend(pos, fdr, cost, minutes):
    if fdr is None:
        return "BLANK"
    if minutes < 60 and cost < 5.5:
        return "SIT"
    if pos == "GKP":
        return "START" if fdr <= 3 else "SIT"
    if pos == "DEF":
        if fdr >= 5:
            return "SIT"
        if fdr >= 4 and cost < 5.5:
            return "SIT"
        return "START"
    if pos == "MID":
        if fdr >= 5 and cost < 8:
            return "SIT"
        if fdr >= 4 and cost < 6.5:
            return "SIT"
        return "START"
    if fdr >= 5 and cost < 8:
        return "SIT"
    return "START"


def score(pos, fdr, form, minutes, cost):
    if fdr is None:
        return -99
    return form * 2 + (6 - int(fdr)) * 2.2 + min(minutes, 270) / 90 + (0.4 if cost >= 9 else 0)


def pick_lineup(players, gw_key):
    ranked = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in players:
        info = p["gws"].get(gw_key) or {}
        ranked[p["pos"]].append((info.get("score", -99), p, info))
    for pos in ranked:
        ranked[pos].sort(key=lambda x: x[0], reverse=True)
    xi, bn = [], []
    for pos, n in NEED.items():
        for i, (_s, p, info) in enumerate(ranked[pos]):
            name = p["name"]
            tag = " (C)" if pos == "FWD" and i == 0 else ""
            if i < n:
                xi.append(name + tag)
            else:
                bn.append(name)
    if xi and not any(" (VC)" in x for x in xi):
        for i, name in enumerate(xi):
            if name.endswith(" (C)"):
                continue
            if any(p["name"] == name.split(" (")[0] and p["pos"] in ("MID", "FWD") for p in players):
                xi[i] = name + " (VC)"
                break
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
    picks_gw = None
    picks = []
    for ev in reversed(events):
        if ev["id"] > (last_fin["id"] if last_fin else 0) + 1:
            continue
        try:
            payload = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{ev['id']}/picks/")
            picks = payload.get("picks") or []
            if picks:
                picks_gw = ev["id"]
                break
        except Exception:
            continue
    if not picks:
        return {"note": "Could not load squad picks.", "upcoming": [], "rows": []}
    maps = {}
    headers = []
    for ev in upcoming:
        maps[ev["id"]] = fixture_map(ev["id"], teams)
        dl = ev.get("deadline_time") or ""
        headers.append({"gw": ev["id"], "name": ev.get("name") or f"GW{ev['id']}", "deadline": dl.replace("T", " ")[:16] + " UTC" if dl else ""})
    players = []
    rows = []
    for pick in sorted(picks, key=lambda p: (elements[p["element"]]["element_type"], p["element"])):
        el = elements[pick["element"]]
        pos = POS[el["element_type"]]
        form = float(el.get("form") or 0)
        mins = int(el.get("minutes") or 0)
        cost = el["now_cost"] / 10
        gws = {}
        row = [pos, el["web_name"], teams[el["team"]]["short_name"]]
        for ev in upcoming:
            info = maps[ev["id"]].get(el["team"])
            fdr = info["fdr"] if info else None
            call = recommend(pos, fdr, cost, mins)
            cell = {"fixture": fmt_fix(info), "fdr": fdr, "call": call, "score": round(score(pos, fdr, form, mins, cost), 2)}
            gws[f"gw{ev['id']}"] = cell
            row.extend([cell["fixture"], fdr if fdr is not None else "-", cell["call"]])
        players.append({"name": el["web_name"], "pos": pos, "gws": gws, "form": form, "cost": cost})
        rows.append(row)
    xis = {}
    for ev in upcoming:
        key = f"gw{ev['id']}"
        xi, bn = pick_lineup(players, key)
        xis[key] = {"xi": xi, "bench": bn}
    last_id = last_fin["id"] if last_fin else 0
    ft = free_transfers_for_next(hist or {})
    fh_used = bool((chips_used or {}).get("freehit"))
    bench_calls = []
    for ev in upcoming:
        key = f"gw{ev['id']}"
        sits = []
        for p in players:
            cell = p["gws"].get(key) or {}
            if cell.get("call") in ("SIT", "BLANK"):
                sits.append({"player": p["name"], "fixture": cell.get("fixture"), "fdr": cell.get("fdr")})
        sits.sort(key=lambda x: -(x["fdr"] or 0))
        top = sits[0] if sits else None
        bench_calls.append({
            "gw": ev["id"],
            "sit": xis[key]["bench"],
            "worst": top["player"] if top else None,
            "why": f"{top['player']} {top['fixture']} FDR {top['fdr']}" if top else "No obvious sit",
        })
    owned = {p["name"] for p in players}
    weakest = None
    weakest_score = -1
    for p in players:
        if p["pos"] == "GKP" or p["cost"] >= 9:
            continue
        fdrs = []
        for ev in upcoming:
            cell = p["gws"].get(f"gw{ev['id']}") or {}
            fdrs.append(int(cell["fdr"]) if cell.get("fdr") is not None else 5)
        comb = sum(fdrs)
        if comb > weakest_score:
            weakest_score = comb
            weakest = {"name": p["name"], "pos": p["pos"], "cost": p["cost"], "fdrs": fdrs, "comb": comb}
    replacement = None
    if weakest:
        cand = []
        for el in boot["elements"]:
            if POS.get(el["element_type"]) != weakest["pos"]:
                continue
            if el["status"] != "a" or el["web_name"] in owned or el["minutes"] < 180:
                continue
            price = el["now_cost"] / 10
            if price > weakest["cost"] + 0.5:
                continue
            fdrs = []
            for ev in upcoming:
                info = maps[ev["id"]].get(el["team"])
                fdrs.append(int(info["fdr"]) if info and info.get("fdr") is not None else 5)
            cand.append((sum(fdrs), price, el["web_name"], teams[el["team"]]["short_name"], fdrs))
        cand.sort()
        if cand and cand[0][0] <= weakest["comb"] - 2:
            replacement = {"name": cand[0][2], "club": cand[0][3], "fdrs": cand[0][4]}
    if not fh_used:
        action, move = "ROLL", None
        reason = f"You have {ft} FT. FH is still unused. A transfer this week dies with the chip. Roll; the FT comes back with Shaaland."
    elif replacement and weakest:
        action = "TRANSFER"
        move = {"out": weakest["name"], "inn": replacement["name"], "inn_club": replacement["club"]}
        reason = f"{weakest['name']} has the worst two-week run (FDR {weakest['fdrs']}). {replacement['name']} ({replacement['club']}) is FDR {replacement['fdrs']}."
    else:
        action, move = "ROLL", None
        reason = f"You have {ft} FT. No clear two-week sell. Bank it."
    transfer = {"ft_available": ft, "action": action, "reason": reason, "move": move, "fh_unused": not fh_used}
    note = f"Plan uses your GW{picks_gw} squad. Last finished GW is {last_id}. Next {len(upcoming)} unfinished gameweeks."
    return {"note": note, "last_finished": last_id, "squad_from_gw": picks_gw, "upcoming": headers, "rows": rows, "xis": xis, "bench_calls": bench_calls, "transfer": transfer}


def main():
    existing = {}
    if DATA.exists():
        raw = DATA.read_text()
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            existing = json.loads(raw[start:end + 1])
    boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
    entry = get(f"https://fantasy.premierleague.com/api/entry/{TEAM_ID}/")
    hist = get(f"https://fantasy.premierleague.com/api/entry/{TEAM_ID}/history/")
    avg = {e["id"]: e.get("average_entry_score") for e in boot["events"]}
    field_avg = dict(existing.get("field_avg_known") or {1: 50, 2: 81, 3: 51})
    chips_used = {c["name"]: c["event"] for c in hist.get("chips", [])}
    gws = []
    for row in hist.get("current", []):
        gw = row["event"]
        fa = field_avg.get(gw) or avg.get(gw) or None
        if fa:
            field_avg[gw] = fa
        gws.append({"gw": gw, "points": row["points"], "bench": row["points_on_bench"], "transfers": row["event_transfers"], "hits": row["event_transfers_cost"], "rank": row["overall_rank"], "gw_rank": row.get("rank"), "value": row.get("value", 0) / 10, "bank": row.get("bank", 0) / 10, "field_avg": fa, "delta": (row["points"] - fa) if fa else None, "chip": next((n for n, ev in chips_used.items() if ev == gw), None)})
    plan = build_plan(boot, TEAM_ID, hist, chips_used)
    data = existing or {}
    data.update({"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "team": {**(existing.get("team") or {}), "id": entry["id"], "name": entry["name"], "manager": f"{entry.get('player_first_name','')} {entry.get('player_last_name','')}".strip(), "overall_points": entry.get("summary_overall_points"), "overall_rank": entry.get("summary_overall_rank"), "gw_points": entry.get("summary_event_points"), "bank": entry.get("last_deadline_bank", 0) / 10, "value": entry.get("last_deadline_value", 0) / 10}, "history": hist.get("past", []), "chips_official": {"bboost": chips_used.get("bboost"), "3xc": chips_used.get("3xc"), "freehit": chips_used.get("freehit"), "wildcard": chips_used.get("wildcard")}, "gameweeks": gws, "field_avg_known": field_avg, "plan": plan})
    DATA.write_text("window.FPL_DATA = " + json.dumps(data, indent=2) + ";\n")
    print(f"Updated {DATA}")
    print("Upcoming:", [u["gw"] for u in plan.get("upcoming", [])], plan.get("transfer"))


if __name__ == "__main__":
    main()
