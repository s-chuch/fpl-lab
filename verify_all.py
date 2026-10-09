import json, subprocess, sys
from pathlib import Path
def sh(*a):
    p = subprocess.run(list(a), capture_output=True, text=True)
    err = [l for l in p.stderr.splitlines() if "WARNING" in l or "Traceback" in l or "Error" in l][:6]
    print("RESULT", " ".join(a), "-> exit", p.returncode, err)
    if p.returncode: print("RESULT STDERR TAIL", p.stderr[-600:])
    return p.returncode
rc = 0
for cmd in (["news_scrape.py"], ["refresh.py"], ["refresh.py", "--team", "1360920", "--out", "bacalhau-data.js"], ["greekgod_analyze.py"], ["wildcard_recommend.py", "bacalhau-wildcard.js"], ["wildcard_recommend.py", "shaaland-wildcard.js"]):
    rc |= sh(sys.executable, *cmd)
def load(p):
    t = Path(p).read_text(); return json.loads(t[t.index("{"): t.rindex("}") + 1])
d = load("data.js")
print("RESULT keys with af_:", [k for k in d if k.startswith("af_")])
fa = d.get("field_avg_known", {}); print("RESULT field_avg_known keys sample:", list(fa)[:6], "n", len(fa))
rr = d.get("rotation_risk"); print("RESULT rotation_risk:", None if rr is None else (len(rr.get("rows", [])), rr.get("gws")))
bb = d.get("bench_audit") or {}; print("RESULT bench_audit gws:", list(bb)[:6] if isinstance(bb, dict) else type(bb))
print("RESULT team_recovery clubs:", len(d["team_recovery"]["teams"]), d["team_recovery"].get("fetched_at"))
print("RESULT deadline:", d["deadline"])
raw = Path("data.js").read_text(); print("RESULT duplicate-key check, 'field_avg_known' appears", raw.count('"field_avg_known"'))
sys.exit(rc)
