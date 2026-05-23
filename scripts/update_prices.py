#!/usr/bin/env python3
"""
Daily card price updater for Riftbound TCG.

Fetches the full card list from RiftCodex, picks the 50 cards with the
oldest cached prices, refreshes them via JustTCG, and writes the result
back to docs/prices.json so GitHub Pages can serve it to the Android app.
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

JUSTTCG_API_KEY = os.environ["JUSTTCG_API_KEY"]
JUSTTCG_GAME    = "riftbound-league-of-legends-trading-card-game"
RIFTCODEX_URL   = "https://api.riftcodex.com"
JUSTTCG_URL     = "https://api.justtcg.com"
PRICES_FILE     = "docs/prices.json"
DAILY_LIMIT     = 50
REQUEST_DELAY   = 1.2  # seconds between JustTCG calls to avoid rate-limiting


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


# ── JustTCG ───────────────────────────────────────────────────────────────────

def fetch_justtcg_price(card_name: str) -> float | None:
    """Return the best available USD price for a card name, or None."""
    resp = requests.get(
        f"{JUSTTCG_URL}/v1/cards",
        headers={"x-api-key": JUSTTCG_API_KEY},
        params={"q": card_name, "game": JUSTTCG_GAME},
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
    variants = match.get("variants") or []

    # Prefer Near Mint price
    nm = next((v for v in variants if "Near Mint" in (v.get("condition") or "")), None)
    variant = nm or (variants[0] if variants else None)
    return variant.get("price") if variant else None


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
            price = fetch_justtcg_price(name)
            prices[name] = {
                "priceUsd":    price,
                "lastUpdated": today,
                "source":      "JustTCG",
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
