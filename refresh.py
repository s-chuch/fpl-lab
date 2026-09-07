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

def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "ShaalandFPLLab/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def main() -> None:
    existing = {}
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
        gws.append(
            {
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
            }
        )

    data = existing or {}
    data.update(
        {
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
        }
    )
    DATA.write_text("window.FPL_DATA = " + json.dumps(data, indent=2) + ";\n")
    print(f"Updated {DATA}")
    print(f"{data['team']['name']}  {data['team']['overall_points']} pts  OR {data['team']['overall_rank']}")
    print("Chips:", data["chips_official"])

if __name__ == "__main__":
    main()
