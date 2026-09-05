#!/usr/bin/env python3
"""
ARBBOT CEX LAB
Read-only public-market-data scanner.

Scans:
1) Binance vs Bybit spot cross-exchange spreads
2) Binance triangular spot cycles
3) Same-venue spot/perpetual basis
4) Stablecoin dislocations

No login, API key, wallet, order placement or transaction signing.
"""

from __future__ import annotations

import csv
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
LATEST = DATA / "market_latest.json"
HISTORY = DATA / "market_history.csv"

ASSETS = ["BTC", "ETH", "SOL"]
CROSS_CEX_BUFFER_BPS = 30.0
TRI_TAKER_FEE_BPS_PER_LEG = 10.0
TRI_EXTRA_BUFFER_BPS = 8.0
BASIS_WATCH_BPS = 20.0
STABLE_WATCH_BPS = 10.0

FIELDS = [
    "timestamp_utc", "strategy", "key", "asset", "direction", "venue",
    "gross_bps", "stressed_bps", "candidate", "capacity_usdt_est",
    "detail_json"
]

def get_json(url: str, retries: int = 3):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "arsider-arbbot/0.4",
    })
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last))

def q(url: str, **params) -> str:
    return url + "?" + urllib.parse.urlencode(params)

def binance_spot_book(symbol: str) -> dict:
    d = get_json(q("https://data-api.binance.vision/api/v3/ticker/bookTicker", symbol=symbol))
    return {
        "bid": float(d["bidPrice"]),
        "bid_qty": float(d["bidQty"]),
        "ask": float(d["askPrice"]),
        "ask_qty": float(d["askQty"]),
    }

def binance_perp_book(symbol: str) -> dict:
    d = get_json(q("https://fapi.binance.com/fapi/v1/ticker/bookTicker", symbol=symbol))
    return {
        "bid": float(d["bidPrice"]),
        "bid_qty": float(d["bidQty"]),
        "ask": float(d["askPrice"]),
        "ask_qty": float(d["askQty"]),
    }

def binance_premium(symbol: str) -> dict:
    d = get_json(q("https://fapi.binance.com/fapi/v1/premiumIndex", symbol=symbol))
    return {
        "mark": float(d["markPrice"]),
        "index": float(d["indexPrice"]),
        "funding_rate": float(d.get("lastFundingRate") or 0),
        "next_funding_time": int(d.get("nextFundingTime") or 0),
    }

def bybit_ticker(symbol: str, category: str) -> dict:
    d = get_json(q("https://api.bybit.com/v5/market/tickers", category=category, symbol=symbol))
    if d.get("retCode") != 0 or not d.get("result", {}).get("list"):
        raise RuntimeError(f"Bybit {category} {symbol}: {d}")
    x = d["result"]["list"][0]
    out = {
        "bid": float(x.get("bid1Price") or 0),
        "bid_qty": float(x.get("bid1Size") or 0),
        "ask": float(x.get("ask1Price") or 0),
        "ask_qty": float(x.get("ask1Size") or 0),
        "last": float(x.get("lastPrice") or 0),
    }
    if category == "linear":
        out.update({
            "mark": float(x.get("markPrice") or 0),
            "index": float(x.get("indexPrice") or 0),
            "funding_rate": float(x.get("fundingRate") or 0),
            "next_funding_time": int(x.get("nextFundingTime") or 0),
        })
    return out

def mid(book: dict) -> float:
    if book["bid"] <= 0 or book["ask"] <= 0:
        raise RuntimeError("invalid book")
    return (book["bid"] + book["ask"]) / 2

def row(ts, strategy, key, asset, direction, venue,
        gross_bps, stressed_bps, candidate, capacity, detail):
    return {
        "timestamp_utc": ts,
        "strategy": strategy,
        "key": key,
        "asset": asset,
        "direction": direction,
        "venue": venue,
        "gross_bps": f"{gross_bps:.6f}",
        "stressed_bps": f"{stressed_bps:.6f}",
        "candidate": "YES" if candidate else "NO",
        "capacity_usdt_est": "" if capacity is None else f"{capacity:.2f}",
        "detail_json": json.dumps(detail, separators=(",", ":"), sort_keys=True),
    }

def ensure_history():
    if not HISTORY.exists():
        with HISTORY.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

def append_rows(rows):
    ensure_history()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writerows(rows)

def cross_exchange_spot(ts, cache):
    rows = []
    for asset in ASSETS:
        symbol = asset + "USDT"
        bn = cache.setdefault(("bn_spot", symbol), binance_spot_book(symbol))
        by = cache.setdefault(("by_spot", symbol), bybit_ticker(symbol, "spot"))

        paths = [
            ("buy Binance / sell Bybit", bn["ask"], by["bid"],
             min(bn["ask"] * bn["ask_qty"], by["bid"] * by["bid_qty"])),
            ("buy Bybit / sell Binance", by["ask"], bn["bid"],
             min(by["ask"] * by["ask_qty"], bn["bid"] * bn["bid_qty"])),
        ]
        for direction, buy_ask, sell_bid, capacity in paths:
            gross = (sell_bid / buy_ask - 1) * 10000
            stressed = gross - CROSS_CEX_BUFFER_BPS
            rows.append(row(
                ts, "cex_cross_spot", f"{asset}:{direction}", asset, direction,
                "Binance<->Bybit", gross, stressed, stressed > 0,
                capacity,
                {
                    "buy_ask": buy_ask,
                    "sell_bid": sell_bid,
                    "buffer_bps": CROSS_CEX_BUFFER_BPS,
                    "note": "Assumes capital already present on both venues; transfer/rebalancing costs not included."
                }
            ))
    return rows

def triangle_for(ts, bridge_asset, cache):
    # Triangle: USDT <-> BTC <-> bridge_asset <-> USDT.
    btcusdt = cache.setdefault(("bn_spot", "BTCUSDT"), binance_spot_book("BTCUSDT"))
    ausdt_sym = bridge_asset + "USDT"
    abtc_sym = bridge_asset + "BTC"
    ausdt = cache.setdefault(("bn_spot", ausdt_sym), binance_spot_book(ausdt_sym))
    abtc = cache.setdefault(("bn_spot", abtc_sym), binance_spot_book(abtc_sym))

    fee_mult = (1 - TRI_TAKER_FEE_BPS_PER_LEG / 10000) ** 3

    # USDT -> BTC -> A -> USDT
    gross_ratio_a = (1 / btcusdt["ask"]) * (1 / abtc["ask"]) * ausdt["bid"]
    net_ratio_a = gross_ratio_a * fee_mult
    gross_a = (gross_ratio_a - 1) * 10000
    stressed_a = (net_ratio_a - 1) * 10000 - TRI_EXTRA_BUFFER_BPS
    cap_a = min(
        btcusdt["ask"] * btcusdt["ask_qty"],
        abtc["ask_qty"] * abtc["ask"] * btcusdt["bid"],
        ausdt["bid_qty"] * ausdt["bid"],
    )

    # USDT -> A -> BTC -> USDT
    gross_ratio_b = (1 / ausdt["ask"]) * abtc["bid"] * btcusdt["bid"]
    net_ratio_b = gross_ratio_b * fee_mult
    gross_b = (gross_ratio_b - 1) * 10000
    stressed_b = (net_ratio_b - 1) * 10000 - TRI_EXTRA_BUFFER_BPS
    cap_b = min(
        ausdt["ask"] * ausdt["ask_qty"],
        abtc["bid_qty"] * ausdt["bid"],
        btcusdt["bid_qty"] * btcusdt["bid"],
    )

    common = {
        "fee_bps_per_leg": TRI_TAKER_FEE_BPS_PER_LEG,
        "extra_buffer_bps": TRI_EXTRA_BUFFER_BPS,
        "top_of_book_only": True,
    }

    return [
        row(ts, "cex_triangle", f"{bridge_asset}:USDT-BTC-{bridge_asset}-USDT",
            bridge_asset, f"USDT->BTC->{bridge_asset}->USDT", "Binance",
            gross_a, stressed_a, stressed_a > 0, cap_a, common),
        row(ts, "cex_triangle", f"{bridge_asset}:USDT-{bridge_asset}-BTC-USDT",
            bridge_asset, f"USDT->{bridge_asset}->BTC->USDT", "Binance",
            gross_b, stressed_b, stressed_b > 0, cap_b, common),
    ]

def triangles(ts, cache):
    rows = []
    for a in ["ETH", "SOL"]:
        try:
            rows.extend(triangle_for(ts, a, cache))
        except Exception as e:
            rows.append(row(
                ts, "cex_triangle_error", f"{a}:error", a, "n/a", "Binance",
                0, -9999, False, None, {"error": str(e)}
            ))
    return rows

def basis_rows(ts, cache):
    rows = []
    for asset in ASSETS:
        symbol = asset + "USDT"

        bn_spot = cache.setdefault(("bn_spot", symbol), binance_spot_book(symbol))
        bn_perp = cache.setdefault(("bn_perp", symbol), binance_perp_book(symbol))
        bn_prem = cache.setdefault(("bn_prem", symbol), binance_premium(symbol))
        bn_basis = (mid(bn_perp) / mid(bn_spot) - 1) * 10000
        rows.append(row(
            ts, "spot_perp_basis", f"{asset}:Binance", asset,
            "long spot / short perp" if bn_basis > 0 else "short spot / long perp",
            "Binance", abs(bn_basis), abs(bn_basis), abs(bn_basis) >= BASIS_WATCH_BPS,
            None,
            {
                "signed_basis_bps": bn_basis,
                "funding_rate": bn_prem["funding_rate"],
                "spot_mid": mid(bn_spot),
                "perp_mid": mid(bn_perp),
                "mark_price": bn_prem["mark"],
                "note": "Basis magnitude is a carry signal, not immediate executable profit."
            }
        ))

        by_spot = cache.setdefault(("by_spot", symbol), bybit_ticker(symbol, "spot"))
        by_perp = cache.setdefault(("by_perp", symbol), bybit_ticker(symbol, "linear"))
        by_basis = (mid(by_perp) / mid(by_spot) - 1) * 10000
        rows.append(row(
            ts, "spot_perp_basis", f"{asset}:Bybit", asset,
            "long spot / short perp" if by_basis > 0 else "short spot / long perp",
            "Bybit", abs(by_basis), abs(by_basis), abs(by_basis) >= BASIS_WATCH_BPS,
            None,
            {
                "signed_basis_bps": by_basis,
                "funding_rate": by_perp.get("funding_rate", 0),
                "spot_mid": mid(by_spot),
                "perp_mid": mid(by_perp),
                "mark_price": by_perp.get("mark", 0),
                "note": "Basis magnitude is a carry signal, not immediate executable profit."
            }
        ))
    return rows

def stablecoin_rows(ts, cache):
    rows = []
    for symbol, asset in [("USDCUSDT", "USDC"), ("FDUSDUSDT", "FDUSD")]:
        for venue in ["Binance", "Bybit"]:
            try:
                if venue == "Binance":
                    book = cache.setdefault(("bn_spot", symbol), binance_spot_book(symbol))
                else:
                    book = cache.setdefault(("by_spot", symbol), bybit_ticker(symbol, "spot"))
                m = mid(book)
                signed = (m - 1.0) * 10000
                deviation = abs(signed)
                rows.append(row(
                    ts, "stable_dislocation", f"{asset}:{venue}", asset,
                    "above peg" if signed > 0 else "below peg",
                    venue, deviation, deviation, deviation >= STABLE_WATCH_BPS,
                    min(book["bid"] * book["bid_qty"], book["ask"] * book["ask_qty"]),
                    {
                        "mid": m,
                        "signed_deviation_bps": signed,
                        "watch_threshold_bps": STABLE_WATCH_BPS,
                        "note": "Peg deviation is a research signal; redemption, venue and issuer risks matter."
                    }
                ))
            except Exception as e:
                # Not every venue necessarily lists every stable pair.
                rows.append(row(
                    ts, "stable_dislocation_error", f"{asset}:{venue}:error", asset,
                    "n/a", venue, 0, -9999, False, None, {"error": str(e)}
                ))
    return rows

def main():
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cache = {}
    rows = []
    errors = []

    jobs = [cross_exchange_spot, triangles, basis_rows, stablecoin_rows]
    for job in jobs:
        try:
            rows.extend(job(ts, cache))
        except Exception as e:
            errors.append(f"{job.__name__}: {e}")

    append_rows(rows)

    ranked = sorted(
        [r for r in rows if not r["strategy"].endswith("_error")],
        key=lambda r: float(r["stressed_bps"]),
        reverse=True,
    )
    payload = {
        "generated_at_utc": ts,
        "mode": "paper_read_only",
        "errors": errors,
        "candidate_count": sum(r["candidate"] == "YES" for r in rows),
        "best": ranked[0] if ranked else None,
        "rows": ranked,
        "risk_note": (
            "Signals are not guarantees. Real execution can lose money through fees, "
            "slippage, latency, basis moves, funding changes, liquidation, transfer "
            "friction and venue/counterparty failure."
        ),
    }
    LATEST.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if ranked:
        best = ranked[0]
        print(
            f"BEST {best['strategy']} {best['key']} "
            f"{float(best['stressed_bps']):+.2f} bps"
        )
    print(f"rows={len(rows)} candidates={payload['candidate_count']} errors={len(errors)}")

if __name__ == "__main__":
    main()
