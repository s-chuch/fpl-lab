"""Stamp every local script/stylesheet tag in the dashboard pages with a short hash of the file's
content (`?v=<hash>`), and turn the old per-minute `document.write` script loaders into plain static
tags. An unchanged file keeps the same URL and stays cached by the browser; a changed file gets a new
URL, so nobody runs a stale copy next to new data. Idempotent; run by refresh.yml before committing.

    python stamp_versions.py [page.html ...]   (default: index.html bacalhau.html)"""
from __future__ import annotations
import hashlib, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGES = ["index.html", "bacalhau.html"]

# <script>document.write('<script src="data.js?t='+Math.floor(Date.now()/60000)+'"><\/script>')</script>
DOC_WRITE = re.compile(r"""<script>document\.write\('<script src="([^"?]+)\?t='\+Math\.floor\(Date\.now\(\)/60000\)\+'"><\\/script>'\)</script>""")
# src="x.js?v=..." / href="x.css?v=..."
VERSIONED = re.compile(r"""\b(src|href)="([^"?:]+\.(?:js|css))\?v=[^"]*\"""")


def digest(name: str) -> str | None:
    p = ROOT / name
    if not p.is_file():
        return None
    return hashlib.sha1(p.read_bytes()).hexdigest()[:8]


def stamp(html: str) -> str:
    def static(m):
        h = digest(m.group(1))
        return f'<script src="{m.group(1)}?v={h}"></script>' if h else m.group(0)

    def refresh(m):
        h = digest(m.group(2))
        return f'{m.group(1)}="{m.group(2)}?v={h}"' if h else m.group(0)

    return VERSIONED.sub(refresh, DOC_WRITE.sub(static, html))


def main(argv):
    changed = []
    for name in argv or PAGES:
        path = ROOT / name
        old = path.read_text()
        new = stamp(old)
        if new != old:
            path.write_text(new)
            changed.append(name)
    print("stamped:", ", ".join(changed) if changed else "no changes")


if __name__ == "__main__":
    main(sys.argv[1:])
