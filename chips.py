"""Chips and free transfers: per-half chip history, chip results, Free Hit / Wildcard audit, free-transfer ledger, chip strategy."""
from __future__ import annotations
from fplbase import *
from fplbase import _warn, _fixtures_for

CHIP_KEYS = ("bboost", "3xc", "freehit", "wildcard")

HALF_SPLIT = 20   # FPL resets every chip at GW20: one play per chip in GW1-19 and one in GW20-38

def chips_by_half(hist):
    """{chip: gameweek} for the first-half play and {chip + "_h2": gameweek} for the second-half one. A
    second-half play must not overwrite the first-half one: results, audits and 'chips left' all key off this."""
    out = {}
    for c in sorted(hist.get("chips", []), key=lambda c: c.get("event") or 0):
        out[c["name"] + ("_h2" if (c.get("event") or 0) >= HALF_SPLIT else "")] = c["event"]
    return out

def chip_for_gw(chips_used, name, gw):
    """The play of `name` in the half that gameweek `gw` falls in (None if unused there)."""
    return chips_used.get(name + "_h2") if (gw or 0) >= HALF_SPLIT else chips_used.get(name)

def chip_base(key):
    return key[:-3] if key.endswith("_h2") else key

def squad_changes_for_chips(team_id, hist):
    """{chip gameweek: players in that gameweek's squad that were not in the squad before it}. FPL logs one
    transfer per swap in a chain (A->B, B->C), so counting its records overstates a Wildcard / Free Hit."""
    out = {}
    chip_gws = {c["event"] for c in hist.get("chips", []) if c.get("name") in ("wildcard", "freehit")}
    fh = {c["event"] for c in hist.get("chips", []) if c.get("name") == "freehit"}
    def ids(gw):
        pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
        return {p["element"] for p in pk.get("picks") or []}
    for gw in sorted(chip_gws):
        prev = gw - 1
        while prev in fh and prev >= 1:
            prev -= 1
        if prev < 1:
            continue
        try:
            out[gw] = len(ids(gw) - ids(prev))
        except Exception as e:
            _warn(f"squad_changes: GW{gw}: {e}")
    return out

def free_transfer_ledger(hist):
    """Gameweek-by-gameweek free-transfer bank. GW1 is the initial squad build (no bank).
    From GW2 you gain 1 free transfer per GW, banked up to 5; each transfer uses one and
    extras are -4 hits (never taking the bank below 0). A Wildcard / Free Hit week is
    neutral: its moves are free, nothing is used and no new free transfer is added, so the
    bank carries through unchanged. Returns (rows, free transfers heading into the next GW)."""
    chips = {c["event"]: c["name"] for c in hist.get("chips", []) if c.get("name") in ("wildcard", "freehit")}
    ft, rows = 0, []
    for row in sorted(hist.get("current", []), key=lambda r: r.get("event") or 0):
        gw = row.get("event")
        made = int(row.get("event_transfers") or 0)
        if gw == 1:
            rows.append({"gw": gw, "chip": None, "had": None, "made": made, "hit": 0, "left": 0})
        elif gw in chips:
            rows.append({"gw": gw, "chip": chips[gw], "had": ft, "made": made, "hit": 0, "left": ft})
        else:
            had = min(5, ft + 1)
            ft = max(0, had - made)
            rows.append({"gw": gw, "chip": None, "had": had, "made": made, "hit": max(0, made - had), "left": ft})
    return rows, min(5, ft + 1)

def free_transfers_for_next(hist):
    return free_transfer_ledger(hist)[1]

def _chip_week_facts(gws, gw):
    """The measurable facts about a gameweek: points, the field average, overall rank before and after."""
    g = next((x for x in (gws or []) if x.get("gw") == gw), None)
    if not g:
        return None
    prev = next((x for x in (gws or []) if x.get("gw") == gw - 1), None)
    return {"points": g.get("points"), "avg": g.get("field_avg"), "rank": g.get("rank"), "prev_rank": (prev or {}).get("rank")}

def _rank_text(f):
    if f and f.get("rank") and f.get("prev_rank"):
        return f" Overall rank {f['prev_rank']:,} → {f['rank']:,}."
    return ""

def build_chip_net(chips_used, caps, bench_audit, boot=None, team_id=None, transfers=None, gws=None):
    """Each played chip's result, using only things that can actually be measured:
      * Bench Boost = the bench's points that week (exactly what the chip added).
      * Triple Captain = the captain's third multiple (exactly what the chip added).
      * Free Hit / Wildcard rebuild the whole squad, so the true "points the chip added" is unknowable:
        it depends on what you would have done without it. The figure shown is therefore a FACT -
        that gameweek's points against the field average - and the unchanged-squad comparison is kept
        only as a labelled estimate in the note."""
    out = {}
    for suffix in ("", "_h2"):
        sfx_label = " (2nd half)" if suffix else ""
        bboost_gw = chips_used.get("bboost" + suffix)
        if bboost_gw:
            bench = (bench_audit.get(f"gw{bboost_gw}") or {}).get("your_bench") or []
            if not bench and boot and team_id:
                try:
                    names = {e["id"]: e["web_name"] for e in boot["elements"]}
                    pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{bboost_gw}/picks/")
                    live = {el["id"]: el["stats"]["total_points"] for el in get(f"https://fantasy.premierleague.com/api/event/{bboost_gw}/live/").get("elements", [])}
                    bench = [[names.get(p["element"], "?"), live.get(p["element"], 0)] for p in pk.get("picks", []) if p["position"] > 11]
                except Exception as e:
                    _warn(f"build_chip_net: could not read the GW{bboost_gw} Bench Boost bench: {e}")
            if bench:
                out["bboost" + suffix] = {"net": sum(pts for _name, pts in bench), "label": "bench",
                                          "note": " + ".join(f"{name} {pts}" for name, pts in bench)}
        xc_gw = chips_used.get("3xc" + suffix)
        if xc_gw:
            row = next((c for c in caps if c.get("gw") == xc_gw), None)
            if row:
                extra = row.get("captain_raw") or 0  # 3xc's only gain over a normal (C) is the 3rd multiple
                out["3xc" + suffix] = {"net": extra, "label": "extra",
                                       "note": f"{row.get('captain')} {extra} × 3 = {extra * 3}"}
        for base, label, prior in (("freehit", "FH", "reverted squad"), ("wildcard", "WC", "previous squad")):
            key = base + suffix
            gw = chips_used.get(key)
            if not gw:
                continue
            f = _chip_week_facts(gws, gw)
            audit = None
            if boot and team_id:
                try:
                    audit = build_fh_audit(boot, team_id, chips_used, key, label + sfx_label, prior)
                except Exception as e:
                    _warn(f"build_chip_net: {label} comparison unavailable: {e}")
            if not f or f.get("points") is None:
                out[key] = {"net": None, "label": "", "note": f"GW{gw} result not available yet", "compare": None}
                continue
            # The chip's effect is the new squad against the one you had before, player for player and bench
            # included (you could have swapped them) - NOT the gameweek score against the field average, which
            # reads as a gain even when the chip made the squad worse.
            net = (audit["all15_new"] - audit["all15_old"]) if audit else None
            text = "" if audit else f"GW{gw} comparison not available yet"
            out[key] = {"net": net, "label": "vs before", "note": text, "compare": (audit or {}).get("compare")}
    return out

def _best_xi_hindsight(players):
    """players: [{"pos","pts"}] x15. The best legal XI by raw points - what perfect swaps would have returned
    from this squad. No captain multiplier: squads are compared player for player."""
    by = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in players:
        by[p["pos"]].append(p["pts"])
    for k in by:
        by[k].sort(reverse=True)
    best = 0
    for d in range(3, 6):
        for m in range(2, 6):
            for f in range(1, 4):
                if 1 + d + m + f != 11 or len(by["GKP"]) < 1 or len(by["DEF"]) < d or len(by["MID"]) < m or len(by["FWD"]) < f:
                    continue
                best = max(best, sum(by["GKP"][:1] + by["DEF"][:d] + by["MID"][:m] + by["FWD"][:f]))
    return best

def _pair_squads(old, new):
    """Rows for a player-for-player list: per position, players in BOTH squads side by side first, then the
    rest paired off by points (highest with highest). Each side is {"name","pts"} or None."""
    rows = []
    for pos in ("GKP", "DEF", "MID", "FWD"):
        o = sorted([p for p in old if p["pos"] == pos], key=lambda p: -p["pts"])
        n = sorted([p for p in new if p["pos"] == pos], key=lambda p: -p["pts"])
        new_names = {p["name"] for p in n}
        kept = [p for p in o if p["name"] in new_names]
        by_new = {p["name"]: p for p in n}
        for p in kept:
            rows.append({"pos": pos, "old": {"name": p["name"], "pts": p["pts"]}, "new": {"name": p["name"], "pts": by_new[p["name"]]["pts"]}, "kept": True})
        kept_names = {p["name"] for p in kept}
        ro = [p for p in o if p["name"] not in kept_names]
        rn = [p for p in n if p["name"] not in kept_names]
        for i in range(max(len(ro), len(rn))):
            side = lambda lst: {"name": lst[i]["name"], "pts": lst[i]["pts"]} if i < len(lst) else None
            rows.append({"pos": pos, "old": side(ro), "new": side(rn), "kept": False})
    return rows

def build_fh_audit(boot, team_id, chips_used, chip_key="freehit", label="FH", prior_label="reverted squad"):
    """Auto-compute the Free Hit process/outcome audit: the FH XI that was
    actually played vs. the best process-based XI from the squad you'd have
    had if you'd rolled instead (FPL guarantees the squad reverts exactly, so
    the prior gameweek's picks are that "original" squad — see
    score_original_squad for why it's re-optimized rather than replayed
    as-started). Replaces the one-off hand-written fh.js, which only ever
    covers whichever GW someone last wrote it for."""
    fh_gw = chips_used.get(chip_key)
    if not fh_gw:
        return None
    elements = {e["id"]: e for e in boot["elements"]}
    try:
        fh_pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{fh_gw}/picks/")
        live = get(f"https://fantasy.premierleague.com/api/event/{fh_gw}/live/")
    except Exception as e:
        _warn(f"build_fh_audit: could not load GW{fh_gw} FH picks/live: {e}")
        return None
    fh_weeks = {v for k, v in chips_used.items() if chip_base(k) == "freehit"}
    orig_gw = fh_gw - 1
    while orig_gw in fh_weeks:      # a Free Hit squad is never carried on: step back to the squad before it
        orig_gw -= 1
    orig_pk = {}
    if orig_gw >= 1:
        try:
            orig_pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{orig_gw}/picks/")
        except Exception as e:
            _warn(f"build_fh_audit: could not load GW{orig_gw} original picks: {e}")
    if not orig_pk.get("picks"):
        return None
    pts = {el["id"]: el["stats"]["total_points"] for el in live.get("elements", [])}
    mins = {el["id"]: el["stats"]["minutes"] for el in live.get("elements", [])}

    def score_fh_squad(pk):
        """The FH squad's own multiplier/position fields already reflect what
        actually happened in fh_gw (FPL's picks API applies real autosubs and
        captain/VC fallback to the returned multiplier) — safe to trust as-is."""
        total, xi = 0, []
        for p in pk.get("picks") or []:
            el = elements.get(p["element"])
            if not el:
                continue
            mult = p.get("multiplier") or 0
            if not mult:
                continue  # bench, or subbed out
            raw = pts.get(p["element"], 0)
            total += raw * mult
            item = {"name": el["web_name"], "pos": POS[el["element_type"]], "got": raw * mult}
            if mult != 1:
                item["mult"] = mult
            if p.get("is_captain"):
                item["captain"] = True
            xi.append(item)
        return total, xi

    def score_original_squad(pk):
        """What the squad you would have carried would really have scored: the lineup you had picked
        (same XI, captain, vice and bench order) replayed against this gameweek's results with FPL's
        own auto-sub and captain-fallback rules - no hindsight reshuffle. A Triple Captain played the
        week before is not carried over (the captain counts double)."""
        import ai_team
        picks = sorted(pk.get("picks") or [], key=lambda p: p.get("position") or 99)
        squad = [{"id": p["element"], "name": elements[p["element"]]["web_name"], "pos": POS[elements[p["element"]]["element_type"]]}
                 for p in picks if p["element"] in elements]
        plan = {"squad": squad, "xi": [p["element"] for p in picks if (p.get("position") or 99) <= 11 and p["element"] in elements],
                "bench": [p["element"] for p in picks if (p.get("position") or 99) > 11 and p["element"] in elements],
                "captain": next((p["element"] for p in picks if p.get("is_captain")), None),
                "vice": next((p["element"] for p in picks if p.get("is_vice_captain")), None), "hit_cost": 0}
        if plan["captain"] is None or plan["vice"] is None or len(plan["xi"]) != 11:
            return 0, [], None
        live_stats = {i: {"minutes": mins.get(i, 0), "points": pts.get(i, 0)} for i in set(pts) | set(mins)}
        res = ai_team.score_plan(plan, live_stats, True)
        out_xi = []
        for l in res["lines"]:
            item = {"name": l["name"], "pos": l["pos"], "got": l["pts"] * l["mult"]}
            if l["mult"] != 1:
                item["mult"] = l["mult"]
                item["captain"] = True
            out_xi.append(item)
        return res["points"], out_xi, res["captain"]

    fh_points, fh_xi = score_fh_squad(fh_pk)
    fh_cap_pick = next((p for p in (fh_pk.get("picks") or []) if p.get("is_captain")), None)
    fh_cap = elements.get((fh_cap_pick or {}).get("element"), {}).get("web_name")
    orig_points, orig_xi, orig_cap = score_original_squad(orig_pk)
    net = fh_points - orig_points
    def squad_players(pk):
        return [{"name": elements[p["element"]]["web_name"], "pos": POS[elements[p["element"]]["element_type"]], "pts": pts.get(p["element"], 0)}
                for p in pk.get("picks") or [] if p["element"] in elements]
    new_sq, old_sq = squad_players(fh_pk), squad_players(orig_pk)
    all15_new, all15_old = sum(p['pts'] for p in new_sq), sum(p['pts'] for p in old_sq)
    best_new, best_old = _best_xi_hindsight(new_sq), _best_xi_hindsight(old_sq)
    eh = fh_pk.get("entry_history") or {}
    if eh.get("points") is not None and fh_points != eh["points"]:
        # Cross-check against FPL's own gameweek points (gross of hits): a mismatch means the multipliers/autosubs were misread.
        _warn(f"build_fh_audit: GW{fh_gw} {label} squad adds up to {fh_points} but FPL reports {eh['points']}")
    return {
        "gw": fh_gw,
        "fh_points": fh_points,
        "original_points": orig_points,
        "net": net,
        "process": "ok",  # a played Free Hit is always a legal, deliberate reset — not a process error by definition
        "outcome": "won" if net > 0 else ("lost" if net < 0 else "even"),
        "original_cap": orig_cap,
        "fh_cap": fh_cap,
        "original_xi": orig_xi,
        "fh_xi": fh_xi,
        "all15_new": all15_new, "all15_old": all15_old, "best_new": best_new, "best_old": best_old,
        "compare": {"rows": _pair_squads(old_sq, new_sq), "old_total": all15_old, "new_total": all15_new,
                    "old_best": best_old, "new_best": best_new},
        "why": f"{label} scored {fh_points} vs {orig_points} for the {prior_label} (same XI, captain and auto-subs) — net {'+' if net >= 0 else ''}{net}.",
    }

CHIP_LABEL = {"wildcard": "Wildcard", "freehit": "Free Hit", "bboost": "Bench Boost", "3xc": "Triple Captain"}

def build_strategy(boot, team_id, hist, gameweeks, transfers, picks_gw, horizon=8):
    """Chip-timing and free-transfer strategy signals for the Strategy tab:
    - chips remaining: each of the 4 chips is usable TWICE a season (once in
      each half) since FPL's 2023-24+ rules — boot['chips'] gives the exact
      GW window for each half, which beats hardcoding a cutoff GW that moves
      year to year.
    - a fixture-swing scan across the next `horizon` gameweeks for your
      CURRENT squad's clubs, flagging blank/double gameweeks and the
      easiest/hardest upcoming run — the standard real-world signal for when
      to wildcard, free hit, bench boost, or triple captain.
    - whether hits taken this season have actually paid for themselves, using
      the same per-transfer net figures already shown on the Transfers tab.
    """
    teams = {t["id"]: t for t in boot["teams"]}
    elements = {e["id"]: e for e in boot["elements"]}
    chip_history = hist.get("chips", [])  # every use this season (a list, unlike the "latest per name" dict used elsewhere)

    # boot['chips']'s own "number" field is always 1 on every entry (confirmed live —
    # it's not a per-half indicator), so derive window order from start_event instead:
    # each chip type's two entries sort into "window 1" (earlier half) and "window 2".
    windows_by_chip = {}
    for c in (boot.get("chips") or []):
        name = c.get("name")
        if not name:
            continue
        windows_by_chip.setdefault(name, []).append({"start": c.get("start_event"), "stop": c.get("stop_event")})
    for ws in windows_by_chip.values():
        ws.sort(key=lambda w: w["start"] or 0)
        for i, w in enumerate(ws, start=1):
            w["number"] = i

    current_gw = max((e["id"] for e in boot["events"] if e.get("finished")), default=1)
    chip_status = []
    for name, windows in windows_by_chip.items():
        entry = {"chip": name, "label": CHIP_LABEL.get(name, name), "windows": []}
        for w in windows:
            used = next((u for u in chip_history if u.get("name") == name and w["start"] <= (u.get("event") or 0) <= w["stop"]), None)
            if used:
                status = "used"
            elif current_gw + 1 < w["start"]:
                status = "upcoming"
            elif current_gw >= w["stop"]:
                status = "expired"
            else:
                status = "open"
            entry["windows"].append({"number": w["number"], "start": w["start"], "stop": w["stop"], "used_gw": (used or {}).get("event"), "status": status})
        chip_status.append(entry)
    chip_status.sort(key=lambda e: e["chip"])

    tr_by_gw = {}
    for t in transfers or []:
        tr_by_gw.setdefault(t.get("gw"), []).append(t)
    hit_rows, total_hit_cost, total_moves_net = [], 0, 0
    for g in gameweeks or []:
        cost = g.get("hits") or 0
        if not cost:
            continue
        moves = [t for t in tr_by_gw.get(g["gw"], []) if t.get("inn") != "ROLL"]
        gw_net = sum(int(str(t.get("net", "0")).replace("+", "")) for t in moves)
        total_hit_cost += cost
        total_moves_net += gw_net
        hit_rows.append({"gw": g["gw"], "cost": cost, "moves_net": gw_net, "paid_off": gw_net > cost})
    hits_summary = {"total_cost": total_hit_cost, "total_moves_net": total_moves_net, "net_after_cost": total_moves_net - total_hit_cost, "rows": hit_rows}

    squad_clubs = []
    squad_by_club = {}
    if picks_gw:
        try:
            pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{picks_gw}/picks/")
            squad_clubs = sorted({elements[p["element"]]["team"] for p in pk.get("picks", []) if p.get("element") in elements})
            for p in pk.get("picks", []):
                el = elements.get(p.get("element"))
                if el:
                    squad_by_club.setdefault(el["team"], []).append(el["web_name"])
        except Exception as e:
            _warn(f"build_strategy: could not load GW{picks_gw} squad for fixture scan: {e}")

    # Only gameweeks you can still act on: once a deadline has passed that squad is
    # locked, so the locked GW is not part of a look-ahead.
    now_utc = datetime.now(timezone.utc)
    upcoming_events = sorted((e for e in boot["events"] if not e.get("finished") and (parse_deadline(e.get("deadline_time")) or now_utc) > now_utc), key=lambda e: e["id"])[:horizon]
    fixture_rows = []
    ticker = {}  # club id -> [{gw, fx: [{side, opp, fdr}]}] for the fixture ticker
    for ev in upcoming_events:
        try:
            fx = fixture_scan(ev["id"], teams)
        except Exception as e:
            _warn(f"build_strategy: could not load GW{ev['id']} fixtures: {e}")
            continue
        for cid in teams:
            ticker.setdefault(cid, []).append({"gw": ev["id"], "fx": [{"side": f["side"], "opp": f["opp"], "fdr": f.get("fdr")} for f in (fx.get(cid) or [])]})
        fdrs, blanks, doubles = [], [], []
        for cid in squad_clubs:
            fixtures = fx.get(cid) or []
            club = teams[cid]["short_name"]
            if not fixtures:
                blanks.append(club)
            else:
                if len(fixtures) > 1:
                    doubles.append(club)
                fdrs.extend(f["fdr"] for f in fixtures if f.get("fdr") is not None)
        avg_fdr = round(sum(fdrs) / len(fdrs), 2) if fdrs else None
        fixture_rows.append({"gw": ev["id"], "avg_fdr": avg_fdr, "blanks": blanks, "doubles": doubles})

    rated = [r for r in fixture_rows if r["avg_fdr"] is not None]
    easiest = min(rated, key=lambda r: r["avg_fdr"], default=None)
    hardest = max(rated, key=lambda r: r["avg_fdr"], default=None)
    first_blank = next((r for r in fixture_rows if r["blanks"]), None)
    first_double = next((r for r in fixture_rows if r["doubles"]), None)

    ticker_n = 6
    ticker_gws = [e["id"] for e in upcoming_events][:ticker_n]
    ticker_rows = []
    for cid, cells in ticker.items():
        cells = [c for c in cells if c["gw"] in ticker_gws]
        fd = [f["fdr"] for c in cells for f in c["fx"] if f.get("fdr") is not None]
        ticker_rows.append({"club": teams[cid]["short_name"], "squad": sorted(squad_by_club.get(cid, [])), "avg_fdr": round(sum(fd) / len(fd), 2) if fd else None, "cells": cells})
    # your clubs first, then everyone else with the kindest run first
    ticker_rows.sort(key=lambda r: (0 if r["squad"] else 1, r["avg_fdr"] if r["avg_fdr"] is not None else 9, r["club"]))

    return {
        "chips": chip_status,
        "free_transfers": free_transfers_for_next(hist or {}),
        "hits": hits_summary,
        "fixtures": {"horizon": horizon, "ticker": {"gws": ticker_gws, "rows": ticker_rows}, "rows": fixture_rows, "easiest": easiest, "hardest": hardest, "first_blank": first_blank, "first_double": first_double},
    }

def current_half_chip_windows(boot):
    """{chip name: (start_gw, stop_gw)} for the half-season window we're in: the
    one containing the next unfinished GW, else the next upcoming one. Every
    chip is usable once per half, so 'chips left' means unused in THIS window."""
    ref = next((e["id"] for e in boot.get("events") or [] if not e.get("finished")), None)
    if ref is None:
        return {}
    by_chip = {}
    for c in boot.get("chips") or []:
        if c.get("name") and c.get("start_event") is not None and c.get("stop_event") is not None:
            by_chip.setdefault(c["name"], []).append((c["start_event"], c["stop_event"]))
    out = {}
    for name, ws in by_chip.items():
        ws.sort()
        w = next((w for w in ws if w[0] <= ref <= w[1]), None) or next((w for w in ws if w[0] > ref), None)
        if w:
            out[name] = w
    return out
