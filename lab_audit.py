"""Process vs outcome helpers for refresh.py."""


CHIP_LABEL = {"wildcard": "Wildcard", "freehit": "Free Hit"}


def add_roll_rows(rows, hist, chips_used, squad_changes=None):
    """Chip weeks (Wildcard / Free Hit) collapse into ONE summary row: those moves are
    free and rebuild the squad (a Free Hit reverts, a Wildcard draft is churn), so judging
    each swap on a single GW's points is noise and must not feed the season net. GW1 is
    the initial squad, never a "roll"."""
    chip_gw = {c["event"]: c["name"] for c in hist.get("chips", []) if c.get("name") in CHIP_LABEL}
    out, counts = [], {}
    for t in rows:
        if t.get("gw") in chip_gw:
            counts[t["gw"]] = counts.get(t["gw"], 0) + 1
        else:
            out.append(t)
    for gw, n in counts.items():
        n = (squad_changes or {}).get(gw, n)      # players really changed, not the transfers FPL logged (swaps in a chain count twice)
        name = CHIP_LABEL[chip_gw[gw]]
        out.append({"gw": gw, "out": name, "inn": f"{n} move{'' if n == 1 else 's'}", "net": "0", "chip": chip_gw[gw],
                    "verdict": "Squad reverts next GW" if chip_gw[gw] == "freehit" else "Free rebuild - judged by the squad, not each swap"})
    have = {(t.get("gw"), t.get("inn")) for t in out}
    for row in hist.get("current", []):
        gw = row["event"]
        if gw == 1 or gw in chip_gw or int(row.get("event_transfers") or 0) != 0:
            continue
        if (gw, "ROLL") in have:
            continue
        out.append({"gw": gw, "out": "\u2014", "inn": "ROLL", "net": "0", "verdict": "Rolled", "process": "ok", "outcome": "n/a"})
    out.sort(key=lambda x: (x.get("gw") or 0, 0 if x.get("inn") == "ROLL" or x.get("chip") else 1))
    return out
