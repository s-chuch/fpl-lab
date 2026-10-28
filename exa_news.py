#!/usr/bin/env python3
"""Latest team news from Exa (https://exa.ai) for the dashboards' News tab - DISPLAY ONLY.

Nothing here feeds the expected-points model, the xP penalties or any recommendation: it writes
`exa-news.js` (`window.EXA_NEWS = {...}`) and the pages show it next to FPL's own flag so a conflict is
visible. refresh.yml runs it after news_scrape.py as `python exa_news.py || true`.

Safety rules (a failure here must never break or blank anything):
  * no EXA_API_KEY            -> print a note, exit 0, leave the previous exa-news.js alone
  * any error / no results    -> keep the previous exa-news.js, exit 0
  * HARD CAP: at most MAX_SEARCHES (10) searches per run, and MONTH_CAP per calendar month
  * cache: a run within CACHE_HOURS of the last generated file for the same gameweek reuses it with no
    spend (push-triggered runs, retries). EXA_FORCE=1 bypasses the cache (local testing only).
  * the key is read from the environment only and is never printed or written.

Queries: 1 general ("Premier League injury news gameweek N FPL") + up to 9 players that are flagged by
FPL (status != 'a' or chance_of_playing < 100): players in either manager's squad first, then the most
owned. Snippets are trimmed sentences copied from the source highlight - nothing is generated."""
from __future__ import annotations
import json, os, re, sys, time, unicodedata, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import fpl_common
from fpl_common import get_logger

log = get_logger("exa_news.py")
ROOT = Path(__file__).resolve().parent
OUT = Path(os.environ.get("EXA_OUT") or ROOT / "exa-news.js")
SQUAD_FILES = {"1360999": "data.js", "1360920": "bacalhau-data.js"}      # team id -> data file (Shaaland, Bacalhau)
BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
API = "https://api.exa.ai/search"

MAX_SEARCHES = 10          # hard cap per run: 1 general + up to 9 players
MONTH_CAP = 600            # hard cap per calendar month (free credit is ~$10, a search costs about a cent)
CACHE_HOURS = 6
RECENT_DAYS = 3
MAX_SNIPPET = 220
MIN_OWNED_TOP = 3.0        # "top owned" candidates need at least this ownership %
MAX_ITEMS = 16

# Reputable first (tier 0). Blog-style FPL sites are deliberately not listed.
DOMAINS_TIER0 = [
    "bbc.co.uk", "bbc.com", "premierleague.com", "theguardian.com", "skysports.com", "telegraph.co.uk",
    "independent.co.uk", "standard.co.uk", "football.london", "theathletic.com", "nytimes.com", "espn.com", "espn.co.uk",
    "mancity.com", "liverpoolfc.com", "arsenal.com", "chelseafc.com", "manutd.com", "nufc.co.uk", "tottenhamhotspur.com",
    "avfc.co.uk", "brightonandhovealbion.com", "evertonfc.com", "fulhamfc.com", "brentfordfc.com", "nottinghamforest.co.uk",
    "afcb.co.uk", "lcfc.com", "whufc.com", "cpfc.co.uk", "wolves.co.uk", "itfc.co.uk", "hullcitytigers.com", "safc.com", "covcity.co.uk",
    "leedsunited.com", "burnleyfootballclub.com", "mirror.co.uk", "manchestereveningnews.co.uk", "liverpoolecho.co.uk",
    "chroniclelive.co.uk", "birminghammail.co.uk", "dailymail.co.uk", "thetimes.com", "thetimes.co.uk", "goal.com", "reuters.com",
]
TIER0 = set(DOMAINS_TIER0)
INJURY_WORDS = re.compile(r"\b(injur\w*|fit|fitness|doubt\w*|out|miss\w*|return\w*|sidelined|knock|hamstring|ankle|calf|thigh|hip|groin|"
                          r"muscle|illness|suspen\w*|ban|available|unavailable|training|rested?|rotation|ruled|race against time|weeks?)\b", re.I)


# ---------------------------------------------------------------- helpers
def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace("ß", "ss")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def read_previous(path: Path = OUT) -> dict:
    try:
        d = fpl_common.load_js_object(path)
        return d if isinstance(d, dict) else {}
    except Exception as e:
        log.warning(f"previous {path.name} unreadable ({e}) - ignoring it")
        return {}


def write_output(obj: dict, path: Path = OUT) -> None:
    body = "window.EXA_NEWS = " + json.dumps(obj, ensure_ascii=False, indent=1) + ";\n"
    if len(body.encode("utf-8")) > 60_000:       # keep it small: drop the lowest-ranked items until it fits
        items = list(obj.get("items") or [])
        while items and len(body.encode("utf-8")) > 60_000:
            items.pop()
            obj = {**obj, "items": items}
            body = "window.EXA_NEWS = " + json.dumps(obj, ensure_ascii=False, indent=1) + ";\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def month_key(now: datetime) -> str:
    return now.strftime("%Y-%m")


def carry_counter(prev: dict, now: datetime) -> dict:
    """Monthly spend counter stored in the output so the spend is visible: {month, searches, cost_usd}."""
    c = prev.get("month_usage") or {}
    if c.get("month") == month_key(now):
        return {"month": c["month"], "searches": int(c.get("searches") or 0), "cost_usd": float(c.get("cost_usd") or 0)}
    return {"month": month_key(now), "searches": 0, "cost_usd": 0.0}


# ---------------------------------------------------------------- FPL side
def load_squads() -> dict:
    """{team_id: set((name, club_short))} from the two data files' 15-man plan rows."""
    out = {}
    for tid, fname in SQUAD_FILES.items():
        try:
            d = fpl_common.load_js_object(ROOT / fname)
            rows = (d.get("plan") or {}).get("rows") or []
            out[tid] = {(r[1], r[2]) for r in rows if len(r) > 2}
        except Exception as e:
            log.warning(f"squad from {fname} unavailable: {e}")
            out[tid] = set()
    return out


def build_candidates(boot: dict, squads: dict) -> list[dict]:
    teams = {t["id"]: t for t in boot["teams"]}
    by_key = {}
    for el in boot["elements"]:
        t = teams.get(el["team"], {})
        by_key[(norm(el["web_name"]), t.get("short_name"))] = el
    squad_ids: dict[int, list[str]] = {}
    for tid, names in squads.items():
        for name, club in names:
            el = by_key.get((norm(name), club))
            if el is None:
                log.warning(f"squad player not matched to FPL: {name} ({club})")
                continue
            squad_ids.setdefault(el["id"], []).append(tid)
    cands = []
    for el in boot["elements"]:
        chance = el.get("chance_of_playing_next_round")
        flagged = el.get("status") != "a" or (chance is not None and chance < 100)
        if not flagged:
            continue
        mine = squad_ids.get(el["id"], [])
        owned = float(el.get("selected_by_percent") or 0)
        if el.get("status") == "u" and not mine:        # left the club: nothing to report
            continue
        if not mine and owned < MIN_OWNED_TOP:
            continue
        t = teams.get(el["team"], {})
        cands.append({"id": el["id"], "name": el["web_name"], "full": f"{el['first_name']} {el['second_name']}", "first": el["first_name"], "second": el["second_name"],
                      "team": t.get("short_name", ""), "club": t.get("name", ""), "status": el.get("status"),
                      "chance": chance, "news": (el.get("news") or "")[:160], "owned": owned, "squads": sorted(mine)})
    cands.sort(key=lambda c: (0 if c["squads"] else 1, -c["owned"]))
    return cands


def current_gw(boot: dict) -> int:
    ev = boot["events"]
    nxt = next((e for e in ev if e.get("is_next")), None) or next((e for e in ev if e.get("is_current")), None) or ev[0]
    return int(nxt["id"])


# ---------------------------------------------------------------- Exa
class ExaError(Exception):
    pass


def exa_search(key: str, query: str, start: datetime, domains: list[str] | None = None, num: int = 8) -> dict:
    body = {"query": query, "type": "auto", "numResults": num, "category": "news",
            "startPublishedDate": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "contents": {"highlights": {"maxCharacters": 900, "query": query}}}
    if domains:
        body["includeDomains"] = domains
    req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST",
                                 headers={"x-api-key": key, "Content-Type": "application/json", "User-Agent": "ShaalandFPLLab/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise ExaError(f"HTTP {e.code} {e.reason}") from None      # never include headers/body: nothing secret can leak
    except Exception as e:
        raise ExaError(type(e).__name__) from None


def domain_of(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def tier(domain: str) -> int:
    return 0 if any(domain == d or domain.endswith("." + d) for d in TIER0) else 1


def parse_date(s) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def clean(text: str) -> str:
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text or "")        # markdown links/images -> their text
    t = re.sub(r"[#*_`>|]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


NAME_EDGE = r"(?<![\w-]){}(?![\w-])"      # whole word; "Thomas" must not match "Thomas-Asante"


def name_forms(c: dict) -> tuple[str, list[str]]:
    """(surname key, identity phrases). The key is what a sentence must contain; the phrases (full name, or the
    club) are what the article as a whole must contain unless the surname is long and distinctive."""
    web = norm(c["name"]).strip()
    m = re.match(r"^([a-z])\.\s*(.+)$", web)            # 'N.Williams' -> surname williams, needs the full name
    key = (m.group(2) if m else web).strip()
    first, second = norm(c.get("first", "")).strip(), norm(c.get("second", "")).strip()
    phrases = [p for p in {f"{first} {second}".strip(), f"{first[:1]}. {second}" if first else "", f"{first[:1]} {second}" if first else "",
                           norm(c.get("full", "")).strip()} if p]
    return key, phrases


def pick_snippet(texts: list[str], key: str) -> str | None:
    """Best sentence (copied from the source, trimmed) that names the player and talks fitness. It must read as
    a whole sentence (start with a capital), not a fragment cut from the middle of one."""
    pat = re.compile(NAME_EDGE.format(re.escape(key)))
    best, best_score = None, -1
    for raw in texts:
        for s in re.split(r"(?<=[.!?])\s+|\n+", clean(raw)):
            s = s.strip().lstrip("\"'“”‘’ ")
            m = pat.search(norm(s))
            if len(s) < 25 or not m or not re.match(r"[A-Z0-9]", s):
                continue
            score = (3 if INJURY_WORDS.search(s) else 0) + (1 if 40 <= len(s) <= MAX_SNIPPET else 0) + (1 if m.start() < 40 else 0)
            if score > best_score:
                best, best_score = s, score
    if not best:
        return None
    if len(best) > MAX_SNIPPET:
        cut = best[:MAX_SNIPPET - 1].rsplit(" ", 1)[0].rstrip(",;:- ")
        best = cut + "…"
    return best


def is_about(c: dict, key: str, phrases: list[str], blob: str) -> bool:
    """The article is about this player: the surname as a whole word, plus (unless it is long/distinctive) his full name or club."""
    if not re.search(NAME_EDGE.format(re.escape(key)), blob):
        return False
    initial_form = bool(re.match(r"^[a-z]\.", norm(c["name"]).strip()))     # 'N.Williams': the surname alone is not enough
    if (len(key) >= 7 or "-" in key) and not initial_form:
        return True
    if any(re.search(NAME_EDGE.format(re.escape(p)), blob) for p in phrases):
        return True
    return bool(norm(c["club"]) and norm(c["club"]) in blob)


def items_from_results(results: list[dict], cands: list[dict], now: datetime, only: dict | None = None) -> dict[int, dict]:
    """Best item per candidate id from one search's results. `only` limits to a single candidate."""
    found: dict[int, dict] = {}
    pool = [only] if only else cands
    for r in results or []:
        pub = parse_date(r.get("publishedDate"))
        if pub is None or pub < now - timedelta(days=RECENT_DAYS) or pub > now + timedelta(hours=2):
            continue
        url = r.get("url") or ""
        if not url.startswith("http"):
            continue
        dom = domain_of(url)
        texts = [h for h in (r.get("highlights") or []) if isinstance(h, str)]
        title = clean(r.get("title") or "")
        blob = norm(title + " " + " ".join(clean(t) for t in texts))
        for c in pool:
            key, phrases = name_forms(c)
            if not is_about(c, key, phrases, blob):
                continue
            snip = pick_snippet(texts + [title], key)
            if not snip:
                continue
            rank = (tier(dom), -pub.timestamp(), 0 if INJURY_WORDS.search(snip) else 1)
            item = {"player": c["name"], "team": c["team"], "fpl_status": c["status"], "fpl_chance": c["chance"],
                    "fpl_news": c["news"], "headline": title[:140], "snippet": snip, "source_domain": dom,
                    "published": pub.strftime("%Y-%m-%d"), "url": url, "yours": c["squads"], "_rank": rank, "_id": c["id"]}
            cur = found.get(c["id"])
            if cur is None or rank < cur["_rank"]:
                found[c["id"]] = item
    return found


# ---------------------------------------------------------------- main
def main() -> int:
    key = os.environ.get("EXA_API_KEY", "").strip()
    if not key:
        print("exa_news.py: EXA_API_KEY not set - skipping (previous exa-news.js kept)")
        return 0
    now = utcnow()
    prev = read_previous()
    force = os.environ.get("EXA_FORCE") == "1"
    boot = fpl_common.get(BOOTSTRAP)
    gw = current_gw(boot)
    gen = max([d for d in (parse_date(prev.get("generated_at")), parse_date(prev.get("last_attempt"))) if d] or [None], key=lambda d: d or datetime.min.replace(tzinfo=timezone.utc))
    if not force and gen and prev.get("gw") == gw and now - gen < timedelta(hours=CACHE_HOURS):
        print(f"exa_news.py: cache hit (generated {gen.isoformat()}, < {CACHE_HOURS}h, GW{gw}) - no searches")
        return 0
    usage = carry_counter(prev, now)
    budget = min(MAX_SEARCHES, MONTH_CAP - usage["searches"])
    if budget <= 0:
        print(f"exa_news.py: monthly cap of {MONTH_CAP} searches reached - skipping")
        return 0
    cands = build_candidates(boot, load_squads())
    start = now - timedelta(days=RECENT_DAYS)
    found: dict[int, dict] = {}
    used, cost, failed_ids = 0, 0.0, set()
    # 1 general search
    queries = [(f"Premier League injury news gameweek {gw} FPL", None)]
    queries += [(f"{c['full']} {c['club']} injury fitness news", c) for c in cands[:MAX_SEARCHES - 1]]
    for q, c in queries[:budget]:
        used += 1
        try:
            resp = exa_search(key, q, start, DOMAINS_TIER0)
            cost += float((resp.get("costDollars") or {}).get("total") or 0)
        except ExaError as e:
            log.warning(f"search failed ({e}): {'general' if c is None else c['name']}")
            if c is not None:
                failed_ids.add(c["id"])
            continue
        for cid, it in items_from_results(resp.get("results"), cands, now, only=c).items():
            cur = found.get(cid)
            if cur is None or it["_rank"] < cur["_rank"]:
                found[cid] = it
    usage["searches"] += used
    usage["cost_usd"] = round(usage["cost_usd"] + cost, 4)
    if used and len(failed_ids) >= used:
        print("exa_news.py: every search failed - previous exa-news.js kept")
        return 0
    # carry over a recent item for a player whose own search failed
    for it in prev.get("items") or []:
        pid = next((c["id"] for c in cands if c["name"] == it.get("player") and c["team"] == it.get("team")), None)
        d = parse_date(it.get("published"))
        if pid in failed_ids and pid not in found and d and d >= now - timedelta(days=RECENT_DAYS):
            found[pid] = {**it, "_rank": (tier(it.get("source_domain", "")), 0, 0), "_id": pid}
    order = {c["id"]: i for i, c in enumerate(cands)}
    items = sorted(found.values(), key=lambda i: (order.get(i["_id"], 999), i["_rank"]))[:MAX_ITEMS]
    for i in items:
        i.pop("_rank", None); i.pop("_id", None)
    out = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "gw": gw, "searches_used": used, "last_attempt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "month_usage": usage, "note": "Display only (Exa web search); not used by the model. FPL flag shown beside each item.",
           "items": items}
    if not items and (prev.get("items")):
        # keep the old items and their generated_at (so the page can age them out), but record the spend and the attempt
        write_output({**prev, "month_usage": usage, "last_attempt": out["generated_at"]})
        print("exa_news.py: no usable results - previous items kept")
        return 0
    write_output(out)
    print(f"exa_news.py: wrote {len(items)} items, {used} searches this run, {usage['searches']} this month (~${usage['cost_usd']})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                       # never fail the refresh
        print(f"exa_news.py: failed ({type(e).__name__}: {e}) - previous exa-news.js kept")
        sys.exit(0)
