"""Build vs-rival tactics from already-fetched mini-league pick counts."""
POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _vs_pair(a, b, my_set, counts, owned_by, elements, teams, n):
    """Unique/shared-pick breakdown vs up to two specific rival rows (a, b)."""
    a_set = owned_by.get((a or {}).get("entry")) or set()
    b_set = owned_by.get((b or {}).get("entry")) or set()

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

    you_unique, they_share = [], []
    if n:
        for pid, c in sorted(counts.items(), key=lambda x: -x[1]):
            it = item_of(pid)
            if not it:
                continue
            if pid in my_set and (pid not in a_set or pid not in b_set) and c <= max(4, n // 3):
                row = dict(it)
                row["vs_a"] = pid not in a_set
                row["vs_b"] = pid not in b_set
                you_unique.append(row)
            if a and b and pid in a_set and pid in b_set and pid not in my_set:
                they_share.append(it)
    return you_unique[:12], they_share[:10]


def _rival_card(row, me_row, ctx_by_entry):
    """{name, pts, gap} for one rival row, plus chip-used/gap-trend/fixture extras
    when analyze_leagues fetched them for this specific rival (rival_ctx)."""
    if not row:
        return None
    card = {
        "name": row.get("entry_name"),
        "pts": row.get("total"),
        "gap": (row.get("total") - (me_row or {}).get("total")) if me_row and me_row.get("total") is not None and row.get("total") is not None else None,
    }
    ctx = (ctx_by_entry or {}).get(row.get("entry"))
    if ctx:
        if ctx.get("chips"):
            card["chips_used"] = sorted(ctx["chips"].keys())
        if ctx.get("gap_trend") is not None:
            card["gap_trend"] = ctx["gap_trend"]
        if ctx.get("fixture"):
            card["fixture"] = ctx["fixture"]
    return card


def build_tactics(rows, team_id, L, n, counts, owned_by, cap_by, my_picks, elements, teams, rival_ctx=None):
    rival_ctx = rival_ctx or {}
    sorted_rows = sorted(rows, key=lambda r: (r.get("rank") is None, r.get("rank") or 10**9))
    me_row = next((r for r in rows if r.get("entry") == team_id), None)
    me_idx = next((i for i, r in enumerate(sorted_rows) if r.get("entry") == team_id), None)
    rivals = [r for r in sorted_rows if r.get("entry") != team_id]
    first = rivals[0] if rivals else None
    second = rivals[1] if len(rivals) > 1 else None
    neighbor_above = sorted_rows[me_idx - 1] if me_idx is not None and me_idx > 0 else None
    neighbor_below = sorted_rows[me_idx + 1] if me_idx is not None and me_idx < len(sorted_rows) - 1 else None
    my_set = owned_by.get(team_id) or my_picks or set()
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

    league_template = []
    if n:
        for pid, c in sorted(counts.items(), key=lambda x: -x[1]):
            it = item_of(pid)
            if it and c >= thresh:
                league_template.append(it)

    cap_last = []
    for pid, c in sorted(cap_by.items(), key=lambda x: -x[1]):
        el = elements.get(pid)
        if el:
            cap_last.append({"name": el["web_name"], "count": c})

    leader_unique, leader_share = _vs_pair(first, second, my_set, counts, owned_by, elements, teams, n)

    result = {
        "n": n,
        "you_rank": (me_row or {}).get("rank") or L.get("entry_rank"),
        "you_pts": (me_row or {}).get("total"),
        "gap_to_first": ((first or {}).get("total") - (me_row or {}).get("total")) if first and me_row and me_row.get("total") is not None else None,
        "gap_to_second": ((second or {}).get("total") - (me_row or {}).get("total")) if second and me_row and me_row.get("total") is not None else None,
        "first": _rival_card(first, me_row, rival_ctx),
        "second": _rival_card(second, me_row, rival_ctx),
        "template": league_template[:10],
        "you_unique": leader_unique,
        "they_share": leader_share,
        "cap_last": cap_last[:6],
    }

    # "Neighbours" (whoever's directly above/below you in the table) is the more
    # actionable comparison once you're not near the top — climbing past 1st/2nd
    # isn't this week's problem if they're 40 points clear. Omit it entirely when
    # it's the same pair as leaders (you're rank 1 or 2), rather than show the
    # same two names twice under different headings.
    neighbor_entries = {r.get("entry") for r in (neighbor_above, neighbor_below) if r}
    leader_entries = {r.get("entry") for r in (first, second) if r}
    if neighbor_entries and not neighbor_entries.issubset(leader_entries):
        n_unique, n_share = _vs_pair(neighbor_above, neighbor_below, my_set, counts, owned_by, elements, teams, n)
        result["neighbors"] = {
            "above": _rival_card(neighbor_above, me_row, rival_ctx),
            "below": _rival_card(neighbor_below, me_row, rival_ctx),
            "you_unique": n_unique,
            "they_share": n_share,
        }
    else:
        result["neighbors"] = None
    return result
