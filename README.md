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

## Local

```bash
python3 refresh.py
python3 -m http.server 8000
```

Bench / transfer write-ups and the GW4–5 plan stay in `data.js` until you edit them or ask Grok to rebuild that section. The Action only refreshes scores, rank, chips and the GW log.
