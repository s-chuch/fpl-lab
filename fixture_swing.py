"""Fixture swing: rank the 20 Premier League clubs by how their next fixtures run.
Pure functions, no network. The caller builds `scan_by_gw` with fplbase.fixture_scan."""


def _scale(values):
    """Return f(v) mapping v linearly onto 1-5 across `values` (3.0 if they are all equal)."""
    vals = [v for v in values if v is not None]
    lo, hi = (min(vals), max(vals)) if vals else (0, 0)
    def f(v):
        if v is None:
            return None
        if hi == lo:
            return 3.0
        return round(1 + 4 * (v - lo) / (hi - lo), 1)
    return f


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def build_swing(boot, scan_by_gw, squad_club_players=None, elo=None, near=2, form=None):
    teams = boot["teams"]
    by_short = {t["short_name"]: t for t in teams}
    # Opponent defence/attack field depends on the venue the opponent plays at.
    sc = {k: _scale([t.get(k) for t in teams]) for k in
          ("strength_defence_home", "strength_defence_away", "strength_attack_home", "strength_attack_away")}
    # FPL's strength_* fields are sometimes unpopulated (all zero this season); then attack/defence difficulty comes from
    # `form` ({club: {"gf": goals scored per game, "ga": conceded per game}}, shrunk towards the league mean by the caller).
    informative = any(len({t.get(k) for t in teams}) > 1 for k in sc)
    use_form = bool(form) and not informative
    if use_form:
        f_att = _scale([-(form.get(t["short_name"]) or {}).get("ga", 0) for t in teams])     # a stingy defence is a hard one to attack
        f_def = _scale([(form.get(t["short_name"]) or {}).get("gf", 0) for t in teams])      # a prolific attack is a hard one to keep out
    gws = sorted(scan_by_gw)
    squad_club_players = squad_club_players or {}

    def fixture(club, fx):
        opp = by_short.get(fx.get("opp"), {})
        home = fx.get("side") == "H"
        dkey = "strength_defence_away" if home else "strength_defence_home"
        akey = "strength_attack_away" if home else "strength_attack_home"
        fdr = fx.get("fdr")
        att = sc[dkey](opp.get(dkey))
        dfn = sc[akey](opp.get(akey))
        if use_form and fx.get("opp") in form:
            att, dfn = f_att(-form[fx["opp"]]["ga"]), f_def(form[fx["opp"]]["gf"])
        out = {"opp": fx.get("opp"), "side": fx.get("side"), "fdr": fdr,
               "att": att if att is not None else fdr, "def": dfn if dfn is not None else fdr}
        if elo and elo.get(club["short_name"]) is not None and elo.get(fx.get("opp")) is not None:
            out["elo_diff"] = int(round(elo[fx["opp"]] - elo[club["short_name"]]))
        return out

    clubs = []
    for t in sorted(teams, key=lambda t: t["short_name"]):
        cells, per_gw = [], []
        for gw in gws:
            fxs = [fixture(t, f) for f in (scan_by_gw[gw].get(t["id"]) or [])]
            per_gw.append(fxs)
            cells.append({"gw": gw, "fixtures": fxs, "blank": not fxs, "double": len(fxs) >= 2})
        near_f = [f["fdr"] for fxs in per_gw[:near] for f in fxs]
        far_f = [f["fdr"] for fxs in per_gw[near:] for f in fxs]
        players = list(squad_club_players.get(t["short_name"]) or [])
        e = (elo or {}).get(t["short_name"])
        clubs.append({"club": t["short_name"], "id": t["id"], "own": len(players), "players": players,
                      "elo": float(e) if e is not None else None, "cells": cells,
                      "avg_fdr_near": _mean(near_f), "avg_fdr_far": _mean(far_f)})
    return {"gws": gws, "near": near, "clubs": clubs}


def rank_clubs(swing, window, key="run"):
    """Club short names ranked over the first `window` gameweeks.
    key="run": ascending mean FDR over the window (easiest run first).
    key="swing": mean FDR of the first `near` gws minus mean FDR of the rest of the window,
    sorted descending. Positive = tough now, EASIER later (a good time to buy); negative =
    easy now, harder later. Clubs with no fixtures on either side of the split sort last."""
    near = swing["near"]

    def fdrs(c, lo, hi):
        return [f["fdr"] for cell in c["cells"][lo:hi] for f in cell["fixtures"] if f["fdr"] is not None]

    scored = []
    for c in swing["clubs"]:
        if key == "swing":
            a, b = _mean(fdrs(c, 0, near)), _mean(fdrs(c, near, window))
            s = None if a is None or b is None else a - b
            scored.append((s is None, -(s or 0), c["club"]))
        else:
            m = _mean(fdrs(c, 0, window))
            scored.append((m is None, m or 0, c["club"]))
    return [x[2] for x in sorted(scored)]
