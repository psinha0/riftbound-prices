#!/usr/bin/env python3
"""
Daily card price updater for Riftbound TCG.

Pages through all Riftbound cards on the tcggo CardMarket API (~12 calls),
converts EUR → USD using a live exchange rate, and writes the full result
to docs/prices.json so GitHub Pages can serve it to the Android app.
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

TCGGO_API_KEY   = os.environ["TCGGO_API_KEY"]
TCGGO_HOST      = "cardmarket-api-tcg.p.rapidapi.com"
TCGGO_GAME      = "riftbound"
EXCHANGE_URL    = "https://open.er-api.com/v6/latest/EUR"
PRICES_FILE     = "docs/prices.json"
PAGE_SIZE       = 100
REQUEST_DELAY   = 1.5  # seconds between tcggo page requests


# ── I/O helpers ───────────────────────────────────────────────────────────────

def load_prices() -> dict:
    try:
        with open(PRICES_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"lastUpdated": "", "prices": {}}


def save_prices(data: dict):
    os.makedirs("docs", exist_ok=True)
    with open(PRICES_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Exchange rate ─────────────────────────────────────────────────────────────

def fetch_eur_to_usd() -> float:
    """Return today's EUR→USD rate; fall back to 1.08 if unavailable."""
    try:
        resp = requests.get(EXCHANGE_URL, timeout=10)
        resp.raise_for_status()
        rate = resp.json()["rates"]["USD"]
        print(f"  EUR→USD rate: {rate}")
        return float(rate)
    except Exception as exc:
        print(f"  Exchange rate fetch failed ({exc}), using fallback 1.08")
        return 1.08


# ── tcggo / CardMarket ────────────────────────────────────────────────────────

def fetch_all_tcggo_cards() -> list[dict]:
    """Page through all Riftbound cards on tcggo, returning every card object."""
    cards = []
    page = 1
    while True:
        resp = requests.get(
            f"https://{TCGGO_HOST}/{TCGGO_GAME}/cards",
            headers={
                "x-rapidapi-key":  TCGGO_API_KEY,
                "x-rapidapi-host": TCGGO_HOST,
            },
            params={"per_page": PAGE_SIZE, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        body  = resp.json()
        items = body.get("data", [])
        cards.extend(items)
        total_pages = body.get("paging", {}).get("total", 1)
        print(f"  Page {page}/{total_pages} — {len(items)} cards")
        if page >= total_pages or not items:
            break
        page += 1
        time.sleep(REQUEST_DELAY)
    return cards


def extract_price_usd(card: dict, eur_to_usd: float) -> float | None:
    cm = (card.get("prices") or {}).get("cardmarket") or {}
    eur_price = cm.get("30d_average") or cm.get("lowest_near_mint")
    if not eur_price:
        return None
    return round(float(eur_price) * eur_to_usd, 2)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Fetching EUR→USD exchange rate…")
    eur_to_usd = fetch_eur_to_usd()

    print("Fetching all Riftbound cards from tcggo…")
    all_cards = fetch_all_tcggo_cards()
    print(f"  {len(all_cards)} cards fetched")

    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prices = {}

    for card in all_cards:
        name = (card.get("name") or "").strip()
        if not name:
            continue
        prices[name] = {
            "priceUsd":    extract_price_usd(card, eur_to_usd),
            "lastUpdated": today,
            "source":      "CardMarket",
        }

    save_prices({"lastUpdated": today, "prices": prices})
    print(f"\nDone. {len(prices)} prices written.")


if __name__ == "__main__":
    main()
