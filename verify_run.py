import json, re, subprocess, sys
from pathlib import Path
def run(args):
    p = subprocess.run([sys.executable, "refresh.py"] + args, capture_output=True, text=True)
    fx = [l for l in p.stderr.splitlines() if "fixtures_external" in l]
    print("RESULT run", args, "exit", p.returncode, "| fixtures_external log lines:", len(fx))
    for l in fx: print("RESULT    ", l)
    if p.returncode: print("RESULT STDERR", p.stderr[-800:])
def load(path):
    t = Path(path).read_text()
    return json.loads(t[t.index("{"): t.rindex("}") + 1])
run(["--out", "/tmp/v1.js"])
run(["--team", "1360920", "--out", "/tmp/v2.js"])  # second run: cache should suppress refetch
d = load("/tmp/v1.js")
print("RESULT top-level keys with recovery:", [k for k in d if "recovery" in k or "af_" in k])
tr = d["team_recovery"]; print("RESULT team_recovery fetched_at", tr.get("fetched_at"), "clubs", len(tr.get("teams", {})))
rr = d["rotation_risk"]; rows = rr["rows"] if isinstance(rr, dict) and "rows" in rr else rr
print("RESULT rotation rows:", len(rows), "with rest_days:", sum(1 for r in rows if r.get("rest_days") is not None), "with next_match_label:", sum(1 for r in rows if r.get("next_match_label")))
for r in rows[:6]: print("RESULT row", r["name"], r["club"], r.get("rest_days"), r.get("next_match_label"), r.get("reason"))
print("RESULT cache file:", Path("team_recovery_cache.json").read_text()[:300].replace("\n", " "))
