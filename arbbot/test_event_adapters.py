#!/usr/bin/env python3
"""Small deterministic tests for the crypto/Betfair event adapters.

Synthetic fixtures verify logic only. They never write to the production ledger.
"""
from datetime import datetime, timezone, timedelta

from crypto_event_adapter import funding_event
from betfair_replay_adapter import evaluate_snapshot


def test_funding_requires_both_killers():
    now = datetime.now(timezone.utc)
    selected = {
        "strategy": "funding_spread",
        "label": "TESTUSDT",
        "direction": "long Bitget / short Gate",
        "venue": "Bitget<->Gate",
        "last_seen_utc": (now - timedelta(seconds=10)).isoformat(),
        "latest_edge_bps": 50.0,
        "capital_utilisation": 0.5,
        "funding_cost_model": {
            "survives_cost_and_basis_haircuts": True,
            "amortized_cost_bps_per_8h": 2.0,
            "amortized_adverse_basis_bps_per_8h": 3.0,
            "holding_horizon_days": 7.0,
        },
    }
    general = {"verdict": "SURVIVES_KILLER", "selected": selected}
    dedicated = {"verdict": "SURVIVES_KILLER", "selected": selected}
    event, reason = funding_event(general, dedicated, now)
    assert event is not None, reason
    assert event["required_preallocation_eur"] == {"Bitget": 125.0, "Gate": 125.0}
    assert event["expected_net_eur"] > 0
    assert event["lock_seconds"] == 7 * 86400

    dedicated_bad = {"verdict": "REJECTED", "selected": selected}
    event, reason = funding_event(general, dedicated_bad, now)
    assert event is None
    assert reason == "funding_killer_not_survived"


def test_betfair_replay_surebet_and_non_surebet():
    now = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
    close = now + timedelta(hours=2)
    good = {
        "observed_at_utc": now.isoformat(),
        "market_close_utc": close.isoformat(),
        "market_id": "1.test",
        "market_name": "Synthetic three-way",
        "market_type": "MATCH_ODDS",
        "complete_outcome_set": True,
        "selections": [
            {"selection_id": "1", "name": "A", "best_back_price": 4.0, "best_back_size_eur": 200},
            {"selection_id": "2", "name": "B", "best_back_price": 4.0, "best_back_size_eur": 200},
            {"selection_id": "3", "name": "C", "best_back_price": 4.0, "best_back_size_eur": 200},
        ],
    }
    event, errors = evaluate_snapshot(good)
    assert event is not None, errors
    assert event["killer_verdict"] == "SURVIVES_KILLER"
    assert event["expected_net_eur"] > 0
    assert event["required_preallocation_eur"]["Betfair"] <= 250.0

    bad = {
        **good,
        "market_id": "1.bad",
        "selections": [
            {"selection_id": "1", "name": "A", "best_back_price": 2.0, "best_back_size_eur": 200},
            {"selection_id": "2", "name": "B", "best_back_price": 3.0, "best_back_size_eur": 200},
            {"selection_id": "3", "name": "C", "best_back_price": 4.0, "best_back_size_eur": 200},
        ],
    }
    event, errors = evaluate_snapshot(bad)
    assert event is None
    assert any("no_surebet" in x for x in errors)


if __name__ == "__main__":
    test_funding_requires_both_killers()
    test_betfair_replay_surebet_and_non_surebet()
    print("event adapter tests: PASS")
