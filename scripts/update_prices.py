#!/usr/bin/env python3
"""
Daily card price updater for Riftbound TCG.

Fetches the full card list from RiftCodex, picks the 50 cards with the
oldest cached prices, refreshes them via the tcggo CardMarket API, converts
EUR → USD using a live exchange rate, and writes the result back to
docs/prices.json so GitHub Pages can serve it to the Android app.
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

TCGGO_API_KEY   = os.environ["TCGGO_API_KEY"]
TCGGO_HOST      = "cardmarket-api-tcg.p.rapidapi.com"
TCGGO_GAME      = "riftbound"
RIFTCODEX_URL   = "https://api.riftcodex.com"
EXCHANGE_URL    = "https://open.er-api.com/v6/latest/EUR"
PRICES_FILE     = "docs/prices.json"
DAILY_LIMIT     = 50
REQUEST_DELAY   = 1.5  # seconds between tcggo calls


# ── I/O helpers ──────────────────────────────────────────────────────────────

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


# ── RiftCodex ─────────────────────────────────────────────────────────────────

def fetch_all_cards() -> list[dict]:
    """Page through RiftCodex /cards until all cards are collected."""
    cards = []
    page, size = 1, 200
    while True:
        resp = requests.get(
            f"{RIFTCODEX_URL}/cards",
            params={"size": size, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        cards.extend(items)
        if page >= data.get("pages", 1) or not items:
            break
        page += 1
    return cards


# ── tcggo / CardMarket ────────────────────────────────────────────────────────

def fetch_tcggo_price(card_name: str, eur_to_usd: float) -> float | None:
    """Return best available USD price for a card name via CardMarket, or None."""
    resp = requests.get(
        f"https://{TCGGO_HOST}/{TCGGO_GAME}/cards",
        headers={
            "x-rapidapi-key":  TCGGO_API_KEY,
            "x-rapidapi-host": TCGGO_HOST,
        },
        params={"search": card_name, "per_page": 5},
        timeout=30,
    )
    resp.raise_for_status()

    items = resp.json().get("data", [])
    if not items:
        return None

    # Prefer exact name match, fall back to first result
    match = next(
        (c for c in items if (c.get("name") or "").lower() == card_name.lower()),
        items[0],
    )

    cm = (match.get("prices") or {}).get("cardmarket") or {}
    # Prefer 30-day average for stability; fall back to lowest NM listing
    eur_price = cm.get("30d_average") or cm.get("lowest_near_mint")
    if not eur_price:
        return None

    return round(float(eur_price) * eur_to_usd, 2)


# ── Main ──────────────────────────────────────────────────────────────────────

def last_updated_ts(card: dict, prices: dict) -> float:
    """Return epoch seconds of when this card was last priced (0 = never)."""
    entry = prices.get(card.get("name", ""), {})
    date_str = entry.get("lastUpdated", "")
    if not date_str:
        return 0.0
    try:
        return datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def main():
    data   = load_prices()
    prices = data.get("prices", {})

    print("Fetching EUR→USD exchange rate…")
    eur_to_usd = fetch_eur_to_usd()

    print("Fetching card list from RiftCodex…")
    all_cards = fetch_all_cards()
    print(f"  {len(all_cards)} cards found")

    # Sort by oldest lastUpdated so every card eventually gets refreshed
    to_update = sorted(all_cards, key=lambda c: last_updated_ts(c, prices))[:DAILY_LIMIT]

    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    updated = 0

    for card in to_update:
        name = card.get("name", "").strip()
        if not name:
            continue

        print(f"  Fetching: {name}")
        try:
            price = fetch_tcggo_price(name, eur_to_usd)
            prices[name] = {
                "priceUsd":    price,
                "lastUpdated": today,
                "source":      "CardMarket",
            }
            updated += 1
        except Exception as exc:
            print(f"    Error: {exc}")

        time.sleep(REQUEST_DELAY)

    data["lastUpdated"] = today
    data["prices"]      = prices
    save_prices(data)
    print(f"\nDone. Updated {updated} prices. Total cached: {len(prices)}")


if __name__ == "__main__":
    main()
