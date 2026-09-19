"""Shared helpers for the refresh/scrape scripts: a retrying JSON GET, ISO date
parsing, the planning-GW/cutoff window used to line up scrape themes with the
live gameweek, the `window.X = {...};` data-file loader, and the player-mention
trend discovery used by both news_scrape.py and x_scrape.py so a name only has
to actually be talked about somewhere to surface as a theme — never a fixed,
hand-maintained watchlist."""
from __future__ import annotations
import json, re, time, unicodedata, urllib.error, urllib.request
from datetime import datetime, timezone

USER_AGENT = "ShaalandFPLLab/1.0"


def get(url, timeout=20, retries=3, backoff=1.5):
    """GET url as JSON, retrying transient failures with exponential backoff."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except (OSError, json.JSONDecodeError) as e:
            last_err = e
            if attempt < retries - 1:
                print(f"get() retry {attempt + 1}/{retries - 1} after {e} — {url}")
                time.sleep(backoff ** attempt)
    raise last_err


def parse_iso(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def event_window(prev=None):
    """Return (planning_gw, cutoff).

    planning_gw = first event whose deadline has *not* passed (next open GW).
    After GW N locks, themes target GW N+1 even if GW N matches are still unfinished.
    cutoff = deadline of the latest locked GW (or last finished), so in-window articles
    are those published after the previous GW locked.
    """
    gw = (prev or {}).get("gw")
    cutoff = None
    try:
        boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
        events = sorted(boot["events"], key=lambda e: e["id"])
        now = datetime.now(timezone.utc)
        locked, open_ev = [], []
        for e in events:
            dl = parse_iso(e.get("deadline_time") or "")
            if dl and now >= dl:
                locked.append(e)
            elif dl and now < dl:
                open_ev.append(e)
            elif not dl and not e.get("finished"):
                open_ev.append(e)
        if open_ev:
            gw = open_ev[0]["id"]
        else:
            unfinished = [e for e in events if not e.get("finished")]
            if unfinished:
                gw = unfinished[0]["id"]
            elif any(e.get("is_current") or e.get("is_next") for e in events):
                cur = next(e for e in events if e.get("is_current") or e.get("is_next"))
                gw = cur["id"]
        # Cutoff = most recently locked GW deadline (picks public); else last finished
        if locked:
            cutoff = parse_iso(locked[-1].get("deadline_time") or "")
        else:
            finished = [e for e in events if e.get("finished")]
            if finished:
                cutoff = parse_iso(finished[-1].get("deadline_time") or "")
            elif gw:
                prev_ev = [e for e in events if e["id"] < int(gw)]
                if prev_ev:
                    cutoff = parse_iso(prev_ev[-1].get("deadline_time") or "")
    except Exception:
        pass
    return gw, cutoff


def load_js_object(path):
    """Parse the JSON object embedded in a `window.X = {...};` data file."""
    if not path.exists():
        return {}
    raw = path.read_text()
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e == -1:
        return {}
    try:
        return json.loads(raw[s:e + 1])
    except Exception:
        return {}


# --- Trend discovery: shared by news_scrape.py (article text) and x_scrape.py
# (tweet text) so "who's being talked about" is discovered once, the same way,
# from whatever source text each scraper hands it. ---

def _norm_keep_case(s):
    """Strip accents (Groß->Gross, João->Joao) but keep case, for name matching."""
    s = (s or "").replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def load_player_index():
    """Every current FPL player, keyed for matching against raw (case-preserved)
    source text — this is what lets a scraper discover whichever names are
    actually trending, instead of only checking a hand-maintained watchlist.
    Single-word names under 5 letters are skipped: matched case-sensitively
    against scraped text they're rarely a problem, but short surnames (Cash,
    King, Cole...) can coincide with ordinary capitalized words often enough
    to not be worth the noise.
    """
    boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    idx, seen = [], set()
    for el in boot["elements"]:
        name = (el.get("web_name") or "").strip()
        if not name or (" " not in name and "-" not in name and len(name) < 5):
            continue
        match = _norm_keep_case(name)
        if match.lower() in seen:
            continue
        seen.add(match.lower())
        idx.append({"web_name": name, "club": teams.get(el["team"], ""), "match": match})
    return idx


QUALIFIER_PATTERNS = [
    ("captain talk", r"captain"),
    ("transfer target", r"transfer in|bring (?:him|her)? ?in|priority (?:buy|pick)|target for"),
    ("injury/doubt", r"\b(?:doubt|injury|injured|knock|fitness|illness)\b"),
    ("differential", r"differential|under[- ]?owned|low[- ]?owned"),
    ("fade/sell", r"\bfade\b|sell (?:him|her)?\b"),
]

ARTICLE_SEP = "\x00"  # joins separate items in a source's blob; never occurs in real text


def qualifiers_near(text, key, window=90):
    """Tags describing HOW a name is being talked about, from the words actually
    surrounding each mention (not a per-player hand-written script). The window is
    clipped at ARTICLE_SEP so a mention in one item can't pick up a qualifier from
    an unrelated sentence in the next item concatenated after it."""
    tags = set()
    for m in re.finditer(rf"\b{re.escape(key)}\b", text):
        left = text.rfind(ARTICLE_SEP, 0, m.start())
        left = 0 if left == -1 else left + 1
        right = text.find(ARTICLE_SEP, m.end())
        right = len(text) if right == -1 else right
        ctx = text[max(left, m.start() - window):min(right, m.end() + window)].lower()
        for tag, pat in QUALIFIER_PATTERNS:
            if re.search(pat, ctx):
                tags.add(tag)
    return tags


# Chip names are a fixed, closed vocabulary (FPL has exactly four chips), unlike
# player names — so hardcoding these specific words isn't the same problem as a
# hardcoded player watchlist. Kept separate from player-mention discovery below.
CONCEPT_PATTERNS = [
    ("wildcard", r"\bwildcard\b"),
    ("free hit", r"\bfree hit\b"),
]


def concept_themes(blobs, gw, unit="sites"):
    total = len(blobs)
    agreed, split = [], []
    for concept, pat in CONCEPT_PATTERNS:
        sources = sorted(s for s, text in blobs.items() if re.search(pat, text, re.I))
        if len(sources) < 2:
            continue  # a single mention is noise, not worth surfacing as an "emerging" theme
        item = {
            "text": f"GW{gw} coverage is talking about a {concept} window — mentioned by {len(sources)}/{total} {unit}.",
            "sources": sources,
        }
        (agreed if len(sources) >= 3 else split).append(item)
    return agreed, split


def build_themes(blobs, gw, player_index, unit="sites"):
    """Discover which players are actually mentioned across the given per-source
    text blobs, instead of checking a fixed list of names someone hand-picked in
    advance. 3+ sources = agreed (matches the "Agreed = 3+ ..." note in the UI).
    `unit` labels what a "source" is in the generated text (sites for news,
    accounts for X)."""
    total = len(blobs)
    mentions = {}
    for source, raw_text in blobs.items():
        text = _norm_keep_case(raw_text)  # match accent-stripped key against accent-stripped text
        for p in player_index:
            if not re.search(rf"\b{re.escape(p['match'])}\b", text):
                continue
            rec = mentions.setdefault(p["web_name"], {"club": p["club"], "sources": set(), "tags": set()})
            rec["sources"].add(source)
            rec["tags"] |= qualifiers_near(text, p["match"])
    agreed, split = [], []
    for name, rec in sorted(mentions.items(), key=lambda kv: (-len(kv[1]["sources"]), kv[0])):
        n = len(rec["sources"])
        if n < 2:
            continue  # a single mention is noise, not worth surfacing as an "emerging" theme
        club = f" ({rec['club']})" if rec["club"] else ""
        tag_str = f" Tags: {', '.join(sorted(rec['tags']))}." if rec["tags"] else ""
        is_agreed = n >= 3
        verb = "is heavily featured in" if is_agreed else "is starting to come up in"
        text = f"{name}{club} {verb} GW{gw} coverage — mentioned by {n}/{total} {unit}.{tag_str}"
        item = {"text": text, "sources": sorted(rec["sources"]), "player": name, "club": rec["club"], "tags": sorted(rec["tags"])}
        (agreed if is_agreed else split).append(item)
    concept_agreed, concept_split = concept_themes(blobs, gw, unit)
    return (agreed + concept_agreed)[:15], (split + concept_split)[:10]
