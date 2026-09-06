#!/usr/bin/env python3
"""ARBBOT stablecoin dislocation round-trip validator.

Read-only. Converts a stablecoin peg deviation into multi-size entry/exit scenarios
using public Binance order-book depth. It explicitly separates:
1) immediate executable round trip (buy asks, sell bids now), and
2) hypothetical convergence to a target price.

The convergence scenario is NOT arbitrage unless a verified redemption/exit path
exists. No credentials, orders, custody or transaction signing.
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
OUT = DATA / "stable_roundtrip_validation.json"

BUDGETS = [25, 50, 100, 250, 500, 1000]
TARGET_PRICE = 1.0
CONSERVATIVE_EXIT_PRICE = 0.9999
FRICTION_BPS = 5.0  # explicit stress for fees/price drift/operational friction


def get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "arsider-arbbot/0.6"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def q(url, **params):
    return url + "?" + urllib.parse.urlencode(params)


def depth(symbol, limit=1000):
    d = get_json(q("https://data-api.binance.vision/api/v3/depth", symbol=symbol, limit=limit))
    return {
        "bids": [(float(p), float(qty)) for p, qty in d.get("bids", [])],
        "asks": [(float(p), float(qty)) for p, qty in d.get("asks", [])],
    }


def buy_vwap(asks, budget):
    remaining_quote = float(budget)
    base = 0.0
    spent = 0.0
    for price, qty in asks:
        level_quote = price * qty
        take_quote = min(remaining_quote, level_quote)
        if take_quote <= 0:
            continue
        take_base = take_quote / price
        base += take_base
        spent += take_quote
        remaining_quote -= take_quote
        if remaining_quote <= 1e-9:
            break
    if remaining_quote > 1e-6 or base <= 0:
        return None
    return {"base_qty": base, "quote_spent": spent, "vwap": spent / base}


def sell_vwap(bids, base_qty):
    remaining = float(base_qty)
    quote = 0.0
    sold = 0.0
    for price, qty in bids:
        take = min(remaining, qty)
        if take <= 0:
            continue
        quote += take * price
        sold += take
        remaining -= take
        if remaining <= 1e-9:
            break
    if remaining > 1e-6 or sold <= 0:
        return None
    return {"base_sold": sold, "quote_received": quote, "vwap": quote / sold}


def bps(ratio):
    return (ratio - 1.0) * 10000.0


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    selected = {}
    try:
        selected = (json.loads(DECISION.read_text(encoding="utf-8")) if DECISION.exists() else {}).get("selected") or {}
    except Exception:
        selected = {}

    if selected.get("strategy") != "stable_dislocation" or not str(selected.get("label", "")).startswith("FDUSD:"):
        payload = {"generated_at_utc": now, "state": "NOT_APPLICABLE", "selected": selected}
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("stable roundtrip validator: not applicable")
        return

    book = depth("FDUSDUSDT")
    rows = []
    for budget in BUDGETS:
        entry = buy_vwap(book["asks"], budget)
        if not entry:
            rows.append({"budget": budget, "state": "INSUFFICIENT_DEPTH"})
            continue
        immediate = sell_vwap(book["bids"], entry["base_qty"])
        immediate_edge = bps(immediate["quote_received"] / budget) if immediate else None
        convergence_quote = entry["base_qty"] * CONSERVATIVE_EXIT_PRICE
        convergence_edge_raw = bps(convergence_quote / budget)
        convergence_edge_stressed = convergence_edge_raw - FRICTION_BPS
        rows.append({
            "budget": budget,
            "entry_vwap": round(entry["vwap"], 8),
            "base_qty": round(entry["base_qty"], 8),
            "immediate_exit_vwap": None if not immediate else round(immediate["vwap"], 8),
            "immediate_roundtrip_edge_bps": None if immediate_edge is None else round(immediate_edge, 4),
            "convergence_exit_price_assumption": CONSERVATIVE_EXIT_PRICE,
            "convergence_edge_before_friction_bps": round(convergence_edge_raw, 4),
            "friction_stress_bps": FRICTION_BPS,
            "convergence_edge_after_friction_bps": round(convergence_edge_stressed, 4),
            "paper_profit_eur_if_full_convergence": round(max(0.0, budget * convergence_edge_stressed / 10000.0), 4),
        })

    max_positive = max((r["budget"] for r in rows if r.get("convergence_edge_after_friction_bps", -1) > 0), default=0)
    payload = {
        "generated_at_utc": now,
        "state": "DIAGNOSTIC_ONLY",
        "selected": selected,
        "symbol": "FDUSDUSDT",
        "target_price": TARGET_PRICE,
        "conservative_exit_price": CONSERVATIVE_EXIT_PRICE,
        "friction_stress_bps": FRICTION_BPS,
        "rows": rows,
        "max_positive_budget_under_hypothetical_convergence": max_positive,
        "verified_exit_path": False,
        "verdict": "INSUFFICIENT_EVIDENCE",
        "reason": "Immediate round trip is directly executable; convergence profit is hypothetical until redemption or another locked exit path is verified and costed.",
        "hard_boundary": "Read-only paper validation; no orders or custody.",
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"stable roundtrip diagnostic max hypothetical positive budget={max_positive}")


if __name__ == "__main__":
    main()
