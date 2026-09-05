#!/usr/bin/env python3
"""
ARBBOT small-capital economics engine.

Turns persistence-board signals into comparable paper economics at several
small capital levels. It penalises strategies that require capital to be split
across two venues/sides.

This is a ranking heuristic, not a profit forecast.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SCOREBOARD = DATA / "scoreboard.json"
OUT = DATA / "capital_rank.json"

BUDGETS = [50, 100, 250, 500]

UTILISATION = {
    "solana_cross_dex": 1.0,
    "cex_triangle": 1.0,
    "eur_triangle": 1.0,
    "stable_eur_dislocation": 1.0,
    "cex_cross_spot": 0.5,
    "eu_cross_spot": 0.5,
    "funding_spread": 0.5,
}

CARRY_PERIODS_PER_DAY = {
    "funding_spread": 3.0,
}

def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not SCOREBOARD.exists():
        OUT.write_text(json.dumps({
            "generated_at_utc": now,
            "ranked": [],
            "reason": "scoreboard missing",
        }, indent=2), encoding="utf-8")
        return

    sb = json.loads(SCOREBOARD.read_text(encoding="utf-8"))
    ranked = []

    for item in sb.get("ranked") or []:
        strategy = item.get("strategy")
        # Only rank strategies whose stored edge is already an executable-style net spread/carry measure.
        # A simple stablecoin deviation from $1 is research context, not by itself a realizable arbitrage.
        if strategy not in UTILISATION:
            continue
        med = max(0.0, float(item.get("median_positive_edge_bps") or 0))
        persistence = max(0.0, min(1.0, float(item.get("persistence") or 0)))
        utilisation = UTILISATION.get(strategy, 0.5)

        economics = {}
        for budget in BUDGETS:
            effective = budget * utilisation
            per_event = effective * med / 10000
            entry = {
                "total_budget": budget,
                "effective_capital_per_edge": round(effective, 2),
                "paper_profit_per_event_at_median_edge": round(per_event, 4),
            }
            if strategy in CARRY_PERIODS_PER_DAY:
                daily = per_event * CARRY_PERIODS_PER_DAY[strategy] * persistence
                entry["paper_daily_carry_if_persistence_continues"] = round(daily, 4)
            economics[str(budget)] = entry

        edge_factor = min(30.0, med) / 30.0
        capital_score = (
            float(item.get("research_score") or 0)
            * persistence
            * (0.25 + 0.75 * edge_factor)
            * utilisation
        )
        ranked.append({
            **item,
            "capital_utilisation": utilisation,
            "capital_efficiency_score": round(capital_score, 2),
            "paper_economics": economics,
        })

    ranked.sort(key=lambda x: (
        x.get("classification") == "strong_watch",
        x.get("classification") == "watch",
        x.get("capital_efficiency_score", 0),
    ), reverse=True)

    OUT.write_text(json.dumps({
        "generated_at_utc": now,
        "budgets": BUDGETS,
        "best": ranked[0] if ranked else None,
        "ranked": ranked,
        "warning": (
            "These are paper arithmetic conversions of observed edge, not expected returns. "
            "Fill probability, fees, slippage, transfer friction and edge decay are not fully captured."
        ),
    }, indent=2), encoding="utf-8")

    if ranked:
        b = ranked[0]
        print(f"BEST CAPITAL-EFFICIENT {b['strategy']} {b['label']} score={b['capital_efficiency_score']:.1f}")
    else:
        print("No ranked opportunities yet.")

if __name__ == "__main__":
    main()
