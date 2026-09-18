#!/usr/bin/env python3
"""Local/manual X stub — does NOT live-scrape X.

Live X ingest is the Grok Bot daily routine (10am ET) via the connected
user-X MCP plugin, which writes x-posts.js with mode:"live".

GitHub Actions must NOT run this script or commit x-posts.js.

Behavior when run locally:
  - If x-posts.js exists and mode is \"live\", leave the file unchanged and exit.
  - If the file is missing or already mode \"manual\", write/refresh the manual stub
    (preserves curated agreed/split themes and accounts from sources.json).
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from fpl_common import event_window, load_js_object

ROOT = Path(__file__).resolve().parent
X_PATH = ROOT / "x-posts.js"
SOURCES = ROOT / "sources.json"

load_js = load_js_object


def accounts():
    if SOURCES.exists():
        try:
            return json.loads(SOURCES.read_text()).get("x_accounts") or []
        except Exception:
            pass
    return []


def main():
    prev = load_js(X_PATH)
    if prev.get("mode") == "live":
        print(
            "x-posts.js mode=live preserved (live ingest is Grok Bot / user-X MCP; "
            "local x_scrape.py will not overwrite)"
        )
        return

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
        "note": (
            "Manual/seeded themes until next live X ingest (Grok Bot 10am ET via "
            "user-X MCP). Accounts listed for follow — not a live scrape. "
            "Agreed/split are curated seeds, not fresh posts."
        ),
    }
    X_PATH.write_text("window.FPL_X = " + json.dumps(data, indent=2) + ";\n")
    print("x-posts.js", "mode=manual", "gw", gw, "cutoff", data["cutoff"], "agreed", len(agreed), "split", len(split))


if __name__ == "__main__":
    main()
