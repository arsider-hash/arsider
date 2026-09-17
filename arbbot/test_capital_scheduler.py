#!/usr/bin/env python3
from datetime import datetime, timezone

from capital_scheduler import choose_best, simulate_plan


def event(event_id, minute, net):
    base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    ts = base.replace(minute=minute) if minute < 60 else base.replace(hour=13, minute=minute - 60)
    return {
        "event_id": event_id,
        "observed_at_utc": ts.isoformat(),
        "habitat": "crypto",
        "strategy": "synthetic_test",
        "label": event_id,
        "required_preallocation_eur": {"A": 100.0, "B": 100.0},
        "lock_seconds": 3600,
        "expected_net_eur": net,
        "human_minutes": 1.0,
        "killer_verdict": "SURVIVES_KILLER",
        "evidence_tier": "executable_shadow",
    }


def main():
    events = [event("e1", 0, 2.0), event("e2", 10, 99.0), event("e3", 70, 3.0)]
    result = simulate_plan(events, {"A": 100.0, "B": 100.0})
    assert result["accepted_events"] == 2, result
    assert result["missed"].get("capital_busy") == 1, result
    assert abs(result["net_eur"] - 5.0) < 1e-9, result

    two = {"net_eur": 50.0, "venue_count": 2, "total_preallocated_eur": 200.0, "human_minutes": 10.0}
    weak_three = {"net_eur": 58.0, "venue_count": 3, "total_preallocated_eur": 240.0, "human_minutes": 10.0}
    chosen, _, _ = choose_best([two, weak_three])
    assert chosen is two, chosen

    strong_three = {"net_eur": 65.0, "venue_count": 3, "total_preallocated_eur": 240.0, "human_minutes": 10.0}
    chosen, _, _ = choose_best([two, strong_three])
    assert chosen is strong_three, chosen
    print("capital scheduler tests: PASS")


if __name__ == "__main__":
    main()
