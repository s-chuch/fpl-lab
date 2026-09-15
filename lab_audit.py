"""Process vs outcome helpers for refresh.py."""
from datetime import datetime, timezone


def add_roll_rows(rows, hist, chips_used):
    have = {(t.get("gw"), t.get("inn")) for t in rows}
    out = list(rows)
    for row in hist.get("current", []):
        gw = row["event"]
        if int(row.get("event_transfers") or 0) != 0:
            continue
        if chips_used.get("freehit") == gw:
            continue
        if (gw, "ROLL") in have:
            continue
        out.append({"gw": gw, "out": "\u2014", "inn": "ROLL", "net": "0", "verdict": "Rolled", "process": "ok", "outcome": "n/a"})
    out.sort(key=lambda x: (x.get("gw") or 0, 0 if x.get("inn") == "ROLL" else 1))
    return out
