#!/usr/bin/env python3
"""Convert current crypto research evidence into scheduler-ready shadow events.

This is the bridge between the existing crypto HUNTER/KILLER/ALLOCATOR and the
single EUR250 capital scheduler. It is intentionally fail-closed: an event is
emitted only when the same fresh route survives every relevant KILLER gate and
the economics can be mapped to explicit venue pre-allocation and lock time.

Research/shadow only. No credentials, orders, signing, custody or transfers.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from opportunity_event import validate_event

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
KILLER = DATA / "killer_report.json"
KILLER_FUNDING = DATA / "killer_funding_report.json"
DEPTH = DATA / "depth_validation.json"
STABLE = DATA / "stable_roundtrip_validation.json"
EVENTS = DATA / "opportunity_events.jsonl"
OUT = DATA / "crypto_event_adapter_latest.json"

REFERENCE_BUDGET_EUR = 250.0
MAX_STALENESS_SECONDS = 900.0
FUNDING_STRESS_REALIZATION = 0.50
CROSS_SPOT_STRESS_REALIZATION = 0.50
PLANNING_HUMAN_MINUTES_PER_MANUAL_PAIR = 2.0


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def same_selected(report, selected):
    r = (report or {}).get("selected") or {}
    return (
        r.get("strategy") == selected.get("strategy")
        and r.get("label") == selected.get("label")
        and r.get("direction") == selected.get("direction")
    )


def fresh(selected, now=None):
    now = now or datetime.now(timezone.utc)
    ts = parse_ts(selected.get("last_seen_utc"))
    return bool(ts and 0 <= (now - ts).total_seconds() <= MAX_STALENESS_SECONDS)


def venues(selected):
    raw = str(selected.get("venue") or "")
    if "<->" in raw:
        left, right = [x.strip() for x in raw.split("<->", 1)]
        if left and right:
            return left, right
    direction = str(selected.get("direction") or "")
    m = re.match(r"^(?:long|buy)\s+(.+?)\s+/\s+(?:short|sell)\s+(.+?)$", direction, re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, None


def existing_ids():
    ids = set()
    if not EVENTS.exists():
        return ids
    for line in EVENTS.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("event_id"):
                ids.add(row["event_id"])
        except Exception:
            pass
    return ids


def append_event(event):
    DATA.mkdir(exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")


def funding_event(general, dedicated, now):
    if general.get("verdict") != "SURVIVES_KILLER":
        return None, "general_killer_not_survived"
    if dedicated.get("verdict") != "SURVIVES_KILLER":
        return None, "funding_killer_not_survived"

    selected = (dedicated.get("selected") or {})
    if selected.get("strategy") != "funding_spread":
        return None, "dedicated_killer_not_funding"
    if not same_selected(general, selected):
        return None, "killer_disagreement"
    if not fresh(selected, now):
        return None, "selected_stale"

    a, b = venues(selected)
    if not a or not b:
        return None, "cannot_resolve_venues"

    model = selected.get("funding_cost_model") or {}
    if not model.get("survives_cost_and_basis_haircuts"):
        return None, "cost_basis_model_not_survived"

    latest = abs(float(selected.get("latest_edge_bps") or 0.0))
    fee = float(model.get("amortized_cost_bps_per_8h") or 0.0)
    basis = float(model.get("amortized_adverse_basis_bps_per_8h") or 0.0)
    stressed_edge = (latest - fee - basis) * FUNDING_STRESS_REALIZATION
    if stressed_edge <= 0:
        return None, "nonpositive_stressed_current_edge"

    utilisation = float(selected.get("capital_utilisation") or 0.5)
    notional = REFERENCE_BUDGET_EUR * utilisation
    pnl = notional * stressed_edge / 10000.0
    if pnl <= 0:
        return None, "nonpositive_stressed_pnl"

    hold_days = float(model.get("holding_horizon_days") or 0.0)
    if hold_days <= 0:
        return None, "missing_holding_horizon"

    half = REFERENCE_BUDGET_EUR / 2.0
    event = {
        "event_id": f"crypto|funding_spread|{selected.get('label')}|{selected.get('last_seen_utc')}|250",
        "observed_at_utc": selected.get("last_seen_utc"),
        "habitat": "crypto",
        "strategy": "funding_spread",
        "label": selected.get("label"),
        "direction": selected.get("direction"),
        "required_preallocation_eur": {a: half, b: half},
        "lock_seconds": round(hold_days * 86400.0, 3),
        "expected_net_eur": round(pnl, 8),
        "human_minutes": PLANNING_HUMAN_MINUTES_PER_MANUAL_PAIR,
        "human_minutes_basis": "planning_assumption_manual_two_leg_authorization",
        "killer_verdict": "SURVIVES_KILLER",
        "evidence_tier": "executable_shadow",
        "source": "fresh_dual_killer_funding_current_edge_after_fee_basis_and_50pct_stress",
        "evidence": {
            "latest_edge_bps": latest,
            "fee_haircut_bps_per_8h": fee,
            "basis_haircut_bps_per_8h": basis,
            "stressed_net_edge_bps_per_8h": round(stressed_edge, 6),
            "reference_budget_eur": REFERENCE_BUDGET_EUR,
            "effective_notional_eur": round(notional, 2),
            "holding_horizon_days": hold_days,
        },
    }
    errors = validate_event(event)
    return (event, None) if not errors else (None, "event_validation:" + ",".join(errors))


def cross_spot_event(general, now):
    if general.get("verdict") != "SURVIVES_KILLER":
        return None, "general_killer_not_survived"
    selected = general.get("selected") or {}
    if selected.get("strategy") not in {"cex_cross_spot", "eu_cross_spot"}:
        return None, "not_cross_spot"
    if not fresh(selected, now):
        return None, "selected_stale"

    depth = load(DEPTH)
    if depth.get("state") != "PASS" or not same_selected(depth, selected):
        return None, "matching_depth_pass_missing"

    # A snapshot PnL is not enough for the EUR100 proof. Until the Lenovo/replay
    # measures how long capital is actually occupied, do not invent lock time.
    measured_lock = depth.get("measured_lock_seconds")
    if measured_lock is None:
        return None, "missing_measured_lock_seconds"

    row = next((x for x in (depth.get("rows") or []) if float(x.get("total_budget") or 0) == REFERENCE_BUDGET_EUR), None)
    if not row or float(row.get("paper_pnl") or 0.0) <= 0:
        return None, "positive_depth_row_250_missing"

    a = depth.get("buy_venue")
    b = depth.get("sell_venue")
    if not a or not b:
        return None, "depth_venues_missing"

    pnl = float(row["paper_pnl"]) * CROSS_SPOT_STRESS_REALIZATION
    half = REFERENCE_BUDGET_EUR / 2.0
    event = {
        "event_id": f"crypto|{selected.get('strategy')}|{selected.get('label')}|{selected.get('last_seen_utc')}|250",
        "observed_at_utc": selected.get("last_seen_utc"),
        "habitat": "crypto",
        "strategy": selected.get("strategy"),
        "label": selected.get("label"),
        "direction": selected.get("direction"),
        "required_preallocation_eur": {a: half, b: half},
        "lock_seconds": float(measured_lock),
        "expected_net_eur": round(pnl, 8),
        "human_minutes": PLANNING_HUMAN_MINUTES_PER_MANUAL_PAIR,
        "human_minutes_basis": "planning_assumption_manual_two_leg_authorization",
        "killer_verdict": "SURVIVES_KILLER",
        "evidence_tier": "executable_shadow",
        "source": "depth_vwap_after_fees_plus_50pct_extra_stress_with_measured_lock",
    }
    errors = validate_event(event)
    return (event, None) if not errors else (None, "event_validation:" + ",".join(errors))


def stable_event(general, now):
    if general.get("verdict") != "SURVIVES_KILLER":
        return None, "general_killer_not_survived"
    selected = general.get("selected") or {}
    if selected.get("strategy") not in {"stable_dislocation", "stable_eur_dislocation"}:
        return None, "not_stable"
    if not fresh(selected, now):
        return None, "selected_stale"

    stable = load(STABLE)
    if not same_selected(stable, selected) or stable.get("verified_exit_path") is not True:
        return None, "verified_exit_path_missing"
    measured_lock = stable.get("measured_lock_seconds")
    if measured_lock is None:
        return None, "missing_measured_lock_seconds"
    # Venue/preallocation semantics vary by redemption/convergence path. Require
    # the validator to provide them explicitly rather than guessing.
    pre = stable.get("required_preallocation_eur")
    row = next((x for x in (stable.get("rows") or []) if float(x.get("budget") or 0) == REFERENCE_BUDGET_EUR), None)
    if not isinstance(pre, dict) or not row:
        return None, "stable_preallocation_or_250_row_missing"
    pnl = float(row.get("paper_profit_eur_if_full_convergence") or 0.0)
    if pnl <= 0:
        return None, "stable_250_pnl_nonpositive"

    event = {
        "event_id": f"crypto|{selected.get('strategy')}|{selected.get('label')}|{selected.get('last_seen_utc')}|250",
        "observed_at_utc": selected.get("last_seen_utc"),
        "habitat": "crypto",
        "strategy": selected.get("strategy"),
        "label": selected.get("label"),
        "direction": selected.get("direction"),
        "required_preallocation_eur": pre,
        "lock_seconds": float(measured_lock),
        "expected_net_eur": round(pnl, 8),
        "human_minutes": 1.0,
        "human_minutes_basis": "planning_assumption_single_path_authorization",
        "killer_verdict": "SURVIVES_KILLER",
        "evidence_tier": "executable_shadow",
        "source": "verified_stable_exit_after_friction_with_measured_lock",
    }
    errors = validate_event(event)
    return (event, None) if not errors else (None, "event_validation:" + ",".join(errors))


def main():
    now = datetime.now(timezone.utc)
    general = load(KILLER)
    dedicated = load(KILLER_FUNDING)
    selected = (general.get("selected") or {})
    strategy = selected.get("strategy")

    attempted = []
    event = None
    reason = None

    if strategy == "funding_spread" or (dedicated.get("selected") or {}).get("strategy") == "funding_spread":
        event, reason = funding_event(general, dedicated, now)
        attempted.append({"strategy": "funding_spread", "result": "EMIT" if event else "SKIP", "reason": reason})
    elif strategy in {"cex_cross_spot", "eu_cross_spot"}:
        event, reason = cross_spot_event(general, now)
        attempted.append({"strategy": strategy, "result": "EMIT" if event else "SKIP", "reason": reason})
    elif strategy in {"stable_dislocation", "stable_eur_dislocation"}:
        event, reason = stable_event(general, now)
        attempted.append({"strategy": strategy, "result": "EMIT" if event else "SKIP", "reason": reason})
    else:
        attempted.append({"strategy": strategy, "result": "SKIP", "reason": "no_supported_surviving_crypto_route"})

    new = 0
    duplicate = False
    if event:
        seen = existing_ids()
        if event["event_id"] in seen:
            duplicate = True
        else:
            append_event(event)
            new = 1

    payload = {
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "habitat": "crypto",
        "status": "APPENDED_EXECUTABLE_SHADOW_EVENT" if new else ("DUPLICATE_EVENT" if duplicate else "NO_ELIGIBLE_EVENT"),
        "new_events_appended": new,
        "event": event,
        "attempted": attempted,
        "policy": {
            "reference_budget_eur": REFERENCE_BUDGET_EUR,
            "max_staleness_seconds": MAX_STALENESS_SECONDS,
            "funding_requires_both_killers_survive_same_route": True,
            "cross_spot_requires_matching_depth_pass_and_measured_lock_time": True,
            "stable_requires_verified_exit_and_measured_lock_time": True,
        },
        "safety": "research/shadow only; no credentials, orders or fund movement",
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"crypto event adapter: {payload['status']} new={new}")


if __name__ == "__main__":
    main()
