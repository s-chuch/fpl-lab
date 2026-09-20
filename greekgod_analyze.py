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

from fpl_common import get, parse_iso, load_js_object, load_player_index, qualifiers_near, norm_keep_case

ROOT = Path(__file__).resolve().parent
ARCHIVE_PATH = ROOT / "greekgod-archive.js"
XPOSTS_PATH = ROOT / "x-posts.js"
HANDLE = "greekgodFpl"
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"

# Self-referential prediction-claim language — flags a post as worth
# checking against what actually happened, not an automated verdict on
# whether the call itself was right (that needs a human read of the
# specific claim vs. the result). Captain/transfer calls get an automated
# verdict instead (see grade_call below) since those resolve to a concrete,
# checkable number (the player's actual points).
CALLED_IT_RE = re.compile(r"\bwe (?:called|told you)\b|\bcalled it\b|\bwe called for\b|\bconfirmed\b", re.I)
CHIP_RE = re.compile(r"\bwildcard\b|\bbench boost\b|\btriple captain\b|\bfree hit\b", re.I)

# Points thresholds for an automated good/bad/mixed verdict. Captaincy
# doubles the score so a captain call needs a real haul to count as "good";
# a transfer target is judged on a single unmultiplied gameweek return.
CAPTAIN_GOOD, CAPTAIN_BAD = 8, 2
TRANSFER_GOOD, TRANSFER_BAD = 6, 1

# fpl_common.qualifiers_near uses a wide symmetric character window, which is
# fine for "does this post touch on captaincy at all" (the loose post-level
# "tags" shown as pills) but too loose to say WHICH player a call is about —
# e.g. "...play Szoboszlai and Captain Bruno" puts "captain" within range of
# Szoboszlai even though the sentence names Bruno, not him. Grading needs the
# stricter question "is this in the same clause as the player's own mention,
# with no and/or/sentence break in between" — "and"/"or"/a full stop reliably
# mark a shift to a different subject; a comma usually doesn't (e.g. "Buytest,
# priority pick for your squad" is still about Buytest), so it's not a break.
CLAUSE_BREAK_RE = re.compile(r"\b(?:and|or)\b|[.\n]", re.I)
CAPTAIN_KEYWORD_RE = re.compile(r"\bcaptain\b", re.I)
TRANSFER_KEYWORD_RE = re.compile(r"transfer in|bring (?:him|her)? ?in|priority (?:buy|pick)|target for", re.I)


def same_clause_as(text, key, keyword_re, radius=80):
    """True if `keyword_re` occurs in the same clause as some mention of
    `key` — on either side, but not past the nearest and/or/sentence break."""
    for m in re.finditer(rf"\b{re.escape(key)}\b", text):
        left = text[max(0, m.start() - radius):m.start()]
        right = text[m.end():m.end() + radius]
        left_clause = CLAUSE_BREAK_RE.split(left)[-1]
        right_clause = CLAUSE_BREAK_RE.split(right)[0]
        if keyword_re.search(left_clause) or keyword_re.search(right_clause):
            return True
    return False


def classify_post(text):
    tags = set()
    if CALLED_IT_RE.search(text):
        tags.add("called_it")
    if CHIP_RE.search(text):
        tags.add("chip")
    return tags


def parse_at(raw):
    """Parse the "YYYY-MM-DD HH:MM UTC" post timestamp format used throughout
    this archive (see toToronto() in dashboard-common.js for the same shape
    handled on the display side)."""
    if not raw:
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})", str(raw))
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def target_gw_for(post_at, events):
    """A captain/transfer call is advice for whichever GW hadn't locked yet
    when the post went out — the first event whose deadline is still ahead
    of the post. Returns None once the post is after every known deadline
    (nothing left to grade it against)."""
    if not post_at:
        return None
    for e in events:
        dl = parse_iso(e.get("deadline_time") or "")
        if dl and post_at < dl:
            return e
    return None


def grade_call(kind, pts):
    good, bad = (CAPTAIN_GOOD, CAPTAIN_BAD) if kind == "captain" else (TRANSFER_GOOD, TRANSFER_BAD)
    if pts >= good:
        return "good"
    if pts <= bad:
        return "bad"
    return "mixed"


def main():
    boot = get(BOOTSTRAP_URL)
    player_index = load_player_index(boot)
    events = sorted(boot["events"], key=lambda e: e["id"])

    live_cache = {}

    def points_for(gw, player_id):
        if gw not in live_cache:
            try:
                live_cache[gw] = {
                    el["id"]: el["stats"]["total_points"]
                    for el in get(f"https://fantasy.premierleague.com/api/event/{gw}/live/").get("elements", [])
                }
            except Exception as e:
                print(f"warn: could not load GW{gw} live data for call grading: {e}")
                live_cache[gw] = {}
        return live_cache[gw].get(player_id, 0)

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
        mentioned_here, graded = [], []
        target_event = target_gw_for(parse_at(p.get("at")), events)
        for pl in player_index:
            if not re.search(rf"\b{re.escape(pl['match'])}\b", text):
                continue
            rec = player_counts.setdefault(pl["web_name"], {"club": pl["club"], "count": 0})
            rec["count"] += 1
            mentioned_here.append(pl["web_name"])
            player_tags = qualifiers_near(text, pl["match"])
            post_tags |= player_tags
            # Grade this specific player's mention, not the whole post — a
            # post can name a captain pick and a separate transfer target in
            # the same breath, and each resolves against its own number.
            # Uses the stricter same-clause check, not the post-level tags
            # above: a wrong attribution here corrupts the automated verdict,
            # whereas the loose tags are just "this post touches the topic".
            if same_clause_as(text, pl["match"], CAPTAIN_KEYWORD_RE):
                kind = "captain"
            elif same_clause_as(text, pl["match"], TRANSFER_KEYWORD_RE):
                kind = "transfer"
            else:
                kind = None
            if kind and target_event:
                gw = target_event["id"]
                if not target_event.get("finished"):
                    graded.append({"player": pl["web_name"], "kind": kind, "gw": gw, "pts": None, "verdict": "pending"})
                else:
                    pts = points_for(gw, pl["id"])
                    graded.append({"player": pl["web_name"], "kind": kind, "gw": gw, "pts": pts, "verdict": grade_call(kind, pts)})
        # Only surface a post as a "call" if it's actionable (captain/transfer
        # advice, chip timing) or a prediction claim — plain commentary/banter
        # with no player mention and no chip/claim language is left out.
        if post_tags & {"captain talk", "transfer target", "chip", "called_it"}:
            calls.append({**p, "tags": sorted(post_tags), "players": mentioned_here, "graded": graded})

    club_counts = {}
    for rec in player_counts.values():
        if rec["club"]:
            club_counts[rec["club"]] = club_counts.get(rec["club"], 0) + rec["count"]

    resolved = [g for c in calls for g in c["graded"] if g["verdict"] != "pending"]
    good = sum(1 for g in resolved if g["verdict"] == "good")
    bad = sum(1 for g in resolved if g["verdict"] == "bad")
    mixed = sum(1 for g in resolved if g["verdict"] == "mixed")
    pending = sum(1 for c in calls for g in c["graded"] if g["verdict"] == "pending")
    total = len(resolved)
    call_grades = {
        "graded": total,
        "pending": pending,
        "good": good,
        "mixed": mixed,
        "bad": bad,
        "good_pct": round(good / total * 100, 1) if total else None,
        "mixed_pct": round(mixed / total * 100, 1) if total else None,
        "bad_pct": round(bad / total * 100, 1) if total else None,
    }

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
        "call_grades": call_grades,
        "calls": sorted(calls, key=lambda p: p.get("at") or "", reverse=True),
        "posts": posts,  # full archive, kept for continuity across runs — not necessarily rendered in full
    }
    ARCHIVE_PATH.write_text("window.FPL_GREEKGOD = " + json.dumps(data, indent=2, ensure_ascii=False) + ";\n")
    print(f"greekgod-archive.js: {len(posts)} posts total ({new_count} new), {len(calls)} tagged calls, "
          f"{total} graded ({good} good / {mixed} mixed / {bad} bad), {pending} pending")


if __name__ == "__main__":
    main()
