#!/usr/bin/env python3
"""Live X ingest via the official X API v2 — no external bot/agent involved.

Reads a bearer token from the X_BEARER_TOKEN environment variable (set as a
GitHub Actions secret; see README for setup and the access-tier tradeoffs).
Without a token configured, this falls back to writing the same manual/seeded
stub as before, so the pipeline degrades gracefully rather than failing
outright when the credential isn't set up yet.
"""
from __future__ import annotations
import json, os
import urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fpl_common import event_window, load_js_object, load_player_index, build_themes, ARTICLE_SEP

ROOT = Path(__file__).resolve().parent
X_PATH = ROOT / "x-posts.js"
SOURCES = ROOT / "sources.json"
API_BASE = "https://api.twitter.com/2"

load_js = load_js_object


def accounts():
    if SOURCES.exists():
        try:
            return json.loads(SOURCES.read_text()).get("x_accounts") or []
        except Exception:
            pass
    return []


def api_get(path, token, **params):
    """GET path against the X API v2 with a bearer token. Returns the parsed JSON
    body even on a non-2xx response (X puts rate-limit/permission detail there
    rather than raising), or None if the request never reached the server."""
    url = f"{API_BASE}{path}"
    qs = {k: v for k, v in params.items() if v is not None}
    if qs:
        url += "?" + urlencode(qs)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "ShaalandFPLLab/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {"status": e.code, "title": str(e)}
        print(f"x_scrape.py: X API {path} returned HTTP {e.code}: {body}")
        return body
    except Exception as e:
        print(f"x_scrape.py: X API {path} request failed: {e}")
        return None


def resolve_user_ids(handles, token):
    """{handle_lower: user_id}, batching up to 100 usernames per call (API limit)."""
    out = {}
    clean = [h.lstrip("@") for h in handles if h]
    for i in range(0, len(clean), 100):
        batch = clean[i:i + 100]
        body = api_get("/users/by", token, usernames=",".join(batch))
        if not body:
            continue
        for u in body.get("data") or []:
            out[u["username"].lower()] = u["id"]
        for err in body.get("errors") or []:
            print(f"x_scrape.py: could not resolve @{err.get('value')}: {err.get('detail')}")
    return out


def fetch_recent_tweets(user_id, token, max_results=10):
    """Recent original tweets (no retweets/replies) for one account, newest first."""
    body = api_get(
        f"/users/{user_id}/tweets", token,
        max_results=max(5, min(max_results, 100)),
        exclude="retweets,replies",
        **{"tweet.fields": "created_at"},
    )
    if not body:
        return []
    return body.get("data") or []


def write_manual_stub(prev, acc, reason):
    """No usable credential: the same graceful manual/seeded stub the local dev
    fallback has always written, just no longer blaming an external AI bot for it."""
    gw, cutoff = event_window(prev)
    agreed = list(prev.get("agreed") or [])
    split = list(prev.get("split") or [])
    data = {
        "gw": gw,
        "cutoff": cutoff.strftime("%Y-%m-%d %H:%M UTC") if cutoff else None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": "manual",
        "accounts": accounts() or prev.get("accounts") or [],
        "new_posts": [],
        "no_new": True,
        "agreed": agreed,
        "split": split,
        "seen": [],
        "note": f"{reason} Add the X_BEARER_TOKEN secret to enable autonomous live ingest (see README).",
    }
    X_PATH.write_text("window.FPL_X = " + json.dumps(data, indent=2) + ";\n")
    print("x-posts.js", "mode=manual", f"({reason})", "gw", gw, "agreed", len(agreed), "split", len(split))


def main():
    prev = load_js(X_PATH)
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        if prev.get("mode") == "live":
            # Never downgrade real accumulated live data just because this run
            # (e.g. before the secret is configured, or a transient env issue)
            # lacks a token — leave the existing file untouched.
            print("x-posts.js mode=live preserved (no X_BEARER_TOKEN this run)")
            return
        write_manual_stub(prev, accounts(), "No X_BEARER_TOKEN configured, so this is a manual/seeded stub, not a live scrape.")
        return

    gw, cutoff = event_window(prev)
    acc = accounts() or prev.get("accounts") or []
    seen_set = {str(s) for s in (prev.get("seen") or [])}
    user_ids = resolve_user_ids([a.get("handle") for a in acc], token)

    blobs, new_posts = {}, []
    for a in acc:
        handle = a.get("handle")
        uid = user_ids.get((handle or "").lower())
        if not handle or not uid:
            continue
        for t in fetch_recent_tweets(uid, token):
            tid, text = t.get("id"), t.get("text") or ""
            dt = None
            if t.get("created_at"):
                try:
                    dt = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
                except Exception:
                    dt = None
            if not tid or not dt or (cutoff and dt <= cutoff):
                continue  # no confirmed in-window date -> skip rather than risk stale content
            blobs[handle] = blobs.get(handle, "") + ARTICLE_SEP + text
            if tid not in seen_set:
                new_posts.append({
                    "handle": handle, "text": text,
                    "url": f"https://x.com/{handle}/status/{tid}",
                    "at": dt.strftime("%Y-%m-%d %H:%M UTC"),
                })
                seen_set.add(tid)

    try:
        player_index = load_player_index()
    except Exception as e:
        print(f"x_scrape.py: could not load player index for theme discovery: {e}")
        player_index = []
    agreed, split = build_themes(blobs, gw, player_index, unit="accounts") if player_index else ([], [])

    if not agreed and not split and prev.get("gw") == gw:
        # Only reuse prior themes within the same planning GW (nothing new this
        # run — e.g. a rate limit — shouldn't blank out otherwise-valid themes).
        agreed = list(prev.get("agreed") or [])
        split = list(prev.get("split") or [])

    data = {
        "gw": gw,
        "cutoff": cutoff.strftime("%Y-%m-%d %H:%M UTC") if cutoff else None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": "live",
        "accounts": acc,
        "new_posts": new_posts[:12],
        "no_new": not new_posts,
        "agreed": agreed,
        "split": split,
        "seen": sorted(seen_set)[-500:],
        "note": "Live X ingest via the X API. Split first. Agreed = 3+ accounts. Themes are handle mentions auto-detected in tweet text, not a fixed watchlist.",
    }
    X_PATH.write_text("window.FPL_X = " + json.dumps(data, indent=2) + ";\n")
    print("x-posts.js", "mode=live", "gw", gw, "new_posts", len(new_posts), "agreed", len(agreed), "split", len(split))


if __name__ == "__main__":
    main()
