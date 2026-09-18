#!/usr/bin/env python3
from __future__ import annotations
import json, re, unicodedata, urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

from fpl_common import get, parse_iso, event_window, load_js_object

ROOT = Path(__file__).resolve().parent
NEWS_PATH = ROOT / "news.js"
JUNK_TITLE = ("log in", "login", "lost password", "sign in", "privacy", "cookie", "wp-login")
JUNK_PATH_PARTS = (
    "/tag/", "/category/", "/categories/", "/wp-json", "/wp-login",
    "/planner", "/transfer-planner", "/rate-my-team", "/my-team",
    "/assistant_manager", "/premium/", "/oauth", "/auth/",
    "/login", "/signin", "/sign-in", "/cart", "/checkout",
)
JUNK_HOST_TOOLS = (
    "fpl-player-comparison-tool", "fpl-match-centre", "fixture-ticker",
    "projected-points", "price-predictions", "price-changes",
    "live-gameweek", "/fpl/draft", "/fpl/fixtures", "/fpl/stats",
    "/fpl/ticker", "/bonus", "/experts",
)
QUERY_LISTING_KEYS = ("category", "tag", "page", "author", "s", "search")


def fetch_html(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ShaalandFPLLab/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def parse_pub_date(html, url):
    patterns = [
        r'property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)',
        r'name=["\']article:published_time["\'][^>]*content=["\']([^"\']+)',
        r'property=["\']og:updated_time["\'][^>]*content=["\']([^"\']+)',
        r'<time[^>]+datetime=["\']([^"\']+)',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"dateCreated"\s*:\s*"([^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html or "", re.I)
        if m:
            dt = parse_iso(m.group(1))
            if dt:
                return dt
    return url_date(url)


def after_cutoff(dt, cutoff):
    if not cutoff:
        return bool(dt)
    return bool(dt) and dt > cutoff


def load_news():
    return load_js_object(NEWS_PATH)


def page_title(html, url):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not m:
        return url
    return re.sub(r"\s+", " ", unescape(m.group(1))).strip()[:160]


def article_text(html, lower=True):
    """Title + main body text only — strip scripts/styles/nav noise for theme match."""
    if not html:
        return ""
    h = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    h = re.sub(r"(?is)<(nav|footer|header|aside|form)[^>]*>.*?</\1>", " ", h)
    title = ""
    mt = re.search(r"<title[^>]*>(.*?)</title>", h, re.I | re.S)
    if mt:
        title = unescape(re.sub(r"<[^>]+>", " ", mt.group(1)))
    body = h
    for pat in (
        r'(?is)<article[^>]*>(.*?)</article>',
        r'(?is)<main[^>]*>(.*?)</main>',
        r'(?is)<div[^>]+class=["\'][^"\']*(?:entry-content|post-content|article-content|article-body|content-body)[^"\']*["\'][^>]*>(.*?)</div>',
    ):
        m = re.search(pat, h)
        if m:
            body = m.group(1)
            break
    text = unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", text).strip()
    result = title + " " + text
    return (result.lower() if lower else result)[:12000]


def is_junk_url(url):
    if not url:
        return True
    try:
        p = urlparse(url)
    except Exception:
        return True
    path = (p.path or "").lower()
    full = url.lower()
    if any(j in full for j in JUNK_PATH_PARTS):
        return True
    if any(j in full for j in JUNK_HOST_TOOLS):
        return True
    # oauth / social auth redirects
    if "redirect_to=" in full or "oauth" in full or "/auth/social/" in full:
        return True
    # query-only listing junk (blog-index?category=..., ?tag=...)
    qs = parse_qs(p.query or "")
    if qs and any(k.lower() in QUERY_LISTING_KEYS for k in qs):
        # allow real articles that happen to have tracking params only if path looks like an article
        if not re.search(r"/\d{4}/\d{2}/", path) and not re.search(r"/blog-index/[^?/]+", path):
            if path.rstrip("/").endswith("blog-index") or path.count("/") <= 2:
                return True
            if any(k.lower() in ("category", "tag", "author", "s", "search") for k in qs):
                return True
    # bare section roots / tool shells
    bare = path.rstrip("/")
    if bare in ("", "/fpl", "/blog-index", "/transfers", "/reveal/captain"):
        return True
    return False


def is_junk(title, url):
    if is_junk_url(url):
        return True
    blob = f"{title} {url}".lower()
    return any(j in blob for j in JUNK_TITLE)


def older_gw_in(url, gw):
    low = (url or "").lower()
    for n in range(1, int(gw or 1)):
        if f"gw{n}" in low or f"gameweek-{n}" in low or f"gameweek_{n}" in low or f"gameweek {n}" in low:
            return True
    return False


def keep_seen(url, gw, cutoff):
    if not url or is_junk("", url):
        return False
    host = urlparse(url).netloc.lower()
    if "rotowire.com" in host:
        return False
    if older_gw_in(url, gw):
        return False
    dt = url_date(url)
    if dt and cutoff and not after_cutoff(dt, cutoff):
        return False
    return True


def extract_article_links(html, base, source, gw):
    host = urlparse(base).netloc
    out, seen = [], set()
    gw_tokens = (f"gw{gw}", f"gameweek-{gw}", f"gameweek {gw}", f"/gw{gw}")
    generic = ("gameweek", "/fpl", "fpl-", "transfer", "captain", "wildcard", "differential", "/2026/", "/blog", "lineup", "preview")
    for href, inner in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        href = urljoin(base, href.split("#")[0])
        if urlparse(href).netloc != host:
            continue
        if is_junk_url(href):
            continue
        low = href.lower() + " " + unescape(re.sub(r"<[^>]+>", " ", inner)).lower()
        if not any(t in low for t in gw_tokens) and not any(x in low for x in generic):
            continue
        text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", inner))).strip()
        if len(text) < 12 or href in seen or is_junk(text, href):
            continue
        seen.add(href)
        out.append({"source": source, "url": href, "title": text[:160], "current": any(t in low for t in gw_tokens)})
    out.sort(key=lambda a: (not a["current"], a["title"]))
    return out[:25]


def site_listings(gw):
    listings = []
    path = ROOT / "sources.json"
    if path.exists():
        try:
            for s in json.loads(path.read_text()).get("sites") or []:
                listings.append((s.get("name") or "Site", s["url"]))
        except Exception:
            listings = []
    if not listings:
        listings = [
            ("Fix", "https://www.fantasyfootballfix.com/"),
            ("Hub", "https://www.fantasyfootballhub.co.uk/fantasy-premier-league-ultimate-guide-fpl-tips"),
            ("Scout", "https://www.fantasyfootballscout.co.uk/"),
            ("AAFPL", "https://allaboutfpl.com/"),
        ]
    # Generic GW-pattern extras (no hardcoded Scout GW5-only URL)
    listings.extend([
        ("Fix", f"https://www.fantasyfootballfix.com/blog-index/fpl-gw{gw}-transfer-tips-2026-27/"),
        ("Scout", f"https://www.fantasyfootballscout.co.uk/the-complete-guide-to-gameweek-{gw}/"),
        ("Scout", f"https://www.fantasyfootballscout.co.uk/fpl-gameweek-{gw}-tips-best-players-predicted-line-ups-team-news-more/"),
        ("AAFPL", f"https://allaboutfpl.com/category/fpl-gw{gw}-ultimate-guide-and-tips/"),
    ])
    # Deduplicate while preserving order
    seen, out = set(), []
    for name, url in listings:
        key = (name, url.rstrip("/"))
        if key in seen:
            continue
        seen.add(key)
        out.append((name, url))
    return out


def _norm_keep_case(s):
    """Strip accents (Groß->Gross, João->Joao) but keep case, for name matching."""
    s = (s or "").replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def load_player_index():
    """Every current FPL player, keyed for matching against raw (case-preserved)
    article text — this is what lets the scraper discover whichever names are
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


ARTICLE_SEP = "\x00"  # joins separate articles in a source's blob; never occurs in real text


def qualifiers_near(text, key, window=90):
    """Tags describing HOW a name is being talked about, from the words actually
    surrounding each mention (not a per-player hand-written script). The window is
    clipped at ARTICLE_SEP so a mention in one article can't pick up a qualifier
    from an unrelated sentence in the next article concatenated after it."""
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


def concept_themes(raw_blobs, gw):
    total = len(raw_blobs)
    agreed, split = [], []
    for concept, pat in CONCEPT_PATTERNS:
        sources = sorted(s for s, text in raw_blobs.items() if re.search(pat, text, re.I))
        if not sources:
            continue
        item = {
            "text": f"GW{gw} coverage is talking about a {concept} window — mentioned by {len(sources)}/{total} sites.",
            "sources": sources,
        }
        (agreed if len(sources) >= 3 else split).append(item)
    return agreed, split


def build_themes(raw_blobs, gw, player_index):
    """Discover which players are actually mentioned across the scraped sites this
    run, instead of checking a fixed list of names someone hand-picked in advance.
    3+ sites = agreed (matches the "Agreed = 3+ sites" note shown in the UI)."""
    total = len(raw_blobs)
    mentions = {}
    for source, raw_text in raw_blobs.items():
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
        club = f" ({rec['club']})" if rec["club"] else ""
        tag_str = f" Tags: {', '.join(sorted(rec['tags']))}." if rec["tags"] else ""
        text = f"{name}{club} is heavily featured in GW{gw} coverage — mentioned by {n}/{total} sites.{tag_str}"
        item = {"text": text, "sources": sorted(rec["sources"]), "player": name, "club": rec["club"], "tags": sorted(rec["tags"])}
        (agreed if n >= 3 else split).append(item)
    concept_agreed, concept_split = concept_themes(raw_blobs, gw)
    return (agreed + concept_agreed)[:15], (split + concept_split)[:20]


def url_date(url):
    m = re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", url or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    except Exception:
        return None


def main():
    prev = load_news()
    gw, cutoff = event_window(prev)
    seen_set = {u for u in (prev.get("seen") or []) if keep_seen(u, gw, cutoff)}
    listings = site_listings(gw)
    # Per-source blobs (title + article body only, not full page HTML), case
    # preserved for player-mention discovery. Articles are joined with ARTICLE_SEP
    # rather than a bare space so qualifier detection can't bleed across articles.
    blobs, links, discovered, used = {}, [], [], set()
    title_blobs = {}  # titles of new articles weighted heavily
    for source, url in listings:
        html = fetch_html(url)
        if source not in used:
            links.append({"name": source, "url": url})
            used.add(source)
        discovered.extend(extract_article_links(html, url, source, gw))
    # Dedupe discovered by URL
    uniq, seen_u = [], set()
    for art in discovered:
        if art["url"] in seen_u:
            continue
        seen_u.add(art["url"])
        uniq.append(art)
    discovered = uniq
    first_seed = len(seen_set) < 8
    new_articles = []
    for art in discovered:
        if not keep_seen(art["url"], gw, cutoff):
            continue
        url_dt = url_date(art["url"])
        body_html = ""
        if art["url"] not in seen_set or first_seed:
            body_html = fetch_html(art["url"])
            if body_html:
                art["title"] = page_title(body_html, art["url"]) or art["title"]
        if is_junk(art["title"], art["url"]):
            continue
        pub = parse_pub_date(body_html, art["url"]) or url_dt
        if not after_cutoff(pub, cutoff):
            continue
        title = art.get("title") or ""
        text_blob = article_text(body_html, lower=False) if body_html else ""
        match_blob = (title + " " + text_blob).strip()
        if not match_blob and body_html:
            # last resort: still avoid raw HTML tags by stripping
            match_blob = re.sub(r"<[^>]+>", " ", body_html)[:8000]
        if match_blob:
            blobs[art["source"]] = blobs.get(art["source"], "") + ARTICLE_SEP + match_blob
        if art["url"] not in seen_set:
            new_articles.append({"source": art["source"], "title": art["title"], "url": art["url"]})
            title_blobs[art["source"]] = title_blobs.get(art["source"], "") + ARTICLE_SEP + title
        seen_set.add(art["url"])
    seen_set = {u for u in seen_set if keep_seen(u, gw, cutoff)}
    # Weight new-article titles heavily by repeating them into the blob
    for src, tb in title_blobs.items():
        blobs[src] = blobs.get(src, "") + ARTICLE_SEP + tb + ARTICLE_SEP + tb
    try:
        player_index = load_player_index()
    except Exception as e:
        print(f"news_scrape.py: could not load player index for theme discovery: {e}")
        player_index = []
    agreed, split = build_themes(blobs, gw, player_index) if player_index else ([], [])
    def filter_themes_for_gw(items, gw_id):
        """Drop carried themes that name a different GW (e.g. GW5 text after roll to 6)."""
        out = []
        for it in items or []:
            t = str(it.get("text") or "")
            mentioned = [int(m) for m in re.findall(r"GW(\d+)", t, flags=re.I)]
            if mentioned and any(m != int(gw_id) for m in mentioned):
                continue
            out.append(it)
        return out

    if not agreed and not split:
        # Only reuse prior themes within the same planning GW, and only if text
        # does not still name an older locked GW.
        if prev.get("gw") == gw:
            agreed = filter_themes_for_gw(prev.get("agreed") or [], gw)
            split = filter_themes_for_gw(prev.get("split") or [], gw)
    news = {
        "gw": gw,
        "cutoff": cutoff.strftime("%Y-%m-%d %H:%M UTC") if cutoff else None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "note": "Public pages only. New = published after last finished GW deadline. Agreed = 3+ sites. Themes are player mentions auto-detected in title+article text, not a fixed watchlist.",
        "agreed": agreed,
        "split": split,
        "links": links,
        "new_articles": new_articles[:12],
        "no_new": not new_articles,
        "seen": sorted(seen_set)[-200:],
    }
    NEWS_PATH.write_text("window.FPL_NEWS = " + json.dumps(news, indent=2) + ";\n")
    print("news.js", "new" if new_articles else "no-new", len(new_articles), "gw", gw, "cutoff", news["cutoff"], "seen", len(seen_set), "agreed", len(agreed), "split", len(split))


if __name__ == "__main__":
    main()
