#!/usr/bin/env python3
"""Throwaway diagnostic: exactly which player(s)/multiplier account for the
Hindsight-vs-Process/They point gap on Bacalhau's GW1. Deleted after use."""
import refresh
from refresh import get, _best_xi, _process_xi, POS

TEAM_ID = 1360920
GW = 1

boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
names = {e["id"]: e["web_name"] for e in boot["elements"]}
pmap = {e["id"]: POS[e["element_type"]] for e in boot["elements"]}

pk = get(f"https://fantasy.premierleague.com/api/entry/{TEAM_ID}/event/{GW}/picks/")
live = get(f"https://fantasy.premierleague.com/api/event/{GW}/live/")
pts = {el["id"]: el["stats"]["total_points"] for el in live.get("elements", [])}
mins = {el["id"]: el["stats"].get("minutes", 0) for el in live.get("elements", [])}

cap = next((p for p in pk.get("picks", []) if p.get("is_captain")), None)
mult = (cap or {}).get("multiplier") or 2
print(f"active_chip={pk.get('active_chip')} captain_mult={mult}")

squad = []
for p in pk.get("picks", []):
    item = {
        "name": names.get(p["element"], "?"), "pos": pmap.get(p["element"], "MID"),
        "pts": pts.get(p["element"], 0), "mins": mins.get(p["element"], 0),
        "trail_mins": 0,  # GW1: no prior finished GWs
        "started": p["position"] <= 11, "captain": bool(p.get("is_captain")),
    }
    squad.append(item)

print("\nFull squad (name, pos, pts, mins, started, captain):")
for s in sorted(squad, key=lambda x: -x["pts"]):
    print(f"  {s['name']:20s} {s['pos']:4s} pts={s['pts']:3d} mins={s['mins']:3d} started={s['started']} captain={s['captain']}")

best = _best_xi(squad)
started_actual = {p["name"] for p in squad if p["started"]}
best_names = {p["name"] for p in best}
raw = sum(p["pts"] for p in best)
top = max((p["pts"] for p in best), default=0)
hindsight = raw + top * (mult - 1)
top_name = next((p["name"] for p in best if p["pts"] == top), "?")

proc_xi = _process_xi(squad, mins_key="trail_mins")
proc_names = {p["name"] for p in proc_xi}
proc_cap_pts = next((p["pts"] for p in proc_xi if p["captain"]), 0)
process = sum(p["pts"] for p in proc_xi) + proc_cap_pts * (mult - 1)

you = (pk.get("entry_history") or {}).get("points")

print(f"\nYou/They actual points: {you}")
print(f"Process score: {process}  (XI: {sorted(proc_names)})")
print(f"Hindsight score: {hindsight}  (XI: {sorted(best_names)}, virtual captain={top_name} pts={top})")

print("\n--- Diff: actual starters NOT in hindsight XI ---")
for name in sorted(started_actual - best_names):
    p = next(s for s in squad if s["name"] == name)
    print(f"  OUT: {name} ({p['pos']}, {p['pts']} pts actual)")

print("\n--- Diff: hindsight XI players who were actually benched ---")
for name in sorted(best_names - started_actual):
    p = next(s for s in squad if s["name"] == name)
    print(f"  IN:  {name} ({p['pos']}, {p['pts']} pts actual)")

actual_cap = next((s["name"] for s in squad if s["captain"]), None)
actual_cap_pts = next((s["pts"] for s in squad if s["captain"]), 0)
print(f"\nActual captain: {actual_cap} ({actual_cap_pts} pts) x{mult} = {actual_cap_pts*mult}")
print(f"Hindsight's captain-equivalent: {top_name} ({top} pts) x{mult} = {top*mult}")
print(f"Captain-swap alone would add: {(top - actual_cap_pts) * (mult - 1)} pts")
