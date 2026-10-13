"""Understat shot data, used for the xG/xA tab's "goal due" / "assist due" lists.

FPL's own API has no shots-on-target or chances-created counts. Understat's JSON endpoints
(the ones its own pages call; need an X-Requested-With header and are gzipped) list every shot
in a match with its player, assist-maker, result and xG. Finished matches never change, so each
one is fetched once and kept in understat_cache.json; later runs only fetch new matches.
Everything here fails soft: on any error the caller falls back to FPL's xG/xA."""
from __future__ import annotations
import gzip, json, re, unicodedata, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://understat.com"
CACHE = Path(__file__).with_name("understat_cache.json")
SCHEMA = 2
WINDOW = 4            # a player's last N appearances
TEAM_MATCHES = 7      # a team's last N matches fetched, so a rotated player still has N appearances
BIG_CHANCE_XG = 0.3   # a shot worth at least this much xG counts as a big chance
ON_TARGET = {"Goal", "SavedShot", "ShotOnPost"}
# Understat club name -> FPL short name where a plain name match is not enough
TEAM_ALIASES = {"manchester city": "MCI", "manchester united": "MUN", "tottenham": "TOT", "newcastle united": "NEW",
                "nottingham forest": "NFO", "wolverhampton wanderers": "WOL", "west ham": "WHU", "leeds": "LEE",
                "leeds united": "LEE", "brighton": "BHA", "coventry": "COV", "hull": "HUL", "ipswich": "IPS"}


def _get(path, referer):
    req = urllib.request.Request(BASE + path, headers={"X-Requested-With": "XMLHttpRequest", "Referer": BASE + referer,
                                                       "User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode())


def _norm(s):
    s = str(s or "").translate(str.maketrans({"ø": "o", "Ø": "O", "ð": "d", "đ": "d", "ł": "l", "æ": "ae", "ß": "ss"}))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s.replace("-", " ")).split()


def _load_cache():
    try:
        c = json.loads(CACHE.read_text())
        if c.get("schema") == SCHEMA:
            return c
    except Exception:
        pass
    return {"schema": SCHEMA, "matches": {}}


def fetch_matches(season):
    """{match_id: {...}} for the last TEAM_MATCHES finished matches of every club, plus the fixture list."""
    league = _get(f"/getLeagueData/EPL/{season}", f"/league/EPL/{season}")
    played = sorted((m for m in league.get("dates", []) if m.get("isResult")), key=lambda m: m["datetime"])
    per_team, wanted = {}, set()
    for m in played:
        for side in ("h", "a"):
            per_team.setdefault(m[side]["title"], []).append(m["id"])
    for ids in per_team.values():
        wanted.update(ids[-TEAM_MATCHES:])
    cache = _load_cache()
    todo = [i for i in wanted if i not in cache["matches"]]

    def one(mid):
        try:
            d = _get(f"/getMatchData/{mid}", f"/match/{mid}")
        except Exception as e:
            print(f"[understat.py] match {mid}: {e}")
            return mid, None
        shots = [[s["player"], s.get("player_assisted") or "", s["result"], round(float(s["xG"]), 3), s["h_a"]]
                 for side in ("h", "a") for s in (d.get("shots", {}).get(side) or [])]
        mins = {}
        for side in ("h", "a"):
            for p in (d.get("rosters", {}).get(side) or {}).values():
                if int(p.get("time") or 0) > 0:
                    mins[p["player"]] = p.get("h_a") or side
        return mid, {"shots": shots, "mins": mins}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for mid, rec in ex.map(one, todo):
            if rec:
                cache["matches"][mid] = rec
    cache["matches"] = {i: v for i, v in cache["matches"].items() if i in wanted}
    try:
        CACHE.write_text(json.dumps(cache, separators=(",", ":")))
    except Exception as e:
        print(f"[understat.py] could not write cache: {e}")
    return played, cache["matches"]


def player_windows(season=2026, before=None, fetched=None):
    """{understat_name: stats over the player's last WINDOW appearances (inside the fetched matches)}.
    `before` ("YYYY-MM-DD HH:MM:SS", UTC) only counts matches kicked off earlier, to rebuild what the
    lists would have shown before a past gameweek; `fetched` reuses an earlier fetch_matches result."""
    played, matches = fetched or fetch_matches(season)
    if before:
        played = [m for m in played if m["datetime"] < before]
    apps = {}  # name -> [(match id, club)] for matches the player played in, oldest first
    for m in played:
        rec = matches.get(m["id"])
        if not rec:
            continue
        for name, side in rec["mins"].items():
            apps.setdefault(name, []).append((m["id"], m[side]["title"]))
    out = {}
    for name, lst in apps.items():
        last = lst[-WINDOW:]
        agg = {"apps": len(last), "shots": 0, "sot": 0, "big": 0, "goals": 0, "xg": 0.0,
               "cc": 0, "big_cc": 0, "assists": 0, "xa": 0.0, "team": last[-1][1]}
        for mid, _club in last:
            for player, assist, result, xg, ha in matches[mid]["shots"]:
                if player == name:
                    agg["shots"] += 1; agg["xg"] += xg
                    agg["sot"] += result in ON_TARGET
                    agg["big"] += xg >= BIG_CHANCE_XG
                    agg["goals"] += result == "Goal"
                if assist == name:
                    agg["cc"] += 1; agg["xa"] += xg
                    agg["big_cc"] += xg >= BIG_CHANCE_XG
                    agg["assists"] += result == "Goal"
        agg["xg"], agg["xa"] = round(agg["xg"], 2), round(agg["xa"], 2)
        out[name] = agg
    return out


def match_to_fpl(windows, boot):
    """{fpl element id: window stats}. A name is matched within its club (Understat's
    full name vs FPL's first/second/web name); anything ambiguous or unmatched is skipped."""
    teams = {t["id"]: t for t in boot["teams"]}
    short_of = {}
    for t in boot["teams"]:
        short_of[" ".join(_norm(t["name"]))] = t["short_name"]
    by_club = {}
    for e in boot["elements"]:
        by_club.setdefault(teams[e["team"]]["short_name"], []).append(e)
    out, unmatched = {}, []
    for uname, w in windows.items():
        title = " ".join(_norm(w["team"] or ""))
        club = TEAM_ALIASES.get(title) or short_of.get(title)
        if not club:
            cand = [s for n, s in short_of.items() if n and (n in title or title in n)]
            club = cand[0] if len(cand) == 1 else None
        if not club:
            continue
        u = _norm(uname)
        club_els = by_club.get(club, [])
        def pick(test):
            hits = [e for e in club_els if test(_norm(e["first_name"] + " " + e["second_name"]), _norm(e["web_name"]))]
            return hits[0] if len(hits) == 1 else None
        e = (pick(lambda full, web: u == full)
             or pick(lambda full, web: bool(web) and u == web)
             or pick(lambda full, web: bool(web) and set(web) <= set(u))
             or pick(lambda full, web: bool(full) and u[-1:] == full[-1:] and u[:1] == full[:1])
             or pick(lambda full, web: bool(u) and u[-1] in full and u[0] in full))
        if e:
            out[e["id"]] = w
        else:
            unmatched.append(uname)
    return out, unmatched
