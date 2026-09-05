#!/usr/bin/env python3
"""
ARBBOT EU CEX scout.

Read-only public market data from Coinbase Exchange and Kraken.
Focuses on EUR-denominated fragmentation and EUR/USDT triangular cycles
that are more relevant to an Italy/EU-based small-capital user.

No account, API key, wallet, order placement or transaction signing.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
LATEST = DATA / "eu_latest.json"
HISTORY = DATA / "eu_history.csv"

ASSETS = ["BTC", "ETH", "SOL"]

CROSS_VENUE_BUFFER_BPS = 45.0
TRI_TAKER_FEE_BPS_PER_LEG = 40.0
TRI_EXTRA_BUFFER_BPS = 10.0
STABLE_EUR_BUFFER_BPS = 35.0

FIELDS = [
    "timestamp_utc", "strategy", "key", "asset", "direction", "venue",
    "gross_bps", "stressed_bps", "candidate", "detail_json"
]

def get_json(url: str, retries: int = 3):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "arsider-arbbot/0.5",
    })
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last))

def coinbase(product: str) -> dict:
    d = get_json(f"https://api.exchange.coinbase.com/products/{product}/ticker")
    bid = float(d["bid"])
    ask = float(d["ask"])
    if bid <= 0 or ask <= 0:
        raise RuntimeError(f"bad Coinbase book for {product}")
    return {"bid": bid, "ask": ask, "last": float(d.get("price") or 0)}

def kraken(pair: str) -> dict:
    url = "https://api.kraken.com/0/public/Ticker?" + urllib.parse.urlencode({"pair": pair})
    d = get_json(url)
    if d.get("error"):
        raise RuntimeError(f"Kraken {pair}: {d['error']}")
    result = d.get("result") or {}
    if not result:
        raise RuntimeError(f"Kraken {pair}: empty")
    x = next(iter(result.values()))
    bid = float(x["b"][0])
    ask = float(x["a"][0])
    if bid <= 0 or ask <= 0:
        raise RuntimeError(f"bad Kraken book for {pair}")
    return {"bid": bid, "ask": ask, "last": float(x["c"][0])}

def make_row(ts, strategy, key, asset, direction, venue,
             gross_bps, stressed_bps, detail):
    return {
        "timestamp_utc": ts,
        "strategy": strategy,
        "key": key,
        "asset": asset,
        "direction": direction,
        "venue": venue,
        "gross_bps": f"{gross_bps:.6f}",
        "stressed_bps": f"{stressed_bps:.6f}",
        "candidate": "YES" if stressed_bps > 0 else "NO",
        "detail_json": json.dumps(detail, separators=(",", ":"), sort_keys=True),
    }

def ensure_history():
    if not HISTORY.exists():
        with HISTORY.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

def append_rows(rows):
    ensure_history()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerows(rows)

def cross_spot(ts, cache):
    rows = []
    for asset in ASSETS:
        cb_product = f"{asset}-EUR"
        kr_pair = ("XBT" if asset == "BTC" else asset) + "EUR"
        cb = cache.setdefault(("cb", cb_product), coinbase(cb_product))
        kr = cache.setdefault(("kr", kr_pair), kraken(kr_pair))

        for direction, buy_ask, sell_bid in [
            ("buy Coinbase / sell Kraken", cb["ask"], kr["bid"]),
            ("buy Kraken / sell Coinbase", kr["ask"], cb["bid"]),
        ]:
            gross = (sell_bid / buy_ask - 1.0) * 10000
            stressed = gross - CROSS_VENUE_BUFFER_BPS
            rows.append(make_row(
                ts, "eu_cross_spot", f"{asset}:{direction}", asset,
                direction, "Coinbase<->Kraken", gross, stressed,
                {
                    "buy_ask": buy_ask,
                    "sell_bid": sell_bid,
                    "buffer_bps": CROSS_VENUE_BUFFER_BPS,
                    "note": "Assumes prefunded balances on both venues; rebalancing and account-specific fees can erase the edge."
                }
            ))
    return rows

def coinbase_triangle(ts, asset, cache):
    stable = cache.setdefault(("cb", "USDT-EUR"), coinbase("USDT-EUR"))
    a_usdt = cache.setdefault(("cb", f"{asset}-USDT"), coinbase(f"{asset}-USDT"))
    a_eur = cache.setdefault(("cb", f"{asset}-EUR"), coinbase(f"{asset}-EUR"))

    fee_mult = (1 - TRI_TAKER_FEE_BPS_PER_LEG / 10000) ** 3

    gross_ratio_a = (1 / stable["ask"]) * (1 / a_usdt["ask"]) * a_eur["bid"]
    gross_a = (gross_ratio_a - 1) * 10000
    stressed_a = (gross_ratio_a * fee_mult - 1) * 10000 - TRI_EXTRA_BUFFER_BPS

    gross_ratio_b = (1 / a_eur["ask"]) * a_usdt["bid"] * stable["bid"]
    gross_b = (gross_ratio_b - 1) * 10000
    stressed_b = (gross_ratio_b * fee_mult - 1) * 10000 - TRI_EXTRA_BUFFER_BPS

    common = {
        "fee_bps_per_leg_assumption": TRI_TAKER_FEE_BPS_PER_LEG,
        "extra_buffer_bps": TRI_EXTRA_BUFFER_BPS,
        "note": "Top-of-book paper cycle. Exact Coinbase fee tier and available size must be validated."
    }
    return [
        make_row(ts, "eur_triangle", f"Coinbase:{asset}:EUR-USDT-{asset}-EUR",
                 asset, f"EUR->USDT->{asset}->EUR", "Coinbase",
                 gross_a, stressed_a, common),
        make_row(ts, "eur_triangle", f"Coinbase:{asset}:EUR-{asset}-USDT-EUR",
                 asset, f"EUR->{asset}->USDT->EUR", "Coinbase",
                 gross_b, stressed_b, common),
    ]

def kraken_triangle(ts, asset, cache):
    base = "XBT" if asset == "BTC" else asset
    stable = cache.setdefault(("kr", "USDTEUR"), kraken("USDTEUR"))
    a_usdt = cache.setdefault(("kr", f"{base}USDT"), kraken(f"{base}USDT"))
    a_eur = cache.setdefault(("kr", f"{base}EUR"), kraken(f"{base}EUR"))

    fee_mult = (1 - TRI_TAKER_FEE_BPS_PER_LEG / 10000) ** 3

    gross_ratio_a = (1 / stable["ask"]) * (1 / a_usdt["ask"]) * a_eur["bid"]
    gross_a = (gross_ratio_a - 1) * 10000
    stressed_a = (gross_ratio_a * fee_mult - 1) * 10000 - TRI_EXTRA_BUFFER_BPS

    gross_ratio_b = (1 / a_eur["ask"]) * a_usdt["bid"] * stable["bid"]
    gross_b = (gross_ratio_b - 1) * 10000
    stressed_b = (gross_ratio_b * fee_mult - 1) * 10000 - TRI_EXTRA_BUFFER_BPS

    common = {
        "fee_bps_per_leg_assumption": TRI_TAKER_FEE_BPS_PER_LEG,
        "extra_buffer_bps": TRI_EXTRA_BUFFER_BPS,
        "note": "Top-of-book paper cycle. Exact Kraken fee tier and available size must be validated."
    }
    return [
        make_row(ts, "eur_triangle", f"Kraken:{asset}:EUR-USDT-{asset}-EUR",
                 asset, f"EUR->USDT->{asset}->EUR", "Kraken",
                 gross_a, stressed_a, common),
        make_row(ts, "eur_triangle", f"Kraken:{asset}:EUR-{asset}-USDT-EUR",
                 asset, f"EUR->{asset}->USDT->EUR", "Kraken",
                 gross_b, stressed_b, common),
    ]

def stable_eur(ts, cache):
    rows = []
    for venue in ["Coinbase", "Kraken"]:
        try:
            if venue == "Coinbase":
                usdt = cache.setdefault(("cb", "USDT-EUR"), coinbase("USDT-EUR"))
                usdc = cache.setdefault(("cb", "USDC-EUR"), coinbase("USDC-EUR"))
            else:
                usdt = cache.setdefault(("kr", "USDTEUR"), kraken("USDTEUR"))
                usdc = cache.setdefault(("kr", "USDCEUR"), kraken("USDCEUR"))

            ratio_a = usdc["bid"] / usdt["ask"]
            gross_a = (ratio_a - 1) * 10000
            stressed_a = gross_a - STABLE_EUR_BUFFER_BPS

            ratio_b = usdt["bid"] / usdc["ask"]
            gross_b = (ratio_b - 1) * 10000
            stressed_b = gross_b - STABLE_EUR_BUFFER_BPS

            detail = {
                "usdt_eur": usdt,
                "usdc_eur": usdc,
                "buffer_bps": STABLE_EUR_BUFFER_BPS,
                "note": "Two-leg stablecoin conversion via EUR; issuer, venue and fee risks remain."
            }
            rows.append(make_row(
                ts, "stable_eur_dislocation", f"{venue}:USDC-EUR-USDT",
                "USDC/USDT", "USDC->EUR->USDT", venue,
                gross_a, stressed_a, detail
            ))
            rows.append(make_row(
                ts, "stable_eur_dislocation", f"{venue}:USDT-EUR-USDC",
                "USDT/USDC", "USDT->EUR->USDC", venue,
                gross_b, stressed_b, detail
            ))
        except Exception as exc:
            rows.append(make_row(
                ts, "stable_eur_dislocation_error", f"{venue}:error",
                "stable", "n/a", venue, 0, -9999,
                {"error": str(exc)}
            ))
    return rows

def main():
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cache = {}
    rows = []
    errors = []

    try:
        rows.extend(cross_spot(ts, cache))
    except Exception as exc:
        errors.append(f"cross_spot: {exc}")

    for asset in ASSETS:
        try:
            rows.extend(coinbase_triangle(ts, asset, cache))
        except Exception as exc:
            errors.append(f"coinbase_triangle {asset}: {exc}")
        try:
            rows.extend(kraken_triangle(ts, asset, cache))
        except Exception as exc:
            errors.append(f"kraken_triangle {asset}: {exc}")

    rows.extend(stable_eur(ts, cache))
    append_rows(rows)

    ranked = sorted(
        [r for r in rows if not r["strategy"].endswith("_error")],
        key=lambda r: float(r["stressed_bps"]),
        reverse=True,
    )
    payload = {
        "generated_at_utc": ts,
        "mode": "paper_read_only",
        "candidate_count": sum(r["candidate"] == "YES" for r in rows),
        "best": ranked[0] if ranked else None,
        "rows": ranked,
        "errors": errors,
        "risk_note": (
            "Public top-of-book signals are not executable-profit guarantees. "
            "Account fees, available depth, KYC/venue eligibility, rebalancing and latency matter."
        )
    }
    LATEST.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if ranked:
        b = ranked[0]
        print(f"BEST {b['strategy']} {b['key']} {float(b['stressed_bps']):+.2f} bps")
    print(f"rows={len(rows)} candidates={payload['candidate_count']} errors={len(errors)}")

if __name__ == "__main__":
    main()
