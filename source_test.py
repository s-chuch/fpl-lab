import json, urllib.request, urllib.error, urllib.parse, re
UA = {"User-Agent": "ShaalandFPLLab/1.0 (https://github.com/s-chuch/fpl-lab)"}
def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)
def out(*a): print("RESULT", *a)
for title in ["2026–27 EFL Cup", "2026–27 FA Cup"]:
    st, b = get("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "parse", "page": title, "prop": "wikitext", "format": "json", "redirects": 1}))
    try:
        d = json.loads(b)
        if "error" in d: out("wikipedia", title, st, d["error"]); continue
        w = d["parse"]["wikitext"]["*"]
        boxes = re.findall(r"\{\{[Ff]ootball box.*?\n\}\}", w, re.S)
        out("wikipedia", title, st, "len", len(w), "footballboxes", len(boxes))
        for bx in boxes[-4:]:
            out("   ", " ".join(bx.split())[:330])
        for sec in re.findall(r"^==+\s*(.+?)\s*==+\s*$", w, re.M)[:25]: out("   section", sec)
    except Exception as e:
        out("wikipedia", title, st, "ERR", str(e)[:100], b[:100])
