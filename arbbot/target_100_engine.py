#!/usr/bin/env python3
"""ARBBOT EUR100/month feasibility challenge.

This is a research/accounting layer only. It never trades or moves funds.
It asks whether the existing evidence actually demonstrates the user's target:
EUR250 starting capital -> EUR100 NET/month, with minimal venue fragmentation
and little human work. Unknown operational inputs stay unknown rather than being
filled with optimistic assumptions.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RANK = DATA / "capital_rank.json"
SHADOW = DATA / "shadow_summary.json"
OUT = DATA / "target_100.json"

STARTING_CAPITAL_EUR = 250.0
TARGET_NET_EUR_MONTH = 100.0
TARGET_HUMAN_MINUTES_MONTH = 60
PREFERRED_MAX_VENUES = 2
HARD_MAX_VENUES_WITH_JUSTIFICATION = 3


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rank = load(RANK)
    shadow = load(SHADOW)
    survivors = rank.get("ranked") or []

    # Shadow PnL is deliberately not annualised/monthly-scaled here. The current
    # ledger does not yet model chronological capital conflicts, capital recycle
    # time, venue pre-allocation or human interventions. Scaling it would create
    # exactly the false confidence this challenge is intended to prevent.
    evidence_shadow_pnl = sum(float(x.get("cumulative_paper_pnl") or 0.0) for x in (shadow.get("ranked") or []))

    best = survivors[0] if survivors else None
    planning_run_rate = None
    if best:
        lens = best.get("monthly_income_lens") or {}
        b250 = (lens.get("by_budget") or {}).get("250") or {}
        planning_run_rate = b250.get("paper_monthly_run_rate_if_persistence_continues")

    missing = [
        "30-day chronological executable shadow ledger using the same EUR250 capital pool",
        "capital lock/release timestamps and measured recycle time",
        "venue-specific minimum pre-allocation and idle-capital accounting",
        "capital-conflict handling when opportunities overlap",
        "measured human interventions/minutes per month",
        "deposit/conversion/rebalance/withdrawal friction where applicable",
    ]

    payload = {
        "generated_at_utc": now,
        "challenge": {
            "starting_capital_eur": STARTING_CAPITAL_EUR,
            "target_net_eur_per_month": TARGET_NET_EUR_MONTH,
            "target_return_on_starting_capital_pct_per_month": round(100 * TARGET_NET_EUR_MONTH / STARTING_CAPITAL_EUR, 2),
            "target_human_minutes_per_month_max": TARGET_HUMAN_MINUTES_MONTH,
            "preferred_max_venues": PREFERRED_MAX_VENUES,
            "hard_max_venues_only_if_materially_justified": HARD_MAX_VENUES_WITH_JUSTIFICATION,
        },
        "status": "NOT_DEMONSTRATED",
        "best_current_killer_survivor": best,
        "best_planning_run_rate_eur_month_at_250": planning_run_rate,
        "all_time_accepted_shadow_pnl_eur_not_monthly_comparable": round(evidence_shadow_pnl, 6),
        "feasibility_pct": None,
        "why_no_feasibility_pct": "A percentage would be misleading until shadow execution shares one chronological EUR250 pool and measures recycle/pre-allocation/human time.",
        "missing_proof": missing,
        "success_rule": (
            "DEMONSTRATED only after a rolling 30-day executable shadow simulation with one EUR250 pool "
            "shows >= EUR100 NET after modeled costs, while respecting venue/pre-allocation constraints, "
            "capital conflicts/recycle time, all KILLER gates, and <=60 measured human minutes/month."
        ),
        "safety": "Research/shadow accounting only; no custody, signing, orders, transfers or live trading.",
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"EUR100 challenge: {payload['status']} planning_run_rate={planning_run_rate}")


if __name__ == "__main__":
    main()
