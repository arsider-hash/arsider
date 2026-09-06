#!/usr/bin/env python3
"""
ARBBOT funding-rate scout.
Read-only public market data only.

Compares Bitget USDT perpetual funding with Gate USDT perpetual funding for
BTC/ETH/SOL. These public endpoints are used because Binance/Bybit/OKX cloud
access has proven unreliable from GitHub-hosted runners.

Legacy CSV column names are retained for backward compatibility.
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
        "User-Agent": "arsider-arbbot/0.8",
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

def bitget(symbol: str) -> dict:
    d = get_json(q(
        "https://api.bitget.com/api/v3/market/current-fund-rate",
        category="USDT-FUTURES", symbol=symbol,
    ))
    if d.get("code") != "00000" or not d.get("data"):
        raise RuntimeError(f"Bitget funding error: {d}")
    x = d["data"][0]
    return {
        "venue": "Bitget USDT perpetual",
        "symbol": symbol,
        "funding_rate": float(x.get("fundingRate") or 0),
        "interval_hours": float(x.get("fundingRateInterval") or 8),
        "next_funding_time": int(x.get("nextUpdate") or 0),
    }

def gate(symbol: str) -> dict:
    contract = symbol.replace("USDT", "_USDT")
    d = get_json(f"https://api.gateio.ws/api/v4/futures/usdt/contracts/{contract}")
    if not isinstance(d, dict) or not d.get("name"):
        raise RuntimeError(f"Gate funding error: {d}")
    interval_seconds = float(d.get("funding_interval") or 28800)
    interval_hours = interval_seconds / 3600.0
    if interval_hours <= 0 or interval_hours > 24:
        interval_hours = 8.0
    return {
        "venue": "Gate USDT perpetual",
        "symbol": symbol,
        "funding_rate": float(d.get("funding_rate") or 0),
        "interval_hours": interval_hours,
        "next_funding_time": int(float(d.get("funding_next_apply") or 0) * 1000),
        "indicative_funding_rate": float(d.get("funding_rate_indicative") or 0),
    }

def ensure_history():
    if not HISTORY.exists():
        with HISTORY.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

def append_history(rows):
    ensure_history()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerows(rows)

def main():
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows, detailed, errors = [], [], []

    for symbol in SYMBOLS:
        try:
            a = bitget(symbol)
            b = gate(symbol)

            a_per_hour = a["funding_rate"] / a["interval_hours"]
            b_per_hour = b["funding_rate"] / b["interval_hours"]
            spread_per_hour = a_per_hour - b_per_hour
            spread_bps_per_hour = spread_per_hour * 10000
            spread_bps_per_8h = spread_bps_per_hour * 8
            annualized_pct = spread_per_hour * 24 * 365 * 100

            direction = (
                "short Bitget / long Gate" if spread_per_hour > 0
                else "long Bitget / short Gate" if spread_per_hour < 0
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
                "venue_a": a,
                "venue_b": b,
                "venue_a_name": "Bitget",
                "venue_b_name": "Gate",
                "round_trip_cost_assumption_bps": ROUND_TRIP_COST_BPS,
                "warning": (
                    "Funding can change before settlement. Basis, liquidation, collateral, "
                    "fee-tier, venue and transfer risk are not fully modeled."
                )
            })
        except Exception as e:
            errors.append(f"{symbol}: {e}")

    append_history(rows)
    detailed.sort(key=lambda x: abs(float(x["spread_bps_per_8h"])), reverse=True)

    payload = {
        "generated_at_utc": ts,
        "mode": "paper_read_only",
        "venues": ["Bitget", "Gate"],
        "candidate_count": sum(x["candidate"] == "YES" for x in rows),
        "best": detailed[0] if detailed else None,
        "rows": detailed,
        "errors": errors,
    }
    LATEST.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if detailed:
        best = detailed[0]
        print(
            f"BEST {best['symbol']} {abs(float(best['spread_bps_per_8h'])):.3f} "
            f"bps/8h | {best['direction']}"
        )
    print(f"rows={len(rows)} errors={len(errors)}")

if __name__ == "__main__":
    main()
