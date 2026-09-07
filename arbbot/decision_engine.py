#!/usr/bin/env python3
"""
ARBBOT decision engine.

Selects one best research candidate, biased toward small-capital efficiency,
and returns WAIT / VALIDATE / READY_FOR_MANUAL_AUTHORIZATION.

Fast arbitrage strategies cannot reach READY unless execution validators pass,
the adversarial KILLER reports SURVIVES_KILLER for the same route, and shadow
canaries are positive. Funding spreads additionally require the dedicated
funding KILLER to survive for the same symbol and direction.

READY is intentionally short-lived for manual authorization: the selected
candidate must be no more than five minutes old, and every READY payload carries
an explicit expiry timestamp. A stale static decision file must therefore never
be interpreted as a current authorization signal.

No orders, signing, wallets or trading credentials.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SCOREBOARD = DATA / "scoreboard.json"
CAPITAL_RANK = DATA / "capital_rank.json"
VALIDATION = DATA / "validation.json"
DEPTH_VALIDATION = DATA / "depth_validation.json"
KILLER_REPORT = DATA / "killer_report.json"
KILLER_FUNDING_REPORT = DATA / "killer_funding_report.json"
SHADOW_SUMMARY = DATA / "shadow_summary.json"
OUT = DATA / "decision.json"

MANUAL_AUTH_MAX_AGE_SECONDS = 300

POLICY = {
    "solana_cross_dex": {
        "min_observations": 8, "min_persistence": 0.75,
        "min_median_edge_bps": 8.0, "min_research_score": 70.0,
    },
    "cex_cross_spot": {
        "min_observations": 8, "min_persistence": 0.75,
        "min_median_edge_bps": 10.0, "min_research_score": 72.0,
    },
    "eu_cross_spot": {
        "min_observations": 8, "min_persistence": 0.75,
        "min_median_edge_bps": 12.0, "min_research_score": 72.0,
    },
    "cex_triangle": {
        "min_observations": 8, "min_persistence": 0.75,
        "min_median_edge_bps": 8.0, "min_research_score": 72.0,
    },
    "eur_triangle": {
        "min_observations": 8, "min_persistence": 0.75,
        "min_median_edge_bps": 10.0, "min_research_score": 72.0,
    },
    "funding_spread": {
        "min_observations": 6, "min_persistence": 0.70,
        "min_median_edge_bps": 2.0, "min_research_score": 65.0,
    },
    "stable_dislocation": {
        "min_observations": 6, "min_persistence": 0.70,
        "min_median_edge_bps": 8.0, "min_research_score": 68.0,
    },
    "stable_eur_dislocation": {
        "min_observations": 6, "min_persistence": 0.70,
        "min_median_edge_bps": 8.0, "min_research_score": 68.0,
    },
}

FAST_STRATEGIES = {
    "cex_cross_spot", "eu_cross_spot",
    "cex_triangle", "eur_triangle",
    "stable_dislocation", "stable_eur_dislocation",
}


def parse_ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def candidate_age_seconds(selected, now_dt=None):
    now_dt = now_dt or datetime.now(timezone.utc)
    seen = parse_ts(selected.get("last_seen_utc"))
    if not seen:
        return None
    return max(0.0, (now_dt - seen).total_seconds())


def load_ranked():
    if CAPITAL_RANK.exists():
        try:
            d = json.loads(CAPITAL_RANK.read_text(encoding="utf-8"))
            ranked = d.get("ranked") or []
            if ranked:
                return ranked, "capital_rank"
        except Exception:
            pass
    if SCOREBOARD.exists():
        d = json.loads(SCOREBOARD.read_text(encoding="utf-8"))
        return d.get("ranked") or [], "scoreboard"
    return [], "none"


def validation_passes(selected):
    strategy = selected.get("strategy")

    if strategy in FAST_STRATEGIES:
        if not VALIDATION.exists():
            return False, "no burst validation yet"
        try:
            v = json.loads(VALIDATION.read_text(encoding="utf-8"))
        except Exception:
            return False, "invalid burst validation file"
        same = (
            (v.get("selected") or {}).get("strategy") == strategy
            and (v.get("selected") or {}).get("label") == selected.get("label")
        )
        if not same:
            return False, "burst validation belongs to another route"
        if v.get("verdict") != "SURVIVES_BURST":
            return False, f"burst verdict is {v.get('verdict')}"

    if strategy in {"cex_cross_spot", "eu_cross_spot"}:
        if not DEPTH_VALIDATION.exists():
            return False, "no depth validation yet"
        try:
            dv = json.loads(DEPTH_VALIDATION.read_text(encoding="utf-8"))
        except Exception:
            return False, "invalid depth validation file"
        same = (
            (dv.get("selected") or {}).get("strategy") == strategy
            and (dv.get("selected") or {}).get("label") == selected.get("label")
        )
        if not same:
            return False, "depth validation belongs to another route"
        if dv.get("state") != "PASS":
            return False, f"depth verdict is {dv.get('state')}"

    return True, "execution_validation_passed"


def report_matches_selected(report, selected):
    reported = report.get("selected") or {}
    return (
        reported.get("strategy") == selected.get("strategy")
        and reported.get("label") == selected.get("label")
        and reported.get("direction") == selected.get("direction")
    )


def killer_passes(selected):
    if not KILLER_REPORT.exists():
        return False, "no killer report yet"
    try:
        k = json.loads(KILLER_REPORT.read_text(encoding="utf-8"))
    except Exception:
        return False, "invalid killer report"
    if not report_matches_selected(k, selected):
        return False, "killer report belongs to another route or direction"
    verdict = k.get("verdict")
    if verdict != "SURVIVES_KILLER":
        return False, f"killer verdict is {verdict}"

    if selected.get("strategy") == "funding_spread":
        if not KILLER_FUNDING_REPORT.exists():
            return False, "no dedicated funding killer report yet"
        try:
            fk = json.loads(KILLER_FUNDING_REPORT.read_text(encoding="utf-8"))
        except Exception:
            return False, "invalid dedicated funding killer report"
        if not report_matches_selected(fk, selected):
            return False, "funding killer report belongs to another route or direction"
        funding_verdict = fk.get("verdict")
        if funding_verdict != "SURVIVES_KILLER":
            return False, f"funding killer verdict is {funding_verdict}"

    return True, "killer_survived"


def shadow_passes(selected):
    if not SHADOW_SUMMARY.exists():
        return False, "no shadow canaries yet"
    try:
        s = json.loads(SHADOW_SUMMARY.read_text(encoding="utf-8"))
    except Exception:
        return False, "invalid shadow summary"
    key = f"{selected.get('strategy')}|{selected.get('label')}"
    item = next((x for x in (s.get("ranked") or []) if x.get("key") == key), None)
    if not item:
        return False, "no shadow history for selected route"
    count = int(item.get("count") or 0)
    positive_rate = float(item.get("positive_rate") or 0)
    cumulative = float(item.get("cumulative_paper_pnl") or 0)
    if count < 3:
        return False, f"only {count} shadow canaries; need 3"
    if positive_rate < 0.67:
        return False, f"shadow positive rate {positive_rate:.2f} below 0.67"
    if cumulative <= 0:
        return False, "shadow cumulative PnL is not positive"
    return True, "shadow_canaries_passed"


def classify(item):
    strategy = item.get("strategy")
    rules = POLICY.get(strategy)
    if not rules:
        return "WAIT", [f"unsupported strategy: {strategy}"]

    obs = int(item.get("observations") or 0)
    persistence = float(item.get("persistence") or 0)
    med = float(item.get("median_positive_edge_bps") or 0)
    score = float(item.get("research_score") or 0)
    classification = item.get("classification")

    checks = [
        (classification == "strong_watch", "not strong_watch yet"),
        (obs >= rules["min_observations"], f"only {obs} observations; need {rules['min_observations']}"),
        (persistence >= rules["min_persistence"], f"persistence {persistence:.2f} below {rules['min_persistence']:.2f}"),
        (med >= rules["min_median_edge_bps"], f"median edge {med:.2f} bps below {rules['min_median_edge_bps']:.2f}"),
        (score >= rules["min_research_score"], f"research score {score:.1f} below {rules['min_research_score']:.1f}"),
    ]
    failed = [reason for ok, reason in checks if not ok]

    if not failed:
        exec_ok, exec_reason = validation_passes(item)
        if not exec_ok:
            return "VALIDATE", [exec_reason]
        killer_ok, killer_reason = killer_passes(item)
        if not killer_ok:
            return "VALIDATE", [killer_reason]
        shadow_ok, shadow_reason = shadow_passes(item)
        if not shadow_ok:
            return "VALIDATE", [shadow_reason]
        age = candidate_age_seconds(item)
        if age is None:
            return "VALIDATE", ["candidate freshness timestamp missing"]
        if age > MANUAL_AUTH_MAX_AGE_SECONDS:
            return "VALIDATE", [
                f"candidate age {age:.0f}s exceeds manual-authorization freshness limit "
                f"{MANUAL_AUTH_MAX_AGE_SECONDS}s"
            ]
        return "READY_FOR_MANUAL_AUTHORIZATION", []

    if classification in {"watch", "strong_watch"} and obs >= max(3, rules["min_observations"] // 2):
        return "VALIDATE", failed

    return "WAIT", failed


def main():
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec="seconds")
    ranked, source = load_ranked()

    if not ranked:
        payload = {
            "generated_at_utc": now,
            "state": "WAIT",
            "reason": "no candidates in rolling history",
            "selected": None,
            "ranking_source": source,
            "next_action": "collect more paper observations",
        }
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("WAIT: no candidates")
        return

    selected = ranked[0]
    state, failed = classify(selected)

    if state == "WAIT":
        next_action = "keep collecting data; no user action"
    elif state == "VALIDATE":
        next_action = (
            "run execution-specific paper validation and adversarial killer checks for this route; "
            "still no money and no credentials"
        )
    else:
        next_action = (
            "prepare one capped live-test plan for explicit user authorization; "
            "do not move funds or place orders"
        )

    seen = parse_ts(selected.get("last_seen_utc"))
    readiness_expiry = None
    if seen:
        readiness_expiry = (seen + timedelta(seconds=MANUAL_AUTH_MAX_AGE_SECONDS)).isoformat(timespec="seconds")

    payload = {
        "generated_at_utc": now,
        "state": state,
        "ranking_source": source,
        "selected": selected,
        "failed_gates": failed,
        "policy": POLICY.get(selected.get("strategy"), {}),
        "manual_authorization_freshness": {
            "max_candidate_age_seconds": MANUAL_AUTH_MAX_AGE_SECONDS,
            "candidate_last_seen_utc": selected.get("last_seen_utc"),
            "valid_until_utc": readiness_expiry,
            "rule": "READY is invalid after valid_until_utc unless a new laboratory run refreshes the evidence",
        },
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
