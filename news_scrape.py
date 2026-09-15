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


def current_gw(prev=None):
    try:
        boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
        upcoming = [e for e in sorted(boot["events"], key=lambda e: e["id"]) if not e.get("finished")]
        if upcoming:
            return upcoming[0]["id"]
        current = next((e["id"] for e in boot["events"] if e.get("is_current") or e.get("is_next")), None)
        if current:
            return current
    except Exception:
        pass
    return (prev or {}).get("gw")


def load_news():
    if not NEWS_PATH.exists():
        return {}
    raw = NEWS_PATH.read_text()
    s, e = raw.find("{{"), raw.rfind("}}" )
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


def extract_article_links(html, base, source, gw):
    host = urlparse(base).netloc
    out, seen = [], set()
    gw_tokens = (f"gw{gw}", f"gameweek-{gw}", f"gameweek {gw}", f"/gw{gw}")
    generic = ("gameweek", "/fpl", "fpl-", "transfer", "captain", "wildcard", "differential", "/2026/", "/blog", "lineup", "preview")
    for href, inner in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        href = urljoin(base, href.split("#")[0])
        if urlparse(href).netloc != host:
            continue
        low = href.lower() + " " + unescape(re.sub(r"<[^>]+>", " ", inner)).lower()
        if not any(t in low for t in gw_tokens) and not any(x in low for x in generic):
            continue
        text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", inner))).strip()
        if len(text) < 12 or href in seen:
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
    listings.extend([
        ("Fix", f"https://www.fantasyfootballfix.com/blog-index/fpl-gw{gw}-transfer-tips-2026-27/"),
        ("Scout", "https://www.fantasyfootballscout.co.uk/the-complete-guide-to-gameweek-5/" if gw == 5 else "https://www.fantasyfootballscout.co.uk/"),
        ("AAFPL", f"https://allaboutfpl.com/category/fpl-gw{gw}-ultimate-guide-and-tips/"),
    ])
    return listings


def themes_for(gw):
    return [
        {"keys": ["gakpo"], "text": f"Gakpo is a priority GW{gw} transfer in."},
        {"keys": ["isak"], "text": f"Isak is a GW{gw} transfer conversation."},
        {"keys": ["rogers"], "text": f"Rogers is a Chelsea attacker to target for GW{gw}."},
        {"keys": ["de cuyper", "decuyper"], "text": "De Cuyper is the standout cheap / OOP defender."},
        {"keys": ["palmer"], "text": f"Palmer is in the GW{gw} captain conversation."},
        {"keys": ["haaland"], "text": f"Haaland remains the default GW{gw} captain."},
        {"keys": ["joao pedro", "jo\u00e3o pedro"], "text": "Jo\u00e3o Pedro stays in the template forward line."},
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


def main():
    prev = load_news()
    seen_set = set(prev.get("seen") or [])
    gw = current_gw(prev)
    listings = site_listings(gw)
    blobs, links, discovered, used = {}, [], [], set()
    for source, url in listings:
        html = fetch_html(url)
        blobs[source] = blobs.get(source, "") + " " + html.lower()
        if source not in used:
            links.append({"name": source, "url": url})
            used.add(source)
        discovered.extend(extract_article_links(html, url, source, gw))
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
    agreed, split = [], []
    for th in themes_for(gw):
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
        "note": "Public pages only. Agreed = 3+ of the sites in sources.json.",
        "agreed": agreed,
        "split": split,
        "links": links,
        "new_articles": new_articles[:12],
        "no_new": not new_articles,
        "seen": sorted(seen_set)[-200:],
    }
    NEWS_PATH.write_text("window.FPL_NEWS = " + json.dumps(news, indent=2) + ";\n")
    print("news.js", "new" if new_articles else "no-new", len(new_articles), "gw", gw)


if __name__ == "__main__":
    main()
