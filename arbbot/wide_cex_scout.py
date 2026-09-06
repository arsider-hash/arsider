#!/usr/bin/env python3
"""
ARBBOT wide cross-CEX spot HUNTER.

Read-only public-market-data scanner aimed at higher-turnover fragmentation
across a broader set of liquid USDT spot pairs. Uses Bitget and Gate public
order-book/ticker endpoints because they have been reliable on GitHub runners.

This is discovery only. No credentials, orders, transfers or custody.
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
LATEST = DATA / "wide_cex_latest.json"
HISTORY = DATA / "wide_cex_history.csv"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "LINKUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT",
    "DOTUSDT", "TRXUSDT", "SUIUSDT", "APTUSDT", "NEARUSDT",
]

# Conservative first-pass friction: two taker legs plus extra execution buffer.
TAKER_FEE_BPS_PER_LEG = 10.0
EXTRA_BUFFER_BPS = 10.0
TOTAL_FRICTION_BPS = 2 * TAKER_FEE_BPS_PER_LEG + EXTRA_BUFFER_BPS
MIN_WATCH_NET_BPS = 8.0

FIELDS = [
    "timestamp_utc", "strategy", "key", "asset", "direction", "venue",
    "gross_bps", "stressed_bps", "candidate", "capacity_usdt_est",
    "detail_json",
]


def get_json(url: str, retries: int = 3):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "arsider-arbbot/1.1",
    })
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            last = exc
            time.sleep(1.25 * (attempt + 1))
    raise RuntimeError(str(last))


def q(url: str, **params) -> str:
    return url + "?" + urllib.parse.urlencode(params)


def bitget_book(symbol: str) -> dict:
    d = get_json(q("https://api.bitget.com/api/v2/spot/market/tickers", symbol=symbol))
    if d.get("code") != "00000" or not d.get("data"):
        raise RuntimeError(f"Bitget spot {symbol}: {d}")
    x = d["data"][0]
    bid = float(x.get("bidPr") or 0)
    ask = float(x.get("askPr") or 0)
    bid_qty = float(x.get("bidSz") or 0)
    ask_qty = float(x.get("askSz") or 0)
    if min(bid, ask, bid_qty, ask_qty) <= 0:
        raise RuntimeError(f"Bitget invalid book {symbol}: {x}")
    return {"bid": bid, "ask": ask, "bid_qty": bid_qty, "ask_qty": ask_qty}


def gate_book(symbol: str) -> dict:
    pair = symbol.replace("USDT", "_USDT")
    d = get_json(q("https://api.gateio.ws/api/v4/spot/order_book", currency_pair=pair, limit=5))
    asks = d.get("asks") or []
    bids = d.get("bids") or []
    if not asks or not bids:
        raise RuntimeError(f"Gate invalid book {symbol}: {d}")
    ask = float(asks[0][0]); ask_qty = float(asks[0][1])
    bid = float(bids[0][0]); bid_qty = float(bids[0][1])
    if min(bid, ask, bid_qty, ask_qty) <= 0:
        raise RuntimeError(f"Gate invalid levels {symbol}: {d}")
    return {"bid": bid, "ask": ask, "bid_qty": bid_qty, "ask_qty": ask_qty}


def make_row(ts, symbol, direction, buy_ask, sell_bid, capacity, buy_venue, sell_venue):
    gross = (sell_bid / buy_ask - 1.0) * 10000
    stressed = gross - TOTAL_FRICTION_BPS
    asset = symbol[:-4]
    return {
        "timestamp_utc": ts,
        "strategy": "wide_cex_cross_spot",
        "key": f"{asset}:{direction}",
        "asset": asset,
        "direction": direction,
        "venue": "Bitget<->Gate",
        "gross_bps": f"{gross:.6f}",
        "stressed_bps": f"{stressed:.6f}",
        "candidate": "YES" if stressed >= MIN_WATCH_NET_BPS else "NO",
        "capacity_usdt_est": f"{capacity:.2f}",
        "detail_json": json.dumps({
            "buy_venue": buy_venue,
            "sell_venue": sell_venue,
            "buy_ask": buy_ask,
            "sell_bid": sell_bid,
            "taker_fee_bps_per_leg": TAKER_FEE_BPS_PER_LEG,
            "extra_buffer_bps": EXTRA_BUFFER_BPS,
            "total_friction_bps": TOTAL_FRICTION_BPS,
            "note": "Discovery snapshot only; assumes capital pre-positioned on both venues. Rebalancing, withdrawal, latency and deeper-book impact are not yet validated.",
        }, separators=(",", ":"), sort_keys=True),
    }


def scan_symbol(ts: str, symbol: str):
    a = bitget_book(symbol)
    b = gate_book(symbol)
    return [
        make_row(
            ts, symbol, "buy Bitget / sell Gate",
            a["ask"], b["bid"],
            min(a["ask"] * a["ask_qty"], b["bid"] * b["bid_qty"]),
            "Bitget", "Gate",
        ),
        make_row(
            ts, symbol, "buy Gate / sell Bitget",
            b["ask"], a["bid"],
            min(b["ask"] * b["ask_qty"], a["bid"] * a["bid_qty"]),
            "Gate", "Bitget",
        ),
    ]


def ensure_history():
    if not HISTORY.exists():
        with HISTORY.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def append_rows(rows):
    ensure_history()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerows(rows)


def main():
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows, errors = [], []
    for symbol in SYMBOLS:
        try:
            rows.extend(scan_symbol(ts, symbol))
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")

    append_rows(rows)
    ranked = sorted(rows, key=lambda r: float(r["stressed_bps"]), reverse=True)
    payload = {
        "generated_at_utc": ts,
        "mode": "paper_read_only",
        "symbol_count": len(SYMBOLS),
        "row_count": len(rows),
        "candidate_count": sum(r["candidate"] == "YES" for r in rows),
        "friction_model_bps": TOTAL_FRICTION_BPS,
        "best": ranked[0] if ranked else None,
        "rows": ranked,
        "errors": errors,
        "warning": "Top-of-book discovery only. Any promoted route still requires burst, multi-size depth, fee-tier, latency, rebalancing and counterparty validation.",
    }
    LATEST.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if ranked:
        b = ranked[0]
        print(f"WIDE BEST {b['key']} {float(b['stressed_bps']):+.2f} bps stressed")
    print(f"rows={len(rows)} candidates={payload['candidate_count']} errors={len(errors)}")


if __name__ == "__main__":
    main()
