# Apartment Watch

A free bot that checks nepremicnine.net for new rental listings matching
your criteria, and shows them on a simple dashboard you can open on your
phone or computer. Nothing runs on your own machine — GitHub does the work.

## How it works
- `scraper.py` opens your saved search in a headless browser (the site needs
  JavaScript to show results) and pulls out each listing.
- A GitHub Actions workflow (`.github/workflows/check.yml`) runs that script
  every 20 minutes, for free, and commits the results to `data/listings.json`
  and `docs/listings.json`.
- GitHub Pages serves `docs/index.html`, a small page that reads
  `listings.json` and shows the listings, flagging new ones.

## One-time setup (about 10 minutes)

1. **Create a GitHub account** if you don't have one: https://github.com/join

2. **Create a new repository** (e.g. `apartment-watch`), and upload all the
   files in this project to it. (Easiest way: on the repo page, choose
   "Add file" → "Upload files", drag in everything, commit.)

3. **Get your search URL:**
   - Go to https://www.nepremicnine.net/nepremicnine.html
   - Set "Posredovanje" to **Oddaja** (rent), pick Stanovanje, your region,
     price range, etc.
   - Click **Prikaži rezultate**.
   - Copy the full URL from your browser's address bar.

4. **Edit `config.json`** in your repo (click the file → pencil/edit icon):
   ```json
   {
     "search_urls": [
       "https://www.nepremicnine.net/....your-url-here...."
     ],
     "filters": {
       "max_price": 700,
       "min_price": null,
       "min_size_m2": 30
     },
     "drop_after_days_missing": 3
   }
   ```
   You can list more than one URL if you want to watch a couple of
   different searches at once (e.g. two different regions).

5. **Turn on GitHub Pages:**
   - In your repo, go to **Settings → Pages**.
   - Under "Build and deployment", set Source = "Deploy from a branch",
     Branch = `main`, Folder = `/docs`. Save.
   - GitHub will give you a URL like
     `https://yourusername.github.io/apartment-watch/` — that's your app.
     Bookmark it / add it to your phone's home screen.

6. **Turn on Actions and run it once:**
   - Go to the **Actions** tab in your repo → you may need to click
     "I understand my workflows, go ahead and enable them".
   - Click "Check for new apartments" → **Run workflow** to trigger it
     manually the first time (don't wait for the 20-minute schedule).
   - After it finishes (~1 minute), refresh your GitHub Pages URL — you
     should see listings.

From then on, it checks automatically every 20 minutes.

## Adjusting the filters
Edit `filters` in `config.json` any time:
- `max_price` / `min_price`: monthly rent in EUR
- `min_size_m2`: minimum size
- Set a value to `null` to not filter on it.

Commit the change and the next run will use the new filters.

## If it stops finding listings
The site's page structure could change. Run `python scraper.py --debug`
locally (needs `pip install playwright && playwright install chromium`
first) to see how many raw listing links it's finding — if that number
is 0, the CSS/URL pattern in `scraper.py` needs updating.

## Notes
- This checks a public search page — no login, no scraping of anything
  behind a paywall.
- Be a good citizen: the 20-minute interval is deliberately not aggressive.
  Don't lower it much further.
