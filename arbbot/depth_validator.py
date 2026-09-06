#!/usr/bin/env python3
"""
ARBBOT depth validator.

For promoted cross-exchange spot signals, replace top-of-book fantasy with
VWAP through real public order-book depth at small capital sizes.

Read-only. No account, API key, order or funds.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DECISION = DATA / "decision.json"
OUT = DATA / "depth_validation.json"

BUDGETS = [25, 50, 100, 250, 500, 1000]
FEES_BPS = {
    "Binance": 10.0,
    "Bybit": 10.0,
    "Coinbase": 60.0,
    "Kraken": 80.0,
}
EXTRA_HAIRCUT_BPS = 5.0
REFERENCE_BUDGET = 100

def get_json(url: str):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "arsider-arbbot/0.7",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

def binance_book(symbol: str):
    q = urllib.parse.urlencode({"symbol": symbol, "limit": 100})
    d = get_json("https://api.binance.com/api/v3/depth?" + q)
    return [[float(p), float(qty)] for p, qty in d["bids"]], [[float(p), float(qty)] for p, qty in d["asks"]]

def bybit_book(symbol: str):
    q = urllib.parse.urlencode({"category": "spot", "symbol": symbol, "limit": 200})
    d = get_json("https://api.bybit.com/v5/market/orderbook?" + q)
    x = d["result"]
    return [[float(p), float(qty)] for p, qty in x["b"]], [[float(p), float(qty)] for p, qty in x["a"]]

def coinbase_book(product: str):
    q = urllib.parse.urlencode({"level": 2})
    d = get_json(f"https://api.exchange.coinbase.com/products/{product}/book?" + q)
    return [[float(x[0]), float(x[1])] for x in d["bids"]], [[float(x[0]), float(x[1])] for x in d["asks"]]

def kraken_book(symbol: str):
    q = urllib.parse.urlencode({"symbol": symbol})
    d = get_json("https://api.kraken.com/0/public/PreTrade?" + q)
    r = d.get("result") or {}
    bids = [[float(x["price"]), float(x["qty"])] for x in (r.get("bids") or [])]
    asks = [[float(x["price"]), float(x["qty"])] for x in (r.get("asks") or [])]
    if not bids or not asks:
        raise RuntimeError(f"Kraken PreTrade returned no depth for {symbol}")
    return bids, asks

def book(venue: str, asset: str, quote: str):
    if venue == "Binance":
        return binance_book(asset + quote)
    if venue == "Bybit":
        return bybit_book(asset + quote)
    if venue == "Coinbase":
        return coinbase_book(f"{asset}-{quote}")
    if venue == "Kraken":
        return kraken_book(f"{asset}/{quote}")
    raise ValueError(venue)

def buy_base(asks, quote_amount):
    remaining = quote_amount
    base = 0.0
    spent = 0.0
    for price, qty in asks:
        level_quote = price * qty
        take_quote = min(remaining, level_quote)
        take_base = take_quote / price
        base += take_base
        spent += take_quote
        remaining -= take_quote
        if remaining <= 1e-9:
            break
    if remaining > 1e-6:
        raise RuntimeError("insufficient ask depth")
    return base, spent, spent / base

def sell_base(bids, base_amount):
    remaining = base_amount
    quote = 0.0
    sold = 0.0
    for price, qty in bids:
        take = min(remaining, qty)
        quote += take * price
        sold += take
        remaining -= take
        if remaining <= 1e-12:
            break
    if remaining > 1e-9:
        raise RuntimeError("insufficient bid depth")
    return quote, sold, quote / sold

def parse_direction(selected):
    direction = selected.get("direction") or ""
    asset = (selected.get("label") or "").split(":", 1)[0]
    if "buy " not in direction or " / sell " not in direction:
        raise RuntimeError(f"unsupported direction: {direction}")
    left, right = direction.split(" / sell ", 1)
    buy_venue = left.replace("buy ", "").strip()
    sell_venue = right.strip()
    quote = "EUR" if selected.get("strategy") == "eu_cross_spot" else "USDT"
    return asset, quote, buy_venue, sell_venue

def main():
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not DECISION.exists():
        OUT.write_text(json.dumps({"generated_at_utc": ts, "state": "SKIP", "reason": "decision missing"}, indent=2), encoding="utf-8")
        return

    d = json.loads(DECISION.read_text(encoding="utf-8"))
    selected = d.get("selected") or {}
    strategy = selected.get("strategy")

    if strategy not in {"cex_cross_spot", "eu_cross_spot"} or d.get("state") not in {"VALIDATE", "READY_FOR_MANUAL_AUTHORIZATION"}:
        OUT.write_text(json.dumps({
            "generated_at_utc": ts,
            "state": "NOT_APPLICABLE",
            "selected": selected,
        }, indent=2), encoding="utf-8")
        print("Depth validation not applicable.")
        return

    asset, quote, buy_venue, sell_venue = parse_direction(selected)
    buy_bids, buy_asks = book(buy_venue, asset, quote)
    sell_bids, sell_asks = book(sell_venue, asset, quote)

    rows = []
    for total_budget in BUDGETS:
        leg_quote = total_budget / 2.0
        base_qty, book_spend, buy_vwap = buy_base(buy_asks, leg_quote)

        buy_fee = book_spend * FEES_BPS[buy_venue] / 10000
        sell_gross, _, sell_vwap = sell_base(sell_bids, base_qty)
        sell_fee = sell_gross * FEES_BPS[sell_venue] / 10000
        extra = leg_quote * EXTRA_HAIRCUT_BPS / 10000

        pnl = sell_gross - sell_fee - book_spend - buy_fee - extra
        pnl_bps_on_total_capital = pnl / total_budget * 10000

        rows.append({
            "total_budget": total_budget,
            "capital_per_side": leg_quote,
            "base_qty": base_qty,
            "buy_vwap": buy_vwap,
            "sell_vwap": sell_vwap,
            "buy_fee_bps": FEES_BPS[buy_venue],
            "sell_fee_bps": FEES_BPS[sell_venue],
            "extra_haircut_bps": EXTRA_HAIRCUT_BPS,
            "paper_pnl": round(pnl, 6),
            "paper_pnl_bps_on_total_capital": round(pnl_bps_on_total_capital, 4),
            "positive": pnl > 0,
        })

    reference = next(x for x in rows if x["total_budget"] == REFERENCE_BUDGET)
    positive_sizes = [x["total_budget"] for x in rows if x["positive"]]
    max_positive_budget = max(positive_sizes) if positive_sizes else 0
    pnl_bps = [float(x["paper_pnl_bps_on_total_capital"]) for x in rows]
    size_decay_bps = round(pnl_bps[0] - pnl_bps[-1], 4) if rows else 0.0
    capacity_class = (
        "UP_TO_1000" if max_positive_budget >= 1000 else
        "UP_TO_500" if max_positive_budget >= 500 else
        "UP_TO_250" if max_positive_budget >= 250 else
        "UP_TO_100" if max_positive_budget >= 100 else
        "TINY_OR_NONE"
    )

    verdict = "PASS" if reference["positive"] else "FAIL"

    payload = {
        "generated_at_utc": ts,
        "state": verdict,
        "selected": selected,
        "asset": asset,
        "quote": quote,
        "buy_venue": buy_venue,
        "sell_venue": sell_venue,
        "rows": rows,
        "capacity": {
            "max_positive_budget": max_positive_budget,
            "capacity_class": capacity_class,
            "positive_sizes": positive_sizes,
            "size_decay_bps_25_to_1000": size_decay_bps,
        },
        "rule": "PASS only if the €/$100 total-capital simulation remains positive after taker fees, real depth and an extra haircut; all six sizes are still reported so the Killer can reject poor scaling.",
        "warning": "Depth snapshots still do not guarantee simultaneous fills; the multi-size curve measures snapshot capacity, not guaranteed executable capacity."
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"DEPTH {verdict} {asset} {buy_venue}->{sell_venue} "
        f"pnl100={reference['paper_pnl']:+.6f} max_positive_budget={max_positive_budget}"
    )

if __name__ == "__main__":
    main()
