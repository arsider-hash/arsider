#!/usr/bin/env python3
"""
ARBBOT funding-rate scout.
Read-only public market data only.

Compares Binance USD-M and Bybit linear perpetual funding for BTC/ETH/SOL,
normalises different funding intervals, estimates the number of funding
periods needed to recover a conservative round-trip execution cost, and
keeps history for persistence analysis.
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
LATEST = DATA / "funding_latest.json"
HISTORY = DATA / "funding_history.csv"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ROUND_TRIP_COST_BPS = 30.0
WATCH_SPREAD_BPS_PER_8H = 2.0

FIELDS = [
    "timestamp_utc", "symbol", "direction",
    "binance_rate", "binance_interval_hours",
    "bybit_rate", "bybit_interval_hours",
    "spread_bps_per_hour", "spread_bps_per_8h",
    "rough_annualized_pct", "breakeven_8h_periods",
    "candidate"
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

def q(url, **params):
    return url + "?" + urllib.parse.urlencode(params)

def binance_interval_map():
    try:
        data = get_json("https://fapi.binance.com/fapi/v1/fundingInfo")
        return {x["symbol"]: float(x["fundingIntervalHours"]) for x in data}
    except Exception:
        return {}

def binance(symbol: str, intervals: dict) -> dict:
    d = get_json(q("https://fapi.binance.com/fapi/v1/premiumIndex", symbol=symbol))
    return {
        "venue": "Binance USD-M",
        "symbol": symbol,
        "mark_price": float(d["markPrice"]),
        "index_price": float(d["indexPrice"]),
        "funding_rate": float(d["lastFundingRate"]),
        "interval_hours": float(intervals.get(symbol, 8.0)),
        "next_funding_time": int(d["nextFundingTime"]),
    }

def bybit(symbol: str) -> dict:
    tick = get_json(q("https://api.bybit.com/v5/market/tickers", category="linear", symbol=symbol))
    if tick.get("retCode") != 0 or not tick.get("result", {}).get("list"):
        raise RuntimeError(f"Bybit ticker error: {tick}")
    x = tick["result"]["list"][0]

    inst = get_json(q("https://api.bybit.com/v5/market/instruments-info", category="linear", symbol=symbol))
    if inst.get("retCode") != 0 or not inst.get("result", {}).get("list"):
        raise RuntimeError(f"Bybit instruments error: {inst}")
    y = inst["result"]["list"][0]
    interval_minutes = float(y.get("fundingInterval") or 480)

    return {
        "venue": "Bybit linear",
        "symbol": symbol,
        "mark_price": float(x["markPrice"]),
        "index_price": float(x["indexPrice"]),
        "funding_rate": float(x["fundingRate"]),
        "interval_hours": interval_minutes / 60.0,
        "next_funding_time": int(x["nextFundingTime"]),
    }

def ensure_history():
    if not HISTORY.exists():
        with HISTORY.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

def append_history(rows):
    ensure_history()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writerows(rows)

def main():
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    intervals = binance_interval_map()
    rows = []
    detailed = []
    errors = []

    for symbol in SYMBOLS:
        try:
            a = binance(symbol, intervals)
            b = bybit(symbol)

            a_per_hour = a["funding_rate"] / a["interval_hours"]
            b_per_hour = b["funding_rate"] / b["interval_hours"]
            spread_per_hour = a_per_hour - b_per_hour
            spread_bps_per_hour = spread_per_hour * 10000
            spread_bps_per_8h = spread_bps_per_hour * 8
            annualized_pct = spread_per_hour * 24 * 365 * 100

            direction = (
                "short Binance / long Bybit" if spread_per_hour > 0
                else "long Binance / short Bybit" if spread_per_hour < 0
                else "flat"
            )
            edge = abs(spread_bps_per_8h)
            breakeven = None if edge <= 0 else ROUND_TRIP_COST_BPS / edge
            candidate = edge >= WATCH_SPREAD_BPS_PER_8H

            hrow = {
                "timestamp_utc": ts,
                "symbol": symbol,
                "direction": direction,
                "binance_rate": f"{a['funding_rate']:.10f}",
                "binance_interval_hours": f"{a['interval_hours']:.4f}",
                "bybit_rate": f"{b['funding_rate']:.10f}",
                "bybit_interval_hours": f"{b['interval_hours']:.4f}",
                "spread_bps_per_hour": f"{spread_bps_per_hour:.6f}",
                "spread_bps_per_8h": f"{spread_bps_per_8h:.6f}",
                "rough_annualized_pct": f"{abs(annualized_pct):.4f}",
                "breakeven_8h_periods": "" if breakeven is None else f"{breakeven:.3f}",
                "candidate": "YES" if candidate else "NO",
            }
            rows.append(hrow)

            detailed.append({
                **hrow,
                "binance": a,
                "bybit": b,
                "round_trip_cost_assumption_bps": ROUND_TRIP_COST_BPS,
                "warning": (
                    "Funding can change before settlement. This does not include basis moves, "
                    "liquidation, collateral, fee-tier, venue or transfer risk."
                )
            })
        except Exception as e:
            errors.append(f"{symbol}: {e}")

    append_history(rows)
    detailed.sort(key=lambda x: abs(float(x["spread_bps_per_8h"])), reverse=True)

    payload = {
        "generated_at_utc": ts,
        "mode": "paper_read_only",
        "candidate_count": sum(x["candidate"] == "YES" for x in rows),
        "best": detailed[0] if detailed else None,
        "rows": detailed,
        "errors": errors,
    }
    LATEST.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if detailed:
        b = detailed[0]
        print(
            f"BEST {b['symbol']} {abs(float(b['spread_bps_per_8h'])):.3f} "
            f"bps/8h | {b['direction']}"
        )
    print(f"rows={len(rows)} errors={len(errors)}")

if __name__ == "__main__":
    main()
