#!/usr/bin/env python3
"""
Daily card price updater for Riftbound TCG.

Source: JustTCG (~40 calls, USD, 7-day price history included).
If JustTCG fails (quota exhausted or network error), the existing
prices.json is kept unchanged — no overwrite with stale/bad data.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

JUSTTCG_API_KEY = os.environ["JUSTTCG_API_KEY"]
JUSTTCG_URL     = "https://api.justtcg.com"
JUSTTCG_GAME    = "riftbound-league-of-legends-trading-card-game"
PRICES_FILE     = "docs/prices.json"
PAGE_SIZE       = 20    # JustTCG free-tier max per request
REQUEST_DELAY   = 7.0   # 10 req/min limit → 6s minimum; 7s gives headroom


# ── I/O helpers ───────────────────────────────────────────────────────────────

def save_prices(data: dict):
    os.makedirs("docs", exist_ok=True)
    with open(PRICES_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── JustTCG ───────────────────────────────────────────────────────────────────

def fetch_all_cards() -> list[dict]:
    """Page through all Riftbound cards on JustTCG."""
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
            except requests.exceptions.HTTPError:
                if resp.status_code == 429 and attempt < 2:
                    print(f"  429 rate limit — waiting 65s before retry…")
                    time.sleep(65)
                else:
                    raise
        body     = resp.json()
        items    = body.get("data", [])
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
    """Return (current_usd_price, 7_day_history) from the Near Mint variant."""
    variants = card.get("variants") or []
    variant  = next(
        (v for v in variants if "Near Mint" in (v.get("condition") or "")),
        variants[0] if variants else None,
    )
    if not variant:
        return None, []
    price   = variant.get("price")
    history = [
        {"price": h["p"], "timestamp": h["t"]}
        for h in (variant.get("priceHistory") or [])
        if "p" in h and "t" in h
    ]
    return price, history


def build_prices(cards: list[dict], today: str) -> dict:
    prices = {}
    for card in cards:
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
    return prices


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("Fetching all Riftbound cards from JustTCG…")
    try:
        cards  = fetch_all_cards()
        prices = build_prices(cards, today)
        print(f"  {len(prices)} prices built from JustTCG")
    except Exception as exc:
        # Keep existing prices.json intact rather than overwriting with bad data.
        print(f"\nJustTCG fetch failed: {exc}")
        print("Keeping existing prices.json unchanged.")
        sys.exit(0)

    save_prices({"lastUpdated": today, "prices": prices})
    print(f"\nDone. {len(prices)} prices written.")


if __name__ == "__main__":
    main()
