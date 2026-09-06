#!/usr/bin/env python3
"""
ARBBOT adversarial KILLER.

Aggregates existing validation evidence and tries to falsify the currently
selected candidate before it can reach READY_FOR_MANUAL_AUTHORIZATION.

This module never places orders, handles credentials, signs transactions or
moves funds. It only writes arbbot/data/killer_report.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DECISION = DATA / "decision.json"
CAPITAL_RANK = DATA / "capital_rank.json"
VALIDATION = DATA / "validation.json"
DEPTH_VALIDATION = DATA / "depth_validation.json"
SHADOW_SUMMARY = DATA / "shadow_summary.json"
OUT = DATA / "killer_report.json"

FAST_STRATEGIES = {
    "cex_cross_spot", "eu_cross_spot", "cex_triangle", "eur_triangle",
    "stable_eur_dislocation",
}
DEPTH_STRATEGIES = {"cex_cross_spot", "eu_cross_spot"}
MAX_STALENESS_SECONDS = 15 * 60


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:
        return None


def same_route(doc, selected):
    s = (doc or {}).get("selected") or {}
    return (
        s.get("strategy") == selected.get("strategy")
        and s.get("label") == selected.get("label")
    )


def selected_candidate():
    decision = load_json(DECISION) or {}
    if decision.get("selected"):
        return decision["selected"]
    rank = load_json(CAPITAL_RANK) or {}
    return rank.get("best")


def age_seconds(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return None


def add(checks, name, status, detail, severity="hard"):
    checks.append({
        "check": name,
        "status": status,
        "severity": severity,
        "detail": detail,
    })


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    selected = selected_candidate()
    if not selected:
        payload = {
            "generated_at_utc": now,
            "verdict": "NO_CANDIDATE",
            "selected": None,
            "checks": [],
            "hard_failures": [],
            "insufficient_evidence": ["no selected candidate"],
        }
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("KILLER NO_CANDIDATE")
        return

    checks = []
    strategy = selected.get("strategy")
    obs = int(selected.get("observations") or 0)
    pos = int(selected.get("positive_observations") or 0)
    persistence = float(selected.get("persistence") or 0)
    med = float(selected.get("median_positive_edge_bps") or 0)
    latest = float(selected.get("latest_edge_bps") or 0)
    relevance = float(selected.get("economic_relevance_score") or 0)

    age = age_seconds(selected.get("last_seen_utc"))
    if age is None:
        add(checks, "freshness", "INSUFFICIENT", "candidate timestamp missing or invalid")
    elif age > MAX_STALENESS_SECONDS:
        add(checks, "freshness", "FAIL", f"candidate is stale by {age:.0f}s")
    else:
        add(checks, "freshness", "PASS", f"candidate age {age:.0f}s")

    if obs <= 0:
        add(checks, "sample_presence", "FAIL", "no observations")
    else:
        add(checks, "sample_presence", "PASS", f"{obs} observations")

    if pos <= 0 or med <= 0:
        add(checks, "positive_edge_evidence", "FAIL", f"positive_observations={pos}, median_positive_edge_bps={med:.4f}")
    else:
        add(checks, "positive_edge_evidence", "PASS", f"positive_observations={pos}, median_positive_edge_bps={med:.4f}")

    if persistence <= 0:
        add(checks, "persistence", "FAIL", f"persistence={persistence:.3f}")
    else:
        add(checks, "persistence", "PASS", f"persistence={persistence:.3f}")

    if latest <= 0:
        add(checks, "latest_edge_sign", "WARN", f"latest_edge_bps={latest:.4f}", severity="soft")
    else:
        add(checks, "latest_edge_sign", "PASS", f"latest_edge_bps={latest:.4f}", severity="soft")

    if relevance <= 0:
        add(checks, "economic_relevance", "WARN", f"economic_relevance_score={relevance:.2f}", severity="soft")
    else:
        add(checks, "economic_relevance", "PASS", f"economic_relevance_score={relevance:.2f}", severity="soft")

    validation = load_json(VALIDATION)
    if strategy in FAST_STRATEGIES:
        if not validation or not same_route(validation, selected):
            add(checks, "burst_validation", "INSUFFICIENT", "no matching burst validation")
        elif validation.get("verdict") != "SURVIVES_BURST":
            add(checks, "burst_validation", "FAIL", f"verdict={validation.get('verdict')}")
        else:
            add(checks, "burst_validation", "PASS", "SURVIVES_BURST")

    depth = load_json(DEPTH_VALIDATION)
    if strategy in DEPTH_STRATEGIES:
        if not depth or not same_route(depth, selected):
            add(checks, "depth_validation", "INSUFFICIENT", "no matching depth validation")
        elif depth.get("state") != "PASS":
            add(checks, "depth_validation", "FAIL", f"state={depth.get('state')}")
        else:
            add(checks, "depth_validation", "PASS", "order-book depth PASS")

    shadow = load_json(SHADOW_SUMMARY) or {}
    key = f"{selected.get('strategy')}|{selected.get('label')}"
    shadow_item = next((x for x in (shadow.get("ranked") or []) if x.get("key") == key), None)
    if shadow_item:
        count = int(shadow_item.get("count") or 0)
        rate = float(shadow_item.get("positive_rate") or 0)
        pnl = float(shadow_item.get("cumulative_paper_pnl") or 0)
        status = "PASS" if count >= 3 and rate >= 0.67 and pnl > 0 else "WARN"
        add(checks, "shadow_evidence", status, f"count={count}, positive_rate={rate:.3f}, cumulative_paper_pnl={pnl:.6f}", severity="soft")
    else:
        add(checks, "shadow_evidence", "INSUFFICIENT", "no matching shadow history", severity="soft")

    hard_failures = [c["detail"] for c in checks if c["severity"] == "hard" and c["status"] == "FAIL"]
    insufficient = [c["detail"] for c in checks if c["severity"] == "hard" and c["status"] == "INSUFFICIENT"]

    if hard_failures:
        verdict = "REJECTED"
    elif insufficient:
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "SURVIVES_KILLER"

    payload = {
        "generated_at_utc": now,
        "verdict": verdict,
        "selected": selected,
        "checks": checks,
        "hard_failures": hard_failures,
        "insufficient_evidence": insufficient,
        "policy": {
            "max_staleness_seconds": MAX_STALENESS_SECONDS,
            "principle": "assume false until execution evidence survives adversarial checks",
        },
        "hard_boundary": "Research/falsification only; no live execution or custody.",
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"KILLER {verdict}: {strategy} {selected.get('label')}")


if __name__ == "__main__":
    main()
