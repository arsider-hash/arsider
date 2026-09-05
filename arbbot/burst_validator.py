#!/usr/bin/env python3
"""
ARBBOT burst validator.

When the decision engine promotes a fast market-structure signal to VALIDATE
or READY_FOR_MANUAL_AUTHORIZATION, rechecks that exact route several times
over roughly one minute. This rejects edges that exist for one API snapshot
but vanish immediately.

Read-only. No credentials, orders or funds.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import cex_market_scout as cex
import eu_cex_scout as eu

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DECISION = DATA / "decision.json"
OUT = DATA / "validation.json"

SAMPLES = 6
PAUSE_SECONDS = 8

FAST_STRATEGIES = {
    "cex_cross_spot",
    "cex_triangle",
    "stable_dislocation",
    "eu_cross_spot",
    "eur_triangle",
    "stable_eur_dislocation",
}

def collect_strategy(strategy: str):
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if strategy == "cex_cross_spot":
        return cex.cross_exchange_spot(ts, {})
    if strategy == "cex_triangle":
        return cex.triangles(ts, {})
    if strategy == "stable_dislocation":
        return cex.stablecoin_rows(ts, {})
    if strategy == "eu_cross_spot":
        return eu.cross_spot(ts, {})
    if strategy == "eur_triangle":
        rows = []
        cache = {}
        for asset in eu.ASSETS:
            try:
                rows.extend(eu.coinbase_triangle(ts, asset, cache))
            except Exception:
                pass
            try:
                rows.extend(eu.kraken_triangle(ts, asset, cache))
            except Exception:
                pass
        return rows
    if strategy == "stable_eur_dislocation":
        return eu.stable_eur(ts, {})
    return []

def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not DECISION.exists():
        OUT.write_text(json.dumps({
            "generated_at_utc": now,
            "state": "SKIP",
            "reason": "decision file missing",
        }, indent=2), encoding="utf-8")
        return

    d = json.loads(DECISION.read_text(encoding="utf-8"))
    state = d.get("state")
    selected = d.get("selected") or {}
    strategy = selected.get("strategy")
    label = selected.get("label")

    if state not in {"VALIDATE", "READY_FOR_MANUAL_AUTHORIZATION"}:
        OUT.write_text(json.dumps({
            "generated_at_utc": now,
            "state": "SKIP",
            "reason": f"decision state is {state}",
            "selected": selected,
        }, indent=2), encoding="utf-8")
        print("Burst validation skipped: decision not promoted.")
        return

    if strategy not in FAST_STRATEGIES:
        OUT.write_text(json.dumps({
            "generated_at_utc": now,
            "state": "NOT_APPLICABLE",
            "reason": f"{strategy} is not a sub-minute edge; persistence history is the relevant validator",
            "selected": selected,
        }, indent=2), encoding="utf-8")
        print("Burst validation not applicable.")
        return

    samples = []
    for i in range(SAMPLES):
        try:
            rows = collect_strategy(strategy)
            match = next((r for r in rows if r.get("key") == label), None)
            if match:
                edge = float(match.get("stressed_bps") or 0)
                samples.append({
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "stressed_bps": edge,
                    "candidate": edge > 0,
                })
            else:
                samples.append({
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "error": "selected route not returned",
                })
        except Exception as exc:
            samples.append({
                "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "error": str(exc),
            })
        if i < SAMPLES - 1:
            time.sleep(PAUSE_SECONDS)

    edges = [x["stressed_bps"] for x in samples if "stressed_bps" in x]
    positives = [x for x in edges if x > 0]
    survival = len(positives) / len(edges) if edges else 0.0
    med = median(edges) if edges else None

    verdict = "FAIL"
    if len(edges) >= 4 and survival >= 0.80 and med is not None and med > 0:
        verdict = "SURVIVES_BURST"
    elif len(edges) >= 3 and survival >= 0.50 and med is not None and med > 0:
        verdict = "MARGINAL"

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selected": selected,
        "sample_count": len(samples),
        "valid_edge_samples": len(edges),
        "positive_samples": len(positives),
        "survival_rate": round(survival, 4),
        "median_stressed_bps": None if med is None else round(med, 4),
        "min_stressed_bps": None if not edges else round(min(edges), 4),
        "max_stressed_bps": None if not edges else round(max(edges), 4),
        "verdict": verdict,
        "samples": samples,
        "warning": "Burst survival is necessary for fast arbitrage but still does not prove fillable profit.",
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"BURST {verdict} survival={survival:.0%} median={med}")

if __name__ == "__main__":
    main()
