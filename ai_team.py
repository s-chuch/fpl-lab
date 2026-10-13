"""AI team: a squad the program picks and plays by itself from the same information the
dashboard shows (FPL's expected points, our xG/xA model, fixtures, availability, Understat
chance volume). It starts at GW7 with the same money you have, keeps the same chips, plays a
full season of lineups, and is scored on real FPL points.

Timeline per gameweek (all driven by refresh runs):
  * Until LOCK_HOURS before the deadline the plan is recomputed every run ("what it plans to do").
  * At the first run LOCK_HOURS before the deadline the plan is recomputed one last time and
    LOCKED: transfers, lineup, bench order, captain and vice are fixed from then on.
  * After the deadline the locked plan becomes the squad it carries forward; once matches are
    played the points are computed from FPL's live data (auto-subs, captain, hits included).

Pure functions + a single `update()` entry point so it can be tested offline."""
from __future__ import annotations
import copy
from datetime import datetime, timedelta

POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
SQUAD_SIZE = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
XI_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
XI_MAX = {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}
GOAL_PTS = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}
CS_PTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
START_GW = 7
LOCK_HOURS = 12
HIT_COST = 4
NEXT_WEIGHT = 0.35        # weight of the gameweek after the target when scoring a squad
BENCH_WEIGHT = 0.18       # a bench player's xP counts this much towards the squad score
MIN_FREE_GAIN = 0.6       # a free transfer must add at least this many points
MIN_HIT_GAIN = HIT_COST + 1.5
MAX_HITS = 2


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def sell_price(buy, now):
    """FPL sell rule: half of any profit (rounded down to 0.1m) is kept; losses pass through."""
    if now <= buy:
        return round(now, 1)
    return round(buy + int((now - buy) * 10 / 2) / 10, 1)


# --------------------------------------------------------------------------- expected points
def availability(el):
    st = el.get("status")
    if st in ("u", "s", "i"):
        return 0.0
    chance = el.get("chance_of_playing_next_round")
    if chance is None:
        return 1.0 if st == "a" else 0.75
    return max(0.0, min(1.0, chance / 100))


# League-typical per-90 rates by position. A season rate over only a few games is noisy, so each
# player's rate is shrunk towards these until they have ~900 minutes (ten full games).
PRIOR = {"GKP": {"xg": 0.0, "xa": 0.0, "cs": 0.30}, "DEF": {"xg": 0.04, "xa": 0.05, "cs": 0.30},
         "MID": {"xg": 0.12, "xa": 0.10, "cs": 0.30}, "FWD": {"xg": 0.30, "xa": 0.10, "cs": 0.30}}


def model_xp(el, fixtures, gws_played, uwin=None):
    """Expected points for one gameweek from the player's own numbers and the fixtures:
    minutes security x (appearance + attacking returns + clean sheet + saves - goals conceded + bonus).
    Everything per fixture, summed (double gameweek = two, blank = zero)."""
    if not fixtures:
        return 0.0
    pos = POS[el["element_type"]]
    mins = _f(el.get("minutes"))
    mp = min(1.0, mins / (90.0 * max(1, gws_played)))
    w = min(1.0, mins / 900.0)
    pr = PRIOR[pos]
    xg90 = w * _f(el.get("expected_goals_per_90")) + (1 - w) * pr["xg"]
    xa90 = w * _f(el.get("expected_assists_per_90")) + (1 - w) * pr["xa"]
    if uwin and uwin.get("apps"):
        # recent shot/chance quality (Understat, last few appearances) blended with the season rate
        xg90 = 0.55 * xg90 + 0.45 * (uwin["xg"] / uwin["apps"])
        xa90 = 0.55 * xa90 + 0.45 * (uwin["xa"] / uwin["apps"])
    attack = xg90 * GOAL_PTS[pos] + xa90 * 3
    cs90 = w * _f(el.get("clean_sheets_per_90")) + (1 - w) * pr["cs"]
    xgc90 = _f(el.get("expected_goals_conceded_per_90"))
    saves = _f(el.get("saves_per_90")) / 3 if pos == "GKP" else 0.0
    bonus = _f(el.get("bonus")) / max(1, gws_played) * 0.5 * w
    total = 0.0
    for fx in fixtures:
        fdr = fx.get("fdr") or 3
        cs = 0.5 * cs90 + 0.5 * max(0.08, min(0.6, 0.40 - 0.07 * (fdr - 3)))
        concede = xgc90 / 2 if pos in ("GKP", "DEF") else 0.0
        att = attack * (1.12 - 0.06 * fdr)  # easier fixture -> a few more attacking returns
        total += 1 + mp + att + cs * CS_PTS[pos] + saves - concede + bonus
    return total * mp


def player_values(boot, fix_next, fix_after, gws_played, uwins=None):
    """{element id: {xp, xp2, value, fixture label...}} for everyone; value = xp + weight * xp2."""
    out = {}
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    for el in boot["elements"]:
        av = availability(el)
        f1, f2 = fix_next.get(el["team"], []), fix_after.get(el["team"], [])
        uw = (uwins or {}).get(el["id"])
        m1 = model_xp(el, f1, gws_played, uw) * av
        ep = _f(el.get("ep_next"), None) if el.get("ep_next") not in (None, "") else None
        xp1 = (0.8 * m1 + 0.2 * ep) if ep is not None and f1 else m1   # ep_next mirrors recent form this season: a light recency nudge
        if av == 0:
            xp1 = 0.0
        xp2 = model_xp(el, f2, gws_played, uw) * (1.0 if av > 0.5 else av)
        label = " + ".join(f"{fx['opp']} ({fx['side']})" for fx in f1) or "Blank"
        out[el["id"]] = {
            "id": el["id"], "name": el["web_name"], "pos": POS[el["element_type"]], "team": el["team"],
            "club": teams[el["team"]], "cost": el["now_cost"] / 10, "xp": round(xp1, 2), "xp2": round(xp2, 2),
            "value": xp1 + NEXT_WEIGHT * xp2, "fixture": label, "fdr": (f1[0].get("fdr") if f1 else None),
            "avail": av, "status": el.get("status"), "news": el.get("news") or "", "owned": _f(el.get("selected_by_percent")),
        }
    return out


# --------------------------------------------------------------------------- lineups
def pick_xi(ids, vals):
    """Best legal XI from 15 ids by value: one keeper, the position minimums, then best remaining."""
    by = {p: sorted([i for i in ids if vals[i]["pos"] == p], key=lambda i: -vals[i]["value"]) for p in XI_MIN}
    xi = [by["GKP"][0]]
    counts = {"GKP": 1, "DEF": 0, "MID": 0, "FWD": 0}
    for p in ("DEF", "MID", "FWD"):
        for i in by[p][:XI_MIN[p]]:
            xi.append(i); counts[p] += 1
    rest = sorted([i for p in ("DEF", "MID", "FWD") for i in by[p] if i not in xi], key=lambda i: -vals[i]["value"])
    for i in rest:
        if len(xi) >= 11:
            break
        p = vals[i]["pos"]
        if counts[p] < XI_MAX[p]:
            xi.append(i); counts[p] += 1
    bench_gk = [i for i in by["GKP"][1:]]
    bench_out = sorted([i for i in ids if i not in xi and vals[i]["pos"] != "GKP"], key=lambda i: -vals[i]["value"])
    return xi, bench_gk + bench_out


def squad_score(ids, vals):
    xi, bench = pick_xi(ids, vals)
    ranked = sorted(xi, key=lambda i: -vals[i]["value"])
    score = sum(vals[i]["value"] for i in xi) + vals[ranked[0]]["value"]  # captain doubles the best
    outfield_bench = [i for i in bench if vals[i]["pos"] != "GKP"][:3]
    # the tiny cost term breaks ties towards cheaper cover so spare money can be moved to the XI
    return score + BENCH_WEIGHT * sum(vals[i]["value"] for i in outfield_bench) - 0.004 * sum(vals[i]["cost"] for i in ids)


def formation(xi, vals):
    c = {"DEF": 0, "MID": 0, "FWD": 0}
    for i in xi:
        if vals[i]["pos"] in c:
            c[vals[i]["pos"]] += 1
    return f"{c['DEF']}-{c['MID']}-{c['FWD']}"


def _club_ok(ids, vals, new_id=None, drop_id=None):
    n = {}
    for i in ids:
        if i != drop_id:
            n[vals[i]["team"]] = n.get(vals[i]["team"], 0) + 1
    if new_id is not None:
        n[vals[new_id]["team"]] = n.get(vals[new_id]["team"], 0) + 1
    return all(v <= 3 for v in n.values())


# --------------------------------------------------------------------------- squad building
def build_squad(vals, budget):
    """Initial 15 within `budget`. Bench first: the best playing 4.0-4.6m outfield cover and the
    cheapest sensible second keeper, so the money goes where points are. Then the rest by
    Lagrangian greedy (value - lambda * price, bisecting lambda so the cost fits), then repeated
    best-improvement swaps over the whole squad until nothing improves."""
    pool = [v for v in vals.values() if v["avail"] > 0 and v["cost"] > 0]
    fodder = []
    gk_min = min(v["cost"] for v in pool if v["pos"] == "GKP")
    gk2 = sorted((v for v in pool if v["pos"] == "GKP" and v["cost"] <= gk_min + 0.5), key=lambda v: -v["value"])
    if gk2:
        fodder.append(gk2[0]["id"])
    cover = sorted((v for v in pool if v["pos"] in ("DEF", "MID") and v["cost"] <= 4.6 and v["avail"] >= 0.9 and v["xp"] > 0),
                   key=lambda v: -v["value"])
    clubs0 = {}
    for v in ([vals[i] for i in fodder] + cover):
        if len([i for i in fodder if vals[i]["pos"] != "GKP"]) >= 3:
            break
        if v["id"] in fodder or clubs0.get(v["team"], 0) >= 2:
            continue
        fodder.append(v["id"]); clubs0[v["team"]] = clubs0.get(v["team"], 0) + 1
    need = dict(SQUAD_SIZE)
    for i in fodder:
        need[vals[i]["pos"]] -= 1
    fod_cost = sum(vals[i]["cost"] for i in fodder)
    fod_clubs = {}
    for i in fodder:
        fod_clubs[vals[i]["team"]] = fod_clubs.get(vals[i]["team"], 0) + 1

    def greedy(lam):
        chosen, clubs = [], dict(fod_clubs)
        for pos, k in need.items():
            cand = sorted((v for v in pool if v["pos"] == pos and v["id"] not in fodder), key=lambda v: -(v["value"] - lam * v["cost"]))
            n = 0
            for v in cand:
                if n >= k:
                    break
                if clubs.get(v["team"], 0) >= 3:
                    continue
                chosen.append(v["id"]); clubs[v["team"]] = clubs.get(v["team"], 0) + 1; n += 1
        return chosen

    lo, hi = 0.0, 4.0
    best = greedy(hi)
    for _ in range(30):
        mid = (lo + hi) / 2
        g = greedy(mid)
        if sum(vals[i]["cost"] for i in g) + fod_cost <= budget + 1e-9:
            best, hi = g, mid
        else:
            lo = mid
    squad = list(best) + fodder
    cands = [v for v in pool if v["value"] > 0.4]
    for _ in range(80):
        cur = squad_score(squad, vals)
        spent = sum(vals[i]["cost"] for i in squad)
        top = (0.0, None, None)
        for out in squad:
            for v in cands:
                if v["pos"] != vals[out]["pos"] or v["id"] in squad:
                    continue
                if spent - vals[out]["cost"] + v["cost"] > budget + 1e-9:
                    continue
                if not _club_ok(squad, vals, v["id"], out):
                    continue
                new = [v["id"] if i == out else i for i in squad]
                gain = squad_score(new, vals) - cur
                if gain > top[0] + 1e-9:
                    top = (gain, out, v["id"])
        if top[1] is None or top[0] < 0.003:
            break
        squad = [top[2] if i == top[1] else i for i in squad]
    # Pair moves: one swap alone can't shift money (cheapen one slot to fund an upgrade elsewhere).
    top_by_pos = {pos: sorted((v for v in cands if v["pos"] == pos), key=lambda v: -v["value"])[:35] for pos in SQUAD_SIZE}
    cheap_by_pos = {pos: sorted((v for v in cands if v["pos"] == pos), key=lambda v: v["cost"])[:25] for pos in SQUAD_SIZE}
    for _ in range(4):
        cur = squad_score(squad, vals)
        spent = sum(vals[i]["cost"] for i in squad)
        best = (0.003, None)
        for a in squad:
            for down in cheap_by_pos[vals[a]["pos"]]:
                if down["id"] in squad or down["cost"] >= vals[a]["cost"] or not _club_ok(squad, vals, down["id"], a):
                    continue
                s1 = [down["id"] if i == a else i for i in squad]
                spent1 = spent - vals[a]["cost"] + down["cost"]
                for b in s1:
                    if b == down["id"]:
                        continue
                    for up in top_by_pos[vals[b]["pos"]]:
                        if up["id"] in s1 or up["cost"] <= vals[b]["cost"]:
                            continue
                        if spent1 - vals[b]["cost"] + up["cost"] > budget + 1e-9 or not _club_ok(s1, vals, up["id"], b):
                            continue
                        gain = squad_score([up["id"] if i == b else i for i in s1], vals) - cur
                        if gain > best[0]:
                            best = (gain, [up["id"] if i == b else i for i in s1])
        if best[1] is None:
            break
        squad = best[1]
    return squad


def plan_transfers(squad, buys, bank, ft, vals):
    """Best set of swaps from the current squad: free transfers must add MIN_FREE_GAIN each, hits
    must add MIN_HIT_GAIN each. Prices: sell at FPL sell value, buy at today's price."""
    squad = list(squad)
    moves, bank_now = [], bank
    hits = 0
    for n in range(ft + MAX_HITS):
        cur = squad_score(squad, vals)
        top = (0.0, None, None, 0.0)
        for out in squad:
            sell = sell_price(buys.get(out, vals[out]["cost"]), vals[out]["cost"])
            for v in vals.values():
                if v["pos"] != vals[out]["pos"] or v["id"] in squad or v["avail"] <= 0:
                    continue
                if v["value"] <= vals[out]["value"] or v["cost"] > bank_now + sell + 1e-9:
                    continue
                if not _club_ok(squad, vals, v["id"], out):
                    continue
                gain = squad_score([v["id"] if i == out else i for i in squad], vals) - cur
                if gain > top[0]:
                    top = (gain, out, v["id"], sell)
        need = MIN_FREE_GAIN if n < ft else MIN_HIT_GAIN
        if top[1] is None or top[0] < need:
            break
        gain, out, inn, sell = top
        moves.append({"out": out, "in": inn, "gain": round(gain, 2), "hit": n >= ft})
        bank_now = round(bank_now + sell - vals[inn]["cost"], 1)
        buys = dict(buys); buys[inn] = vals[inn]["cost"]
        squad = [inn if i == out else i for i in squad]
        hits += 1 if n >= ft else 0
    return squad, moves, bank_now, hits, buys


# --------------------------------------------------------------------------- plans
def _why(v, uwin, role):
    bits = [f"xP {v['xp']:.1f}", v["fixture"] + (f" FDR {v['fdr']}" if v["fdr"] else "")]
    if uwin and uwin.get("apps"):
        if v["pos"] != "GKP" and (uwin.get("sot") or uwin.get("big") or uwin.get("cc")):
            bits.append(f"{uwin.get('sot', 0)} SoT, {uwin.get('big', 0)} big chances, {uwin.get('cc', 0)} chances created in last {uwin['apps']}")
    if v["avail"] < 1:
        bits.append(f"{int(v['avail'] * 100)}% fit" + (f" ({v['news']})" if v["news"] else ""))
    return " · ".join(bits)


def make_plan(gw, deadline, vals, state, uwins, now):
    """Compute (not lock) the plan for `gw` from the carried squad (or build the initial one)."""
    initial = not state.get("squad")
    plan = {"gw": gw, "deadline": deadline.isoformat(), "lock_at": (deadline - timedelta(hours=LOCK_HOURS)).isoformat(),
            "locked": False, "locked_at": None, "computed_at": now.isoformat(), "initial": initial}
    if initial:
        squad = build_squad(vals, state["budget"])
        spent = round(sum(vals[i]["cost"] for i in squad), 1)
        buys = {i: vals[i]["cost"] for i in squad}
        bank, moves, hits, ft_before = round(state["budget"] - spent, 1), [], 0, None
    else:
        ft_before = state["ft"]
        buys = {int(k): v for k, v in state["buys"].items()}
        squad, moves, bank, hits, buys = plan_transfers([int(i) for i in state["squad"]], buys, state["bank"], ft_before, vals)
    xi, bench = pick_xi(squad, vals)
    ranked = sorted(xi, key=lambda i: -vals[i]["value"])
    captain = ranked[0]
    vice = next((i for i in ranked[1:] if vals[i]["team"] != vals[captain]["team"]), ranked[1])
    ft_after = None if ft_before is None else max(0, ft_before - len(moves))
    plan.update({
        "squad": [{**{k: vals[i][k] for k in ("id", "name", "pos", "club", "cost", "xp", "fixture", "fdr", "avail")},
                   "buy": buys.get(i, vals[i]["cost"]), "why": _why(vals[i], (uwins or {}).get(i), "")} for i in xi + bench],
        "xi": xi, "bench": bench, "captain": captain, "vice": vice, "formation": formation(xi, vals),
        "transfers": [{"out": vals[m["out"]]["name"], "out_id": m["out"], "in": vals[m["in"]]["name"], "in_id": m["in"],
                       "gain": m["gain"], "hit": m["hit"]} for m in moves],
        "hits": hits, "hit_cost": hits * HIT_COST, "ft_before": ft_before, "ft_after": ft_after, "bank": bank,
        "squad_cost": round(sum(vals[i]["cost"] for i in squad), 1),
        "xp_xi": round(sum(vals[i]["xp"] for i in xi) + vals[captain]["xp"], 1), "chip": None,
        "buys": {str(k): v for k, v in buys.items()},
    })
    return plan


# --------------------------------------------------------------------------- scoring
def _valid_formation(xi, pos_of):
    c = {"GKP": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for i in xi:
        c[pos_of[i]] += 1
    return c["GKP"] == 1 and all(c[p] >= XI_MIN[p] for p in XI_MIN) and all(c[p] <= XI_MAX[p] for p in XI_MAX)


def score_plan(plan, live, final):
    """Points the locked plan made, using FPL's live minutes/points, with FPL auto-sub and
    captaincy rules. `live` is {id: {"minutes", "points"}}."""
    pos_of = {p["id"]: p["pos"] for p in plan["squad"]}
    name_of = {p["id"]: p["name"] for p in plan["squad"]}
    got = lambda i: (live.get(i) or {}).get("points", 0)
    played = lambda i: ((live.get(i) or {}).get("minutes", 0) or 0) > 0
    xi, bench = list(plan["xi"]), list(plan["bench"])
    subs = []
    gk_bench = [b for b in bench if pos_of[b] == "GKP"]
    for b in gk_bench:
        starter = next((s for s in xi if pos_of[s] == "GKP"), None)
        if starter is not None and not played(starter) and played(b):
            xi[xi.index(starter)] = b; subs.append({"out": name_of[starter], "in": name_of[b]})
    for b in [b for b in bench if pos_of[b] != "GKP"]:
        if not played(b):
            continue
        for s in xi:
            if pos_of[s] == "GKP" or played(s):
                continue
            trial = [b if i == s else i for i in xi]
            if _valid_formation(trial, pos_of):
                xi = trial; subs.append({"out": name_of[s], "in": name_of[b]}); break
    cap = plan["captain"] if played(plan["captain"]) or not played(plan["vice"]) else plan["vice"]
    mult = 3 if plan.get("chip") == "3xc" else 2
    lines = [{"id": i, "name": name_of[i], "pos": pos_of[i], "pts": got(i), "mult": mult if i == cap else 1,
              "played": played(i)} for i in xi]
    gross = sum(l["pts"] * l["mult"] for l in lines)
    bench_pts = sum(got(b) for b in bench if b not in xi)
    return {"points": gross - plan.get("hit_cost", 0), "gross": gross, "hits": plan.get("hit_cost", 0),
            "captain": name_of[cap], "lines": lines, "autosubs": subs, "bench_pts": bench_pts, "final": final}


# --------------------------------------------------------------------------- main entry
def new_state(budget, chips_used):
    return {"version": 1, "start_gw": START_GW, "budget": round(budget, 1), "bank": round(budget, 1), "ft": 0,
            "squad": [], "buys": {}, "chips_used": dict(chips_used), "plan": None, "history": {}}


def update(state, ctx):
    """Advance the AI team one refresh. ctx keys: now (datetime, UTC), boot, deadline_state,
    fix_scan (callable gw -> {team: [fixtures]}), live (callable gw -> {id: {minutes, points}}),
    budget (user's sell value + bank), chips_used (user's), user_points ({gw: pts}), uwins ({id: window}).
    Returns the new state (pure: input is not mutated)."""
    state = copy.deepcopy(state) if state else None
    now, boot, ds = ctx["now"], ctx["boot"], ctx["deadline_state"]
    events = {e["id"]: e for e in boot["events"]}
    target = ds.get("next_gw")
    if state is None:
        if not target or target < START_GW:
            return None
        state = new_state(ctx["budget"], ctx["chips_used"])
    finished = {i for i, e in events.items() if e.get("finished")}
    gws_played = max(1, len(finished) + (1 if ds.get("locked_gw") and ds["locked_gw"] not in finished else 0))

    # 1. a plan whose deadline has passed becomes history and the carried squad
    plan = state.get("plan")
    if plan and (target is None or plan["gw"] < target):
        if not plan["locked"]:
            plan["locked"], plan["locked_at"] = True, now.isoformat()   # missed the window: freeze what we had
        state["history"][f"gw{plan['gw']}"] = plan
        state["squad"] = [p["id"] for p in plan["squad"]]
        state["buys"] = plan["buys"]
        state["bank"] = plan["bank"]
        left = plan["ft_after"] if plan["ft_after"] is not None else 0
        state["ft"] = min(5, left + 1)
        state["plan"] = plan = None

    # 2. plan / lock the target gameweek
    if target and target >= START_GW:
        deadline = datetime.fromisoformat(events[target]["deadline_time"].replace("Z", "+00:00"))
        lock_at = deadline - timedelta(hours=LOCK_HOURS)
        if not (plan and plan["locked"]):
            fix1, fix2 = ctx["fix_scan"](target), (ctx["fix_scan"](target + 1) if target + 1 in events else {})
            vals = player_values(boot, fix1, fix2, gws_played, ctx.get("uwins"))
            plan = make_plan(target, deadline, vals, state, ctx.get("uwins"), now)
            if now >= lock_at:
                plan["locked"], plan["locked_at"] = True, now.isoformat()
            state["plan"] = plan

    # 3. score every played gameweek from live data
    for key, p in state["history"].items():
        gw = p["gw"]
        if p.get("result", {}).get("final"):
            continue
        try:
            live = ctx["live"](gw)
        except Exception:
            continue
        p["result"] = score_plan(p, live, gw in finished)
        p["user_points"] = (ctx.get("user_points") or {}).get(gw)
    h = state["history"].values()
    state["total_points"] = sum(p.get("result", {}).get("points", 0) for p in h)
    state["user_total"] = sum(p.get("user_points") or 0 for p in h)
    state["chips_available"] = [c for c in ("wildcard", "freehit", "bboost", "3xc") if not (ctx["chips_used"] or {}).get(c)]
    state["generated_at"] = now.isoformat()
    return state
