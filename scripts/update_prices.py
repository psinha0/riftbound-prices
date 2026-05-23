#!/usr/bin/env python3
"""
Daily card price updater for Riftbound TCG.

Primary source: JustTCG (~58 calls, USD, 7-day price history included).
Fallback source: tcggo CardMarket API (~12 calls, EUR→USD, no history)
  — used automatically when JustTCG's daily limit is exhausted.

Set TCGGO_API_KEY secret in GitHub Actions to enable the fallback.
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

JUSTTCG_API_KEY = os.environ["JUSTTCG_API_KEY"]
TCGGO_API_KEY   = os.environ.get("TCGGO_API_KEY", "")   # optional fallback
JUSTTCG_URL     = "https://api.justtcg.com"
JUSTTCG_GAME    = "riftbound-league-of-legends-trading-card-game"
TCGGO_HOST      = "cardmarket-api-tcg.p.rapidapi.com"
TCGGO_GAME      = "riftbound"
EXCHANGE_URL    = "https://open.er-api.com/v6/latest/EUR"
PRICES_FILE     = "docs/prices.json"
PAGE_SIZE_JT    = 20    # JustTCG free-tier max
PAGE_SIZE_TG    = 100   # tcggo max
REQUEST_DELAY   = 7.0   # JustTCG: 10 req/min limit → 6s minimum; 7s gives headroom
TCGGO_DELAY     = 1.5   # tcggo has no stated per-minute limit


# ── I/O helpers ───────────────────────────────────────────────────────────────

def save_prices(data: dict):
    os.makedirs("docs", exist_ok=True)
    with open(PRICES_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── JustTCG (primary) ─────────────────────────────────────────────────────────

def fetch_all_cards_justtcg() -> list[dict]:
    """Page through all Riftbound cards on JustTCG. Raises on unrecoverable failure."""
    cards  = []
    offset = 0
    while True:
        for attempt in range(3):
            try:
                resp = requests.get(
                    f"{JUSTTCG_URL}/v1/cards",
                    headers={"x-api-key": JUSTTCG_API_KEY},
                    params={"game": JUSTTCG_GAME, "limit": PAGE_SIZE_JT, "offset": offset},
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
        offset += PAGE_SIZE_JT
        time.sleep(REQUEST_DELAY)
    return cards


def extract_justtcg_price_and_history(card: dict) -> tuple[float | None, list[dict]]:
    """Return (current_usd_price, 7_day_history) from the best variant."""
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


def build_prices_justtcg(cards: list[dict], today: str) -> dict:
    prices = {}
    for card in cards:
        name = (card.get("name") or "").strip()
        if not name:
            continue
        price, history = extract_justtcg_price_and_history(card)
        prices[name] = {
            "priceUsd":     price,
            "lastUpdated":  today,
            "source":       "JustTCG",
            "priceHistory": history,
        }
    return prices


# ── tcggo / CardMarket (fallback) ─────────────────────────────────────────────

def fetch_eur_to_usd() -> float:
    try:
        resp = requests.get(EXCHANGE_URL, timeout=10)
        resp.raise_for_status()
        rate = float(resp.json()["rates"]["USD"])
        print(f"  EUR→USD rate: {rate}")
        return rate
    except Exception as exc:
        print(f"  Exchange rate fetch failed ({exc}), using fallback 1.08")
        return 1.08


def fetch_all_cards_tcggo() -> list[dict]:
    """Page through all Riftbound cards on tcggo."""
    cards = []
    page  = 1
    while True:
        resp = requests.get(
            f"https://{TCGGO_HOST}/{TCGGO_GAME}/cards",
            headers={
                "x-rapidapi-key":  TCGGO_API_KEY,
                "x-rapidapi-host": TCGGO_HOST,
            },
            params={"per_page": PAGE_SIZE_TG, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        body        = resp.json()
        items       = body.get("data", [])
        cards.extend(items)
        total_pages = body.get("paging", {}).get("total", 1)
        print(f"  page {page}/{total_pages} — {len(items)} cards")
        if page >= total_pages or not items:
            break
        page += 1
        time.sleep(TCGGO_DELAY)
    return cards


def build_prices_tcggo(cards: list[dict], today: str, eur_to_usd: float) -> dict:
    prices = {}
    for card in cards:
        name = (card.get("name") or "").strip()
        if not name:
            continue
        cm        = (card.get("prices") or {}).get("cardmarket") or {}
        eur_price = cm.get("30d_average") or cm.get("lowest_near_mint")
        prices[name] = {
            "priceUsd":     round(float(eur_price) * eur_to_usd, 2) if eur_price else None,
            "lastUpdated":  today,
            "source":       "CardMarket",
            "priceHistory": [],
        }
    return prices


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("Fetching all Riftbound cards from JustTCG…")
    try:
        cards  = fetch_all_cards_justtcg()
        prices = build_prices_justtcg(cards, today)
        print(f"  {len(prices)} prices built from JustTCG")
    except Exception as exc:
        print(f"  JustTCG failed: {exc}")
        if not TCGGO_API_KEY:
            raise RuntimeError("JustTCG failed and TCGGO_API_KEY is not set — cannot fall back") from exc
        print("Falling back to tcggo CardMarket API…")
        eur_to_usd = fetch_eur_to_usd()
        cards      = fetch_all_cards_tcggo()
        prices     = build_prices_tcggo(cards, today, eur_to_usd)
        print(f"  {len(prices)} prices built from CardMarket (fallback)")

    save_prices({"lastUpdated": today, "prices": prices})
    print(f"\nDone. {len(prices)} prices written.")


if __name__ == "__main__":
    main()
