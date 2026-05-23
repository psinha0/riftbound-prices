#!/usr/bin/env python3
"""
Daily card price updater for Riftbound TCG.

Pages through all Riftbound cards on JustTCG (~58 calls at limit=20),
stores the current USD price and 7-day price history per card, and writes
the full result to docs/prices.json so GitHub Pages can serve it to the
Android app.
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

JUSTTCG_API_KEY = os.environ["JUSTTCG_API_KEY"]
JUSTTCG_URL     = "https://api.justtcg.com"
JUSTTCG_GAME    = "riftbound-league-of-legends-trading-card-game"
PRICES_FILE     = "docs/prices.json"
PAGE_SIZE       = 20   # free-tier max
REQUEST_DELAY   = 7.0  # free tier allows 10 req/min → 6s minimum; 7s gives headroom


# ── I/O helpers ───────────────────────────────────────────────────────────────

def save_prices(data: dict):
    os.makedirs("docs", exist_ok=True)
    with open(PRICES_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── JustTCG ───────────────────────────────────────────────────────────────────

def fetch_all_cards() -> list[dict]:
    """Page through all Riftbound cards on JustTCG using limit/offset."""
    cards  = []
    offset = 0
    while True:
        for attempt in range(3):
            try:
                resp = requests.get(
                    f"{JUSTTCG_URL}/v1/cards",
                    headers={"x-api-key": JUSTTCG_API_KEY},
                    params={"game": JUSTTCG_GAME, "limit": PAGE_SIZE, "offset": offset},
                    timeout=30,
                )
                resp.raise_for_status()
                break
            except requests.exceptions.HTTPError as e:
                if resp.status_code == 429 and attempt < 2:
                    print(f"  429 rate limit — waiting 65s before retry…")
                    time.sleep(65)
                else:
                    raise
        body  = resp.json()
        items = body.get("data", [])
        cards.extend(items)
        meta     = body.get("meta", {})
        has_more = meta.get("hasMore", False)
        total    = meta.get("total", 0)
        print(f"  offset={offset:4d}  got {len(items):2d}  total={total}  hasMore={has_more}")
        if not has_more or not items:
            break
        offset += PAGE_SIZE
        time.sleep(REQUEST_DELAY)
    return cards


def extract_price_and_history(card: dict) -> tuple[float | None, list[dict]]:
    """Return (current_usd_price, 7_day_history) from the best variant."""
    variants = card.get("variants") or []
    # Prefer Near Mint; fall back to first variant
    variant = next(
        (v for v in variants if "Near Mint" in (v.get("condition") or "")),
        variants[0] if variants else None,
    )
    if not variant:
        return None, []

    price = variant.get("price")
    # JustTCG history format: [{"p": <price>, "t": <epoch_seconds>}, ...]
    history = [
        {"price": h["p"], "timestamp": h["t"]}
        for h in (variant.get("priceHistory") or [])
        if "p" in h and "t" in h
    ]
    return price, history


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Fetching all Riftbound cards from JustTCG…")
    all_cards = fetch_all_cards()
    print(f"  {len(all_cards)} cards fetched")

    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prices = {}

    for card in all_cards:
        name = (card.get("name") or "").strip()
        if not name:
            continue
        price, history = extract_price_and_history(card)
        prices[name] = {
            "priceUsd":     price,
            "lastUpdated":  today,
            "source":       "JustTCG",
            "priceHistory": history,
        }

    save_prices({"lastUpdated": today, "prices": prices})
    print(f"\nDone. {len(prices)} prices written.")


if __name__ == "__main__":
    main()
