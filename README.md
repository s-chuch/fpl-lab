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

- **FPL scores / rank / chips / GW log** (`data.js`, `bacalhau-data.js`) and **news** (`news.js`): GitHub Actions workflow `Refresh FPL data` (`news_scrape.py` + `refresh.py`).
- **X posts** (`x-posts.js`): **not** updated by Actions. The official X API's free tier doesn't allow reading account timelines/search at any useful volume — the paid tiers that do aren't worth it for this. Live ingest is instead the Grok Bot daily ~10am ET routine via the connected user-X MCP plugin (`mode: "live"`). `x_scrape.py` is a local stub that preserves an existing live file and only writes a manual stub if the file is missing or already manual.

### News sources (`sources.json`)

For each site in `"sites"`, `news_scrape.py` tries its RSS/Atom feed first (autodiscovered from the homepage's `<link rel="alternate">`, then common paths like `/feed/`) since a feed gives real publish dates and full clean article content instead of scraped-page guesswork. If no feed is found it falls back to scraping links off the page directly. If a site's real feed lives somewhere non-standard, add it explicitly: `{"name": "Fix", "url": "...", "feed": "https://.../actual-feed-url"}`.

`news_scrape.py` discovers trending players by scanning scraped text against the live FPL player list (`fpl_common.py`), rather than checking a fixed, hand-maintained watchlist — so a new breakout player shows up on their own merit, without anyone needing to edit code.

## Local

```bash
python3 refresh.py
python3 -m http.server 8000
```

Bench / transfer write-ups and the GW4–5 plan stay in `data.js` until you edit them or ask Grok to rebuild that section. The Action only refreshes scores, rank, chips, the GW log and news.
