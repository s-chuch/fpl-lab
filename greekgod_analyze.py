#!/usr/bin/env python3
"""Season-long archive + analysis for a single X account (greekgodFpl).

x-posts.js only ever holds a rolling recent-post window from the live
Grok Bot ingest (an external process this repo doesn't control) — posts
age out of it over time. This persists every distinct post ever seen from
this one handle into a standalone archive, so a season-long view survives
that rolling window. Run every refresh cycle: reads whatever's currently
in x-posts.js, merges in any new greekgodFpl posts (dedup by id) on top
of the existing archive, then recomputes mention/call analysis from the
FULL archived history using real player/team names — the same discovery
approach news_scrape.py/x_scrape.py use for cross-source theme detection
(fpl_common.load_player_index / qualifiers_near), just applied within one
account's own post history instead of across multiple sources.

Coverage note: live X ingest itself only started partway through this
season (previously a manual/seeded stub) — a handful of earlier posts
were hand-recovered from git history of x-posts.js as the initial seed,
but anything from before live ingest began was never scraped and can't
be recovered. "Season-long" here means "since we started actually
tracking it."
"""
from __future__ import annotations
import json, re
from pathlib import Path
from datetime import datetime, timezone

from fpl_common import load_js_object, load_player_index, qualifiers_near, norm_keep_case

ROOT = Path(__file__).resolve().parent
ARCHIVE_PATH = ROOT / "greekgod-archive.js"
XPOSTS_PATH = ROOT / "x-posts.js"
HANDLE = "greekgodFpl"

# Self-referential prediction-claim language — flags a post as worth
# checking against what actually happened, not an automated verdict on
# whether the call itself was right (that needs a human read of the
# specific claim vs. the result).
CALLED_IT_RE = re.compile(r"\bwe (?:called|told you)\b|\bcalled it\b|\bwe called for\b|\bconfirmed\b", re.I)
CHIP_RE = re.compile(r"\bwildcard\b|\bbench boost\b|\btriple captain\b|\bfree hit\b", re.I)


def classify_post(text):
    tags = set()
    if CALLED_IT_RE.search(text):
        tags.add("called_it")
    if CHIP_RE.search(text):
        tags.add("chip")
    return tags


def main():
    player_index = load_player_index()

    archive = load_js_object(ARCHIVE_PATH)
    posts_by_id = {p["id"]: p for p in archive.get("posts", []) if p.get("id")}

    xposts = load_js_object(XPOSTS_PATH)
    new_count = 0
    for p in xposts.get("posts", []) or []:
        if p.get("handle") == HANDLE and p.get("id") and p["id"] not in posts_by_id:
            posts_by_id[p["id"]] = {"id": p["id"], "at": p.get("at"), "text": p.get("text", ""), "url": p.get("url")}
            new_count += 1

    posts = sorted(posts_by_id.values(), key=lambda p: p.get("at") or "")

    player_counts, calls = {}, []
    for p in posts:
        text = norm_keep_case(p.get("text") or "")
        post_tags = classify_post(p.get("text") or "")
        mentioned_here = []
        for pl in player_index:
            if not re.search(rf"\b{re.escape(pl['match'])}\b", text):
                continue
            rec = player_counts.setdefault(pl["web_name"], {"club": pl["club"], "count": 0})
            rec["count"] += 1
            mentioned_here.append(pl["web_name"])
            post_tags |= qualifiers_near(text, pl["match"])
        # Only surface a post as a "call" if it's actionable (captain/transfer
        # advice, chip timing) or a prediction claim — plain commentary/banter
        # with no player mention and no chip/claim language is left out.
        if post_tags & {"captain talk", "transfer target", "chip", "called_it"}:
            calls.append({**p, "tags": sorted(post_tags), "players": mentioned_here})

    club_counts = {}
    for rec in player_counts.values():
        if rec["club"]:
            club_counts[rec["club"]] = club_counts.get(rec["club"], 0) + rec["count"]

    data = {
        "handle": HANDLE,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "post_count": len(posts),
        "new_since_last_run": new_count,
        "earliest": posts[0]["at"] if posts else None,
        "latest": posts[-1]["at"] if posts else None,
        "player_mentions": sorted(
            ({"name": k, "club": v["club"], "count": v["count"]} for k, v in player_counts.items()),
            key=lambda x: -x["count"],
        )[:20],
        "club_mentions": sorted(
            ({"club": k, "count": v} for k, v in club_counts.items()), key=lambda x: -x["count"]
        )[:15],
        "calls": sorted(calls, key=lambda p: p.get("at") or "", reverse=True),
        "posts": posts,  # full archive, kept for continuity across runs — not necessarily rendered in full
    }
    ARCHIVE_PATH.write_text("window.FPL_GREEKGOD = " + json.dumps(data, indent=2, ensure_ascii=False) + ";\n")
    print(f"greekgod-archive.js: {len(posts)} posts total ({new_count} new), {len(calls)} tagged calls")


if __name__ == "__main__":
    main()
