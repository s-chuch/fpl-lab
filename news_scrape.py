#!/usr/bin/env python3
from __future__ import annotations
import json, re, urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent
NEWS_PATH = ROOT / "news.js"

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

def extract_article_links(html, base, source):
    host = urlparse(base).netloc
    out, seen = [], set()
    for href, inner in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        href = urljoin(base, href.split("#")[0])
        if urlparse(href).netloc != host:
            continue
        low = href.lower()
        if not any(x in low for x in ("gameweek", "gw4", "gw5", "/fpl", "fpl-", "transfer", "captain", "wildcard", "differential", "/2026/", "/blog")):
            continue
        text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", inner))).strip()
        if len(text) < 12 or href in seen:
            continue
        seen.add(href)
        out.append({"source": source, "url": href, "title": text[:160]})
    return out[:25]

def main():
    prev = load_news()
    seen_set = set(prev.get("seen") or [])
    try:
        boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
        upcoming = [e for e in sorted(boot["events"], key=lambda e: e["id"]) if not e.get("finished")]
        gw = upcoming[0]["id"] if upcoming else prev.get("gw")
    except Exception:
        gw = prev.get("gw")
    listings = [
        ("Fix", "https://www.fantasyfootballfix.com/"),
        ("Fix", "https://www.fantasyfootballfix.com/blog-index/fpl-gw4-transfer-tips-2026-27/"),
        ("Hub", "https://www.fantasyfootballhub.co.uk/fantasy-premier-league-ultimate-guide-fpl-tips"),
        ("Scout", "https://www.fantasyfootballscout.co.uk/"),
        ("Scout", "https://www.fantasyfootballscout.co.uk/2026/09/09/goals-assists-imminent-who-is-due-in-fpl-gameweek-4/"),
        ("AAFPL", "https://allaboutfpl.com/"),
        ("AAFPL", "https://allaboutfpl.com/category/fpl-gw4-ultimate-guide-and-tips/"),
    ]
    blobs, links, discovered, used = {}, [], [], set()
    for source, url in listings:
        html = fetch_html(url)
        blobs[source] = blobs.get(source, "") + " " + html.lower()
        if source not in used:
            links.append({"name": source, "url": url})
            used.add(source)
        discovered.extend(extract_article_links(html, url, source))
    first_seed = len(seen_set) < 8
    new_articles = []
    if not first_seed:
        for art in discovered:
            if art["url"] in seen_set:
                continue
            body = fetch_html(art["url"])
            if body:
                blobs[art["source"]] = blobs.get(art["source"], "") + " " + body.lower()
                art["title"] = page_title(body, art["url"]) or art["title"]
            new_articles.append({"source": art["source"], "title": art["title"], "url": art["url"]})
            seen_set.add(art["url"])
    for art in discovered:
        seen_set.add(art["url"])
    themes = [
        {"keys": ["gakpo"], "text": "Gakpo is a priority GW transfer in."},
        {"keys": ["isak"], "text": "Isak is a priority GW transfer in after the Ipswich brace."},
        {"keys": ["rogers"], "text": "Rogers is a Chelsea attacker to target."},
        {"keys": ["de cuyper", "decuyper"], "text": "De Cuyper is the standout cheap / OOP defender."},
        {"keys": ["palmer"], "text": "Palmer is in the captain conversation (Hull / Chelsea attack)."},
        {"keys": ["haaland"], "text": "Haaland remains the default captain."},
        {"keys": ["joao pedro", "joão pedro"], "text": "João Pedro stays in the template forward line."},
        {"keys": ["szoboszlai", "szobos"], "text": "Szoboszlai is listed as a Liverpool mid option."},
        {"keys": ["chelsea"], "text": "Chelsea attack is the main fixture to load (Hull)."},
        {"keys": ["liverpool"], "text": "Liverpool attackers are a second stack (Fulham)."},
        {"keys": ["wissa"], "text": "Wissa is a popular forward move."},
        {"keys": ["wildcard"], "text": "GW4 is a live wildcard window for some elite sides."},
        {"keys": ["manchester united", "man utd", "man united"], "text": "United assets are fade / sell into City."},
    ]
    agreed, split = [], []
    for th in themes:
        sources = [n for n, blob in blobs.items() if any(k in blob for k in th["keys"])]
        item = {"text": th["text"], "sources": sources}
        if len(sources) >= 3:
            agreed.append(item)
        elif sources:
            split.append(item)
    if not agreed and not split:
        agreed = prev.get("agreed") or []
        split = prev.get("split") or []
    news = {
        "gw": gw,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "note": "Public pages only. Agreed = 3+ of Fix, Hub, Scout, AAFPL.",
        "agreed": agreed,
        "split": split,
        "links": links,
        "new_articles": new_articles[:12],
        "no_new": not new_articles,
        "seen": sorted(seen_set)[-200:],
    }
    NEWS_PATH.write_text("window.FPL_NEWS = " + json.dumps(news, indent=2) + ";\n")
    print("news.js", "new" if new_articles else "no-new", len(new_articles))

if __name__ == "__main__":
    main()
