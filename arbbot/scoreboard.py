#!/usr/bin/env python3
"""
ARBBOT persistence scoreboard.

Rejects one-off quote noise and ranks repeated paper signals over a rolling
window. Sources currently include global CEX, EU CEX, Solana and funding.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "scoreboard.json"
LOOKBACK_HOURS = 48

def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def pct(xs, p):
    if not xs:
        return None
    ys = sorted(xs)
    idx = min(len(ys) - 1, max(0, round((len(ys) - 1) * p)))
    return ys[idx]

def load_generic_history(filename, cutoff):
    path = DATA / filename
    groups = defaultdict(list)
    if not path.exists():
        return groups
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts = parse_ts(r.get("timestamp_utc", ""))
            if not ts or ts < cutoff:
                continue
            strategy = r.get("strategy", "")
            if not strategy or strategy.endswith("_error"):
                continue
            try:
                edge = float(r["stressed_bps"])
            except Exception:
                continue
            label = r.get("key") or "?"
            groups[f"{strategy}|{label}"].append({
                "ts": ts,
                "edge": edge,
                "candidate": r.get("candidate") == "YES",
                "strategy": strategy,
                "label": label,
                "direction": r.get("direction", ""),
                "venue": r.get("venue", ""),
            })
    return groups

def load_solana(cutoff):
    path = DATA / "history.csv"
    groups = defaultdict(list)
    if not path.exists():
        return groups
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts = parse_ts(r.get("timestamp_utc", ""))
            if not ts or ts < cutoff:
                continue
            try:
                edge = float(r["stressed_bps"])
            except Exception:
                continue
            label = f"{r.get('buy_dex','?')}->{r.get('sell_dex','?')}"
            groups[f"solana_cross_dex|{label}"].append({
                "ts": ts,
                "edge": edge,
                "candidate": r.get("candidate") == "YES",
                "strategy": "solana_cross_dex",
                "label": label,
                "direction": label,
                "venue": "Solana",
            })
    return groups

def load_funding(cutoff):
    path = DATA / "funding_history.csv"
    groups = defaultdict(list)
    if not path.exists():
        return groups
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts = parse_ts(r.get("timestamp_utc", ""))
            if not ts or ts < cutoff:
                continue
            try:
                edge = abs(float(r["spread_bps_per_8h"]))
            except Exception:
                continue
            label = r.get("symbol", "?")
            groups[f"funding_spread|{label}"].append({
                "ts": ts,
                "edge": edge,
                "candidate": r.get("candidate") == "YES",
                "strategy": "funding_spread",
                "label": label,
                "direction": r.get("direction", ""),
                "venue": "Binance<->Bybit",
            })
    return groups

def score_group(key, obs):
    obs = sorted(obs, key=lambda x: x["ts"])
    xs = [x["edge"] for x in obs]
    positives = [x for x in obs if x["candidate"] and x["edge"] > 0]
    positive_edges = [x["edge"] for x in positives]
    persistence = len(positives) / len(obs) if obs else 0

    repeated = len(obs) >= 4 and len(positives) >= 3
    med = median(positive_edges) if positive_edges else 0.0
    p90 = pct(positive_edges, 0.90) or 0.0

    magnitude = min(1.0, max(0.0, med) / 20.0)
    sample = min(1.0, len(obs) / 12.0)
    research_score = 100 * (0.55 * persistence + 0.25 * magnitude + 0.20 * sample)

    latest = obs[-1]
    classification = "noise"
    if repeated and persistence >= 0.70 and med > 0:
        classification = "strong_watch"
    elif repeated and persistence >= 0.40 and med > 0:
        classification = "watch"

    return {
        "key": key,
        "strategy": latest["strategy"],
        "label": latest["label"],
        "direction": latest["direction"],
        "venue": latest["venue"],
        "observations": len(obs),
        "positive_observations": len(positives),
        "persistence": round(persistence, 4),
        "median_positive_edge_bps": round(med, 4),
        "p90_positive_edge_bps": round(p90, 4),
        "max_edge_bps": round(max(xs), 4) if xs else None,
        "latest_edge_bps": round(latest["edge"], 4),
        "research_score": round(research_score, 2),
        "classification": classification,
        "last_seen_utc": latest["ts"].isoformat(),
    }

def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)

    merged = defaultdict(list)
    sources = [
        load_generic_history("market_history.csv", cutoff),
        load_generic_history("eu_history.csv", cutoff),
        load_solana(cutoff),
        load_funding(cutoff),
    ]
    for source in sources:
        for k, v in source.items():
            merged[k].extend(v)

    ranked = [score_group(k, v) for k, v in merged.items()]
    ranked.sort(
        key=lambda x: (
            x["classification"] == "strong_watch",
            x["classification"] == "watch",
            x["research_score"],
        ),
        reverse=True,
    )

    out = {
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "lookback_hours": LOOKBACK_HOURS,
        "strong_watch_count": sum(x["classification"] == "strong_watch" for x in ranked),
        "watch_count": sum(x["classification"] == "watch" for x in ranked),
        "best": ranked[0] if ranked else None,
        "ranked": ranked,
        "interpretation": (
            "This is a noise-rejection research score, not a forecast or guarantee. "
            "Only repeated signals are promoted. Live profitability still requires "
            "execution-specific fee, slippage, latency, capital and risk validation."
        ),
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    if ranked:
        b = ranked[0]
        print(
            f"BEST {b['classification']} {b['key']} "
            f"score={b['research_score']:.1f} persistence={b['persistence']:.2f}"
        )
    else:
        print("No history yet.")

if __name__ == "__main__":
    main()
