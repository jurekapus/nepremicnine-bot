#!/usr/bin/env python3
"""
Apartment-alert scraper for nepremicnine.net

Visits one or more saved search URLs (rentals), pulls out individual
listing cards, and merges them into data/listings.json so a static
dashboard (docs/index.html) can show what's new.

Why Playwright and not plain requests?
nepremicnine.net renders its search results with JavaScript, so a
plain HTTP GET returns an (almost) empty shell. Playwright runs a
real (headless) browser so the results actually load before we read
the page.

HOW TO GET YOUR SEARCH URL
1. Go to https://www.nepremicnine.net/nepremicnine.html
2. Set up your search exactly how you want it: Posredovanje = Oddaja,
   Nepremičnina = Stanovanje, pick your region/price range/size etc.
3. Click "Prikaži rezultate" (Show results).
4. Copy the URL from your browser's address bar and paste it into
   config.json as one of the "search_urls".

If nepremicnine.net changes its page layout, the CSS selectors below
(see LISTING_LINK_PATTERN / parse_listing) may need updating — see
the README for how to debug that.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "data" / "listings.json"
DOCS_DATA_PATH = ROOT / "docs" / "listings.json"

# Matches links to individual ad pages, e.g.
# https://www.nepremicnine.net/nepremicnine.html?id=7437434
LISTING_LINK_PATTERN = re.compile(r"nepremicnine\.html\?id=(\d+)")

PRICE_PATTERN = re.compile(
    r"(?:Cena|Najemnina)\s*:?\s*([\d.,]+)\s*EUR", re.IGNORECASE
)
SIZE_PATTERN = re.compile(r"([\d.,]+)\s*m2", re.IGNORECASE)
ROOMS_PATTERN = re.compile(r"(\d+)\s*-?\s*sobno", re.IGNORECASE)


def load_config():
    if not CONFIG_PATH.exists():
        sys.exit(f"Missing {CONFIG_PATH}. Copy config.example.json to config.json and edit it.")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_existing():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return {}


def parse_price(text):
    m = PRICE_PATTERN.search(text)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def parse_size(text):
    m = SIZE_PATTERN.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def parse_rooms(text):
    m = ROOMS_PATTERN.search(text)
    return int(m.group(1)) if m else None


def guess_location(text):
    # Location is typically the leading ALL-CAPS chunk of the link text,
    # e.g. "VELIKA GORICA 55 m2, 1-sobno, ...".
    words = text.strip().split()
    loc_words = []
    for w in words:
        if w.isupper() and not w.isdigit():
            loc_words.append(w)
        else:
            break
    return " ".join(loc_words) if loc_words else None


def scrape_url(page, url, debug=False, index=0):
    page.goto(url, wait_until="networkidle", timeout=60000)
    # Give any lazy-loaded JS content a moment to settle.
    page.wait_for_timeout(3000)

    anchors = page.eval_on_selector_all(
        "a[href*='nepremicnine.html?id=']",
        "els => els.map(e => ({href: e.href, text: e.innerText}))",
    )

    # Always dump a screenshot + full HTML so we can debug selector issues
    # without needing to run this locally. These get uploaded as a GitHub
    # Actions artifact (see workflow file) and can just be downloaded.
    debug_dir = ROOT / "debug"
    debug_dir.mkdir(exist_ok=True)
    page.screenshot(path=str(debug_dir / f"screenshot_{index}.png"), full_page=True)
    (debug_dir / f"page_{index}.html").write_text(page.content(), encoding="utf-8")

    print(f"[info] {url} -> {len(anchors)} raw anchors found", file=sys.stderr)

    results = {}
    for a in anchors:
        m = LISTING_LINK_PATTERN.search(a["href"])
        if not m:
            continue
        listing_id = m.group(1)
        text = " ".join(a["text"].split())  # collapse whitespace
        if not text:
            continue
        results[listing_id] = {
            "id": listing_id,
            "url": a["href"].split("?")[0] + f"?id={listing_id}",
            "raw_text": text,
            "location": guess_location(text),
            "price_eur": parse_price(text),
            "size_m2": parse_size(text),
            "rooms": parse_rooms(text),
        }
    return results


def matches_filters(listing, filters):
    price = listing.get("price_eur")
    size = listing.get("size_m2")
    if filters.get("max_price") and price and price > filters["max_price"]:
        return False
    if filters.get("min_price") and price and price < filters["min_price"]:
        return False
    if filters.get("min_size_m2") and size and size < filters["min_size_m2"]:
        return False
    return True


def main():
    config = load_config()
    existing = load_existing()
    now = datetime.now(timezone.utc).isoformat()
    debug = "--debug" in sys.argv

    all_found = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        )
        for i, url in enumerate(config["search_urls"]):
            try:
                found = scrape_url(page, url, debug=debug, index=i)
                all_found.update(found)
            except Exception as e:
                print(f"[warn] failed to scrape {url}: {e}", file=sys.stderr)
        browser.close()

    filters = config.get("filters", {})
    merged = dict(existing)
    new_count = 0
    for listing_id, listing in all_found.items():
        if not matches_filters(listing, filters):
            continue
        if listing_id not in merged:
            listing["first_seen"] = now
            listing["is_new"] = True
            new_count += 1
        else:
            listing["first_seen"] = merged[listing_id].get("first_seen", now)
            listing["is_new"] = merged[listing_id].get("is_new", False)
        listing["last_seen"] = now
        merged[listing_id] = listing

    # Drop listings we haven't seen in the last 3 scrapes worth of days
    # (keeps the dashboard from filling up with delisted apartments).
    cutoff_days = config.get("drop_after_days_missing", 3)
    still_active = {}
    for listing_id, listing in merged.items():
        last_seen = datetime.fromisoformat(listing["last_seen"])
        age_days = (datetime.now(timezone.utc) - last_seen).total_seconds() / 86400
        if age_days <= cutoff_days:
            still_active[listing_id] = listing

    # Anything not "new" for more than 2 days stops being flagged as new.
    for listing in still_active.values():
        first_seen = datetime.fromisoformat(listing["first_seen"])
        if (datetime.now(timezone.utc) - first_seen).total_seconds() > 2 * 86400:
            listing["is_new"] = False

    DATA_PATH.parent.mkdir(exist_ok=True)
    DATA_PATH.write_text(json.dumps(still_active, indent=2, ensure_ascii=False), encoding="utf-8")
    DOCS_DATA_PATH.write_text(json.dumps(still_active, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Scraped {len(all_found)} raw listings, {len(still_active)} active after filters, {new_count} new this run.")


if __name__ == "__main__":
    main()
