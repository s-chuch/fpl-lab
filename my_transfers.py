"""Transfers you have already made in FPL for the next gameweek, logged by hand before the deadline.

FPL hides your next-gameweek squad until the deadline, so the program cannot see them. You log them on the Plan tab (it opens a pre-filled
GitHub issue), `log_transfers.py` validates the issue against FPL and stores it in `my_transfers.json`, and each refresh turns it into
`data["logged_transfers"]`: your moves next to the model's recommendation, and the XI / bench / captain advice for the squad after them.
The frozen recommendation in the Decision log is not touched (it stays the model's own call from your pre-move squad).

my_transfers.json: {"<team id>": {"<gw>": {"moves": [{"out": id, "in": id}], "logged_at": iso, "issue": n}}}"""
from __future__ import annotations

import json
import os
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILE = ROOT / "my_transfers.json"
TEAMS = {"Shaaland": 1360999, "Bacalhau": 1360920}
POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
HIT = 4
MAX_MOVES = 15


def load(path=FILE):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def save(doc, path=FILE):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _fold(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().casefold().strip()


def resolve(ref, boot, squad_ids=None):
    """A player id from a request entry: an explicit id, else a web_name (plus club when the name is shared). Returns (id, error)."""
    els = {e["id"]: e for e in boot["elements"]}
    if isinstance(ref.get("id"), int):
        return (ref["id"], None) if ref["id"] in els else (None, f"no player with id {ref['id']}")
    name, club = _fold(ref.get("name")), _fold(ref.get("club"))
    short = {t["id"]: _fold(t["short_name"]) for t in boot["teams"]}
    hits = [e for e in boot["elements"] if _fold(e["web_name"]) == name and (not club or short.get(e["team"]) == club)]
    if not hits:                                            # a looser second try: full name contains the text
        hits = [e for e in boot["elements"] if name and name in _fold(f"{e.get('first_name')} {e.get('second_name')}") and (not club or short.get(e["team"]) == club)]
    if squad_ids:
        mine = [e for e in hits if e["id"] in squad_ids]
        hits = mine or hits
    if len(hits) == 1:
        return hits[0]["id"], None
    if not hits:
        return None, f"could not find a player called '{ref.get('name')}'"
    return None, f"'{ref.get('name')}' matches {len(hits)} players: add the club (for example 'in_club': 'TOT')"


def validate(req, boot, squad_ids, now=None):
    """Check a logging request. req = {"team": name, "gw": n, "moves": [{"out": {...}, "in": {...}}]} where each side is {"id"} or {"name", "club"}.
    Returns (moves, errors): moves = [{"out": id, "in": id}] when legal, errors = [text]."""
    now = now or datetime.now(timezone.utc)
    errs = []
    if req.get("team") not in TEAMS:
        return [], [f"team must be one of {', '.join(TEAMS)}"]
    events = {e["id"]: e for e in boot["events"]}
    nxt = next((e for e in sorted(boot["events"], key=lambda e: e["id"]) if not e.get("finished")
                and datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")) > now), None)
    if not nxt or req.get("gw") != nxt["id"]:
        return [], [f"gameweek {req.get('gw')} is not the next open gameweek (that is GW{nxt['id'] if nxt else '?'}, and its deadline must still be ahead)"]
    moves_in = req.get("moves") or []
    if not isinstance(moves_in, list) or not (1 <= len(moves_in) <= MAX_MOVES):
        return [], ["give between 1 and 15 moves"]
    els = {e["id"]: e for e in boot["elements"]}
    squad = set(squad_ids)
    outs, ins, moves = [], [], []
    for m in moves_in:
        o, e1 = resolve(m.get("out") or {}, boot, squad)
        i, e2 = resolve(m.get("in") or {}, boot)
        if e1 or e2:
            errs += [x for x in (e1, e2) if x]
            continue
        if o not in squad:
            errs.append(f"{els[o]['web_name']} is not in your squad")
        if POS[els[o]["element_type"]] != POS[els[i]["element_type"]]:
            errs.append(f"{els[o]['web_name']} -> {els[i]['web_name']}: different positions")
        moves.append({"out": o, "in": i}); outs.append(o); ins.append(i)
    if len(set(outs)) != len(outs) or len(set(ins)) != len(ins):
        errs.append("a player appears twice")
    if errs:
        return [], errs
    after = apply_moves(list(squad_ids), moves)
    if len(set(after)) != 15:
        errs.append("a bought player is already in your squad")
    clubs = {}
    for i in after:
        c = els[i]["team"]; clubs[c] = clubs.get(c, 0) + 1
    team = {t["id"]: t["short_name"] for t in boot["teams"]}
    errs += [f"more than 3 players from {team[c]}" for c, n in clubs.items() if n > 3]
    return ([] if errs else moves), errs


def apply_moves(squad_ids, moves):
    swap = {m["out"]: m["in"] for m in moves}
    return [swap.get(i, i) for i in squad_ids]


def record(doc, team_id, gw, moves, issue=None, now=None):
    """Store the moves for (team, gameweek), replacing any earlier entry."""
    now = now or datetime.now(timezone.utc)
    doc = dict(doc or {})
    t = dict(doc.get(str(team_id)) or {})
    t[str(gw)] = {"moves": moves, "logged_at": now.isoformat(timespec="seconds"), **({"issue": issue} if issue else {})}
    doc[str(team_id)] = t
    return doc


def build_view(logged, squad_ids, vals, rec, ft, pick_xi):
    """data["logged_transfers"]: your logged moves, the lineup advice for the squad after them, and how they compare with the model's
    recommendation. `vals` = ai_team.player_values for the gameweek, `rec` = the frozen recommendation entry (rec_log) or None, `ft` = free
    transfers, `pick_xi(ids, vals, "xp")` = ai_team.pick_xi."""
    moves = logged["moves"]
    after = apply_moves(squad_ids, moves)
    if any(i not in vals for i in after) or any(i not in vals for i in squad_ids):
        return None

    def lineup(ids):
        xi, bench = pick_xi(ids, vals, "xp")
        ranked = sorted(xi, key=lambda i: -vals[i]["xp"])
        order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
        row = lambda i: {"name": vals[i]["name"], "pos": vals[i]["pos"], "club": vals[i]["club"], "xp": vals[i]["xp"]}
        xi_sorted = sorted(xi, key=lambda i: (order[vals[i]["pos"]], -vals[i]["xp"]))
        n = lambda p: sum(1 for i in xi if vals[i]["pos"] == p)
        total = sum(vals[i]["xp"] for i in xi) + vals[ranked[0]]["xp"]
        return {"formation": f"{n('DEF')}-{n('MID')}-{n('FWD')}", "captain": vals[ranked[0]]["name"], "vice": vals[ranked[1]]["name"],
                "xi": [row(i) for i in xi_sorted], "bench": [row(i) for i in bench], "xp": round(total, 1)}

    hits = max(0, len(moves) - int(ft or 0))
    mine, before = lineup(after), lineup(squad_ids)
    flags = []
    for m in moves:
        v = vals[m["in"]]
        if v.get("avail", 1) < 1:
            flags.append(f"{v['name']} is {int(round(v['avail'] * 100))}% fit")
        for r in (v.get("risks") or [])[:1]:
            flags.append(f"{v['name']}: {r}")
    out = {"gw": logged.get("gw"), "logged_at": logged.get("logged_at"), "hits": hits, "hit_cost": hits * HIT, "ft": ft,
           "moves": [{"out": vals[m["out"]]["name"], "in": vals[m["in"]]["name"], "pos": vals[m["in"]]["pos"], "in_club": vals[m["in"]]["club"],
                      "out_xp": vals[m["out"]]["xp"], "in_xp": vals[m["in"]]["xp"], "in_cost": vals[m["in"]]["cost"]} for m in moves],
           "lineup": mine, "xp": round(mine["xp"] - hits * HIT, 1), "xp_if_no_moves": before["xp"], "flags": flags}
    if rec and rec.get("xp") is not None:
        out["model_xp"] = rec["xp"]
        out["model_moves"] = [f"{t.get('out')} -> {t.get('in')}" for t in rec.get("transfers") or []]
        out["diff_vs_model"] = round(out["xp"] - rec["xp"], 1)
    return out
