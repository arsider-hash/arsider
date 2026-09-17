#!/usr/bin/env python3
"""ARBBOT EUR100/month feasibility challenge.

Research/accounting only. It asks whether the evidence demonstrates the user's
operational target with ONE chronological EUR250 capital pool. Planning run-rates
remain visible, but only the shared capital scheduler can prove the target.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RANK = DATA / "capital_rank.json"
SHADOW = DATA / "shadow_summary.json"
SCHEDULE = DATA / "capital_schedule.json"
HABITATS = DATA / "habitat_board.json"
OUT = DATA / "target_100.json"

STARTING_CAPITAL_EUR = 250.0
TARGET_NET_EUR_MONTH = 100.0
TARGET_HUMAN_MINUTES_MONTH = 60
PREFERRED_MAX_VENUES = 2
HARD_MAX_VENUES_WITH_JUSTIFICATION = 3
MIN_PROOF_SPAN_DAYS = 29.0


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rank = load(RANK)
    shadow = load(SHADOW)
    schedule = load(SCHEDULE)
    habitats = load(HABITATS)
    survivors = rank.get("ranked") or []

    evidence_shadow_pnl = sum(
        float(x.get("cumulative_paper_pnl") or 0.0)
        for x in (shadow.get("ranked") or [])
    )

    best = survivors[0] if survivors else None
    planning_run_rate = None
    if best:
        lens = best.get("monthly_income_lens") or {}
        b250 = (lens.get("by_budget") or {}).get("250") or {}
        planning_run_rate = b250.get("paper_monthly_run_rate_if_persistence_continues")

    best_plan = schedule.get("best_plan") or None
    span_days = float(schedule.get("proof_window_span_days") or 0.0)
    proof_net = float((best_plan or {}).get("net_eur") or 0.0)
    proof_human = float((best_plan or {}).get("human_minutes") or 0.0)
    proof_venues = int((best_plan or {}).get("venue_count") or 0)
    proof_events = int((best_plan or {}).get("accepted_events") or 0)

    has_full_window = (
        schedule.get("status") == "SIMULATED"
        and best_plan is not None
        and proof_events > 0
        and span_days >= MIN_PROOF_SPAN_DAYS
    )

    feasibility_pct = round(100.0 * proof_net / TARGET_NET_EUR_MONTH, 2) if has_full_window else None
    demonstrated = (
        has_full_window
        and proof_net >= TARGET_NET_EUR_MONTH
        and proof_human <= TARGET_HUMAN_MINUTES_MONTH
        and proof_venues <= HARD_MAX_VENUES_WITH_JUSTIFICATION
    )

    missing = []
    if not has_full_window:
        missing.append(
            "rolling ~30-day chronological executable-shadow evidence using the same EUR250 pool"
        )
    if schedule.get("status") in {None, "NO_EXECUTABLE_EVENTS"}:
        missing.append(
            "normalized executable-shadow opportunity events with venue pre-allocation and lock/release time"
        )
    if best_plan is None:
        missing.append("a feasible static pre-allocation plan within EUR250")
    if has_full_window and proof_human > TARGET_HUMAN_MINUTES_MONTH:
        missing.append("human intervention time <=60 minutes/month")
    if has_full_window and proof_venues > HARD_MAX_VENUES_WITH_JUSTIFICATION:
        missing.append("venue/account count within the <=3 hard limit")
    if has_full_window and proof_net < TARGET_NET_EUR_MONTH:
        missing.append(f"another EUR {round(TARGET_NET_EUR_MONTH - proof_net, 2)} NET inside the same proof window")

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
        "status": "DEMONSTRATED" if demonstrated else "NOT_DEMONSTRATED",
        "feasibility_pct": feasibility_pct,
        "feasibility_basis": (
            "actual chronological shadow NET from the best static pre-allocation of one EUR250 pool"
            if feasibility_pct is not None
            else "withheld until a near-30-day chronological capital-scheduler window exists"
        ),
        "capital_scheduler_proof": {
            "status": schedule.get("status") or "NOT_RUN",
            "proof_window_span_days": span_days,
            "best_plan": best_plan,
        },
        "habitat_board": habitats.get("habitats") or [],
        "best_current_killer_survivor": best,
        "best_planning_run_rate_eur_month_at_250": planning_run_rate,
        "all_time_accepted_shadow_pnl_eur_not_monthly_comparable": round(evidence_shadow_pnl, 6),
        "missing_proof": missing,
        "success_rule": (
            "DEMONSTRATED only when a near-30-day chronological executable-shadow simulation with one EUR250 pool "
            "shows >=EUR100 NET after modeled costs, while respecting static venue pre-allocation, overlapping "
            "capital locks/release time, all KILLER gates, <=3 venues with the third materially justified, and "
            "<=60 measured human minutes/month."
        ),
        "safety": "Research/shadow accounting only; no custody, signing, orders, transfers or live trading.",
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"EUR100 challenge: {payload['status']} feasibility={feasibility_pct} "
        f"proof_net={proof_net} span_days={span_days}"
    )


if __name__ == "__main__":
    main()
