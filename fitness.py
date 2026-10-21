"""One reading of FPL's fitness fields, shared by the expected-points model (ai_team.availability) and the page flags
(fplbase.player_availability), so the two never disagree.

FPL gives `chance_of_playing_next_round` and `chance_of_playing_this_round` (0-100 or None) plus a status
(a available, d doubtful, i injured, s suspended, u unavailable) and a news line. A doubtful player sometimes has
no percentage at all: the old code then guessed 75%. FPL's own doubtful buckets are 25 / 50 / 75, so a doubt with
nothing stated is read from the news text ("50% chance of playing") and, failing that, assumed to be 50%, the
middle of the buckets, and flagged as assumed."""
from __future__ import annotations
import re

ASSUMED_DOUBT = 50
_PCT = re.compile(r"(\d{1,3})\s*%\s*chance", re.I)


def chance(el):
    """-> (percent 0-100, source) with source one of "next", "this", "news", "assumed" (a doubt with no number) or "status"
    (no number needed: available / out)."""
    st = (el.get("status") or "a").lower()
    if st in ("u", "s", "i"):
        return 0, "status"
    for key, src in (("chance_of_playing_next_round", "next"), ("chance_of_playing_this_round", "this")):
        v = el.get(key)
        if v is not None:
            return max(0, min(100, int(v))), src
    m = _PCT.search(el.get("news") or "")
    if m:
        return max(0, min(100, int(m.group(1)))), "news"
    if st == "d":
        return ASSUMED_DOUBT, "assumed"
    return 100, "status"
