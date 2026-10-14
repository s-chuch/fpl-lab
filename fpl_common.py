"""Shared helpers for the refresh/scrape scripts: a retrying JSON GET, ISO date
parsing, the planning-GW/cutoff window used to line up scrape themes with the
live gameweek, the `window.X = {...};` data-file loader, and the player-mention
trend discovery used by news_scrape.py so a name only has
to actually be talked about somewhere to surface as a theme — never a fixed,
hand-maintained watchlist."""
from __future__ import annotations
import http.client, json, re, threading, time, unicodedata, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

USER_AGENT = "ShaalandFPLLab/1.0"


_local = threading.local()


def _connection(host, timeout):
    """One keep-alive HTTPS connection per host per thread, so a run of ~70 requests pays for the TLS
    handshake once instead of every time."""
    conns = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = {}
    c = conns.get(host)
    if c is None:
        c = conns[host] = http.client.HTTPSConnection(host, timeout=timeout)
    return c


def _drop(host):
    c = getattr(_local, "conns", {}).pop(host, None)
    if c is not None:
        try:
            c.close()
        except Exception:
            pass


def _get_urllib(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get(url, timeout=20, retries=3, backoff=1.5):
    """GET url as JSON over a reused connection. Transient failures (timeouts, dropped connections,
    5xx, 429, bad JSON) are retried with exponential backoff; any other 4xx (e.g. the expected 404 for a
    gameweek that has not locked yet) is raised straight away - retrying cannot change the answer."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        return _get_urllib(url, timeout)
    path = parts.path + (("?" + parts.query) if parts.query else "")
    last_err = None
    for attempt in range(retries):
        try:
            conn = _connection(parts.netloc, timeout)
            conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
            resp = conn.getresponse()
            body = resp.read()
            if resp.status in (301, 302, 303, 307, 308):
                _drop(parts.netloc)
                return _get_urllib(url, timeout)   # let urllib follow the redirect
            if resp.status >= 400:
                err = urllib.error.HTTPError(url, resp.status, resp.reason, resp.headers, None)
                if resp.status < 500 and resp.status != 429:
                    raise err
                raise _Transient(err)
            return json.loads(body.decode())
        except urllib.error.HTTPError as e:
            raise e                                 # a non-retryable 4xx
        except (OSError, http.client.HTTPException, json.JSONDecodeError, _Transient) as e:
            _drop(parts.netloc)
            last_err = e.args[0] if isinstance(e, _Transient) else e
            if attempt < retries - 1:
                print(f"get() retry {attempt + 1}/{retries - 1} after {last_err} — {url}")
                time.sleep(backoff ** attempt)
    raise last_err


class _Transient(Exception):
    pass


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
    except Exception as e:
        if cutoff is None:
            # Bootstrap failed: don't silently leave cutoff=None (every dated article
            # would count as new). Reuse the previous run's cutoff when we have one.
            prev_cut = parse_iso(((prev or {}).get("cutoff") or "").replace(" UTC", "+00:00").replace(" ", "T", 1))
            if prev_cut:
                cutoff = prev_cut
                print(f"warn: event_window bootstrap failed ({e}) — reusing previous cutoff {prev['cutoff']}")
            else:
                print(f"warn: event_window bootstrap failed ({e}) and no previous cutoff — every dated article will count as new")
    return gw, cutoff


def load_js_object(path):
    """Parse the JSON object embedded in a `window.X = {...};` data file.
    {} only for a missing (or blank) file; a corrupt/merge-conflicted file raises
    ValueError so callers fail loudly instead of rebuilding and overwriting it."""
    if not path.exists():
        return {}
    raw = path.read_text()
    if not raw.strip():
        return {}
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e == -1:
        raise ValueError(f"{path.name}: no JSON object found (corrupt or merge-conflicted?)")
    try:
        return json.loads(raw[s:e + 1])
    except Exception as ex:
        raise ValueError(f"{path.name}: cannot parse embedded JSON ({ex}) — fix or restore the file") from ex


# --- Trend discovery for news_scrape.py (article text)
# (tweet text) so "who's being talked about" is discovered once, the same way,
# from whatever source text each scraper hands it. ---

def norm_keep_case(s):
    """Strip accents (Groß->Gross, João->Joao) but keep case, for name matching."""
    s = (s or "").replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def load_player_index(boot=None):
    """Every current FPL player, keyed for matching against raw (case-preserved) source text, so a scraper
    discovers whichever names are actually trending instead of checking a hand-kept watchlist.

    Matching is by name AND club-safe rules, because surnames collide:
      * a name written with an initial ("B.Fernandes") is also matched by its surname alone, since that is how
        articles write it;
      * when several players share a match key (Fernandes: Mateus 0.7% owned, Bruno 34%), the more-owned player
        wins - an article that says "Fernandes" almost always means him;
      * a key that is also the first name of two or more players ("David", "James") is matched only as the
        full "First Surname" form, so the bare word does not turn into a player;
      * every player is also matchable by his full name, which is unambiguous.
    Single-word keys under 5 letters are skipped (Cash, King, Cole... clash with ordinary words).
    Each entry carries ownership, status and transfer momentum so themes can be sanity-checked against FPL.

    Pass an already-fetched `boot` (bootstrap-static response) to avoid a second network round-trip."""
    boot = boot or get("https://fantasy.premierleague.com/api/bootstrap-static/")
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    first_counts = {}
    for el in boot["elements"]:
        fn = norm_keep_case((el.get("first_name") or "").strip()).lower()
        if fn:
            first_counts[fn] = first_counts.get(fn, 0) + 1
    def owned(el):
        try:
            return float(el.get("selected_by_percent") or 0)
        except (TypeError, ValueError):
            return 0.0
    def info(el, key):
        net = int(el.get("transfers_in_event") or 0) - int(el.get("transfers_out_event") or 0)
        return {"id": el["id"], "web_name": (el.get("web_name") or "").strip(), "club": teams.get(el["team"], ""), "match": key,
                "owned": owned(el), "status": el.get("status") or "a", "chance": el.get("chance_of_playing_next_round"), "net_transfers": net}
    keys = {}                     # lower-case match key -> {element id: (key as written, element)}
    def add(key, el):
        if not key:
            return
        keys.setdefault(key.lower(), {})[el["id"]] = (key, el)
    for el in boot["elements"]:
        name = (el.get("web_name") or "").strip()
        if not name:
            continue
        match = norm_keep_case(name)
        # web_name: plain, short single words skipped; a first-name clash is matched only in full
        single = " " not in name and "-" not in name
        first = norm_keep_case((el.get("first_name") or "").strip())
        common_first = first_counts.get(match.lower(), 0) >= 2 and single
        if not (single and len(name) < 5) and not common_first:
            add(match, el)
        if "." in name:                                  # "B.Fernandes" is written "Fernandes" in articles
            sur = match.split(".", 1)[1].strip()
            if len(sur) >= 5 or " " in sur or "-" in sur:
                add(sur, el)
        second = norm_keep_case((el.get("second_name") or "").strip())
        if first and second:
            add(f"{first} {second}", el)
            add(f"{first.split()[0]} {second.split()[-1]}", el)       # "Bruno Fernandes" for Bruno Miguel Borges Fernandes
        if first and match and not match.startswith(first) and single and not common_first and len(match) >= 5:
            add(f"{first} {match}", el)
        elif first and common_first:
            add(f"{first} {match}", el)
    idx, used = [], set()
    for lk, group in keys.items():
        key, el = max(group.values(), key=lambda v: (owned(v[1]), int(v[1].get("minutes") or 0)))
        entry = info(el, key)
        if (entry["id"], lk) in used:
            continue
        used.add((entry["id"], lk))
        idx.append(entry)
    return idx


QUALIFIER_PATTERNS = [
    ("captain talk", r"captain"),
    ("transfer target", r"transfer in|bring (?:him|her)? ?in|priority (?:buy|pick)|target for"),
    ("injury/doubt", r"\b(?:doubt|injury|injured|knock|fitness|illness)\b"),
    ("differential", r"differential|under[- ]?owned|low[- ]?owned"),
    ("fade/sell", r"\bfade\b|sell (?:him|her)?\b"),
    ("rotation risk", r"champions league|europa (?:league|conference)|conference league|uefa|carabao cup|efl cup|fa cup|rotat(?:e|ed|ion)|midweek (?:trip|clash|tie|game|fixture)|squad rotation|rested (?:him|her)?|managed minutes"),
]

ARTICLE_SEP = "\x00"  # joins separate items in a source's blob; never occurs in real text


def qualifiers_near(text, key, window=90):
    """Tags describing HOW a name is being talked about, from the words actually
    surrounding each mention (not a per-player hand-written script). The window is
    clipped at ARTICLE_SEP so a mention in one item can't pick up a qualifier from
    an unrelated sentence in the next item concatenated after it."""
    tags = set()
    for m in re.finditer(rf"\b{re.escape(key)}\b", text):
        left = text.rfind(ARTICLE_SEP, 0, m.start())
        left = 0 if left == -1 else left + 1
        right = text.find(ARTICLE_SEP, m.end())
        right = len(text) if right == -1 else right
        ctx = text[max(left, m.start() - window):min(right, m.end() + window)].lower()
        for tag, pat in QUALIFIER_PATTERNS:
            if re.search(pat, ctx):
                tags.add(tag)
    return tags


# Chip names are a fixed, closed vocabulary (FPL has exactly four chips), unlike
# player names — so hardcoding these specific words isn't the same problem as a
# hardcoded player watchlist. Kept separate from player-mention discovery below.
CONCEPT_PATTERNS = [
    ("wildcard", r"\bwildcard\b"),
    ("free hit", r"\bfree hit\b"),
]


def concept_themes(blobs, gw, unit="sites"):
    total = len(blobs)
    agreed, split = [], []
    for concept, pat in CONCEPT_PATTERNS:
        sources = sorted(s for s, text in blobs.items() if re.search(pat, text, re.I))
        if len(sources) < 2:
            continue  # a single mention is noise, not worth surfacing as an "emerging" theme
        item = {
            "text": f"GW{gw} coverage is talking about a {concept} window — mentioned by {len(sources)}/{total} {unit}.",
            "sources": sources,
        }
        (agreed if len(sources) >= 3 else split).append(item)
    return agreed, split


def sane_tags(tags, p):
    """Keyword tags come from words near a name, so check them against what FPL itself says: 'injury/doubt' only
    when FPL flags the player, 'differential' only for genuinely low ownership, 'fade/sell' not for a player
    being bought in bulk."""
    out = set(tags)
    if "injury/doubt" in out and p.get("status", "a") == "a" and p.get("chance") in (None, 100):
        out.discard("injury/doubt")
    if "differential" in out and (p.get("owned") or 0) >= 15:
        out.discard("differential")
    if "fade/sell" in out and (p.get("net_transfers") or 0) > 100000:
        out.discard("fade/sell")
    return out


# --- What the articles actually SAY about a player (not just that he is mentioned) ---------------------------
STANCE_PATTERNS = {
    "buy": r"\b(?:buy|buying|bring(?:ing)? (?:him|her) in|transfer(?:ring)? (?:him|her)? ?in|must[- ]have|essential|get (?:him|her) in|"
           r"great value|bargain|top pick|best (?:option|pick|buy)|in form|flying|recommend\w*|target(?:s|ing)?|differential|priority)\b",
    "sell": r"\b(?:sell|selling|fade|fading|avoid|dump|move (?:him|her) on|overpriced|overrated|not worth|stay away|get rid|offload|bin)\b",
    "hold": r"\b(?:keep|hold|stay put|sit tight|patient|stick with|roll(?:ing)? on)\b",
    "captain": r"\bcaptain(?:s|ed|ing|cy)?\b|\barmband\b",
    "risk": r"\b(?:injur\w*|doubt\w*|knock|fitness|rotat\w*|rested|benched|suspend\w*|illness|ruled out|fitness test)\b",
}
_NEGATION = re.compile(r"(?:\bnot|n't|\bnever|\bno)\s+(?:\w+\s+){0,2}$", re.I)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


_MARKET_FACT = re.compile(r"\b(?:managers|owners|in droves|most[- ]sold|most[- ]bought|sales|top 10|transfer combinations?)\b", re.I)
_BOILERPLATE = re.compile(r"coming soon|player profile|mini-league code|ultimate guide|sign up|subscribe|newsletter|cookie", re.I)


def sentence_stance(sentence, key):
    """Stance tags for one sentence that contains the player: buy / sell / captain / risk. 'not buy' flips to sell
    and 'not sell' to buy; a stance word counts only inside the sentence, so one player's praise cannot leak to a
    neighbour."""
    low = sentence.lower()
    hits = {}
    for tag, pat in STANCE_PATTERNS.items():
        for m in re.finditer(pat, low):
            before = low[max(0, m.start() - 24):m.start()]
            t = tag
            if tag in ("buy", "sell") and _MARKET_FACT.search(sentence):
                continue            # "100,000 managers sold him" reports what the market did, not what the writer advises
            if tag in ("buy", "sell") and _NEGATION.search(before):
                t = "sell" if tag == "buy" else "buy"
            hits[t] = hits.get(t, 0) + 1
    return hits


_LIST_OF_NAMES = re.compile(r"(?:[A-Z][\w.'\u2019-]+,\s+){2,}[A-Z]")      # "De Cuyper, Pedro, Cherki, Gibbs-White": a roundup headline
_FEED_FOOTER = re.compile(r"\s*The post .*$", re.S)                            # WordPress feeds append "The post X appeared first on Y"


def stance_quotes(raw_text, key, window=80):
    """The sentences of `raw_text` that mention `key` and say something about him (a buy/sell/captain/risk cue
    within `window` characters of the name).
    Roundup headlines that list several players ('A, B, C, D: buy, keep or sell?') are skipped: one verdict on a
    list is not a verdict on each name."""
    found, seen = [], set()
    pat = re.compile(rf"\b{re.escape(key)}\b")
    for item in raw_text.split(ARTICLE_SEP):
        for sent in _SENT_SPLIT.split(item):
            sent = _FEED_FOOTER.sub("", sent).strip()
            if (len(sent) < 25 or _LIST_OF_NAMES.search(sent) or re.search(r"keep or sell|buy, hold or sell", sent, re.I)
                    or _BOILERPLATE.search(sent) or sent.count("\u00a3") >= 3):
                continue
            plain = norm_keep_case(sent)
            near = ""
            for m in pat.finditer(plain):
                near += " " + plain[max(0, m.start() - window):m.end() + window]
            if not near:
                continue
            hits = sentence_stance(near, key)
            if not hits:
                continue
            k = sent.lower()[:80]
            if k in seen:
                continue
            seen.add(k)
            found.append((sum(hits.values()), hits, sent))
    return [{"text": (sent[:230] + "...") if len(sent) > 230 else sent, "key": sent.lower()[:80], "stance": sorted(h), "n": n_}
            for n_, h, sent in found]


def stance_verdict(counts):
    """One-line read of the counts: what the coverage is leaning towards."""
    b, se, c, r = (counts.get(k, 0) for k in ("buy", "sell", "captain", "risk"))
    h = counts.get("hold", 0)
    if r >= 2 and r >= max(b, se):
        return "Fitness or rotation doubts"
    if b and se and abs(b - se) <= 1:
        return "Mixed: some say buy, some say sell"
    if se > b:
        return "Leaning sell / avoid"
    if c >= 2 and c >= b:
        return "Captain candidate"
    if b:
        return "Leaning buy"
    if h:
        return "Leaning keep / hold"
    return "Mentioned, no clear view"


def build_themes(blobs, gw, player_index, unit="sites", checked=None):
    """Discover which players are actually mentioned across the given per-source
    text blobs, instead of checking a fixed list of names someone hand-picked in
    advance. 3+ sources = agreed (matches the "Agreed = 3+ ..." note in the UI).
    `unit` labels what a "source" is in the generated text (sites for news,
    accounts for X)."""
    total = len(blobs)
    mentions = {}
    for source, raw_text in blobs.items():
        text = norm_keep_case(raw_text)  # match accent-stripped key against accent-stripped text
        for p in player_index:
            if not re.search(rf"\b{re.escape(p['match'])}\b", text):
                continue
            rec = mentions.setdefault(p["web_name"], {"club": p["club"], "sources": set(), "tags": set(), "p": p, "sent": {}})
            rec["sources"].add(source)
            rec["tags"] |= qualifiers_near(text, p["match"])
            for q in stance_quotes(raw_text, p["match"]):
                rec["sent"].setdefault((source, q["key"]), {"source": source, **q})      # one record per sentence, however many aliases hit it
    agreed, split = [], []
    for name, rec in sorted(mentions.items(), key=lambda kv: (-len(kv[1]["sources"]), kv[0])):
        n = len(rec["sources"])
        if n < 2:
            continue  # a single mention is noise, not worth surfacing as an "emerging" theme
        rec["tags"] = sane_tags(rec["tags"], rec["p"])
        club = f" ({rec['club']})" if rec["club"] else ""
        is_agreed = n >= 3
        sents = sorted(rec["sent"].values(), key=lambda q: -q["n"])
        rec["counts"] = {}
        for q in sents:
            for tg in q["stance"]:
                rec["counts"][tg] = rec["counts"].get(tg, 0) + 1
        quotes, seen_src = [], {}
        for q in sents:                    # best sentence per site first, then the next best, up to four
            if seen_src.get(q["source"], 0) < 1:
                quotes.append(q); seen_src[q["source"]] = 1
        for q in sents:
            if len(quotes) >= 4:
                break
            if q not in quotes:
                quotes.append(q)
        rec["quotes"] = [{"source": q["source"], "text": q["text"], "stance": q["stance"]} for q in quotes[:4]]
        verdict = stance_verdict(rec["counts"])
        scope = f"{n}/{total} {unit} with fresh articles" + (f" ({checked} checked)" if checked and checked != total else "")
        cnt = rec["counts"]
        says = ", ".join(f"{cnt[k]} {lbl}" for k, lbl in (("buy", "buy"), ("hold", "keep"), ("sell", "sell/avoid"), ("captain", "captain"), ("risk", "fitness/rotation")) if cnt.get(k))
        text = f"{name}{club} — {verdict}" + (f" ({says} mentions)" if says else "") + f" · {scope}"
        item = {"text": text, "sources": sorted(rec["sources"]), "player": name, "club": rec["club"], "tags": sorted(rec["tags"]), "id": rec["p"]["id"],
                "verdict": verdict, "stance": rec["counts"], "quotes": rec["quotes"]}
        (agreed if is_agreed else split).append(item)
    concept_agreed, concept_split = concept_themes(blobs, gw, unit)
    return (agreed + concept_agreed)[:15], (split + concept_split)[:10]
