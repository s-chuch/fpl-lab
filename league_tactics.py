"""Build vs-1st/2nd tactics from already-fetched mini-league pick counts."""
POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def build_tactics(rows, team_id, L, n, counts, owned_by, cap_by, my_picks, elements, teams):
    rivals = [r for r in rows if r.get("entry") != team_id]
    first = rivals[0] if rivals else None
    second = rivals[1] if len(rivals) > 1 else None
    me_row = next((r for r in rows if r.get("entry") == team_id), None)
    my_set = owned_by.get(team_id) or my_picks or set()
    first_set = owned_by.get((first or {}).get("entry")) or set()
    second_set = owned_by.get((second or {}).get("entry")) or set()
    thresh = max(3, (n + 1) // 2) if n else 7

    def item_of(pid):
        el = elements.get(pid)
        if not el:
            return None
        return {
            "name": el["web_name"],
            "club": teams[el["team"]]["short_name"],
            "pos": POS[el["element_type"]],
            "count": counts.get(pid, 0),
            "n": n,
            "own": round(100 * counts.get(pid, 0) / n) if n else 0,
        }

    league_template, you_unique, they_share = [], [], []
    if n:
        for pid, c in sorted(counts.items(), key=lambda x: -x[1]):
            it = item_of(pid)
            if not it:
                continue
            if c >= thresh:
                league_template.append(it)
            if pid in my_set and (pid not in first_set or pid not in second_set) and c <= max(4, n // 3):
                row = dict(it)
                row["vs_first"] = pid not in first_set
                row["vs_second"] = pid not in second_set
                you_unique.append(row)
            if pid in first_set and pid in second_set and pid not in my_set:
                they_share.append(it)
    cap_last = []
    for pid, c in sorted(cap_by.items(), key=lambda x: -x[1]):
        el = elements.get(pid)
        if el:
            cap_last.append({"name": el["web_name"], "count": c})
    return {
        "n": n,
        "you_rank": (me_row or {}).get("rank") or L.get("entry_rank"),
        "you_pts": (me_row or {}).get("total"),
        "gap_to_first": ((first or {}).get("total") - (me_row or {}).get("total")) if first and me_row and me_row.get("total") is not None else None,
        "gap_to_second": ((second or {}).get("total") - (me_row or {}).get("total")) if second and me_row and me_row.get("total") is not None else None,
        "first": {"name": (first or {}).get("entry_name"), "pts": (first or {}).get("total")} if first else None,
        "second": {"name": (second or {}).get("entry_name"), "pts": (second or {}).get("total")} if second else None,
        "template": league_template[:10],
        "you_unique": you_unique[:12],
        "they_share": they_share[:10],
        "cap_last": cap_last[:6],
    }
