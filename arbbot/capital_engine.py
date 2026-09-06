#!/usr/bin/env python3
"""
ARBBOT small-capital economics engine.

Turns persistence-board signals into comparable paper economics at several
small capital levels. It penalises strategies that require capital to be split
across two venues/sides and de-prioritises technically positive but economically
trivial candidates for small-capital use.

Funding carry is additionally haircut by a conservative round-trip cost budget
amortised over a fixed holding horizon, so gross funding spreads cannot look
profitable merely because entry/exit friction was omitted.

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

BUDGETS = [25, 50, 100, 250, 500, 1000]
REFERENCE_BUDGET = 250
REFERENCE_PAYOFF_EUR = 0.25

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

# Funding is only credited for small-capital ranking after charging a deliberately
# conservative 30 bps round trip across a seven-day holding horizon (21 x 8h).
# This is an economics haircut, not an execution assumption or live-trading rule.
FUNDING_ROUND_TRIP_COST_BPS = 30.0
FUNDING_HOLD_DAYS = 7.0
FUNDING_PERIODS_PER_DAY = 3.0
FUNDING_HOLD_PERIODS = FUNDING_HOLD_DAYS * FUNDING_PERIODS_PER_DAY
FUNDING_COST_BPS_PER_8H = FUNDING_ROUND_TRIP_COST_BPS / FUNDING_HOLD_PERIODS

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
        if strategy not in UTILISATION:
            continue

        gross_med = max(0.0, float(item.get("median_positive_edge_bps") or 0))
        persistence = max(0.0, min(1.0, float(item.get("persistence") or 0)))
        utilisation = UTILISATION.get(strategy, 0.5)

        if strategy == "funding_spread":
            med = max(0.0, gross_med - FUNDING_COST_BPS_PER_8H)
        else:
            med = gross_med

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
                entry["gross_median_funding_spread_bps_per_8h"] = round(gross_med, 4)
                entry["amortized_round_trip_cost_bps_per_8h"] = round(FUNDING_COST_BPS_PER_8H, 4)
                entry["net_median_funding_spread_bps_per_8h"] = round(med, 4)
            economics[str(budget)] = entry

        edge_factor = min(30.0, med) / 30.0
        capital_score = (
            float(item.get("research_score") or 0)
            * persistence
            * (0.25 + 0.75 * edge_factor)
            * utilisation
        )

        ref = economics[str(REFERENCE_BUDGET)]
        if strategy in CARRY_PERIODS_PER_DAY:
            reference_payoff = float(ref.get("paper_daily_carry_if_persistence_continues") or 0.0)
            reference_basis = "paper_daily_carry_if_persistence_continues_after_cost_haircut"
        else:
            reference_payoff = float(ref.get("paper_profit_per_event_at_median_edge") or 0.0)
            reference_basis = "paper_profit_per_event_at_median_edge"

        relevance_factor = max(0.0, min(1.0, reference_payoff / REFERENCE_PAYOFF_EUR))
        economic_relevance_score = capital_score * relevance_factor

        extra = {}
        if strategy == "funding_spread":
            extra["funding_cost_model"] = {
                "gross_median_spread_bps_per_8h": round(gross_med, 4),
                "round_trip_cost_bps": FUNDING_ROUND_TRIP_COST_BPS,
                "holding_horizon_days": FUNDING_HOLD_DAYS,
                "holding_periods_8h": FUNDING_HOLD_PERIODS,
                "amortized_cost_bps_per_8h": round(FUNDING_COST_BPS_PER_8H, 4),
                "net_median_spread_bps_per_8h": round(med, 4),
                "survives_cost_haircut": med > 0,
            }

        ranked.append({
            **item,
            **extra,
            "capital_utilisation": utilisation,
            "capital_efficiency_score": round(capital_score, 2),
            "economic_relevance_score": round(economic_relevance_score, 2),
            "economic_relevance": {
                "reference_budget_eur": REFERENCE_BUDGET,
                "reference_basis": reference_basis,
                "reference_payoff_eur": round(reference_payoff, 4),
                "reference_target_eur": REFERENCE_PAYOFF_EUR,
                "relevance_factor": round(relevance_factor, 4),
                "economically_material_at_reference_budget": reference_payoff >= REFERENCE_PAYOFF_EUR,
            },
            "paper_economics": economics,
        })

    ranked.sort(key=lambda x: (
        x.get("classification") == "strong_watch",
        x.get("classification") == "watch",
        x.get("economic_relevance_score", 0),
        x.get("capital_efficiency_score", 0),
    ), reverse=True)

    OUT.write_text(json.dumps({
        "generated_at_utc": now,
        "budgets": BUDGETS,
        "reference_budget_eur": REFERENCE_BUDGET,
        "reference_payoff_eur": REFERENCE_PAYOFF_EUR,
        "funding_cost_model": {
            "round_trip_cost_bps": FUNDING_ROUND_TRIP_COST_BPS,
            "holding_horizon_days": FUNDING_HOLD_DAYS,
            "amortized_cost_bps_per_8h": round(FUNDING_COST_BPS_PER_8H, 4),
        },
        "best": ranked[0] if ranked else None,
        "ranked": ranked,
        "warning": (
            "These are conservative paper arithmetic conversions, not expected returns. "
            "Funding carry is haircut by an amortized round-trip cost assumption. "
            "Fill probability, basis moves, funding changes, liquidation, slippage, transfer friction, "
            "latency, collateral and venue risk still require separate validation."
        ),
    }, indent=2), encoding="utf-8")

    if ranked:
        b = ranked[0]
        print(
            f"BEST SMALL-CAPITAL {b['strategy']} {b['label']} "
            f"relevance={b['economic_relevance_score']:.1f} "
            f"capital={b['capital_efficiency_score']:.1f}"
        )
    else:
        print("No ranked opportunities yet.")

if __name__ == "__main__":
    main()
