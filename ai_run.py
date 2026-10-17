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
        allfx = get("https://fantasy.premierleague.com/api/fixtures/")
        def done(f):
            return bool(f.get("finished") or f.get("finished_provisional"))
        def clubs_over(gw):      # clubs whose every match in `gw` is over (FPL marks the whole gameweek finished only after its checks)
            fx = [f for f in allfx if f.get("event") == gw]
            return {t for f in fx for t in (f["team_h"], f["team_a"]) if all(done(x) for x in fx if t in (x["team_h"], x["team_a"]))}
        started = sorted(e["id"] for e in boot["events"] if e.get("finished") or any(f.get("event") == e["id"] and done(f) for f in allfx))[-3:]
        team_of = {e["id"]: e["team"] for e in boot["elements"]}
        for g in started:
            lv = live(g)
            over_ = clubs_over(g)
            played = {team_of[eid] for eid, st in lv.items() if st["minutes"] and eid in team_of} & over_
            for eid, st in lv.items():
                if team_of.get(eid) in played:      # a club's blank gameweek is not a rest; a club whose match is not over yet is skipped
                    risk["recent_minutes"].setdefault(eid, []).append(min(90, st["minutes"]))
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

def _model_ref():
    """Short git sha of the code that produced this run, so a changed AI plan can say which model update caused it."""
    import os, subprocess
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha[:7]
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5, cwd=str(ROOT)).stdout.strip() or None
    except Exception:
        return None


def run_ai_team(data, boot, team_id, ds, chips_used, gws, teams_by_id, team_recovery=None, hist=None, inputs=None, signals=None):
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
               "clone": clone, "user_points": {g["gw"]: g["points"] - (g.get("hits") or 0) for g in gws}, "uwins": uwins, "signals": signals, "model_ref": _model_ref()}
        return ai_team.update(data.get("ai_team"), ctx)
    except Exception as e:
        _warn(f"ai_team: update failed, keeping the previous state: {e}")
        return data.get("ai_team")


def run_planner(boot, team_id, ds, hist, chips_used, team, teams_by_id, inputs, signals=None):
    """Multi-gameweek transfer plan for your locked squad (planner.py), on the same model inputs as the AI team."""
    import planner
    clone = _clone_user_team(boot, team_id, ds, hist, chips_used, team)
    uwins, risk, _live = inputs
    cache = {}
    def fix_scan(gw):
        if gw not in cache:
            cache[gw] = fixture_scan(gw, teams_by_id)
        return cache[gw]
    return planner.build_planner(boot, clone, ds, fix_scan, uwins, risk, signals=signals)


def build_news_players(boot, ds, teams_by_id, inputs, news, they_share=(), mine=()):
    """The numbers to put beside each News theme's player: ownership, price, FPL status, the model's expected
    points and next fixture, plus whether you own him and whether 1st and 2nd both own him."""
    import ai_team
    from signals import _rotation_flagged_players  # noqa: F401  (kept for symmetry with model inputs)
    nxt = ds.get("next_gw")
    if not nxt:
        return {}
    uwins, risk, _live = inputs
    events = {e["id"]: e for e in boot["events"]}
    finished = sum(1 for e in boot["events"] if e.get("finished"))
    locked = ds.get("locked_gw")
    played = max(1, finished + (1 if locked and not events.get(locked, {}).get("finished") else 0))
    vals = ai_team.player_values(boot, fixture_scan(nxt, teams_by_id), {}, played, uwins, risk)
    by_key = {(e["web_name"], teams_by_id[e["team"]]["short_name"]): e["id"] for e in boot["elements"]}
    out = {}
    for it in (news.get("agreed") or []) + (news.get("split") or []):
        eid = it.get("id") or by_key.get((it.get("player"), it.get("club")))
        v = vals.get(eid)
        if not v:
            continue
        out[str(eid)] = {"name": v["name"], "club": v["club"], "pos": v["pos"], "cost": v["cost"], "owned": v["owned"], "xp": v["xp"],
                         "fixture": v["fixture"], "status": v["status"], "chance": int(v["avail"] * 100), "news": v["news"],
                         "yours": eid in mine, "top2": v["name"] in set(they_share)}
    return out


# --- everything the program knows, folded into transfer decisions ---------------------------------------------
# The expected-points model (xG/xA, minutes, fixtures, rotation, congestion, availability, DEFCON, Understat) already
# does the heavy lifting. These are the signals it does not contain. Each is a small, capped bonus in expected points,
# applied to the player being bought and (with the sign reversed) to the one being sold. They are judgement priors, not
# fitted values: every one is listed as a reason beside the move so you can see what tipped it.
ADJ_CAP = 1.2
NEWS_W = {"buy": 0.35, "captain": 0.30, "keep": 0.10, "monitor": 0.0, "mixed": 0.0, "sell": -0.35, "avoid": -0.35, "doubt": -0.25}
RULE_VERDICT = {"Leaning buy": "buy", "Captain candidate": "captain", "Leaning sell / avoid": "sell", "Leaning keep / hold": "keep",
                "Fitness or rotation doubts": "doubt"}


def build_transfer_signals(boot, news=None, elite=None, league=None, set_pieces=None):
    """{player id: {"adj": total, "adj_ai": total without the rivals component, "reasons": [...], "parts": {...}}}.
    news: news.js themes (with ids); elite: data["elite"]; league: {"counts": {id: n}, "n": members, "mode": defend|chase|climb};
    set_pieces: data["set_pieces"]."""
    sig = {}
    def put(eid, part, pts, reason):
        s = sig.setdefault(int(eid), {"parts": {}, "reasons": []})
        s["parts"][part] = round(pts, 2)
        s["reasons"].append(reason)
    # 1. what the articles recommend (Claude's read when present, else the rule-based verdict)
    for it in (news or {}).get("agreed", []) + (news or {}).get("split", []):
        if it.get("id") is None:
            continue
        llm = it.get("llm") or {}
        verdict = llm.get("verdict") or RULE_VERDICT.get(str(it.get("verdict", "")).split(" (")[0], ("mixed" if str(it.get("verdict", "")).startswith("Mixed") else None))
        if verdict == "no_view":
            verdict = None
        w = NEWS_W.get(verdict)
        if not w:
            continue
        sites = len(it.get("sources") or [])
        conf = {"high": 1.0, "medium": 0.8, "low": 0.5}.get(llm.get("confidence"), 0.7)
        scale = (1.0 if sites >= 3 else 0.6) * conf
        label = ("Claude: " if llm else "") + verdict
        put(it["id"], "news", w * scale, f"News ({sites} sites): {label}")
    # 2. what the best managers hold
    if (elite or {}).get("n"):
        for eid, c in (elite.get("own") or {}).items():
            pct = 100 * c / elite["n"]
            if pct >= 10:
                put(eid, "elite", 0.4 * min(1.0, pct / 50), f"Top-{elite['n']} own {round(pct)}%")
    # 3. price: buy before a rise, sell before a fall. FPL publishes its own progress towards a change and a likelihood bucket
    # (price_change_projections[0].likelihood: 4 = about to rise ... -4 = about to fall); transfer momentum is the fallback.
    total = boot.get("total_players") or 0
    for el in boot["elements"]:
        proj = (el.get("price_change_projections") or [None])[0]
        pct = el.get("price_change_percent")
        if proj is not None and pct not in (None, ""):
            lk = proj.get("likelihood") or 0
            if lk >= 3:
                put(el["id"], "price", 0.3, "Price likely to rise")
            elif lk == 2:
                put(el["id"], "price", 0.12, "Price may rise")
            elif lk <= -3:
                put(el["id"], "price", -0.3, "Price likely to fall")
            elif lk == -2:
                put(el["id"], "price", -0.12, "Price may fall")
            continue
        net = int(el.get("transfers_in_event") or 0) - int(el.get("transfers_out_event") or 0)
        owners = float(el.get("selected_by_percent") or 0) / 100 * total
        mom = net / owners * 100 if owners >= 1 else 0
        if abs(mom) >= 5 and abs(net) >= 5000:
            put(el["id"], "price", 0.3 if net > 0 else -0.3, f"Price {'rising' if net > 0 else 'falling'} ({net:+,} net transfers)")
    # 4. set-piece duties
    by_name = {}
    for el in boot["elements"]:
        by_name.setdefault((el["web_name"], el["team"]), el["id"])
    teams = {t["short_name"]: t["id"] for t in boot["teams"]}
    for row in (set_pieces or {}).get("rows", []):
        tid = teams.get(row["club"])
        for p in row.get("pens", []):
            eid = by_name.get((p["name"], tid))
            if eid:
                put(eid, "setpiece", 0.25, "Takes penalties")
        for kind, lbl in (("fks", "free kicks"), ("corners", "corners")):
            for p in row.get(kind, []):
                eid = by_name.get((p["name"], tid))
                if eid and "setpiece" not in sig.get(eid, {}).get("parts", {}):
                    put(eid, "setpiece", 0.1, f"Takes {lbl}")
    # 5. your rivals (you only): defend a lead with the template, chase with differentials
    if league and league.get("n"):
        n, mode = league["n"], league.get("mode")
        for el in boot["elements"]:
            c = (league.get("counts") or {}).get(el["id"], 0)
            share = c / n
            if mode == "defend":
                if share >= 0.4:
                    put(el["id"], "league", 0.3, f"{c}/{n} rivals own him (covers a lead)")
                elif share <= 0.1:
                    put(el["id"], "league", -0.2, "differential adds risk while you lead")
            else:
                if c <= 3 and share <= 0.25:
                    put(el["id"], "league", 0.4, f"only {c}/{n} rivals own him (differential)")
                elif share >= 0.5:
                    put(el["id"], "league", -0.1, f"{c}/{n} rivals own him (no gain on them)")
    for eid, s in sig.items():
        total_adj = sum(s["parts"].values())
        s["adj"] = round(max(-ADJ_CAP, min(ADJ_CAP, total_adj)), 2)
        s["adj_ai"] = round(max(-ADJ_CAP, min(ADJ_CAP, total_adj - s["parts"].get("league", 0))), 2)
    return sig


START_FLOOR = 0.50      # Target drops a player whose chance of starting is below this
START_WARN = 0.75       # ...and tags one below this ("might not start")
START_RECENT_W = (0.2, 0.3, 0.5)     # weights of his last three gameweeks, newest last


def rotation_start(mp, avail, factors):
    """The Predictions rotation list's number: share of minutes he normally plays x fitness x every factor the model applies
    (minutes falling, rest, reported rotation). Target uses the same figure, so the two pages agree."""
    f = 1.0
    for x in (factors or []):
        f *= x.get("factor", 1.0)
    return min(1.0, mp) * avail * f


def start_chance(el, recent, played, avail=1.0, factors=()):
    """Chance he is in the starting XI next gameweek: 40% his season starts per gameweek, 60% his last three gameweeks
    (a start = 60+ minutes; the latest counts most, so a game he did not play hurts), times his fitness and the
    reported-rotation / rest factors the model already applies. Not the same as minutes share: a sub who plays 30 minutes every week scores low."""
    season = min(1.0, (el.get("starts") or 0) / max(1, played))
    if recent and len(recent) >= 2:
        w = START_RECENT_W[-len(recent):]
        rec = sum(wi * (1.0 if m >= 60 else 0.0) for wi, m in zip(w, recent)) / sum(w)
        base = 0.4 * season + 0.6 * rec
    else:
        base = season
    f = 1.0
    for x in factors:
        if x.get("label") in ("rotation", "rest"):
            f *= x.get("factor", 1.0)
    return max(0.0, min(1.0, base * avail * f))


def enrich_with_model(data, boot, ds, teams_by_id, inputs, signals):
    """Put the expected-points model and the extra signals beside every scouting list (Target 1/3/6, transfer targets):
    each row gets `xp` (expected points over its horizon, or the next gameweek) and `sig` (the reasons behind its
    signal adjustment), so no list recommends a player the model and the other data disagree with unseen."""
    import ai_team
    uwins, risk, _live = inputs
    nxt = ds.get("next_gw")
    if not nxt:
        return
    events = {e["id"]: e for e in boot["events"]}
    gws = [g for g in range(nxt, nxt + 6) if g in events]
    finished = sum(1 for e in boot["events"] if e.get("finished"))
    locked = ds.get("locked_gw")
    played = max(1, finished + (1 if locked and not events.get(locked, {}).get("finished") else 0))
    per_gw = [ai_team.player_values(boot, fixture_scan(g, teams_by_id), {}, played, uwins, risk) for g in gws]
    by_key = {(e["web_name"], teams_by_id[e["team"]]["short_name"]): e["id"] for e in boot["elements"]}
    def xp_sum(eid, n):
        return round(sum((v.get(eid) or {}).get("xp", 0) for v in per_gw[:n]), 1)
    def annotate(row, n):
        eid = row.get("id") or by_key.get((row.get("name"), row.get("club")))
        if eid is None:
            return
        row["xp"] = xp_sum(eid, n)
        row["xp_n"] = min(n, len(per_gw))
        s = (signals or {}).get(eid)
        if s:
            row["sig"] = s["reasons"][:4]
            row["adj"] = s["adj"]
    els = {e["id"]: e for e in boot["elements"]}
    fx_next = fixture_scan(nxt, teams_by_id)
    rec_min = (risk or {}).get("recent_minutes") or {}
    def starts_of(r):
        eid = r.get("id") or by_key.get((r.get("name"), r.get("club")))
        v = (per_gw[0] if per_gw else {}).get(eid) or {}
        if eid not in els:
            return None
        s1 = start_chance(els[eid], rec_min.get(eid), played, v.get("avail", 1.0), v.get("adj_factors") or [])
        o = ai_team.model_outlook(els[eid], fx_next.get(els[eid]["team"], []), played, (uwins or {}).get(eid), rec_min.get(eid))
        if not o:
            return s1
        return min(s1, rotation_start(o["mp"], v.get("avail", 1.0), v.get("adj_factors") or []))      # the rotation list's own number
    def gate(rows):
        """Remove players unlikely to start and tag the doubtful ones, so Target does not recommend someone who sits on the bench."""
        keep = []
        for r in rows:
            s = starts_of(r)
            if s is not None:
                r["start"] = round(100 * s)
                if s < START_FLOOR:
                    continue
                if s < START_WARN:
                    r["why"] = list(r.get("why") or []) + [f"Rotation risk · starts ~{r['start']}%"]
            keep.append(r)
        return keep
    for key, h in ((data.get("targets") or {}).get("horizons") or {}).items():
        for r in h.get("top") or []:
            annotate(r, int(h.get("horizon") or key))
        h["top"] = gate(h.get("top") or [])
    for r in (data.get("targets") or {}).get("wc_top3") or []:
        annotate(r, 6)
    tt = data.get("transfer_targets") or {}
    for r in (tt.get("xg") or []) + (tt.get("defcon") or []):
        annotate(r, 1)


def build_predictions(boot, ds, teams_by_id, inputs, top_n=10, scale=None):
    """Next-gameweek predictions: the top `top_n` players likeliest to score, to assist and to reach the DEFCON threshold, the clubs
    likeliest to keep a clean sheet, plus rotation risks. Same inputs as the expected-points model; players who are out or unlikely
    to play are left out. `scale` ({category: factor}, from pred_track.calibration) corrects the probabilities for how the earlier
    predictions actually performed; `raw` keeps the uncorrected value so the correction can be judged later."""
    import ai_team, math
    scale = scale or {}
    uwins, risk, _live = inputs
    nxt = ds.get("next_gw")
    if not nxt:
        return {}
    events = {e["id"]: e for e in boot["events"]}
    finished = sum(1 for e in boot["events"] if e.get("finished"))
    locked = ds.get("locked_gw")
    played = max(1, finished + (1 if locked and not events.get(locked, {}).get("finished") else 0))
    fixtures = fixture_scan(nxt, teams_by_id)
    vals = ai_team.player_values(boot, fixtures, {}, played, uwins, risk)
    rec = (risk or {}).get("recent_minutes") or {}
    rows, club_cs = [], {}
    for el in boot["elements"]:
        v = vals.get(el["id"])
        fx = fixtures.get(el["team"], [])
        if not v or not fx:
            continue
        o = ai_team.model_outlook(el, fx, played, (uwins or {}).get(el["id"]), rec.get(el["id"]))
        if not o:
            continue
        pos = v["pos"]
        playing = v["avail"] > 0.5 and o["mp"] >= 0.5
        rows.append({"id": el["id"], "team": el["team"], "name": v["name"], "club": v["club"], "pos": pos, "fixture": v["fixture"], "avail": v["avail"],
                     "goals": o["goals"] * v["avail"], "assists": o["assists"] * v["avail"], "cs": o["cs"], "defcon": o["defcon"] * v["avail"],
                     "mp": o["mp"], "playing": playing, "risks": v["risks"], "factors": v.get("adj_factors") or [], "xp": v["xp"],
                     "cost": v["cost"], "own": float(el.get("selected_by_percent") or 0), "form": float(el.get("form") or 0), "minutes": int(el.get("minutes") or 0),
                     "xg90": float(el.get("expected_goals_per_90") or 0), "xa90": float(el.get("expected_assists_per_90") or 0),
                     "fdr": (fx[0].get("fdr") if fx else None), "home": 1 if fx and fx[0].get("side") == "H" else 0,
                     "vol": {k: int(((uwins or {}).get(el["id"]) or {}).get(k, 0)) for k in ("apps", "shots", "sot", "big", "cc", "big_cc")}})
        if pos in ("GKP", "DEF") and playing:
            club_cs.setdefault(v["club"], {"team": el["team"], "fixture": v["fixture"], "cs": [], "who": []})
            club_cs[v["club"]]["cs"].append(o["cs"])
            club_cs[v["club"]]["who"].append((v["xp"], v["name"]))
    def pct(x, cat):
        return round(100 * min(0.97, (1 - math.exp(-x)) * scale.get(cat, 1.0)))
    def raw(x):
        return round(100 * (1 - math.exp(-x)))
    def item(r, cat, val, extra):
        return {"id": r["id"], "name": r["name"], "club": r["club"], "pos": r["pos"], "fixture": r["fixture"], "p": pct(val, cat), "raw": raw(val), "vol": r.get("vol"), **extra}
    gpts = ai_team.GOAL_PTS
    for x in rows:
        x["ap"] = x["goals"] * gpts.get(x["pos"], 4) + x["assists"] * 3          # expected attacking points: goals x 4-6 + assists x 3
    aps = sorted((x for x in rows if x["playing"] and x["pos"] != "GKP"), key=lambda x: -x["ap"])[:top_n]
    gis = sorted((r for r in rows if r["playing"] and r["pos"] != "GKP"), key=lambda r: -(r["goals"] + r["assists"]))[:top_n]
    # every player's chances for the Target cards and the saved snapshot
    chances = {}
    for r in rows:
        if r["pos"] != "GKP" and r["xp"] >= 1.0:
            chances[f"{r['name']}|{r['club']}"] = [raw(r["goals"]), raw(r["assists"]), raw(r["goals"] + r["assists"])]
    scorers = sorted((r for r in rows if r["playing"] and r["pos"] != "GKP"), key=lambda r: -r["goals"])[:top_n]
    assisters = sorted((r for r in rows if r["playing"] and r["pos"] != "GKP"), key=lambda r: -r["assists"])[:top_n]
    dcs = sorted((r for r in rows if r["playing"] and r["pos"] != "GKP"), key=lambda r: -r["defcon"])[:top_n]
    sheets = []
    for c, d in club_cs.items():
        p = sum(d["cs"]) / len(d["cs"])
        sheets.append({"team": d["team"], "club": c, "fixture": d["fixture"], "p": round(100 * min(0.97, p * scale.get("clean_sheets", 1.0))), "raw": round(100 * p),
                       "who": [n for _x, n in sorted(d["who"], reverse=True)[:2]]})
    sheets = sorted(sheets, key=lambda r: -r["raw"])[:top_n]
    # rotation: players who matter (decent expected points) ranked by how likely they are NOT to play a full part this gameweek:
    # 1 - (share of minutes he normally plays x fitness x the rest / minutes-falling / reported-rotation factors the model applies)
    def start_prob(r):
        return rotation_start(r["mp"], r["avail"], r.get("factors"))
    for r in rows:
        r["start"] = start_prob(r)
    rot = sorted((r for r in rows if r["xp"] >= 3.0 and r["avail"] > 0.5 and 1 - r["start"] >= 0.15), key=lambda r: r["start"])[:top_n]
    return {
        "gw": nxt,
        "goals": [item(r, "goals", r["goals"], {"xg": round(r["goals"], 2)}) for r in scorers],
        "assists": [item(r, "assists", r["assists"], {"xa": round(r["assists"], 2)}) for r in assisters],
        "ap": [{"id": x["id"], "name": x["name"], "club": x["club"], "pos": x["pos"], "fixture": x["fixture"], "ap": round(x["ap"], 2), "xg": round(x["goals"], 2), "xa": round(x["assists"], 2)} for x in aps],
        "gi": [item(r, "gi", r["goals"] + r["assists"], {"xg": round(r["goals"], 2), "xa": round(r["assists"], 2)}) for r in gis],
        "defcon": [item(r, "defcon", -math.log(max(1e-9, 1 - min(0.999, r["defcon"]))), {}) for r in dcs],
        "chances": chances,
        "_rows": [r for r in rows if r["xp"] >= 1.0],
        "clean_sheets": sheets,
        "rotation": [{"id": r["id"], "team": r["team"], "name": r["name"], "club": r["club"], "pos": r["pos"], "fixture": r["fixture"], "rotate": round(100 * (1 - r["start"])), "start": round(100 * r["start"]),
                      "why": r["risks"][:2] or [f"has played {round(100 * min(1.0, r['mp']))}% of the minutes available"]} for r in rot],
        "scale": {c: s for c, s in scale.items() if s != 1.0},
    }


def build_swing_data(boot, ds, teams_by_id, plan, elo=None, horizon=8):
    """Club-by-club fixture swing for the next `horizon` open gameweeks (fixture_swing.py), highlighting the clubs your
    squad owns. `elo` is {club short name: rating} when Club Elo was reachable."""
    import fixture_swing
    nxt = ds.get("next_gw")
    if not nxt:
        return {}
    events = {e["id"] for e in boot["events"]}
    gws = [g for g in range(nxt, nxt + horizon) if g in events]
    scan = {g: fixture_scan(g, teams_by_id) for g in gws}
    owned = {}
    for row in (plan or {}).get("rows") or []:
        owned.setdefault(row[2], []).append(row[1])
    return fixture_swing.build_swing(boot, scan, owned, elo, form=_team_form(boot))


def _team_form(boot):
    """Goals scored / conceded per game for every club from the season's finished fixtures, shrunk towards the league
    mean (three games' worth), for attack/defence difficulty when FPL's own strength ratings are empty."""
    import fplbase
    fx = fplbase._fixtures_cache.get("all")
    if fx is None:
        fx = get("https://fantasy.premierleague.com/api/fixtures/")
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    gf, ga, n = {}, {}, {}
    for f in fx:
        if not f.get("finished") and not f.get("finished_provisional"):
            continue
        h, a, hs, as_ = f["team_h"], f["team_a"], f.get("team_h_score"), f.get("team_a_score")
        if hs is None or as_ is None:
            continue
        for t, s_for, s_against in ((h, hs, as_), (a, as_, hs)):
            gf[t] = gf.get(t, 0) + s_for; ga[t] = ga.get(t, 0) + s_against; n[t] = n.get(t, 0) + 1
    games = sum(n.values()) / 2 or 1
    mean = sum(gf.values()) / (2 * games) if gf else 1.4
    k = 3
    return {teams[t]: {"gf": (gf.get(t, 0) + mean * k) / (n.get(t, 0) + k), "ga": (ga.get(t, 0) + mean * k) / (n.get(t, 0) + k)} for t in teams}



def setup_odds(boot, ds, teams_by_id, horizon=8):
    """Fetch bookmaker odds (odds.py, football-data.co.uk) and register them for fixture_scan. Free odds cover only the next
    matchweek or so (and nothing during an international break), so most fixtures stay on the difficulty rating.
    Returns a small summary for data["odds"]."""
    import fplbase, odds
    fplbase.set_odds({})
    nxt = ds.get("next_gw")
    res = odds.fetch_odds(boot, cache_path=ROOT / "odds_cache.json")
    matches = res.get("matches") or []
    summary = {"matches": len(matches), "fetched_at": res.get("fetched_at"), "error": res.get("error"), "matched_fixtures": 0}
    if not matches or not nxt:
        return summary
    events = {e["id"] for e in boot["events"]}
    scan = {g: fplbase.fixture_scan(g, teams_by_id) for g in range(nxt, nxt + horizon) if g in events}
    by_gw = odds.by_team(res, scan, boot)
    fplbase.set_odds(by_gw)
    summary["matched_fixtures"] = sum(len(v) for g in by_gw.values() for v in g.values())
    summary["first"] = [{"home": m["home"], "away": m["away"], "date": m.get("date"), "p_home": m["p_home"], "p_draw": m["p_draw"], "p_away": m["p_away"],
                         "xg_home": m["xg_home"], "xg_away": m["xg_away"]} for m in matches[:12]]
    return summary
