#!/usr/bin/env python3
"""
ARBBOT decision engine.

Purpose:
- read the persistence scoreboard
- select exactly one best research candidate
- return WAIT / VALIDATE / READY_FOR_MANUAL_AUTHORIZATION
- never place orders, sign transactions, access wallets, or use trading credentials

This is a rules engine for research triage, not a discretionary portfolio manager.
"""

from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SCOREBOARD = DATA / "scoreboard.json"
OUT = DATA / "decision.json"

# Strategy-specific minimums. These are deliberately conservative research gates.
POLICY = {
    "solana_cross_dex": {
        "min_observations": 8,
        "min_persistence": 0.75,
        "min_median_edge_bps": 8.0,
        "min_research_score": 70.0,
    },
    "cex_cross_spot": {
        "min_observations": 8,
        "min_persistence": 0.75,
        "min_median_edge_bps": 10.0,
        "min_research_score": 72.0,
    },
    "cex_triangle": {
        "min_observations": 8,
        "min_persistence": 0.75,
        "min_median_edge_bps": 8.0,
        "min_research_score": 72.0,
    },
    "funding_spread": {
        "min_observations": 6,
        "min_persistence": 0.70,
        "min_median_edge_bps": 2.0,
        "min_research_score": 65.0,
    },
    "spot_perp_basis": {
        "min_observations": 6,
        "min_persistence": 0.70,
        "min_median_edge_bps": 15.0,
        "min_research_score": 65.0,
    },
    "stable_dislocation": {
        "min_observations": 6,
        "min_persistence": 0.70,
        "min_median_edge_bps": 8.0,
        "min_research_score": 68.0,
    },
}

def classify(item: dict) -> tuple[str, list[str]]:
    strategy = item.get("strategy")
    rules = POLICY.get(strategy)
    reasons = []

    if not rules:
        return "WAIT", [f"unsupported strategy: {strategy}"]

    obs = int(item.get("observations") or 0)
    persistence = float(item.get("persistence") or 0)
    med = float(item.get("median_positive_edge_bps") or 0)
    score = float(item.get("research_score") or 0)
    classification = item.get("classification")

    checks = [
        (classification == "strong_watch", "scoreboard has not promoted this to strong_watch"),
        (obs >= rules["min_observations"], f"only {obs} observations, need {rules['min_observations']}"),
        (persistence >= rules["min_persistence"], f"persistence {persistence:.2f} below {rules['min_persistence']:.2f}"),
        (med >= rules["min_median_edge_bps"], f"median edge {med:.2f} bps below {rules['min_median_edge_bps']:.2f} bps"),
        (score >= rules["min_research_score"], f"research score {score:.1f} below {rules['min_research_score']:.1f}"),
    ]

    failed = [reason for ok, reason in checks if not ok]

    if not failed:
        return "READY_FOR_MANUAL_AUTHORIZATION", []

    # If it is already a repeated watch but not yet strong enough, move to validation.
    if classification in {"watch", "strong_watch"} and obs >= max(3, rules["min_observations"] // 2):
        return "VALIDATE", failed

    return "WAIT", failed

def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not SCOREBOARD.exists():
        payload = {
            "generated_at_utc": now,
            "state": "WAIT",
            "reason": "scoreboard not available yet",
            "selected": None,
            "next_action": "collect more paper observations",
        }
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("WAIT: scoreboard not available")
        return

    sb = json.loads(SCOREBOARD.read_text(encoding="utf-8"))
    ranked = sb.get("ranked") or []

    if not ranked:
        payload = {
            "generated_at_utc": now,
            "state": "WAIT",
            "reason": "no candidates in rolling history",
            "selected": None,
            "next_action": "collect more paper observations",
        }
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("WAIT: no candidates")
        return

    # Choose exactly one candidate: the top-ranked item from the scoreboard.
    selected = ranked[0]
    state, failed = classify(selected)

    if state == "WAIT":
        next_action = "keep collecting data; no user action"
    elif state == "VALIDATE":
        next_action = (
            "build/refresh an execution-specific paper validator for this single strategy; "
            "still no money and no credentials"
        )
    else:
        next_action = (
            "prepare one capped live-test plan for user authorization; "
            "do not move funds or place orders without explicit authorization"
        )

    payload = {
        "generated_at_utc": now,
        "state": state,
        "selected": selected,
        "failed_gates": failed,
        "policy": POLICY.get(selected.get("strategy"), {}),
        "next_action": next_action,
        "hard_boundary": (
            "ARBBOT may research, rank and prepare a test plan. "
            "It must not custody funds, sign transactions, place orders, "
            "or enable live trading without explicit user authorization."
        ),
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"{state}: {selected.get('strategy')} {selected.get('label')}")

if __name__ == "__main__":
    main()
