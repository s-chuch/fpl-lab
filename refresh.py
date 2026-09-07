#!/usr/bin/env python3
"""Refresh Shaaland dashboard from the official FPL API. Run from this folder."""
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


def fixture_map(event_id: int, teams: dict) -> dict:
    fx = get(f"https://fantasy.premierleague.com/api/fixtures/?event={event_id}")
    out = {}
    for f in fx:
        h, a = f["team_h"], f["team_a"]
        out[h] = {
            "side": "H",
            "opp": teams[a]["short_name"],
            "fdr": f.get("team_h_difficulty"),
            "kickoff": f.get("kickoff_time"),
        }
        out[a] = {
            "side": "A",
            "opp": teams[h]["short_name"],
            "fdr": f.get("team_a_difficulty"),
            "kickoff": f.get("kickoff_time"),
        }
    return out


def fmt_fix(info):
    if not info:
        return "Blank"
    return f"{info['side']} {info['opp']}"


def recommend(pos: str, fdr, cost: float, minutes: int) -> str:
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


def score(pos: str, fdr, form: float, minutes: int, cost: float) -> float:
    if fdr is None:
        return -99
    ease = 6 - int(fdr)
    return form * 2 + ease * 2.2 + min(minutes, 270) / 90 + (0.4 if cost >= 9 else 0)


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
            tag = ""
            if pos == "FWD" and i == 0:
                tag = " (C)"
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


def build_plan(boot, team_id):
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
        headers.append({
            "gw": ev["id"],
            "name": ev.get("name") or f"GW{ev['id']}",
            "deadline": dl.replace("T", " ")[:16] + " UTC" if dl else "",
        })
    players = []
    rows = []
    for pick in sorted(picks, key=lambda p: (elements[p["element"]]["element_type"], p["element"])):
        el = elements[pick["element"]]
        pos = POS[el["element_type"]]
        club = teams[el["team"]]["short_name"]
        form = float(el.get("form") or 0)
        mins = int(el.get("minutes") or 0)
        cost = el["now_cost"] / 10
        gws = {}
        row = [pos, el["web_name"], club]
        for ev in upcoming:
            info = maps[ev["id"]].get(el["team"])
            fdr = info["fdr"] if info else None
            call = recommend(pos, fdr, cost, mins)
            sc = score(pos, fdr, form, mins, cost)
            cell = {"fixture": fmt_fix(info), "fdr": fdr, "call": call, "score": round(sc, 2)}
            gws[f"gw{ev['id']}"] = cell
            row.extend([cell["fixture"], fdr if fdr is not None else "—", cell["call"]])
        players.append({"name": el["web_name"], "pos": pos, "gws": gws, "form": form, "cost": cost})
        rows.append(row)
    xis = {}
    for ev in upcoming:
        key = f"gw{ev['id']}"
        xi, bn = pick_lineup(players, key)
        xis[key] = {"xi": xi, "bench": bn}
    last_id = last_fin["id"] if last_fin else 0
    note = (
        f"Plan uses your GW{picks_gw} squad (last saved picks). "
        f"Last finished GW is {last_id}. Showing the next {len(upcoming)} unfinished gameweeks."
    )
    return {
        "note": note,
        "last_finished": last_id,
        "squad_from_gw": picks_gw,
        "upcoming": headers,
        "rows": rows,
        "xis": xis,
    }


def main() -> None:
    existing = {}
    if DATA.exists():
        raw = DATA.read_text()
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            existing = json.loads(raw[start : end + 1])
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
        gws.append({
            "gw": gw,
            "points": row["points"],
            "bench": row["points_on_bench"],
            "transfers": row["event_transfers"],
            "hits": row["event_transfers_cost"],
            "rank": row["overall_rank"],
            "gw_rank": row.get("rank"),
            "value": row.get("value", 0) / 10,
            "bank": row.get("bank", 0) / 10,
            "field_avg": fa,
            "delta": (row["points"] - fa) if fa else None,
            "chip": next((n for n, ev in chips_used.items() if ev == gw), None),
        })
    plan = build_plan(boot, TEAM_ID)
    data = existing or {}
    data.update({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "team": {
            **(existing.get("team") or {}),
            "id": entry["id"],
            "name": entry["name"],
            "manager": f"{entry.get('player_first_name','')} {entry.get('player_last_name','')}".strip(),
            "overall_points": entry.get("summary_overall_points"),
            "overall_rank": entry.get("summary_overall_rank"),
            "gw_points": entry.get("summary_event_points"),
            "bank": entry.get("last_deadline_bank", 0) / 10,
            "value": entry.get("last_deadline_value", 0) / 10,
        },
        "history": hist.get("past", []),
        "chips_official": {
            "bboost": chips_used.get("bboost"),
            "3xc": chips_used.get("3xc"),
            "freehit": chips_used.get("freehit"),
            "wildcard": chips_used.get("wildcard"),
        },
        "gameweeks": gws,
        "field_avg_known": field_avg,
        "plan": plan,
    })
    DATA.write_text("window.FPL_DATA = " + json.dumps(data, indent=2) + ";\n")
    print(f"Updated {DATA}")
    print(f"{data['team']['name']}  {data['team']['overall_points']} pts  OR {data['team']['overall_rank']}")
    print("Upcoming:", [u["gw"] for u in plan.get("upcoming", [])])
    print("Chips:", data["chips_official"])


if __name__ == "__main__":
    main()
