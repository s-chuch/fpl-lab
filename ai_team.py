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
import math
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
MIN_FREE_GAIN = 0.6       # a free transfer must add at least this many points when a banked one would be lost anyway (already holding FT_CAP)
FREE_HURDLE = 1.5         # otherwise it must add this much: a banked free transfer buys a second swap next week that realised ~2.1-2.7 points in two seasons of history (calibrate_decisions.py)
FT_CAP = 5                # FPL lets 5 free transfers bank
HYSTERESIS = MIN_FREE_GAIN   # a new set of transfers must beat the previous (kept) one by this much to replace it
KEEP_FLOOR = FREE_HURDLE / 2   # kept moves that have decayed below this gain are dropped
KEEP_AVAIL = 0.75          # a kept "in" player below this fitness forces a re-plan
MIN_HIT_GAIN = HIT_COST + 1.5
MAX_HITS = 2
LEAGUE_AVG_TEAM_XG = 1.4   # goals per team per match, for scaling bookmaker goal expectations
HALF_SPLIT = 20            # chips reset at GW20
RESULT_VERSION = 2         # shape of a stored gameweek result; a settled result with an older one is rescored once (v2: subbed-off player kept on the bench)

# Expected-points model knobs (values unchanged; each is a judgement call, backtested by calibrate.py)
MINUTES_FALLING_FACTOR = 0.85   # a regular whose recent minutes fell well below his season share
MINUTES_FALLING_SHARE = 0.6     # ...recent share of minutes below this fraction of his season share
MINUTES_REGULAR_SEASON = 0.5    # ...only judged for players who have played at least this share of the season
MINUTES_BENCHED_BELOW = 45      # ...or whose last appearance was shorter than this
REST_FACTOR = 0.93              # next match is within CONGESTION_DAYS of the last one, or followed by another soon
CONGESTION_DAYS = 3
ROTATION_REPORTED_FACTOR = 0.8  # news says he is being rotated
EP_NEXT_WEIGHT = 0.2            # FPL's ep_next mostly repeats form, so it only gets a light weight
FDR_CS_BASE, FDR_CS_SLOPE, FDR_CS_RANGE = 0.40, 0.07, (0.08, 0.6)   # clean-sheet chance by difficulty rating
FDR_ATT_BASE, FDR_ATT_SLOPE = 1.12, 0.06                            # attacking returns by difficulty rating


def _load_doc():
    try:
        import json
        from pathlib import Path
        return json.loads((Path(__file__).resolve().parent / "learned.json").read_text())
    except (OSError, ValueError, AttributeError):
        return {}


def _load_learned():
    """The per-position correction learn.py wrote from this season's graded results (identity until there is enough evidence)."""
    return {p: v for p, v in (_load_doc().get("per_position") or {}).items() if v.get("applied")}


LEARNED_DOC = _load_doc()
LEARNED = _load_learned()


def learned_factor(label, prior):
    """A multiplier (rest / minutes / rotation) as this season's results measured it, else the hand-set constant (learn.fit_factors)."""
    f = (LEARNED_DOC.get("factors") or {}).get(label) or {}
    return f.get("factor", prior) if f.get("applied") else prior


def elite_weight():
    e = LEARNED_DOC.get("elite") or {}
    return e.get("own_weight", 0.4) if e.get("own_applied") else 0.4


def captain_elite_weight():
    e = LEARNED_DOC.get("elite") or {}
    return e.get("cap_weight", 0.0) if e.get("cap_applied") else 0.0


def hurdle_mult():
    t = LEARNED_DOC.get("transfers") or {}
    return t.get("mult", 1.0) if t.get("applied") else 1.0


def free_need(ft, n):
    """Points the n-th free transfer of a plan must add: low only when waiting would waste one (already at the bank cap), else FREE_HURDLE (x learned)."""
    return (MIN_FREE_GAIN if ft - n >= FT_CAP else FREE_HURDLE) * hurdle_mult()


def adjust_xp(pos, xp):
    """Expected points nudged by what this season's graded gameweeks showed (see learn.py): the per-position line, then the shift for the
    captain pool (players the model rates highest). 0 stays 0 (unavailable)."""
    if xp <= 0:
        return xp
    c = LEARNED.get(pos)
    if c:
        xp = max(0.0, c["a"] + c["b"] * xp)
    top = LEARNED_DOC.get("top") or {}
    if top.get("applied") and xp >= top.get("min_xp", 5.0):
        xp = max(0.0, xp + top.get("shift", 0.0))
    return xp


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def tenths(x):
    return int(round(float(x) * 10))


def sell_price(buy, now):
    """FPL sell rule, in whole tenths of a million (no float drift): you keep half of any profit
    since you bought (rounded down to 0.1m); if the price has dropped you take the full loss."""
    b, n = tenths(buy), tenths(now)
    return (b + (n - b) // 2 if n > b else n) / 10


# --------------------------------------------------------------------------- expected points
def availability(el):
    """0-1: how likely he is to play (see fitness.chance: next round, else this round, else the news text, else a doubt is 50%)."""
    import fitness
    pct, _src = fitness.chance(el)
    return max(0.0, min(1.0, pct / 100))


# League-typical per-90 rates by position. A season rate over only a few games is noisy, so each
# player's rate is shrunk towards these until they have ~900 minutes (ten full games).
PRIOR = {"GKP": {"xg": 0.0, "xa": 0.0, "cs": 0.30, "dc": 0.0}, "DEF": {"xg": 0.06, "xa": 0.05, "cs": 0.30, "dc": 8.0},
         "MID": {"xg": 0.15, "xa": 0.11, "cs": 0.30, "dc": 7.0}, "FWD": {"xg": 0.35, "xa": 0.09, "cs": 0.30, "dc": 4.0}}
SHRINK_MINUTES = 500.0     # a player's own rate has full weight after ~five full games (regulars' priors above)
DEFCON_THRESHOLD = {"DEF": 10.0, "MID": 12.0, "FWD": 12.0}   # defensive contributions per match for the +2 points


def model_xp(el, fixtures, gws_played, uwin=None, recent=None):
    """Expected points for one gameweek from the player's own numbers and the fixtures:
    minutes security x (appearance + attacking returns + clean sheet + saves - goals conceded + bonus).
    Everything per fixture, summed (double gameweek = two, blank = zero)."""
    if not fixtures:
        return 0.0
    pos = POS[el["element_type"]]
    mins = _f(el.get("minutes"))
    mp = min(1.0, mins / (90.0 * max(1, gws_played)))
    if recent and len(recent) >= 2:
        # what he has actually played in the last few finished gameweeks counts as much as the season
        mp = 0.5 * mp + 0.5 * min(1.0, sum(min(90, m) for m in recent) / (90.0 * len(recent)))
    w = min(1.0, mins / SHRINK_MINUTES)
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
    defcon = 0.0
    thr = DEFCON_THRESHOLD.get(pos)
    if thr:
        # chance of reaching the defensive-contribution threshold (+2): his own per-90 rate (shrunk to the
        # position's typical rate) against the threshold, as a logistic curve
        mu = w * _f(el.get("defensive_contribution_per_90")) + (1 - w) * pr["dc"]
        defcon = 2.0 / (1.0 + math.exp(-(mu - thr) / (0.18 * thr)))
    total = 0.0
    for fx in fixtures:
        fdr = fx.get("fdr") or 3
        fdr_cs = max(FDR_CS_RANGE[0], min(FDR_CS_RANGE[1], FDR_CS_BASE - FDR_CS_SLOPE * (fdr - 3)))
        fdr_att = FDR_ATT_BASE - FDR_ATT_SLOPE * fdr         # easier fixture -> a few more attacking returns
        # With bookmaker odds for this match (fplbase.ODDS) the market's clean-sheet chance and goal expectations replace
        # half of the difficulty-rating guess; without them (most fixtures) it is the rating alone, as before.
        if fx.get("cs") is not None:
            fdr_cs = 0.5 * fdr_cs + 0.5 * max(0.05, min(0.75, fx["cs"]))
        if fx.get("xg_for") is not None:
            fdr_att = 0.5 * fdr_att + 0.5 * max(0.6, min(1.6, fx["xg_for"] / LEAGUE_AVG_TEAM_XG))
        cs = 0.5 * cs90 + 0.5 * fdr_cs
        concede = xgc90 / 2 if pos in ("GKP", "DEF") else 0.0
        if fx.get("xg_against") is not None and pos in ("GKP", "DEF"):
            concede = 0.5 * concede + 0.5 * fx["xg_against"] / 2
        att = attack * fdr_att
        total += 1 + mp + att + cs * CS_PTS[pos] + saves - concede + bonus + defcon
    return total * mp


def model_outlook(el, fixtures, gws_played, uwin=None, recent=None):
    """The same ingredients as model_xp, kept apart: {mp, goals, assists, cs} for the fixtures given (expected goals and assists
    this gameweek, chance of a clean sheet, share of the game he is expected to play). Used for the Predictions card."""
    if not fixtures:
        return None
    pos = POS[el["element_type"]]
    mins = _f(el.get("minutes"))
    mp = min(1.0, mins / (90.0 * max(1, gws_played)))
    if recent and len(recent) >= 2:
        mp = 0.5 * mp + 0.5 * min(1.0, sum(min(90, m) for m in recent) / (90.0 * len(recent)))
    w = min(1.0, mins / SHRINK_MINUTES)
    pr = PRIOR[pos]
    xg90 = w * _f(el.get("expected_goals_per_90")) + (1 - w) * pr["xg"]
    xa90 = w * _f(el.get("expected_assists_per_90")) + (1 - w) * pr["xa"]
    if uwin and uwin.get("apps"):
        xg90 = 0.55 * xg90 + 0.45 * (uwin["xg"] / uwin["apps"])
        xa90 = 0.55 * xa90 + 0.45 * (uwin["xa"] / uwin["apps"])
    cs90 = w * _f(el.get("clean_sheets_per_90")) + (1 - w) * pr["cs"]
    goals = assists = 0.0
    p_cs_none = 1.0
    thr = DEFCON_THRESHOLD.get(pos)
    p_dc = 0.0
    if thr:     # chance of reaching the defensive-contribution threshold in a match he plays (same curve as model_xp)
        mu = w * _f(el.get("defensive_contribution_per_90")) + (1 - w) * pr["dc"]
        p_dc = 1.0 / (1.0 + math.exp(-(mu - thr) / (0.18 * thr)))
    p_dc_none = 1.0
    for fx in fixtures:
        fdr = fx.get("fdr") or 3
        fdr_cs = max(FDR_CS_RANGE[0], min(FDR_CS_RANGE[1], FDR_CS_BASE - FDR_CS_SLOPE * (fdr - 3)))
        fdr_att = FDR_ATT_BASE - FDR_ATT_SLOPE * fdr
        if fx.get("cs") is not None:
            fdr_cs = 0.5 * fdr_cs + 0.5 * max(0.05, min(0.75, fx["cs"]))
        if fx.get("xg_for") is not None:
            fdr_att = 0.5 * fdr_att + 0.5 * max(0.6, min(1.6, fx["xg_for"] / LEAGUE_AVG_TEAM_XG))
        goals += xg90 * fdr_att * mp
        assists += xa90 * fdr_att * mp
        p_cs_none *= 1 - (0.5 * cs90 + 0.5 * fdr_cs)
        p_dc_none *= 1 - p_dc * mp
    return {"mp": mp, "goals": goals, "assists": assists, "cs": 1 - p_cs_none, "defcon": 1 - p_dc_none}


def player_values(boot, fix_next, fix_after, gws_played, uwins=None, risk=None):
    """{element id: {xp, xp2, value, fixture label...}} for everyone; value = xp + weight * xp2."""
    out = {}
    risk = risk or {}
    rec = risk.get("recent_minutes") or {}
    club_rest = risk.get("club_rest") or {}
    rot_names = risk.get("rot_names") or {}
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    for el in boot["elements"]:
        av = availability(el)
        flags, factor, adjf = [], 1.0, []
        recent = rec.get(el["id"])
        if recent and len(recent) >= 2:
            season = min(1.0, _f(el.get("minutes")) / (90.0 * max(1, gws_played)))
            share = sum(min(90, m) for m in recent) / (90.0 * len(recent))
            if season >= MINUTES_REGULAR_SEASON and (share < MINUTES_FALLING_SHARE * season or recent[-1] < MINUTES_BENCHED_BELOW):
                flags.append(f"minutes falling ({' → '.join(str(m) for m in recent)})"); mf = learned_factor("minutes", MINUTES_FALLING_FACTOR); factor *= mf
                adjf.append({"why": flags[-1], "factor": mf, "label": "minutes"})
        cr = club_rest.get(el["team"]) or {}
        if cr.get("rest_days") is not None and cr["rest_days"] <= CONGESTION_DAYS:
            flags.append(f"only {cr['rest_days']}d rest before its next match"); rf = learned_factor("rest", REST_FACTOR); factor *= rf
            adjf.append({"why": flags[-1], "factor": rf, "label": "rest"})
        if cr.get("turnaround") is not None and cr["turnaround"] <= CONGESTION_DAYS:
            flags.append(f"plays again {cr['turnaround']}d after its next match"); rf = learned_factor("rest", REST_FACTOR); factor *= rf
            adjf.append({"why": flags[-1], "factor": rf, "label": "rest"})
        rot_txt = rot_names.get(f"id:{el['id']}") or rot_names.get(el["web_name"])
        if rot_txt:
            flags.append(f"rotation reported: {str(rot_txt)[:90]}"); of = learned_factor("rotation", ROTATION_REPORTED_FACTOR); factor *= of
            adjf.append({"why": flags[-1], "factor": of, "label": "rotation"})
        f1, f2 = fix_next.get(el["team"], []), fix_after.get(el["team"], [])
        uw = (uwins or {}).get(el["id"])
        m1 = model_xp(el, f1, gws_played, uw, recent) * av * factor
        ep = _f(el.get("ep_next"), None) if el.get("ep_next") not in (None, "") else None
        # ep_next mirrors recent form this season (a light recency nudge) and is per fixture, so it is scaled
        # by fitness and by the number of fixtures like the model's own figure
        xp1 = ((1 - EP_NEXT_WEIGHT) * m1 + EP_NEXT_WEIGHT * ep * factor * len(f1)) if ep is not None and f1 else m1      # FPL's ep_next already includes its own chance-of-playing
        if av == 0:
            xp1 = 0.0
        xp2 = model_xp(el, f2, gws_played, uw, recent) * (1.0 if av > 0.5 else av) * factor
        raw1 = xp1
        xp1, xp2 = adjust_xp(POS[el["element_type"]], xp1), adjust_xp(POS[el["element_type"]], xp2)
        label = " + ".join(f"{fx['opp']} ({fx['side']})" for fx in f1) or "Blank"
        out[el["id"]] = {
            "id": el["id"], "name": el["web_name"], "pos": POS[el["element_type"]], "team": el["team"],
            "club": teams[el["team"]], "cost": el["now_cost"] / 10, "xp": round(xp1, 2), "xp_raw": round(raw1, 2), "xp2": round(xp2, 2),
            "value": xp1 + NEXT_WEIGHT * xp2, "fixture": label, "fdr": (f1[0].get("fdr") if f1 else None),
            "avail": av, "status": el.get("status"), "news": el.get("news") or "", "owned": _f(el.get("selected_by_percent")),
            "risks": flags, "adj_factors": adjf,
        }
    return out


# --------------------------------------------------------------------------- lineups
def pick_xi(ids, vals, key="value"):
    """Best legal XI from 15 ids: one keeper, the position minimums, then best remaining. `key` is "value"
    (this + next gameweek, for transfer decisions) or "xp" (this gameweek only, for the lineup actually played)."""
    by = {p: sorted([i for i in ids if vals[i]["pos"] == p], key=lambda i: -vals[i][key]) for p in XI_MIN}
    xi = [by["GKP"][0]]
    counts = {"GKP": 1, "DEF": 0, "MID": 0, "FWD": 0}
    for p in ("DEF", "MID", "FWD"):
        for i in by[p][:XI_MIN[p]]:
            xi.append(i); counts[p] += 1
    rest = sorted([i for p in ("DEF", "MID", "FWD") for i in by[p] if i not in xi], key=lambda i: -vals[i][key])
    for i in rest:
        if len(xi) >= 11:
            break
        p = vals[i]["pos"]
        if counts[p] < XI_MAX[p]:
            xi.append(i); counts[p] += 1
    bench_gk = [i for i in by["GKP"][1:]]
    bench_out = sorted([i for i in ids if i not in xi and vals[i]["pos"] != "GKP"], key=lambda i: -vals[i][key])
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


def plan_transfers(squad, buys, bank, ft, vals, signals=None):
    """Best set of swaps from the current squad: free transfers must add MIN_FREE_GAIN each, hits
    must add MIN_HIT_GAIN each. Prices: sell at FPL sell value, buy at today's price."""
    squad = list(squad)
    moves, bank_now = [], bank
    hits = 0
    signals = signals or {}      # {id: {"adj", "reasons"}}: news, elite ownership, price momentum, set pieces (see ai_run)
    adj = lambda i: (signals.get(i) or {}).get("adj_ai", 0.0)
    for n in range(ft + MAX_HITS):
        cur = squad_score(squad, vals)
        top = (0.0, None, None, 0.0)
        for out in squad:
            sell = sell_price(buys.get(out, vals[out]["cost"]), vals[out]["cost"])
            for v in vals.values():
                if v["pos"] != vals[out]["pos"] or v["id"] in squad or v["avail"] <= 0:
                    continue
                if v["value"] + adj(v["id"]) <= vals[out]["value"] + adj(out) or v["cost"] > bank_now + sell + 1e-9:
                    continue
                if not _club_ok(squad, vals, v["id"], out):
                    continue
                gain = squad_score([v["id"] if i == out else i for i in squad], vals) - cur + adj(v["id"]) - adj(out)
                if gain > top[0]:
                    top = (gain, out, v["id"], sell)
        need = (free_need(ft, n) if n < ft else MIN_HIT_GAIN * hurdle_mult())
        if top[1] is None or top[0] < need:
            break
        gain, out, inn, sell = top
        moves.append({"out": out, "in": inn, "gain": round(gain, 2), "hit": n >= ft, "sell": sell,
                      "bought_at": buys.get(out, vals[out]["cost"]), "cost_in": vals[inn]["cost"],
                      "adj": round(adj(inn) - adj(out), 2), "reasons_in": (signals.get(inn) or {}).get("reasons", []),
                      "reasons_out": (signals.get(out) or {}).get("reasons", [])})
        bank_now = round((tenths(bank_now) + tenths(sell) - tenths(vals[inn]["cost"])) / 10, 1)
        buys = dict(buys); buys[inn] = vals[inn]["cost"]
        squad = [inn if i == out else i for i in squad]
        hits += 1 if n >= ft else 0
    return squad, moves, bank_now, hits, buys


def rescore_transfers(state, vals, prev_moves, signals=None):
    """Re-apply the previous plan's transfers (pairs of out_id -> in_id) to the carried squad with today's values
    and the same scoring plan_transfers uses. Returns (squad, moves, bank, hits, buys) like plan_transfers, or None
    if any move is no longer legal (out player gone, in player unavailable / unaffordable / club limit) or has
    decayed (gain below KEEP_FLOOR, in player under KEEP_AVAIL fitness)."""
    squad = [int(i) for i in state["squad"]]
    buys = {int(k): v for k, v in state["buys"].items()}
    bank_now, ft = state["bank"], state["ft"]
    signals = signals or {}
    adj = lambda i: (signals.get(i) or {}).get("adj_ai", 0.0)
    moves, hits = [], 0
    for n, (out, inn) in enumerate(prev_moves):
        if out not in squad or inn in squad or out not in vals or inn not in vals:
            return None
        if vals[inn]["avail"] <= 0 or vals[inn]["avail"] < KEEP_AVAIL or vals[inn]["pos"] != vals[out]["pos"]:
            return None
        sell = sell_price(buys.get(out, vals[out]["cost"]), vals[out]["cost"])
        if vals[inn]["cost"] > bank_now + sell + 1e-9 or not _club_ok(squad, vals, inn, out):
            return None
        cur = squad_score(squad, vals)
        gain = squad_score([inn if i == out else i for i in squad], vals) - cur + adj(inn) - adj(out)
        if gain < KEEP_FLOOR + (HIT_COST if n >= ft else 0):     # a kept -4 hit must still pay for itself
            return None
        moves.append({"out": out, "in": inn, "gain": round(gain, 2), "hit": n >= ft, "sell": sell,
                      "bought_at": buys.get(out, vals[out]["cost"]), "cost_in": vals[inn]["cost"],
                      "adj": round(adj(inn) - adj(out), 2), "reasons_in": (signals.get(inn) or {}).get("reasons", []),
                      "reasons_out": (signals.get(out) or {}).get("reasons", [])})
        bank_now = round((tenths(bank_now) + tenths(sell) - tenths(vals[inn]["cost"])) / 10, 1)
        buys = dict(buys); buys[inn] = vals[inn]["cost"]
        squad = [inn if i == out else i for i in squad]
        hits += 1 if n >= ft else 0
    return squad, moves, bank_now, hits, buys


def keep_previous(state, vals, prev, new_plan, signals=None):
    """Hysteresis: the rescored previous transfers (same shape as plan_transfers' result) if they should stay,
    else None. They stay while still legal and the fresh plan does not beat them by HYSTERESIS."""
    if set(_pairs(prev)) == set(_pairs(new_plan)):
        return None                      # nothing to keep: identical moves
    kept = rescore_transfers(state, vals, _pairs(prev), signals)
    if kept is None or _net_gain(new_plan["transfers"]) - _net_gain(kept[1]) >= HYSTERESIS:
        return None
    return kept


def _net_gain(moves):
    return sum(m["gain"] for m in moves) - HIT_COST * sum(1 for m in moves if m["hit"])


# --------------------------------------------------------------------------- plans
def _why(v, uwin, role):
    xp_txt = f"xP {v['xp']:.1f}"
    if v.get("adj_factors"):
        xp_txt += " (" + ", ".join(f"{a.get('label', 'adj')} ×{a['factor']:g}" for a in v["adj_factors"]) + ")"
    bits = [xp_txt, v["fixture"] + (f" FDR {v['fdr']}" if v["fdr"] else "")]
    if uwin and uwin.get("apps"):
        if v["pos"] != "GKP" and (uwin.get("sot") or uwin.get("big") or uwin.get("cc")):
            bits.append(f"{uwin.get('sot', 0)} SoT, {uwin.get('big', 0)} big chances, {uwin.get('cc', 0)} chances created in last {uwin['apps']}")
    if v["avail"] < 1:
        bits.append(f"{int(v['avail'] * 100)}% fit" + (f" ({v['news']})" if v["news"] else ""))
    bits.extend("risk: " + r for r in v.get("risks", []))
    return " · ".join(bits)


def make_plan(gw, deadline, vals, state, uwins, now, signals=None, forced=None):
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
        if forced is not None:       # hysteresis: the previous plan's transfers, rescored (see choose_transfers)
            squad, moves, bank, hits, buys = forced
        else:
            squad, moves, bank, hits, buys = plan_transfers([int(i) for i in state["squad"]], buys, state["bank"], ft_before, vals, signals)
    xi, bench = pick_xi(squad, vals, "xp")          # the lineup played is chosen on this gameweek's expected points
    cw = captain_elite_weight()       # 0 until this season's results show the top managers' captain choice adds something (learn.fit_elite)
    ranked = sorted(xi, key=lambda i: -(vals[i]["xp"] + cw * (vals[i].get("e_cap") or 0)))
    captain = ranked[0]
    vice = next((i for i in ranked[1:] if vals[i]["team"] != vals[captain]["team"]), ranked[1])
    ft_after = None if ft_before is None else max(0, ft_before - len(moves))
    plan.update({
        "squad": [{**{k: vals[i][k] for k in ("id", "name", "pos", "club", "cost", "xp", "fixture", "fdr", "avail")},
                   "news": vals[i]["news"], "risks": vals[i].get("risks", []), "adj_factors": vals[i].get("adj_factors", []),
                   "buy": buys.get(i, vals[i]["cost"]), "why": _why(vals[i], (uwins or {}).get(i), "")} for i in xi + bench],
        "xi": xi, "bench": bench, "captain": captain, "vice": vice, "formation": formation(xi, vals),
        "transfers": [{"out": vals[m["out"]]["name"], "out_id": m["out"], "in": vals[m["in"]]["name"], "in_id": m["in"],
                       "gain": m["gain"], "xp_in": vals[m["in"]]["xp"], "xp_out": vals[m["out"]]["xp"], "hit": m["hit"], "sell": m["sell"], "bought_at": m["bought_at"], "cost_in": m["cost_in"],
                       "adj": m.get("adj", 0), "reasons_in": m.get("reasons_in", []), "reasons_out": m.get("reasons_out", [])} for m in moves],
        "hits": hits, "hit_cost": hits * HIT_COST, "ft_before": ft_before, "ft_after": ft_after, "bank": bank,
        "squad_cost": round(sum(vals[i]["cost"] for i in squad), 1),
        # what the squad would sell for today (FPL profit-share rule) - the money that really counts
        "sell_value": round(sum(sell_price(buys.get(i, vals[i]["cost"]), vals[i]["cost"]) for i in squad), 1),
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
    subs, swaps = [], []
    # Until the gameweek is over a player on 0 minutes may simply not have kicked off yet: no auto-sub or
    # vice-captain promotion is applied (they would show up and then reverse), so the total is a floor.
    gk_bench = [b for b in bench if pos_of[b] == "GKP"] if final else []
    for b in gk_bench:
        starter = next((s for s in xi if pos_of[s] == "GKP"), None)
        if starter is not None and not played(starter) and played(b):
            xi[xi.index(starter)] = b; subs.append({"out": name_of[starter], "in": name_of[b]}); swaps.append((starter, b))
    for b in [b for b in bench if pos_of[b] != "GKP"] if final else []:
        if not played(b):
            continue
        for s in xi:
            if pos_of[s] == "GKP" or played(s):
                continue
            trial = [b if i == s else i for i in xi]
            if _valid_formation(trial, pos_of):
                xi = trial; subs.append({"out": name_of[s], "in": name_of[b]}); swaps.append((s, b)); break
    cap = plan["captain"] if (not final or played(plan["captain"]) or not played(plan["vice"])) else plan["vice"]
    mult = 3 if plan.get("chip") == "3xc" else 2
    came_on = {b for _, b in swaps}
    lines = [{"id": i, "name": name_of[i], "pos": pos_of[i], "pts": got(i), "mult": mult if i == cap else 1,
              "played": played(i), **({"sub": "in"} if i in came_on else {})} for i in xi]
    gross = sum(l["pts"] * l["mult"] for l in lines)
    bench_pts = sum(got(b) for b in bench if b not in xi)
    if plan.get("chip") == "bboost":
        gross += bench_pts                       # Bench Boost: the bench scores too
    went_off = {b: o for o, b in swaps}          # a player who came on leaves his slot on the bench to the one he replaced
    bench_lines = [{"id": o, "name": name_of[o], "pos": pos_of[o], "pts": got(o), "played": played(o), "off": True} if b in went_off else
                   {"id": b, "name": name_of[b], "pos": pos_of[b], "pts": got(b), "played": played(b)}
                   for b in bench for o in [went_off.get(b)]]
    return {"points": gross - plan.get("hit_cost", 0), "gross": gross, "hits": plan.get("hit_cost", 0),
            "captain": name_of[cap], "lines": lines, "autosubs": subs, "bench_pts": bench_pts, "bench_lines": bench_lines, "final": final,
            "provisional": not final}


# --------------------------------------------------------------------------- main entry
VERSION = 3   # v2: copy of the user's team; v3: same, with prices/sell values in exact tenths


def new_state(clone, start_gw, now):
    """The AI team begins as a snapshot of your team - same 15 players at the prices you paid, same
    bank, same free transfers, same chips, same points so far - and plays on its own from then on."""
    return {"version": VERSION, "start_gw": start_gw, "cloned_from_gw": clone["gw"], "cloned_at": now.isoformat(),
            "budget": round(clone["sell_value"] + clone["bank"], 1), "bank": round(clone["bank"], 1), "ft": int(clone["ft"]),
            "squad": [int(i) for i in clone["squad"]], "buys": {str(k): v for k, v in clone["buys"].items()},
            "chips_used": dict(clone["chips_used"]), "plan": None, "history": {}, "changes": []}


from ai_changes import _flag_text, _pairs, _move_text, _transfer_cause, diff_plans, _entry_pairs, merge_changes, watch_locked  # noqa: E402,F401  (split out; re-exported)


def apply_chips(plan, state, gw, deadline, ctx, gws_played, now):
    """Decide whether the AI plays a chip this gameweek (see ai_chips) and put it in the plan. Triple Captain and Bench Boost just
    flag the plan; Free Hit and Wildcard replace the squad (the Free Hit squad is not carried forward, see update)."""
    import ai_chips
    plan["chip_watch"] = {}
    if plan.get("initial"):
        return plan
    avail = ai_chips.available(state.get("chips_used"), gw)
    if not avail:
        return plan
    boot = ctx["boot"]
    events = {e["id"]: e for e in boot["events"]}
    gws = [g for g in range(gw, ai_chips.window_end(gw) + 1) if g in events][:ai_chips.HORIZON]
    vals_by_gw = [player_values(boot, ctx["fix_scan"](g), ctx["fix_scan"](g + 1) if g + 1 in events else {}, gws_played, ctx.get("uwins"), ctx.get("risk")) for g in gws]
    squad = [p["id"] for p in plan["squad"]]
    buys = {int(k): v for k, v in plan["buys"].items()}
    dec = ai_chips.decide(squad, buys, plan["bank"], gw, state.get("chips_used"), vals_by_gw)
    plan["chip_watch"] = dec["watch"]
    chip, vals = dec["chip"], vals_by_gw[0]
    if not chip:
        return plan
    info = {"name": ai_chips.NAMES[chip], "reason": dec["reason"]}
    if chip in ("3xc", "bboost"):
        plan["chip"], plan["chip_info"] = chip, info
        plan["xp_xi"] = round(plan["xp_xi"] + (vals[plan["captain"]]["xp"] if chip == "3xc" else sum(vals[i]["xp"] for i in plan["bench"])), 1)
        return plan
    old = [int(i) for i in state["squad"]]
    old_buys = {int(k): v for k, v in state["buys"].items()}
    new = dec["squad"]
    keep = [i for i in new if i in old]
    spend = sum(T_sell(old_buys, vals, i) for i in keep) + sum(vals[i]["cost"] for i in new if i not in old)
    bank = round(dec["money"] - spend, 1)
    if bank < -1e-9:
        return plan                                   # does not fit the money after all: keep the ordinary plan
    new_buys = {i: (old_buys.get(i, vals[i]["cost"]) if i in old else vals[i]["cost"]) for i in new}
    moves = ai_chips.moves_between(old, new, vals, old_buys)
    ft_before = state["ft"]
    newplan = make_plan(gw, deadline, vals, state, ctx.get("uwins"), now, ctx.get("signals"), forced=(new, moves, bank, 0, new_buys))
    newplan.update({"chip": chip, "chip_info": info, "chip_watch": dec["watch"], "ft_after": ft_before, "hits": 0, "hit_cost": 0})
    return newplan


def T_sell(buys, vals, i):
    return sell_price(buys.get(i, vals[i]["cost"]), vals[i]["cost"])


def update(state, ctx):
    """Advance the AI team one refresh. ctx keys: now (datetime, UTC), boot, deadline_state,
    fix_scan (callable gw -> {team: [fixtures]}), live (callable gw -> {id: {minutes, points}}),
    clone (your squad/bank/free transfers/chips at the moment of the copy), user_points ({gw: pts}),
    uwins ({id: window}), risk (daily-check inputs).
    Returns the new state (pure: input is not mutated)."""
    state = copy.deepcopy(state) if state else None
    now, boot, ds = ctx["now"], ctx["boot"], ctx["deadline_state"]
    events = {e["id"]: e for e in boot["events"]}
    target = ds.get("next_gw")
    if state is not None and state.get("version") != VERSION:
        state = None                     # an older AI team that was built from scratch: replace it with the copy
    if state is None:
        clone = ctx.get("clone")
        if not clone or not target or target < START_GW:
            return None
        state = new_state(clone, target, now)
    finished = {i for i, e in events.items() if e.get("finished")}
    settled = {i for i in finished if events[i].get("data_checked")}     # FPL can still adjust points until then
    gws_played = max(1, len(finished) + (1 if ds.get("locked_gw") and ds["locked_gw"] not in finished else 0))

    # 1. a plan whose deadline has passed becomes history and the carried squad
    plan = state.get("plan")
    if plan and (target is None or plan["gw"] < target):
        if not plan["locked"]:
            plan["locked"], plan["locked_at"] = True, now.isoformat()   # missed the window: freeze what we had
        state["history"][f"gw{plan['gw']}"] = plan
        if plan.get("chip"):
            import ai_chips
            state.setdefault("chips_used", {})[ai_chips.used_key(plan["chip"], plan["gw"])] = plan["gw"]
        if plan.get("chip") != "freehit":            # a Free Hit squad lasts one gameweek: the one before it comes back
            state["squad"] = [p["id"] for p in plan["squad"]]
            state["buys"] = plan["buys"]
            state["bank"] = plan["bank"]
        left = plan["ft_after"] if plan["ft_after"] is not None else 0
        state["ft"] = min(5, left + 1)
        state["plan"] = plan = None

    # 2. plan / lock the target gameweek, logging every change the daily check finds
    state.setdefault("changes", [])
    if target and target >= START_GW:
        deadline = datetime.fromisoformat(events[target]["deadline_time"].replace("Z", "+00:00"))
        lock_at = deadline - timedelta(hours=LOCK_HOURS)
        fix1, fix2 = ctx["fix_scan"](target), (ctx["fix_scan"](target + 1) if target + 1 in events else {})
        vals = player_values(boot, fix1, fix2, gws_played, ctx.get("uwins"), ctx.get("risk"))
        _el = ctx.get("elite") or {}
        for k, c in ((_el.get("cap") or {}).items() if _el.get("n") else []):      # what the top managers captained (their last locked gameweek)
            if int(k) in vals:
                vals[int(k)]["e_cap"] = round(c / _el["n"], 3)
        if not (plan and plan["locked"]):
            prev = plan
            ref = ctx.get("model_ref")
            plan = make_plan(target, deadline, vals, state, ctx.get("uwins"), now, ctx.get("signals"))
            if prev and prev["gw"] == target and not plan["initial"] and prev.get("transfers") is not None and prev.get("chip") not in ("freehit", "wildcard"):
                # hysteresis: keep the previous transfers (rescored on today's numbers) unless the fresh plan beats them
                kept = keep_previous(state, vals, prev, plan, ctx.get("signals"))
                if kept is not None:
                    plan = make_plan(target, deadline, vals, state, ctx.get("uwins"), now, ctx.get("signals"), forced=kept)
                    plan["kept_transfers"] = True
            try:
                plan = apply_chips(plan, state, target, deadline, ctx, gws_played, now)
            except Exception as e:                    # chips are an add-on: a failure here keeps the ordinary plan
                plan["chip_error"] = f"{type(e).__name__}: {str(e)[:120]}"
            if prev and prev["gw"] == target and (prev.get("chip") or None) != (plan.get("chip") or None):
                state["changes"].append({"at": now.isoformat(), "gw": target, "kind": "chip",
                                         "text": (f"Chip: {plan['chip_info']['reason']}" if plan.get("chip") else f"Chip: no longer playing {prev.get('chip')} this gameweek")})
            plan["model_ref"] = ref
            try:
                import ai_decisions
                plan["decisions"] = ai_decisions.build(plan, vals, state, ctx.get("signals"))
            except Exception as e:                    # an explanation is an add-on: a failure here never touches the plan
                plan["decisions_error"] = f"{type(e).__name__}: {str(e)[:120]}"
            if now >= lock_at:
                plan["locked"], plan["locked_at"] = True, now.isoformat()
            state["plan"] = plan
            if prev and prev["gw"] == target:
                state["changes"] = merge_changes(state["changes"], diff_plans(prev, plan, vals, now, ref))
        else:
            state["changes"] += watch_locked(plan, vals, now)

    # 3. score every played gameweek from live data
    for key, p in state["history"].items():
        gw = p["gw"]
        if p.get("result", {}).get("final") and p["result"].get("v") == RESULT_VERSION:
            continue
        try:
            live = ctx["live"](gw)
        except Exception:
            continue
        res = score_plan(p, live, gw in finished)
        res["final"] = gw in settled
        res["v"] = RESULT_VERSION
        p["result"] = res
        p["user_points"] = (ctx.get("user_points") or {}).get(gw)
    # 3b. look back at every settled gameweek once (and again if the top managers' picks only became public later)
    try:
        import ai_review
        reviews = state.setdefault("reviews", {})
        elite = ctx.get("elite")
        for p in state["history"].values():
            res = p.get("result") or {}
            if not res.get("final"):
                continue
            rv = reviews.get(str(p["gw"]))
            if rv is None or (not rv.get("elite") and elite and elite.get("gw") == p["gw"]):
                try:
                    reviews[str(p["gw"])] = ai_review.review(p, res, ctx["live"](p["gw"]), elite)
                except Exception:
                    pass
        state["review_totals"] = ai_review.totals(reviews)
    except Exception as e:                                   # the review is an add-on: it never breaks the plan
        state["review_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    h = state["history"].values()
    state["total_points"] = sum(p.get("result", {}).get("points", 0) for p in h)
    state["user_total"] = sum(p.get("user_points") or 0 for p in h)
    up = ctx.get("user_points") or {}
    state["baseline_points"] = sum(v for g, v in up.items() if g < state["start_gw"])   # copied from you
    state["season_points"] = state["baseline_points"] + state["total_points"]
    state["user_season"] = sum(up.values())
    # every chip is usable once per half, and the clone's chips_used is only the snapshot taken at the copy:
    # from GW20 on, the first-half plays no longer count
    second = (target or max(finished, default=0) + 1) >= HALF_SPLIT
    state["chips_available"] = [c for c in ("wildcard", "freehit", "bboost", "3xc")
                                if not state["chips_used"].get(c + "_h2" if second else c)]
    state["changes"] = [c for c in state["changes"] if c.get("kind") != "swap"][-60:]      # legacy per-player swap lines repeated the plan
    state["last_check"] = now.isoformat()
    state["generated_at"] = now.isoformat()
    return state
