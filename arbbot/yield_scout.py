#!/usr/bin/env python3
"""
ARBBOT stable-yield subsidy radar.

Uses public DeFiLlama yield data to identify large stablecoin pools where
yield appears to come from base lending/fees and/or explicit incentives.

This is read-only research. It does not deposit funds or recommend that a
protocol is safe. High APY is treated as a risk signal, not free money.
"""

from __future__ import annotations

import csv
import json
import math
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
LATEST = DATA / "yield_latest.json"
HISTORY = DATA / "yield_history.csv"

MIN_TVL = 20_000_000
MAX_APY = 20.0
MAX_ROWS = 30

PREFERRED_CHAINS = {"Ethereum", "Base", "Arbitrum", "Optimism", "Solana"}
PREFERRED_PROJECT_HINTS = (
    "aave", "compound", "spark", "sky", "morpho", "kamino",
    "fluid", "euler", "curve", "maker"
)

FIELDS = [
    "timestamp_utc", "pool", "chain", "project", "symbol", "tvl_usd",
    "apy", "apy_base", "apy_reward", "score", "candidate"
]

def get_json(url: str):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "arsider-arbbot/0.5",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def safe_float(v, default=0.0):
    try:
        if v is None:
            return default
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default

def project_ok(name: str) -> bool:
    low = (name or "").lower()
    return any(h in low for h in PREFERRED_PROJECT_HINTS)

def score_pool(p):
    tvl = safe_float(p.get("tvlUsd"))
    apy = safe_float(p.get("apy"))
    reward = safe_float(p.get("apyReward"))
    apy_mean_30d = safe_float(p.get("apyMean30d"), apy)

    tvl_score = min(1.0, max(0.0, (math.log10(max(tvl, 1)) - 7.0) / 3.0))
    yield_score = min(1.0, max(0.0, min(apy, 12.0) / 12.0))
    persistence = 1.0 - min(1.0, abs(apy - apy_mean_30d) / max(abs(apy_mean_30d), 1.0))
    reward_share = reward / max(apy, 0.0001) if apy > 0 else 0
    quality = 0.40 * tvl_score + 0.25 * yield_score + 0.25 * persistence + 0.10 * (1 - min(1.0, reward_share))
    return round(100 * quality, 2)

def main():
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    raw = get_json("https://yields.llama.fi/pools")
    pools = raw.get("data") or []

    selected = []
    for p in pools:
        if not p.get("stablecoin"):
            continue
        chain = p.get("chain") or ""
        project = p.get("project") or ""
        if chain not in PREFERRED_CHAINS or not project_ok(project):
            continue

        tvl = safe_float(p.get("tvlUsd"))
        apy = safe_float(p.get("apy"))
        if tvl < MIN_TVL or apy <= 0 or apy > MAX_APY:
            continue

        row = {
            "timestamp_utc": ts,
            "pool": str(p.get("pool") or ""),
            "chain": chain,
            "project": project,
            "symbol": p.get("symbol") or "",
            "tvl_usd": tvl,
            "apy": apy,
            "apy_base": safe_float(p.get("apyBase")),
            "apy_reward": safe_float(p.get("apyReward")),
            "score": score_pool(p),
        }
        row["candidate"] = "YES" if row["score"] >= 65 and tvl >= 50_000_000 else "NO"
        selected.append(row)

    selected.sort(key=lambda x: (x["score"], x["tvl_usd"]), reverse=True)
    selected = selected[:MAX_ROWS]

    if not HISTORY.exists():
        with HISTORY.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerows(selected)

    payload = {
        "generated_at_utc": ts,
        "mode": "read_only_research",
        "filters": {
            "min_tvl_usd": MIN_TVL,
            "max_apy_pct": MAX_APY,
            "preferred_chains": sorted(PREFERRED_CHAINS),
        },
        "best": selected[0] if selected else None,
        "rows": selected,
        "warning": (
            "Yield is not arbitrage and is not guaranteed. Smart-contract, oracle, "
            "liquidity, stablecoin, governance and regulatory risks can cause losses."
        ),
    }
    LATEST.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if selected:
        b = selected[0]
        print(f"BEST {b['project']} {b['symbol']} APY={b['apy']:.2f}% TVL=${b['tvl_usd']:,.0f} score={b['score']}")
    else:
        print("No pools passed filters.")

if __name__ == "__main__":
    main()
