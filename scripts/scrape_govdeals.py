"""
Scrapes GovDeals coin listings using a real (headless) browser, since the
site renders its listings with JavaScript and a plain HTTP request won't see them.
Output: raw_listings.json - a list of dicts with name, url, current_bid, time_left, bid_count
"""
import json
import re
import sys
from playwright.sync_api import sync_playwright
# Pages to check. Add more search/category URLs here as you discover useful ones.
SEARCH_URLS = [
    "https://www.govdeals.com/en/coin-collections",
    "https://www.govdeals.com/en/search?keywords=coin",
]
OUTPUT_FILE = "raw_listings.json"
# Candidate CSS selectors for a single listing "card" on the results page.
# GovDeals may change their markup over time, so we try several patterns
# and use whichever one actually finds elements on the page.
CARD_SELECTOR_CANDIDATES = [
    "[data-testid='asset-card']",
    ".asset-card",
    ".search-result-card",
    "article",
]
def money_to_float(text):
    if not text:
        return None
    match = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    return float(match.group()) if match else None
def scrape_page(page, url):
    listings = []
    page.goto(url, wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(2000)  # let any lazy-loaded content settle
    cards = []
    for selector in CARD_SELECTOR_CANDIDATES:
        found = page.query_selector_all(selector)
        if found:
            cards = found
            print(f"Using selector '{selector}', found {len(found)} cards", file=sys.stderr)
            break
    if not cards:
        # Nothing matched. Save the page HTML and a screenshot so we can
        # inspect what the browser actually saw and fix selectors (or
        # discover we're being blocked/challenged).
        with open("debug_page.html", "w") as f:
            f.write(page.content())
        page.screenshot(path="debug_page.png", full_page=True)
        print("No cards found with any selector. Saved debug_page.html and debug_page.png for inspection.", file=sys.stderr)
        return listings
    for card in cards:
        text = card.inner_text()
        link_el = card.query_selector("a")
        href = link_el.get_attribute("href") if link_el else None
        if href and href.startswith("/"):
            href = "https://www.govdeals.com" + href
        # Heuristic extraction from the card's visible text. GovDeals cards
        # typically include the item name, a "Current Bid: $X" line, and a
        # "Time Left" line. Adjust these regexes after the first real run
        # if the wording differs.
        name_match = text.split("\n")[0].strip() if text else None
        bid_match = re.search(r"(?:Current Bid|Bid)[:\s]*\$?([\d,]+\.?\d*)", text, re.IGNORECASE)
        time_match = re.search(r"(?:Time Left|Closes?)[:\s]*([^\n]+)", text, re.IGNORECASE)
        listings.append({
            "name": name_match,
            "url": href,
            "current_bid": money_to_float(bid_match.group(1)) if bid_match else None,
            "time_left": time_match.group(1).strip() if time_match else None,
            "raw_text": text,
        })
    return listings
def main():
    all_listings = []
    with sync_playwright() as p:
        # Launch with a flag that hides the most common automation
        # fingerprint, and set a real desktop user-agent + viewport so the
        # page is less likely to be flagged/blocked as a bot.
        browser = p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        for url in SEARCH_URLS:
            print(f"Scraping {url}", file=sys.stderr)
            all_listings.extend(scrape_page(page, url))
        browser.close()
    # De-duplicate by URL in case the same item appears on multiple pages
    seen = set()
    deduped = []
    for item in all_listings:
        if item["url"] and item["url"] not in seen:
            seen.add(item["url"])
            deduped.append(item)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(deduped, f, indent=2)
    print(f"Saved {len(deduped)} listings to {OUTPUT_FILE}", file=sys.stderr)
if __name__ == "__main__":
    main()
