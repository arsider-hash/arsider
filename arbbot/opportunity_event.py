#!/usr/bin/env python3
"""Normalized opportunity-event contract for ARBBOT habitats.

Every habitat may discover opportunities differently, but the capital scheduler
only accepts events which can answer the same operational questions: when was it
seen, where must capital already be parked, how much is required on each venue,
how long is it locked, what conservative NET paper PnL remains, and did KILLER
survive for the same evidence.

Research/shadow only. No orders, credentials, signing, custody or transfers.
"""
from __future__ import annotations

from datetime import datetime

SURVIVING_KILLER = "SURVIVES_KILLER"
EXECUTABLE_EVIDENCE_TIER = "executable_shadow"


def parse_ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def validate_event(event):
    errors = []
    required_text = ("event_id", "observed_at_utc", "habitat", "strategy", "label")
    for key in required_text:
        if not str(event.get(key) or "").strip():
            errors.append(f"missing_{key}")

    if parse_ts(event.get("observed_at_utc")) is None:
        errors.append("invalid_observed_at_utc")

    try:
        lock_seconds = float(event.get("lock_seconds"))
        if lock_seconds < 0:
            errors.append("negative_lock_seconds")
    except Exception:
        errors.append("invalid_lock_seconds")

    try:
        net = float(event.get("expected_net_eur"))
        if net <= 0:
            errors.append("nonpositive_expected_net_eur")
    except Exception:
        errors.append("invalid_expected_net_eur")

    try:
        human = float(event.get("human_minutes") or 0.0)
        if human < 0:
            errors.append("negative_human_minutes")
    except Exception:
        errors.append("invalid_human_minutes")

    pre = event.get("required_preallocation_eur")
    if not isinstance(pre, dict) or not pre:
        errors.append("missing_required_preallocation_eur")
    else:
        total = 0.0
        for venue, amount in pre.items():
            if not str(venue or "").strip():
                errors.append("blank_venue")
                continue
            try:
                amount = float(amount)
                if amount <= 0:
                    errors.append(f"nonpositive_preallocation_{venue}")
                total += max(0.0, amount)
            except Exception:
                errors.append(f"invalid_preallocation_{venue}")
        if total <= 0:
            errors.append("zero_total_preallocation")

    if event.get("killer_verdict") != SURVIVING_KILLER:
        errors.append("killer_not_survived")
    if event.get("evidence_tier") != EXECUTABLE_EVIDENCE_TIER:
        errors.append("not_executable_shadow_evidence")

    return errors


def is_scheduler_eligible(event):
    return not validate_event(event)
