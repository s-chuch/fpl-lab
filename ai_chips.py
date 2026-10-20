"""Chip decisions for the AI team: when to play Triple Captain, Bench Boost, Free Hit and the Wildcard.

Every refresh (until the plan locks) each chip the AI still holds is scored for this gameweek and for the next few
(inside the current half: chips reset at GW20), using the same expected points as everything else:

  Triple Captain  extra points = the captain's expected points (a third multiple)
  Bench Boost     extra points = the four bench players' expected points
  Free Hit        best 15-player squad for this one gameweek (within the money) minus the current XI's expected points;
                  the squad reverts afterwards
  Wildcard        best 15 for the next six gameweeks minus the current squad over the same six, minus what normal transfers
                  would add anyway (WC_BASELINE)

A chip is played now when its gain reaches a minimum worth spending it on AND is not clearly beaten by a later gameweek in
the window (NEAR_BEST), or when it is the last gameweek of the half (use it or lose it; the bar drops in the final
LATE_GWS gameweeks). Only one chip per gameweek: the one furthest above its minimum. Pure functions, no I/O."""
from __future__ import annotations
import ai_team as T

MIN_GAIN = {"3xc": 9.0, "bboost": 17.0, "freehit": 15.0, "wildcard": 20.0}   # a normal week gives ~6 (captain) / ~12 (bench): these need a double gameweek or a blank
NEAR_BEST = 0.92            # play now if today's gain is at least this share of the best gain later in the window
LATE_GWS = 4                # in the last N gameweeks of a half the minimum is relaxed...
LATE_FACTOR = 0.6           # ...to this share
HORIZON = 6                 # how far ahead chips are scored (never past the end of the half)
WC_BASELINE = 8.0           # points normal transfers would add over the horizon without a wildcard
WC_WEIGHTS = (1.0, 1.0, 1.0, 0.9, 0.8, 0.7)
LAST_GW = 38
NAMES = {"3xc": "Triple Captain", "bboost": "Bench Boost", "freehit": "Free Hit", "wildcard": "Wildcard"}


def window_end(gw):
    return T.HALF_SPLIT - 1 if gw < T.HALF_SPLIT else LAST_GW


def available(chips_used, gw):
    """Chips not yet played in this gameweek's half (the first-half plays stop counting from GW20)."""
    second = gw >= T.HALF_SPLIT
    return [c for c in ("wildcard", "freehit", "bboost", "3xc") if not (chips_used or {}).get(c + "_h2" if second else c)]


def used_key(chip, gw):
    return chip + "_h2" if gw >= T.HALF_SPLIT else chip


def xi_total(ids, vals):
    """Expected points of the best XI for one gameweek, captain doubled."""
    xi, _ = T.pick_xi(list(ids), vals, "xp")
    xs = [vals[i]["xp"] for i in xi]
    return sum(xs) + (max(xs) if xs else 0.0)


def tc_gain(ids, vals):
    xi, _ = T.pick_xi(list(ids), vals, "xp")
    return max((vals[i]["xp"] for i in xi), default=0.0)


def bb_gain(ids, vals):
    _, bench = T.pick_xi(list(ids), vals, "xp")
    return sum(vals[i]["xp"] for i in bench)


def _as(vals, key_fn):
    return {i: {**v, "value": key_fn(i, v)} for i, v in vals.items()}


def fh_squad(ids, vals, budget):
    """(gain, squad): the best 15 for this gameweek alone against the current squad."""
    sq = T.build_squad(_as(vals, lambda i, v: v["xp"]), budget)
    return xi_total(sq, vals) - xi_total(ids, vals), sq


def horizon_total(ids, vals_list, weights=WC_WEIGHTS):
    return sum(w * xi_total(ids, v) for w, v in zip(weights, vals_list))


def wc_squad(ids, vals_list, budget, weights=WC_WEIGHTS):
    """(gain, squad): best 15 over the horizon against the current squad, less WC_BASELINE."""
    w = weights[:len(vals_list)]
    comb = {i: {**v, "value": sum(wi * vl[i]["xp"] for wi, vl in zip(w, vals_list) if i in vl)} for i, v in vals_list[0].items()}
    sq = T.build_squad(comb, budget)
    return horizon_total(sq, vals_list, w) - horizon_total(ids, vals_list, w) - WC_BASELINE, sq


def moves_between(old, new, vals, buys):
    """Pair up who leaves and who arrives, position by position, for display and for the carried squad."""
    out, moves = [i for i in old if i not in new], []
    inn = [i for i in new if i not in old]
    for pos in ("GKP", "DEF", "MID", "FWD"):
        o = sorted([i for i in out if vals[i]["pos"] == pos], key=lambda i: vals[i]["xp"])
        n = sorted([i for i in inn if vals[i]["pos"] == pos], key=lambda i: vals[i]["xp"])
        for a, b in zip(o, n):
            sell = T.sell_price(buys.get(a, vals[a]["cost"]), vals[a]["cost"])
            moves.append({"out": a, "in": b, "gain": round(vals[b]["xp"] - vals[a]["xp"], 2), "hit": False, "sell": sell,
                          "bought_at": buys.get(a, vals[a]["cost"]), "cost_in": vals[b]["cost"], "adj": 0.0, "reasons_in": [], "reasons_out": []})
    return moves


def decide(squad, buys, bank, gw, chips_used, vals_by_gw):
    """vals_by_gw: [player_values for gw, gw+1, ...] (already cut at the end of the half). Returns
    {"chip": name|None, "reason": str, "watch": {chip: {...}}, "squad": [...]|None}."""
    avail = available(chips_used, gw)
    end = window_end(gw)
    left = end - gw                                   # gameweeks left in the half after this one
    vals0 = vals_by_gw[0]
    money = round(sum(T.sell_price(buys.get(i, vals0[i]["cost"]), vals0[i]["cost"]) for i in squad) + bank, 1)
    late = left < LATE_GWS
    watch, picks = {}, {}
    squads = {}
    for c in avail:
        minimum = MIN_GAIN[c] * (LATE_FACTOR if late else 1.0)
        if c in ("3xc", "bboost"):
            fn = tc_gain if c == "3xc" else bb_gain
            gains = [fn(squad, v) for v in vals_by_gw]
        elif c == "freehit":
            gains, sqs = [], []
            for v in vals_by_gw:
                g, sq = fh_squad(squad, v, money)
                gains.append(g); sqs.append(sq)
            squads[c] = sqs[0]
        else:       # wildcard: only the gain from now is scored (the rest of the half would need a re-plan each week)
            g, sq = wc_squad(squad, vals_by_gw[:HORIZON], money)
            gains = [g]; squads[c] = sq
        now = gains[0]
        later = gains[1:]
        best_later = max(later) if later else None
        best_gw = (gw + 1 + later.index(best_later)) if later else None
        forced = left == 0
        good = now >= minimum and (best_later is None or now >= NEAR_BEST * best_later)
        watch[c] = {"now": round(now, 1), "min": round(minimum, 1), "best_later": None if best_later is None else round(best_later, 1),
                    "best_gw": best_gw, "play": bool(good or (forced and now > 0))}
        if watch[c]["play"]:
            picks[c] = now / minimum if minimum else 1.0
    chip = max(picks, key=picks.get) if picks else None
    reason = ""
    if chip:
        w = watch[chip]
        reason = (f"{NAMES[chip]}: +{w['now']} expected points this gameweek"
                  + (f", the best of the window (next best +{w['best_later']} in GW{w['best_gw']})" if w["best_later"] is not None and w["now"] >= w["best_later"]
                     else f" (GW{w['best_gw']} looks similar: +{w['best_later']})" if w["best_later"] is not None else "")
                  + (" - last gameweek before the chips reset, use it or lose it" if left == 0 else ""))
    return {"chip": chip, "reason": reason, "watch": watch, "squad": squads.get(chip) if chip in ("freehit", "wildcard") else None, "money": money}
