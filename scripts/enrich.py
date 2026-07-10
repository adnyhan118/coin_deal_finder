"""
Takes raw_listings.json (from scrape_govdeals.py) and enriches each item with:
  - estimated_value: what the coin(s) are likely worth
  - confidence: High / Medium / Low, based on how much reliable comp data was found
  - reasoning: one-line note on where the estimate came from

Output: docs/data.json - what the dashboard (docs/index.html) reads.

Requires the ANTHROPIC_API_KEY environment variable to be set
(this is provided as a GitHub Actions secret - see .github/workflows/daily.yml).
"""

import json
import os
import re
import sys
import time
import anthropic

INPUT_FILE = "raw_listings.json"
OUTPUT_FILE = "docs/data.json"

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

PROMPT_TEMPLATE = """You are helping a coin reseller evaluate a GovDeals auction listing.

Listing name: {name}
Listing description text: {raw_text}
Current bid: ${current_bid}

Research this item's likely resale value using web search (recent sold listings,
numismatic price guides, melt value if it's bullion). Then respond with ONLY a
JSON object, no other text, no markdown fences:

{{
  "estimated_value": <number, your best estimate of total resale value in USD>,
  "confidence": "High" | "Medium" | "Low",
  "reasoning": "<one short sentence on what data supported this estimate>"
}}

Confidence guide:
- High: multiple recent, closely comparable sold listings agree closely
- Medium: some relevant comps found, but with some uncertainty (condition, exact contents unclear, etc)
- Low: vague/unsorted lot, or few to no reliable comps found
"""


def enrich_item(item):
    prompt = PROMPT_TEMPLATE.format(
        name=item.get("name") or "Unknown",
        raw_text=(item.get("raw_text") or "")[:500],
        current_bid=item.get("current_bid") or 0,
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )

    text_parts = [b.text for b in response.content if b.type == "text"]
    full_text = "\n".join(text_parts).strip()

    # Strip any accidental markdown fences before parsing
    cleaned = re.sub(r"^```json|```$", "", full_text.strip(), flags=re.MULTILINE).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        print(f"Could not parse enrichment for '{item.get('name')}': {full_text[:200]}", file=sys.stderr)
        parsed = {"estimated_value": None, "confidence": "Low", "reasoning": "Could not parse research result"}

    return parsed


def main():
    with open(INPUT_FILE) as f:
        listings = json.load(f)

    enriched = []
    for i, item in enumerate(listings):
        print(f"Enriching {i+1}/{len(listings)}: {item.get('name')}", file=sys.stderr)
        try:
            result = enrich_item(item)
        except Exception as e:
            print(f"Error enriching '{item.get('name')}': {e}", file=sys.stderr)
            result = {"estimated_value": None, "confidence": "Low", "reasoning": "Enrichment failed"}

        bid = item.get("current_bid") or 0
        value = result.get("estimated_value")
        profit = (value - bid) if (value is not None and bid is not None) else None
        profit_pct = round((profit / bid) * 100) if (profit is not None and bid) else None

        enriched.append({
            "name": item.get("name"),
            "url": item.get("url"),
            "current_bid": bid,
            "time_left": item.get("time_left"),
            "estimated_value": value,
            "profit": profit,
            "profit_pct": profit_pct,
            "confidence": result.get("confidence", "Low"),
            "reasoning": result.get("reasoning", ""),
        })

        time.sleep(1)  # small pause between API calls

    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "listings": enriched,
        }, f, indent=2)

    print(f"Saved {len(enriched)} enriched listings to {OUTPUT_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
