# Shaaland FPL Lab

Live dashboard for FPL team **1360999**. Points, rank, chips and the GW log refresh from the official API.

Public site (after you finish step 4):

`https://YOUR_GITHUB_USERNAME.github.io/fpl-lab/`

## One-time setup (about 5 minutes)

1. On GitHub, click **New repository**.
   - Name: `fpl-lab`
   - Public
   - Do **not** add a README (the folder already has one)

2. Upload this folder.
   - Easiest: on the empty repo page, click **uploading an existing file** and drop every file in this folder, including the hidden `.github` directory.
   - Or on a computer:
     ```bash
     cd fpl-lab
     git init
     git add .
     git commit -m "Shaaland FPL lab"
     git branch -M main
     git remote add origin https://github.com/YOUR_GITHUB_USERNAME/fpl-lab.git
     git push -u origin main
     ```
   If the web uploader hides `.github`, create the file in the repo:
   `.github/workflows/refresh.yml` (copy from this folder).

3. Enable Actions  
   Repo → **Settings** → **Actions** → **General**  
   - Allow all actions  
   - Workflow permissions: **Read and write**

4. Enable Pages  
   Repo → **Settings** → **Pages**  
   - Source: **Deploy from a branch**  
   - Branch: `main`  
   - Folder: `/ (root)`  
   Save. After a minute the URL is  
   `https://YOUR_GITHUB_USERNAME.github.io/fpl-lab/`

5. Run the first refresh  
   Repo → **Actions** → **Refresh FPL data** → **Run workflow**

After that it runs twice a day on its own. GitHub pauses scheduled jobs if the repo sits untouched for 60 days — open the repo once a month during the season.


## Data refresh ownership

Everything refreshes autonomously via the GitHub Actions workflow `Refresh FPL data` — no manual step or AI assistant is needed for the pipeline to keep running:

- **FPL scores / rank / chips / GW log** (`data.js`, `bacalhau-data.js`): `refresh.py`.
- **News** (`news.js`): `news_scrape.py` — see below.
- **X posts** (`x-posts.js`): `x_scrape.py`, via the official X API. Requires a repo secret (see next section); without one it writes a manual/seeded stub instead of failing.

### X live ingest setup

`x_scrape.py` reads a bearer token from the `X_BEARER_TOKEN` environment variable, which the workflow passes in from a GitHub Actions secret:

1. Get a bearer token from the [X Developer Portal](https://developer.x.com/) for an app with read access to user timelines. Note: meaningful read volume (the `/2/users/:id/tweets` endpoint used here, across the accounts in `sources.json`) needs at least the Basic paid API tier — the free tier's read access is too limited for this to be useful.
2. Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret** → name it `X_BEARER_TOKEN`, paste the token.
3. Re-run the workflow (**Actions** → **Refresh FPL data** → **Run workflow**). `x-posts.js` will switch from `mode: "manual"` to `mode: "live"`.

Without the secret configured, `x_scrape.py` keeps writing the same manual/seeded stub it always has — the rest of the pipeline (scores, news, plan) is unaffected either way.

### News sources (`sources.json`)

For each site in `"sites"`, `news_scrape.py` tries its RSS/Atom feed first (autodiscovered from the homepage's `<link rel="alternate">`, then common paths like `/feed/`) since a feed gives real publish dates and full clean article content instead of scraped-page guesswork. If no feed is found it falls back to scraping links off the page directly. If a site's real feed lives somewhere non-standard, add it explicitly: `{"name": "Fix", "url": "...", "feed": "https://.../actual-feed-url"}`.

Both `news_scrape.py` and `x_scrape.py` discover trending players by scanning scraped text against the live FPL player list (`fpl_common.py`), rather than checking a fixed, hand-maintained watchlist — so a new breakout player shows up on their own merit, without anyone needing to edit code.

## Local

```bash
python3 refresh.py
python3 -m http.server 8000
```

The Action refreshes scores, rank, chips, the GW log, news and (with `X_BEARER_TOKEN` set) X posts — all of it autonomously, on the existing twice-daily schedule.
