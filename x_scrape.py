#!/usr/bin/env python3
"""Honest X handler: no live scrape until real post ingest exists.

Preserves manual/seeded agreed+split themes and the accounts list from
sources.json. Does not invent posts, rewrite GW labels onto stale themes,
or claim a fresh crawl.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
X_PATH = ROOT / "x-posts.js"
SOURCES = ROOT / "sources.json"


def get(url):
    import urllib.request
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
    """current_gw = first unfinished; cutoff = last finished GW deadline."""
    gw = (prev or {}).get("gw")
    cutoff = None
    try:
        boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
        events = sorted(boot["events"], key=lambda e: e["id"])
        finished = [e for e in events if e.get("finished")]
        upcoming = [e for e in events if not e.get("finished")]
        if upcoming:
            gw = upcoming[0]["id"]
        elif any(e.get("is_current") or e.get("is_next") for e in events):
            cur = next(e for e in events if e.get("is_current") or e.get("is_next"))
            gw = cur["id"]
        if finished:
            cutoff = parse_iso(finished[-1].get("deadline_time") or "")
        elif gw:
            prev_ev = [e for e in events if e["id"] < int(gw)]
            if prev_ev:
                cutoff = parse_iso(prev_ev[-1].get("deadline_time") or "")
    except Exception:
        pass
    return gw, cutoff


def load_js(path):
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


def accounts():
    if SOURCES.exists():
        try:
            return json.loads(SOURCES.read_text()).get("x_accounts") or []
        except Exception:
            pass
    return []


def main():
    prev = load_js(X_PATH)
    gw, cutoff = event_window(prev)
    acc = accounts() or prev.get("accounts") or []
    # Preserve manual/seeded themes as-is — do NOT rewrite GW numbers
    agreed = list(prev.get("agreed") or [])
    split = list(prev.get("split") or [])
    data = {
        "gw": gw,
        "cutoff": cutoff.strftime("%Y-%m-%d %H:%M UTC") if cutoff else None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": "manual",
        "accounts": acc,
        "new_posts": [],
        "no_new": True,
        "agreed": agreed,
        "split": split,
        "seen": [],
        "note": "Manual/seeded themes until live X ingest exists. Accounts listed for follow — not a live scrape. Agreed/split are curated seeds, not fresh posts.",
    }
    X_PATH.write_text("window.FPL_X = " + json.dumps(data, indent=2) + ";\n")
    print("x-posts.js", "mode=manual", "gw", gw, "cutoff", data["cutoff"], "agreed", len(agreed), "split", len(split))


if __name__ == "__main__":
    main()
