#!/usr/bin/env python3
"""Turn a "Transfers GW<n> <team>" issue into my_transfers.json (see my_transfers.py). Run by .github/workflows/log-transfers.yml.

The issue text arrives through environment variables only (ISSUE_BODY, ISSUE_TITLE, ISSUE_NUMBER) and is treated as untrusted data: it is parsed
as JSON and every field is checked against FPL before anything is written. Writes the reply for the issue to the file named by REPLY_FILE
and exits 0 when the moves were stored, 1 when they were refused."""
from __future__ import annotations

import json
import os
import re
import sys

import my_transfers as T
from fplbase import get


def parse_body(text):
    """The JSON object in the issue body (plain or inside a ``` fence)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.S) or re.search(r"(\{.*\})", text or "", re.S)
    if not m:
        raise ValueError("no JSON found in the issue body")
    req = json.loads(m.group(1))
    if not isinstance(req, dict):
        raise ValueError("the issue body must be a JSON object")
    return req


def squad_before(boot, team_id):
    """Your 15 players at the last deadline (the squad the next gameweek's transfers start from)."""
    fin = sorted((e["id"] for e in boot["events"] if e.get("finished")), reverse=True)
    for gw in fin[:3]:
        pk = get(f"https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/")
        if pk.get("active_chip") == "freehit":          # a Free Hit squad reverts: the squad before it is the real starting point
            continue
        ids = [p["element"] for p in pk.get("picks") or []]
        if len(ids) == 15:
            return ids
    return []


def main():
    reply = os.environ.get("REPLY_FILE") or "log_reply.md"
    def done(ok, text):
        open(reply, "w").write(text + "\n")
        print(text)
        return 0 if ok else 1
    try:
        req = parse_body(os.environ.get("ISSUE_BODY", ""))
    except (ValueError, TypeError) as e:
        return done(False, f"Not saved: {e}.")
    boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
    team_id = T.TEAMS.get(req.get("team"))
    if not team_id:
        return done(False, f"Not saved: team must be one of {', '.join(T.TEAMS)}.")
    squad = squad_before(boot, team_id)
    if not squad:
        return done(False, "Not saved: could not read your squad from FPL right now. Try again in a few minutes.")
    moves, errs = T.validate(req, boot, squad)
    if errs:
        return done(False, "Not saved:\n" + "\n".join(f"- {e}" for e in errs))
    name = {e["id"]: e["web_name"] for e in boot["elements"]}
    doc = T.record(T.load(), team_id, req["gw"], moves, issue=os.environ.get("ISSUE_NUMBER"))
    T.save(doc)
    return done(True, f"Saved for {req['team']} GW{req['gw']}: " + ", ".join(f"{name[m['out']]} -> {name[m['in']]}" for m in moves)
                + ". The Plan tab updates after the next refresh (a couple of minutes).")


if __name__ == "__main__":
    sys.exit(main())
