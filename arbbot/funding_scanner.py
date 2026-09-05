#!/usr/bin/env python3
"""
ARBBOT funding-rate scout.
Read-only. Public market-data endpoints only. No account, keys or trades.
Compares Binance USD-M and Bybit linear perpetual funding for BTC/ETH/SOL.
"""

from __future__ import annotations
import json, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
OUT = DATA / "funding_latest.json"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "arsider-arbbot/0.3",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

def binance(symbol: str) -> dict:
    q = urllib.parse.urlencode({"symbol": symbol})
    d = get_json("https://fapi.binance.com/fapi/v1/premiumIndex?" + q)
    return {
        "venue": "Binance USD-M",
        "symbol": symbol,
        "mark_price": float(d["markPrice"]),
        "index_price": float(d["indexPrice"]),
        "funding_rate": float(d["lastFundingRate"]),
        "next_funding_time": int(d["nextFundingTime"]),
    }

def bybit(symbol: str) -> dict:
    q = urllib.parse.urlencode({"category": "linear", "symbol": symbol})
    d = get_json("https://api.bybit.com/v5/market/tickers?" + q)
    if d.get("retCode") != 0 or not d.get("result", {}).get("list"):
        raise RuntimeError(f"Bybit error: {d}")
    x = d["result"]["list"][0]
    return {
        "venue": "Bybit linear",
        "symbol": symbol,
        "mark_price": float(x["markPrice"]),
        "index_price": float(x["indexPrice"]),
        "funding_rate": float(x["fundingRate"]),
        "next_funding_time": int(x["nextFundingTime"]),
    }

def main():
    rows, errors = [], []
    for symbol in SYMBOLS:
        try:
            a = binance(symbol)
            b = bybit(symbol)
            # Directional funding spread only. Positive means Binance funding > Bybit.
            spread = a["funding_rate"] - b["funding_rate"]
            rows.append({
                "symbol": symbol,
                "binance": a,
                "bybit": b,
                "funding_spread": spread,
                "funding_spread_bps": spread * 10000,
                "abs_spread_bps": abs(spread) * 10000,
                "paper_direction": (
                    "short Binance / long Bybit" if spread > 0
                    else "long Binance / short Bybit" if spread < 0
                    else "flat"
                ),
                "warning": "Funding spread alone is not executable profit; fees, basis, interval alignment, liquidation and venue risk matter."
            })
        except Exception as e:
            errors.append(f"{symbol}: {e}")

    rows.sort(key=lambda x: x["abs_spread_bps"], reverse=True)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "paper_read_only",
        "rows": rows,
        "errors": errors,
        "best": rows[0] if rows else None,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if rows:
        best = rows[0]
        print(f"BEST {best['symbol']}: {best['abs_spread_bps']:.4f} bps | {best['paper_direction']}")
    if errors:
        print("ERRORS:", *errors, sep="\n")

if __name__ == "__main__":
    main()
