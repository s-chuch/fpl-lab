# fpl-lab project notes

## API-Football (recovery-period feature)

- Signed up for a free API-Football account at **https://dashboard.api-football.com/register**.
- The API key is stored as a **GitHub repository secret** named `API_FOOTBALL_KEY`
  (Settings → Secrets and variables → Actions → `API_FOOTBALL_KEY`, in
  `s-chuch/fpl-lab`). It is NOT stored anywhere in this repo's files or in
  any Claude session — only in that GitHub secret.
- `.github/workflows/refresh.yml` passes it into the refresh step's `env:`
  block as `API_FOOTBALL_KEY: ${{ secrets.API_FOOTBALL_KEY }}`.
- `fixtures_external.py` reads it via `os.environ.get("API_FOOTBALL_KEY")`
  in `refresh.py`'s `main()`, to compute real all-competition rest-days for
  each Premier League club (Champions League/Europa/Conference League/FA
  Cup/EFL Cup, not just Premier League — FPL's own API has no data on those
  other competitions at all). Feeds the "Rest" column on the Rotations tab.
- **Free-tier limitation discovered on the first live run (2026-09-29):**
  API-Football's free plan does not include current-season data — a
  `/teams?league=39&season=2026` call came back with
  `"errors": {"plan": "Free plans do not have access to this season, try
  from 2022 to 2024."}`. Working around this by resolving each club's
  API-Football team id via `/teams?search=<name>` instead (not season-
  scoped) and caching those ids permanently (they don't change season to
  season). Whether the `/fixtures?team=X&next=1` / `&last=1` calls
  themselves are also blocked for the current season is still being
  verified live — if so, the free tier can't support this feature at all
  and the fallback is scraping worldfootball.net instead (already
  researched as a free, unlimited backstop).
