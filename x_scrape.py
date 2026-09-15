#!/usr/bin/env python3
from __future__ import annotations
import json, re, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
X_PATH = ROOT / "x-posts.js"
SOURCES = ROOT / "sources.json"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ShaalandFPLLab/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def parse_iso(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def event_window(prev=None):
    gw, cutoff = (prev or {}).get("gw"), None
    try:
        boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
        events = sorted(boot["events"], key=lambda e: e["id"])
        upcoming = [e for e in events if not e.get("finished")]
        if upcoming:
            cur = upcoming[0]
            gw = cur["id"]
            cutoff = parse_iso(cur.get("deadline_time") or "")
        elif any(e.get("is_current") or e.get("is_next") for e in events):
            cur = next(e for e in events if e.get("is_current") or e.get("is_next"))
            gw = cur["id"]
            cutoff = parse_iso(cur.get("deadline_time") or "")
    except Exception:
        pass
    return gw, cutoff


def load_js(path):
    if not path.exists():
        return {}
    raw = path.read_text()
    s, e = raw.find("{{"), raw.rfind("}}" )
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e == -1:
        return {}
    try:
        return json.loads(raw[s:e + 1])
    except Exception:
        return {}


def accounts():
    if SOURCES.exists():
        try:
            return json.loads(SOURCES.read_text()).get("x_accounts") or []
        except Exception:
            pass
    return []


def older_gw_in(text, gw):
    low = str(text or "").lower()
    for n in range(1, int(gw or 1)):
        if f"gw{n}" in low or f"gameweek {n}" in low or f"gameweek-{n}" in low:
            return True
    return False


def keep_item(item, gw, cutoff):
    blob = " ".join(str(item.get(k) or "") for k in ("text", "url", "id", "handle"))
    if older_gw_in(blob, gw):
        return False
    raw = item.get("at") or item.get("published") or ""
    dt = parse_iso(raw)
    if dt and cutoff and dt <= cutoff:
        return False
    return True


def themes_for(gw):
    return [
        {"keys": ["haaland"], "text": f"Haaland remains the default GW{gw} captain."},
        {"keys": ["gibbs-white", "gibbs white", "mgw"], "text": f"Gibbs-White is a GW{gw} Forest mid target."},
        {"keys": ["rogers"], "text": f"Rogers is a Chelsea attacker to target for GW{gw}."},
        {"keys": ["palmer"], "text": f"Palmer is in the GW{gw} captain conversation."},
        {"keys": ["gakpo"], "text": f"Gakpo is a GW{gw} Liverpool mid conversation."},
        {"keys": ["isak"], "text": f"Isak is a GW{gw} transfer conversation."},
        {"keys": ["joao pedro", "jo\u00e3o pedro"], "text": "Jo\u00e3o Pedro stays in the template forward line."},
        {"keys": ["wissa"], "text": "Wissa is a popular forward move."},
        {"keys": ["wildcard", "wc5", "wc 5"], "text": f"GW{gw} is a live wildcard window for some elite sides."},
        {"keys": ["free hit", "fh"], "text": f"GW{gw} Free Hit drafts are a live talking point."},
        {"keys": ["muharemovic", "muaharemovic"], "text": "Muharemovi\u0107 is a cheap defender alternative this week."},
        {"keys": ["price"], "text": "Daily price risers / fallers."},
    ]


def main():
    prev = load_js(X_PATH)
    gw, cutoff = event_window(prev)
    acc = accounts() or prev.get("accounts") or []
    seen_set = {u for u in (prev.get("seen") or []) if not older_gw_in(u, gw)}
    posts = [p for p in (prev.get("posts") or prev.get("new_posts") or []) if keep_item(p, gw, cutoff)]
    blobs = {}
    for p in posts:
        h = p.get("handle") or "?"
        blobs[h] = blobs.get(h, "") + " " + str(p.get("text") or "").lower()
    new_posts = []
    for p in posts:
        key = p.get("id") or p.get("text")
        if key and key not in seen_set:
            new_posts.append({"handle": p.get("handle"), "text": p.get("text")})
            seen_set.add(key)
        elif key:
            seen_set.add(key)
    agreed, split = [], []
    for th in themes_for(gw):
        sources = [n for n, blob in blobs.items() if any(k in blob for k in th["keys"])]
        item = {"text": th["text"], "sources": sources}
        if len(sources) >= 3:
            agreed.append(item)
        elif sources:
            split.append(item)
    if not posts:
        agreed = [x for x in (prev.get("agreed") or []) if not older_gw_in(x.get("text"), gw)]
        split = [x for x in (prev.get("split") or []) if not older_gw_in(x.get("text"), gw)]
        for row in agreed + split:
            row["text"] = re.sub(r"GW\d+", f"GW{gw}", row.get("text") or "")
    data = {
        "gw": gw,
        "cutoff": cutoff.strftime("%Y-%m-%d %H:%M UTC") if cutoff else None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "accounts": acc,
        "new_posts": new_posts[:12],
        "no_new": not new_posts,
        "agreed": agreed,
        "split": split,
        "seen": sorted(str(x) for x in seen_set)[-200:],
        "note": "Agreed = 3+ of the tracked X accounts. New = after current GW deadline. Public posts only.",
    }
    X_PATH.write_text("window.FPL_X = " + json.dumps(data, indent=2) + ";\n")
    print("x-posts.js", "new" if new_posts else "no-new", len(new_posts), "gw", gw, "cutoff", data["cutoff"])


if __name__ == "__main__":
    main()
