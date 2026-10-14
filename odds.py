"""Bookmaker odds -> per-fixture goal expectations and clean-sheet chances.

Source: football-data.co.uk/fixtures.csv (free, no key). Rows for the Premier
League have Div == "E0". Odds columns are chosen per match, preferring the
market average (Avg*), then Bet365 (B365*), then the best price (Max*).

Method: decimal odds -> implied probabilities -> margin removed by proportional
normalisation (1X2 triple, and the over/under 2.5 pair). Then an INDEPENDENT
POISSON model is fitted: find (lambda_home, lambda_away) minimising the squared
error between the model's P(home), P(draw), P(away), P(total goals > 2.5) and
the de-margined market numbers (the over term is skipped if no total-goals
odds exist). Plain-Python grid search then local refinement; no numpy/scipy.
Independent Poisson ignores goal correlation and the extra draw mass of real
football, so the fit is a decent expectation, not an exact score distribution.

Clean sheet: cs_home = P(away scores 0) = exp(-lambda_away); cs_away = exp(-lambda_home).

Optional enrichment: public functions return an "error" key instead of raising.
Coverage is limited to matches the bookmakers have priced (usually the next
matchweek or so); callers fall back to FDR for anything missing.
"""
from __future__ import annotations
import csv, io, json, math, os, re, sys, urllib.request
from datetime import datetime, timedelta, timezone

URL = "https://www.football-data.co.uk/fixtures.csv"
UA = "Mozilla/5.0 (compatible; fpl-lab/1.0; odds.py)"
CACHE_HOURS = 3
LEAGUE_AVG_TEAM_XG = 1.4
MAX_GOALS = 12

ALIASES = {
    "MCI": ["mancity", "manchestercity"],
    "MUN": ["manunited", "manutd", "manchesterunited"],
    "TOT": ["tottenham", "spurs", "tottenhamhotspur"],
    "WOL": ["wolves", "wolverhampton", "wolverhamptonwanderers"],
    "NFO": ["forest", "nottmforest", "nottinghamforest"],
    "NEW": ["newcastle", "newcastleunited"],
    "LEE": ["leeds", "leedsunited"],
    "BHA": ["brighton", "brightonhovealbion"],
    "BOU": ["bournemouth", "afcbournemouth"],
    "WHU": ["westham", "westhamunited"],
    "CRY": ["crystalpalace", "palace"],
    "AVL": ["astonvilla", "villa"],
    "BUR": ["burnley"],
    "SUN": ["sunderland"],
    "COV": ["coventry", "coventrycity"],
    "HUL": ["hull", "hullcity"],
    "IPS": ["ipswich", "ipswichtown"],
    "LEI": ["leicester", "leicestercity"],
    "SOU": ["southampton"],
    "NOR": ["norwich", "norwichcity"],
    "SHU": ["sheffieldunited", "sheffutd"],
    "LUT": ["luton", "lutontown"],
}

# (source label, home, draw, away, over, under)
COLUMN_SETS = [
    ("Avg", "AvgH", "AvgD", "AvgA", "Avg>2.5", "Avg<2.5"),
    ("B365", "B365H", "B365D", "B365A", "B365>2.5", "B365<2.5"),
    ("Max", "MaxH", "MaxD", "MaxA", "Max>2.5", "Max<2.5"),
]


def _log(msg):
    print(f"[odds.py] {msg}", file=sys.stdout, flush=True)


def _now():
    return datetime.now(timezone.utc)


def norm(name):
    return re.sub(r"[^a-z]", "", str(name).lower())


def _keys_for(team):
    keys = {norm(team.get("name", "")), norm(team.get("short_name", ""))}
    keys.update(ALIASES.get(team.get("short_name"), []))
    keys.discard("")
    return keys


def name_map(boot):
    """normalised club name -> FPL short_name."""
    out = {}
    for t in boot.get("teams", []):
        for k in _keys_for(t):
            out.setdefault(k, t["short_name"])
    return out


def _http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8-sig", "replace")


def _price(v):
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x if x > 1.0 else None


def remove_margin(prices):
    """Decimal odds -> probabilities summing to 1 (proportional normalisation)."""
    inv = [1.0 / p for p in prices]
    s = sum(inv)
    return [x / s for x in inv]


def _iso_date(s):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_csv(text):
    """fixtures.csv text -> list of Premier League rows with de-margined probs:
    {home, away (raw names), date, p_home, p_draw, p_away, over25|None, source}.
    Rows without a usable 1X2 set are skipped. Tolerates a BOM."""
    text = (text or "").lstrip("﻿")
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip().lstrip("﻿"): v for k, v in r.items()}
        if (r.get("Div") or "").strip() != "E0":
            continue
        home, away = (r.get("HomeTeam") or "").strip(), (r.get("AwayTeam") or "").strip()
        if not home or not away:
            continue
        for src, h, d, a, ov, un in COLUMN_SETS:
            p3 = [_price(r.get(c)) for c in (h, d, a)]
            if None in p3:
                continue
            ph, pd, pa = remove_margin(p3)
            o, u = _price(r.get(ov)), _price(r.get(un))
            over = remove_margin([o, u])[0] if o and u else None
            out.append({"home": home, "away": away, "date": _iso_date(r.get("Date")),
                        "p_home": ph, "p_draw": pd, "p_away": pa, "over25": over, "source": src})
            break
    return out


def _pois(lam):
    p = [math.exp(-lam)]
    for k in range(1, MAX_GOALS + 1):
        p.append(p[-1] * lam / k)
    return p


def model_probs(lh, la):
    """Independent Poisson -> (P home win, P draw, P away win, P total > 2.5)."""
    ph, pa = _pois(lh), _pois(la)
    win = draw = lose = under = 0.0
    for i, x in enumerate(ph):
        for j, y in enumerate(pa):
            w = x * y
            if i > j:
                win += w
            elif i == j:
                draw += w
            else:
                lose += w
            if i + j <= 2:
                under += w
    return win, draw, lose, 1.0 - under


def fit_lambdas(p_home, p_draw, p_away, over25=None):
    """Least-squares fit of independent-Poisson means to the market numbers."""
    target = [p_home, p_draw, p_away] + ([over25] if over25 is not None else [])

    def loss(lh, la):
        m = model_probs(lh, la)
        return sum((m[i] - t) ** 2 for i, t in enumerate(target))

    best = (float("inf"), 1.4, 1.1)
    for i in range(4, 81, 2):          # 0.2 .. 4.0 step 0.1
        for j in range(4, 81, 2):
            lh, la = i / 20.0, j / 20.0
            v = loss(lh, la)
            if v < best[0]:
                best = (v, lh, la)
    v, lh, la = best
    step = 0.05
    while step > 0.0005:
        improved = False
        for dh, da in ((step, 0), (-step, 0), (0, step), (0, -step),
                       (step, step), (-step, -step), (step, -step), (-step, step)):
            nh, na = lh + dh, la + da
            if nh < 0.05 or na < 0.05:
                continue
            nv = loss(nh, na)
            if nv < v:
                v, lh, la, improved = nv, nh, na, True
        if not improved:
            step /= 2
    return lh, la


def clean_sheets(lh, la):
    """(cs_home, cs_away): home keeps a clean sheet if away scores 0."""
    return math.exp(-la), math.exp(-lh)


def build_matches(boot, rows):
    """Parsed rows -> (match dicts, unmatched raw names)."""
    nm = name_map(boot)
    matches, unmatched = [], []
    for r in rows:
        h, a = nm.get(norm(r["home"])), nm.get(norm(r["away"]))
        if not h or not a:
            for raw, s in ((r["home"], h), (r["away"], a)):
                if not s and raw not in unmatched:
                    unmatched.append(raw)
            continue
        lh, la = fit_lambdas(r["p_home"], r["p_draw"], r["p_away"], r["over25"])
        csh, csa = clean_sheets(lh, la)
        matches.append({
            "home": h, "away": a, "date": r["date"],
            "p_home": round(r["p_home"], 4), "p_draw": round(r["p_draw"], 4),
            "p_away": round(r["p_away"], 4),
            "xg_home": round(lh, 3), "xg_away": round(la, 3),
            "cs_home": round(csh, 4), "cs_away": round(csa, 4),
            "over25": None if r["over25"] is None else round(r["over25"], 4),
            "source": r["source"]})
    return matches, unmatched


def _cache_fresh(cache, now=None, hours=CACHE_HOURS):
    try:
        if not cache or not cache.get("matches"):
            return False
        at = datetime.fromisoformat(cache["fetched_at"])
        return (now or _now()) - at < timedelta(hours=hours)
    except (KeyError, TypeError, ValueError):
        return False


def fetch_odds(boot, getter=None, cache_path=None):
    """-> {"matches": [...], "fetched_at", "unmatched"} or {"matches": [], "error"};
    never raises. `getter(url)->text` is injectable; `cache_path` is a JSON
    cache refreshed at most every 3 hours."""
    try:
        if cache_path and os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as f:
                    cache = json.load(f)
            except (OSError, ValueError):
                cache = None
            if _cache_fresh(cache):
                _log(f"using cache from {cache['fetched_at']} ({len(cache['matches'])} matches)")
                return cache
        text = (getter or _http_get)(URL)
        rows = parse_csv(text)
        matches, unmatched = build_matches(boot, rows)
        if not matches:
            raise ValueError("no priced Premier League match found")
        out = {"matches": matches, "fetched_at": _now().isoformat(timespec="seconds"),
               "unmatched": unmatched}
        if unmatched:
            _log(f"no FPL team for: {', '.join(unmatched)} (add to ALIASES)")
        _log(f"{len(matches)} Premier League matches priced")
        if cache_path:
            try:
                tmp = cache_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(out, f, separators=(",", ":"))
                os.replace(tmp, cache_path)
            except OSError as e:
                _log(f"could not write cache: {e}")
        return out
    except Exception as e:  # noqa: BLE001 - optional enrichment must not raise
        _log(f"unavailable: {e}")
        return {"matches": [], "error": f"{type(e).__name__}: {e}"}


def by_team(odds_result, scan_by_gw, boot):
    """Attach odds to each FPL fixture: {gw: {team_id: [ {opp, side, xg_for,
    xg_against, cs, p_win} ]}} in the same order as scan_by_gw; fixtures with no
    priced match are omitted (caller falls back to FDR). A team with no priced
    fixture in a gameweek gets no entry."""
    out = {}
    try:
        idx = {(m["home"], m["away"]): m for m in (odds_result or {}).get("matches", [])}
        short = {t["id"]: t["short_name"] for t in boot.get("teams", [])}
        if not idx:
            return out
        for gw, teams in (scan_by_gw or {}).items():
            gw_out = {}
            for tid, fixtures in teams.items():
                me = short.get(tid)
                lst = []
                for fx in fixtures:
                    home = fx["side"] == "H"
                    m = idx.get((me, fx["opp"]) if home else (fx["opp"], me))
                    if not m or me is None:
                        continue
                    lst.append({
                        "opp": fx["opp"], "side": fx["side"],
                        "xg_for": m["xg_home"] if home else m["xg_away"],
                        "xg_against": m["xg_away"] if home else m["xg_home"],
                        "cs": m["cs_home"] if home else m["cs_away"],
                        "p_win": m["p_home"] if home else m["p_away"]})
                if lst:
                    gw_out[tid] = lst
            out[gw] = gw_out
    except Exception as e:  # noqa: BLE001
        _log(f"by_team failed: {e}")
    return out
