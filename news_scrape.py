#!/usr/bin/env python3
from __future__ import annotations
import json, re, urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

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


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ShaalandFPLLab/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def fetch_html(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ShaalandFPLLab/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception:
        return ""


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
        locked = []
        open_ev = []
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


def parse_iso(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


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
    if not NEWS_PATH.exists():
        return {}
    raw = NEWS_PATH.read_text()
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e == -1:
        return {}
    try:
        return json.loads(raw[s:e + 1])
    except Exception:
        return {}


def page_title(html, url):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not m:
        return url
    return re.sub(r"\s+", " ", unescape(m.group(1))).strip()[:160]


def article_text(html):
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
    return (title + " " + text).lower()[:12000]


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


def themes_for(gw):
    return [
        {"keys": ["gakpo"], "text": f"Gakpo is a priority GW{gw} transfer in."},
        {"keys": ["isak"], "text": f"Isak is a GW{gw} transfer conversation."},
        {"keys": ["rogers"], "text": f"Rogers is a Chelsea attacker to target for GW{gw}."},
        {"keys": ["de cuyper", "decuyper"], "text": "De Cuyper is the standout cheap / OOP defender."},
        {"keys": ["palmer"], "text": f"Palmer is in the GW{gw} captain conversation."},
        {"keys": ["haaland"], "text": f"Haaland remains the default GW{gw} captain."},
        {"keys": ["joao pedro", "joão pedro"], "text": "João Pedro stays in the template forward line."},
        {"keys": ["szoboszlai", "szobos"], "text": "Szoboszlai is listed as a Liverpool mid option."},
        {"keys": ["gibbs-white", "gibbs white"], "text": f"Gibbs-White is a GW{gw} Forest mid target."},
        {"keys": ["gvardiol"], "text": f"Gvardiol is a popular GW{gw} defender move."},
        {"keys": ["saka"], "text": f"Saka is in the GW{gw} premium mid conversation."},
        {"keys": ["chelsea"], "text": f"Chelsea attack is a GW{gw} stack to consider."},
        {"keys": ["liverpool"], "text": f"Liverpool attackers stay in the GW{gw} conversation."},
        {"keys": ["wissa"], "text": "Wissa is a popular forward move."},
        {"keys": ["wildcard"], "text": f"GW{gw} is a live wildcard window for some elite sides."},
        {"keys": ["manchester united", "man utd", "man united"], "text": "United assets are a fade / sell conversation."},
    ]


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
    # source_blobs: title + article body text only (not full page HTML)
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
        text_blob = article_text(body_html) if body_html else ""
        # Always weight the title; prefer title+body over full HTML
        title_l = (art.get("title") or "").lower()
        match_blob = (title_l + " " + text_blob).strip()
        if not match_blob and body_html:
            # last resort: still avoid raw HTML tags by stripping
            match_blob = re.sub(r"<[^>]+>", " ", body_html).lower()[:8000]
        if match_blob:
            blobs[art["source"]] = blobs.get(art["source"], "") + " " + match_blob
        if art["url"] not in seen_set:
            new_articles.append({"source": art["source"], "title": art["title"], "url": art["url"]})
            title_blobs[art["source"]] = title_blobs.get(art["source"], "") + " " + title_l
        seen_set.add(art["url"])
    seen_set = {u for u in seen_set if keep_seen(u, gw, cutoff)}
    # Theme match: title+body blobs; boost new_articles titles (already in blobs via title_l)
    for src, tb in title_blobs.items():
        blobs[src] = blobs.get(src, "") + " " + tb + " " + tb  # weight titles heavily
    agreed, split = [], []
    for th in themes_for(gw):
        sources = [n for n, blob in blobs.items() if any(k in blob for k in th["keys"])]
        item = {"text": th["text"], "sources": sources}
        if len(sources) >= 3:
            agreed.append(item)
        elif sources:
            split.append(item)
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
        "note": "Public pages only. New = published after last finished GW deadline. Agreed = 3+ sites. Themes from title+article text.",
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
