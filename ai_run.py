"""Running the AI team and daily check inside a refresh (inputs for the model, the clone of your team, the update)."""
from __future__ import annotations
from datetime import datetime, timezone
from fplbase import *
from fplbase import _warn
from chips import free_transfers_for_next
from signals import _rotation_flagged_players

def build_daily_check(prev, boot, squad_ids, ai_plan, rotation, now):
    """Program-wide daily check: compares today's state of everyone you own and everyone in the AI
    team's plan with the previous run, and lists what changed - new injuries / doubts, news updates,
    price moves and new rotation risks. The snapshot is kept so the next run can diff against it."""
    els = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    rot_by_name = {r["name"]: r.get("reason") for r in ((rotation or {}).get("rows") or [])}
    watch = {}
    for i in squad_ids or []:
        watch.setdefault(i, set()).add("your squad")
    for p in (ai_plan or {}).get("squad", []):
        watch.setdefault(p["id"], set()).add("AI team")
    snap = {}
    for i, who in watch.items():
        el = els.get(i)
        if not el:
            continue
        av = player_availability(el)
        snap[str(i)] = {"name": el["web_name"], "club": teams[el["team"]], "kind": av["kind"], "label": av["label"],
                        "news": av["news"], "cost": el["now_cost"] / 10, "rot": rot_by_name.get(el["web_name"]),
                        "who": sorted(who)}
    old = (prev or {}).get("snapshot") or {}
    at = now.isoformat()
    changes = []
    for k, n in snap.items():
        o = old.get(k)
        if not o:
            continue
        who = " & ".join(n["who"])
        tag = f"{n['name']} ({n['club']})"
        if (o["label"] or None) != (n["label"] or None):
            changes.append({"at": at, "who": who, "kind": "availability",
                            "text": f"{tag}: {o['label'] or 'fit'} → {n['label'] or 'fit'}" + (f" — {n['news']}" if n["news"] else "")})
        elif n["news"] and n["news"] != o["news"]:
            changes.append({"at": at, "who": who, "kind": "news", "text": f"{tag}: {n['news']}"})
        if n["cost"] != o["cost"]:
            changes.append({"at": at, "who": who, "kind": "price", "text": f"{tag}: £{o['cost']:.1f} → £{n['cost']:.1f}"})
        if n["rot"] != o.get("rot") and n["rot"]:
            changes.append({"at": at, "who": who, "kind": "rotation", "text": f"{tag}: new {n['rot']} risk on the Rotation tab"})
    history = ((prev or {}).get("history") or []) + changes
    return {"checked_at": at, "previous_check": (prev or {}).get("checked_at"), "watching": len(snap),
            "changes": changes, "history": history[-80:], "snapshot": snap}

def _clone_user_team(boot, team_id, ds, hist, chips_used, team):
    """Snapshot of the user's team right now for the AI team: the locked gameweek's 15 players at the
    prices actually paid (latest transfer in, ignoring Free Hit weeks; otherwise the start price), the
    bank, the free transfers banked for the next gameweek, and the chips already used."""
    import ai_team
    gw = ds.get("locked_gw")
    if not gw:
        return None
    els = {e["id"]: e for e in boot["elements"]}
    pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
    ids = [p["element"] for p in pk.get("picks", [])]
    if len(ids) != 15:
        return None
    fh = {c["event"] for c in (hist or {}).get("chips", []) if c.get("name") == "freehit"}
    paid = {}
    for t in sorted(get(f"https://fantasy.premierleague.com/api/entry/{team_id}/transfers/"), key=lambda t: (t.get("event") or 0, t.get("time") or "")):
        if t.get("event") not in fh:
            paid[t["element_in"]] = (t.get("element_in_cost") or 0) / 10
    buys = {i: paid.get(i) or (els[i]["now_cost"] - (els[i].get("cost_change_start") or 0)) / 10 for i in ids}
    sell = round(sum(ai_team.sell_price(buys[i], els[i]["now_cost"] / 10) for i in ids), 1)
    live_value = (team or {}).get("live_value")
    if live_value is not None and abs(sell - float(live_value)) > 0.05:
        _warn(f"ai_team clone: sell value {sell} differs from the dashboard's live value {live_value}")
    return {"gw": gw, "squad": ids, "buys": buys, "sell_value": sell, "bank": float(team.get("bank") or 0.0),
            "ft": free_transfers_for_next(hist or {}), "chips_used": dict(chips_used)}

def model_inputs(boot, team_recovery=None):
    """The extra signals the expected-points model uses: Understat chance volume per player and the daily
    risk checks (recent minutes, club rest, reported rotation). Shared by the AI team and the Plan tab so
    both rank players on the same numbers. Every part fails soft."""
    uwins = {}
    try:
        import understat
        matched, _ = understat.match_to_fpl(understat.player_windows(2026), boot)
        uwins = matched
    except Exception as e:
        _warn(f"model_inputs: Understat unavailable, continuing without it: {e}")
    def live(gw):
        return {el["id"]: {"minutes": int(el["stats"].get("minutes") or 0), "points": int(el["stats"].get("total_points") or 0)}
                for el in get(f"https://fantasy.premierleague.com/api/event/{gw}/live/").get("elements", [])}
    risk = {"recent_minutes": {}, "club_rest": {}, "rot_names": {}}
    try:
        fin = sorted(e["id"] for e in boot["events"] if e.get("finished"))[-3:]
        for g in fin:
            for eid, st in live(g).items():
                risk["recent_minutes"].setdefault(eid, []).append(st["minutes"])
    except Exception as e:
        _warn(f"model_inputs: recent minutes unavailable: {e}")
    try:
        short_to_id = {t["short_name"]: t["id"] for t in boot["teams"]}
        for club, rec in (team_recovery or {}).items():
            fol = rec.get("following_match") or {}
            risk["club_rest"][short_to_id[club]] = {"rest_days": rec.get("rest_days"), "turnaround": fol.get("days_after")}
    except Exception as e:
        _warn(f"model_inputs: club rest unavailable: {e}")
    try:
        risk["rot_names"] = _rotation_flagged_players(ROOT)
    except Exception as e:
        _warn(f"model_inputs: reported rotation unavailable: {e}")
    return uwins, risk, live

def run_ai_team(data, boot, team_id, ds, chips_used, gws, teams_by_id, team_recovery=None, hist=None, inputs=None):
    """Advance the AI team (ai_team.py) one refresh. It gets the same money (your squad's sell
    value + bank) and the same chip availability as you, and Understat chance volume as an extra
    signal when reachable. Never lets a failure here break the rest of the refresh."""
    import ai_team
    try:
        uwins, risk, live = inputs or model_inputs(boot, team_recovery)
        team = data.get("team") or {}
        clone = None
        if (data.get("ai_team") or {}).get("version") != ai_team.VERSION:      # only needed once, to make the copy
            clone = _clone_user_team(boot, team_id, ds, hist, chips_used, team)
        scan_cache = {}
        def fix_scan(gw):
            if gw not in scan_cache:
                scan_cache[gw] = fixture_scan(gw, teams_by_id)
            return scan_cache[gw]
        ctx = {"now": datetime.now(timezone.utc), "boot": boot, "deadline_state": ds, "fix_scan": fix_scan, "live": live, "risk": risk,
               "clone": clone, "user_points": {g["gw"]: g["points"] - (g.get("hits") or 0) for g in gws}, "uwins": uwins}
        return ai_team.update(data.get("ai_team"), ctx)
    except Exception as e:
        _warn(f"ai_team: update failed, keeping the previous state: {e}")
        return data.get("ai_team")
