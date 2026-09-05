#!/usr/bin/env python3
"""
ARSIDER ARBBOT - read-only Solana cross-DEX paper scanner.

No wallet, no private key, no signing, no transactions.
Uses Jupiter keyless quote access and logs simulated USDC->SOL->USDC
round trips restricted to individual DEXes.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path

API = "https://api.jup.ag/swap/v1/quote"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL = "So11111111111111111111111111111111111111112"

USDC_DECIMALS = 6
SOL_DECIMALS = 9

DEXES = ["Raydium CLMM", "Orca Whirlpool", "Meteora DLMM"]
START_USDC = 100.0
SLIPPAGE_BPS = 10
EXECUTION_BUFFER_BPS = 20.0
REQUEST_GAP_SECONDS = 2.25

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
CSV_PATH = DATA / "history.csv"
LATEST_PATH = DATA / "latest.json"

FIELDS = [
    "timestamp_utc", "buy_dex", "sell_dex", "start_usdc", "sol_bought",
    "final_usdc", "gross_profit_usdc", "gross_bps", "execution_buffer_bps",
    "stressed_bps", "candidate", "buy_price_impact_pct",
    "sell_price_impact_pct", "buy_latency_ms", "sell_latency_ms",
    "buy_route", "sell_route"
]

_last_request = 0.0

def _wait_rate_limit():
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < REQUEST_GAP_SECONDS:
        time.sleep(REQUEST_GAP_SECONDS - elapsed)

def _get(params: dict) -> tuple[dict, float]:
    global _last_request
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{API}?{query}",
        headers={"Accept": "application/json", "User-Agent": "arsider-arbbot/0.2"},
    )

    for attempt in range(5):
        _wait_rate_limit()
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                payload = json.loads(r.read().decode("utf-8"))
            _last_request = time.monotonic()
            return payload, (time.perf_counter() - t0) * 1000
        except urllib.error.HTTPError as e:
            _last_request = time.monotonic()
            if e.code == 429 and attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code}: {body[:250]}") from e
        except Exception:
            _last_request = time.monotonic()
            if attempt < 4:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise RuntimeError("request retries exhausted")

def quote(input_mint: str, output_mint: str, amount_raw: int, dex: str) -> dict:
    payload, latency = _get({
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount_raw),
        "slippageBps": str(SLIPPAGE_BPS),
        "instructionVersion": "V2",
        "onlyDirectRoutes": "true",
        "dexes": dex,
    })
    if "outAmount" not in payload:
        raise RuntimeError(payload.get("error") or f"bad quote response: {payload}")
    labels = []
    for leg in payload.get("routePlan", []):
        label = leg.get("swapInfo", {}).get("label")
        if label:
            labels.append(label)
    return {
        "out_raw": int(payload["outAmount"]),
        "price_impact_pct": float(payload.get("priceImpactPct") or 0.0) * 100,
        "latency_ms": latency,
        "route": " > ".join(labels) or dex,
    }

def ensure_csv():
    if not CSV_PATH.exists():
        with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

def append_row(row: dict):
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(row)

def scan_pair(buy_dex: str, sell_dex: str) -> dict:
    start_raw = round(START_USDC * 10**USDC_DECIMALS)
    buy = quote(USDC, SOL, start_raw, buy_dex)
    sell = quote(SOL, USDC, buy["out_raw"], sell_dex)

    sol_bought = buy["out_raw"] / 10**SOL_DECIMALS
    final_usdc = sell["out_raw"] / 10**USDC_DECIMALS
    gross_profit = final_usdc - START_USDC
    gross_bps = (final_usdc / START_USDC - 1) * 10000
    stressed_bps = gross_bps - EXECUTION_BUFFER_BPS

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "buy_dex": buy_dex,
        "sell_dex": sell_dex,
        "start_usdc": f"{START_USDC:.6f}",
        "sol_bought": f"{sol_bought:.9f}",
        "final_usdc": f"{final_usdc:.6f}",
        "gross_profit_usdc": f"{gross_profit:.6f}",
        "gross_bps": f"{gross_bps:.3f}",
        "execution_buffer_bps": f"{EXECUTION_BUFFER_BPS:.3f}",
        "stressed_bps": f"{stressed_bps:.3f}",
        "candidate": "YES" if stressed_bps > 0 else "NO",
        "buy_price_impact_pct": f"{buy['price_impact_pct']:.6f}",
        "sell_price_impact_pct": f"{sell['price_impact_pct']:.6f}",
        "buy_latency_ms": f"{buy['latency_ms']:.1f}",
        "sell_latency_ms": f"{sell['latency_ms']:.1f}",
        "buy_route": buy["route"],
        "sell_route": sell["route"],
    }

def main():
    ensure_csv()
    rows = []
    errors = []

    for buy_dex, sell_dex in permutations(DEXES, 2):
        try:
            row = scan_pair(buy_dex, sell_dex)
            append_row(row)
            rows.append(row)
            print(
                f"{buy_dex} -> {sell_dex}: "
                f"{float(row['gross_bps']):+.2f} bps gross, "
                f"{float(row['stressed_bps']):+.2f} bps stressed"
            )
        except Exception as e:
            msg = f"{buy_dex} -> {sell_dex}: {e}"
            errors.append(msg)
            print("ERROR", msg)

    ranked = sorted(rows, key=lambda r: float(r["stressed_bps"]), reverse=True)
    best = ranked[0] if ranked else None
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "paper_read_only",
        "start_usdc": START_USDC,
        "execution_buffer_bps": EXECUTION_BUFFER_BPS,
        "pairs_tested_ok": len(rows),
        "errors": errors,
        "candidate_count": sum(r["candidate"] == "YES" for r in rows),
        "best": best,
        "rows": ranked,
        "warning": "Quoted paper edge is not proof of executable profit."
    }
    LATEST_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if best:
        print(
            f"BEST {best['buy_dex']} -> {best['sell_dex']} "
            f"{float(best['stressed_bps']):+.2f} bps stressed"
        )

if __name__ == "__main__":
    main()
