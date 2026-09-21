#!/usr/bin/env python3
from __future__ import annotations
import json, re, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

from fpl_common import get, parse_iso, event_window, load_js_object, load_player_index, build_themes, ARTICLE_SEP

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
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=20) as r:
            status = r.getcode()
            body = r.read().decode("utf-8", "ignore")
            print(f"news_scrape.py: fetch {url} -> HTTP {status}, {len(body)} bytes")
            return body
    except Exception as e:
        print(f"news_scrape.py: fetch FAILED for {url}: {type(e).__name__}: {e}")
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


ATOM_NS = "http://www.w3.org/2005/Atom"
CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"


def _feed_pub_date(raw):
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)  # RSS pubDate is RFC 822 (email-style)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return parse_iso(raw)  # Atom's dates are ISO 8601


def parse_feed_items(xml_text):
    """Parse an RSS 2.0 or Atom feed into {title, link, pub_date, html}. RSS's
    <content:encoded> (standard for WordPress, which all these sites run on) is
    the full article HTML — objectively cleaner and more reliable to work from
    than scraping the rendered page, since it comes straight from the site's own
    publishing pipeline with no nav/ads/cookie-banner noise to filter out."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for it in root.findall(".//item"):
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "pub_date": _feed_pub_date(it.findtext("pubDate")),
            "html": it.findtext(CONTENT_ENCODED) or it.findtext("description") or "",
        })
    if items:
        return items
    ns = {"a": ATOM_NS}
    for e in root.findall(".//a:entry", ns):
        link_el = e.find("a:link", ns)
        pub_raw = e.findtext("a:published", default="", namespaces=ns) or e.findtext("a:updated", default="", namespaces=ns)
        items.append({
            "title": (e.findtext("a:title", default="", namespaces=ns) or "").strip(),
            "link": (link_el.get("href") if link_el is not None else "") or "",
            "pub_date": _feed_pub_date(pub_raw),
            "html": e.findtext("a:content", default="", namespaces=ns) or e.findtext("a:summary", default="", namespaces=ns) or "",
        })
    return items


FEED_PATH_CANDIDATES = ("feed/", "feed", "rss/", "rss.xml", "?feed=rss2")


def discover_feed_url(base_url, homepage_html=None):
    """Try <link rel=alternate> autodiscovery from the homepage first (authoritative
    when present), then common WordPress/Atom feed paths. Returns (feed_url, items)
    for the first candidate that parses with at least one item, else (None, [])."""
    root = base_url if base_url.endswith("/") else base_url + "/"
    candidates = []
    if homepage_html:
        for m in re.finditer(
            r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*href=["\']([^"\']+)["\']',
            homepage_html, re.I,
        ):
            candidates.append(urljoin(base_url, m.group(1)))
    candidates.extend(urljoin(root, suffix) for suffix in FEED_PATH_CANDIDATES)
    seen = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        xml_text = fetch_html(cand)
        if not xml_text or ("<rss" not in xml_text[:2000].lower() and "<feed" not in xml_text[:2000].lower()):
            continue
        items = parse_feed_items(xml_text)
        if items:
            return cand, items
    return None, []


def load_feed_overrides():
    """Optional {"feed": "https://.../real-feed-url"} per entry in sources.json,
    for a site whose feed isn't at a path discover_feed_url() would find."""
    path = ROOT / "sources.json"
    out = {}
    if path.exists():
        try:
            for s in json.loads(path.read_text()).get("sites") or []:
                if s.get("feed"):
                    out[s.get("name") or "Site"] = s["feed"]
        except Exception:
            pass
    return out


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
    feed_overrides = load_feed_overrides()
    gw_tokens = (f"gw{gw}", f"gameweek-{gw}", f"gameweek {gw}", f"/gw{gw}")
    by_source = {}
    for source, url in listings:
        by_source.setdefault(source, []).append(url)
        if source not in used:
            links.append({"name": source, "url": url})
            used.add(source)
    for source, urls in by_source.items():
        base = urls[0]
        override = feed_overrides.get(source)
        if override:
            xml_text = fetch_html(override)
            feed_url, feed_items = (override, parse_feed_items(xml_text)) if xml_text else (None, [])
        else:
            feed_url, feed_items = discover_feed_url(base, fetch_html(base))
        if feed_items:
            print(f"news_scrape.py: {source} feed OK ({feed_url}) — {len(feed_items)} items")
            # Feed found: it covers this source's whole output, so use it once
            # instead of also HTML-scraping each of this source's listing URLs.
            site_discovered = 0
            for fi in feed_items:
                link = urljoin(base, fi["link"] or "")
                if is_junk_url(link):
                    continue
                title = (fi["title"] or "")[:160]
                low = (link + " " + title).lower()
                discovered.append({
                    "source": source, "url": link, "title": title,
                    "current": any(t in low for t in gw_tokens),
                    "pub_date": fi["pub_date"], "body_html": fi["html"],
                })
                site_discovered += 1
            print(f"news_scrape.py: {source} {site_discovered} non-junk feed items kept")
        else:
            print(f"news_scrape.py: {source} no feed found — falling back to HTML listing scrape of {len(urls)} URL(s)")
            site_discovered = 0
            for u in urls:
                html = fetch_html(u)
                links_found = extract_article_links(html, u, source, gw)
                site_discovered += len(links_found)
                discovered.extend(links_found)
            print(f"news_scrape.py: {source} HTML scrape found {site_discovered} candidate link(s)")
    # Dedupe discovered by URL
    uniq, seen_u = [], set()
    for art in discovered:
        if art["url"] in seen_u:
            continue
        seen_u.add(art["url"])
        uniq.append(art)
    discovered = uniq
    print(f"news_scrape.py: {len(discovered)} unique candidate link(s) across all sources before filtering")
    first_seed = len(seen_set) < 8
    new_articles = []
    drop_seen_stale, drop_junk, drop_cutoff = 0, 0, 0
    for art in discovered:
        if not keep_seen(art["url"], gw, cutoff):
            drop_seen_stale += 1
            continue
        url_dt = url_date(art["url"])
        body_html = art.get("body_html") or ""
        # A feed's <content:encoded> already gives the full article for free; only
        # fall back to fetching the rendered page when the feed gave us nothing (or
        # just a short <description> summary too thin for good mention detection).
        if len(body_html) < 400 and (art["url"] not in seen_set or first_seed):
            fetched = fetch_html(art["url"])
            if fetched:
                body_html = fetched
                art["title"] = page_title(body_html, art["url"]) or art["title"]
        if is_junk(art["title"], art["url"]):
            drop_junk += 1
            continue
        pub = art.get("pub_date") or parse_pub_date(body_html, art["url"]) or url_dt
        if not after_cutoff(pub, cutoff):
            drop_cutoff += 1
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
    print(f"news_scrape.py: filter funnel — {len(discovered)} candidates, "
          f"{drop_seen_stale} dropped (already seen / before cutoff by URL date), "
          f"{drop_junk} dropped (junk title/url), {drop_cutoff} dropped (pub date not after cutoff), "
          f"{len(new_articles)} new")
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
    def filter_themes_for_gw(items, gw_id, min_sources=1):
        """Drop carried themes that name a different GW (e.g. GW5 text after roll to 6),
        or that fall below the current source-count floor — e.g. stale 1-source items
        carried forward from before build_themes()'s "Emerging" threshold was raised to
        2+, which would otherwise linger here indefinitely since this path never
        re-runs build_themes() on them."""
        out = []
        for it in items or []:
            t = str(it.get("text") or "")
            mentioned = [int(m) for m in re.findall(r"GW(\d+)", t, flags=re.I)]
            if mentioned and any(m != int(gw_id) for m in mentioned):
                continue
            if len(it.get("sources") or []) < min_sources:
                continue
            out.append(it)
        return out

    if not agreed and not split:
        # Only reuse prior themes within the same planning GW, and only if text
        # does not still name an older locked GW.
        if prev.get("gw") == gw:
            agreed = filter_themes_for_gw(prev.get("agreed") or [], gw, min_sources=3)
            split = filter_themes_for_gw(prev.get("split") or [], gw, min_sources=2)
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
