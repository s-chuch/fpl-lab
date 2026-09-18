"""Shared helpers for the refresh/scrape scripts: a retrying JSON GET, ISO date
parsing, the planning-GW/cutoff window used to line up scrape themes with the
live gameweek, and the `window.X = {...};` data-file loader."""
from __future__ import annotations
import json, time, urllib.error, urllib.request
from datetime import datetime, timezone

USER_AGENT = "ShaalandFPLLab/1.0"


def get(url, timeout=20, retries=3, backoff=1.5):
    """GET url as JSON, retrying transient failures with exponential backoff."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except (OSError, json.JSONDecodeError) as e:
            last_err = e
            if attempt < retries - 1:
                print(f"get() retry {attempt + 1}/{retries - 1} after {e} — {url}")
                time.sleep(backoff ** attempt)
    raise last_err


def parse_iso(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def event_window(prev=None):
    """Return (planning_gw, cutoff).

    planning_gw = first event whose deadline has *not* passed (next open GW).
    After GW N locks, themes target GW N+1 even if GW N matches are still unfinished.
    cutoff = deadline of the latest locked GW (or last finished), so in-window articles
    are those published after the previous GW locked.
    """
    gw = (prev or {}).get("gw")
    cutoff = None
    try:
        boot = get("https://fantasy.premierleague.com/api/bootstrap-static/")
        events = sorted(boot["events"], key=lambda e: e["id"])
        now = datetime.now(timezone.utc)
        locked, open_ev = [], []
        for e in events:
            dl = parse_iso(e.get("deadline_time") or "")
            if dl and now >= dl:
                locked.append(e)
            elif dl and now < dl:
                open_ev.append(e)
            elif not dl and not e.get("finished"):
                open_ev.append(e)
        if open_ev:
            gw = open_ev[0]["id"]
        else:
            unfinished = [e for e in events if not e.get("finished")]
            if unfinished:
                gw = unfinished[0]["id"]
            elif any(e.get("is_current") or e.get("is_next") for e in events):
                cur = next(e for e in events if e.get("is_current") or e.get("is_next"))
                gw = cur["id"]
        # Cutoff = most recently locked GW deadline (picks public); else last finished
        if locked:
            cutoff = parse_iso(locked[-1].get("deadline_time") or "")
        else:
            finished = [e for e in events if e.get("finished")]
            if finished:
                cutoff = parse_iso(finished[-1].get("deadline_time") or "")
            elif gw:
                prev_ev = [e for e in events if e["id"] < int(gw)]
                if prev_ev:
                    cutoff = parse_iso(prev_ev[-1].get("deadline_time") or "")
    except Exception:
        pass
    return gw, cutoff


def load_js_object(path):
    """Parse the JSON object embedded in a `window.X = {...};` data file."""
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
