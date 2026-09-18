#!/usr/bin/env python3
"""Cross-habitat ARBBOT research board.

Crypto remains the existing baseline. New habitats add evidence beside it rather
than replacing it. This board is descriptive only; it cannot promote candidates
past KILLER/decision gates.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CAPITAL_RANK = DATA / "capital_rank.json"
CRYPTO_ADAPTER = DATA / "crypto_event_adapter_latest.json"
BETFAIR_REPLAY = DATA / "betfair_replay_latest.json"
BETFAIR = DATA / "betfair_latest.json"
SCHEDULE = DATA / "capital_schedule.json"
OUT = DATA / "habitat_board.json"


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    rank = load(CAPITAL_RANK)
    crypto_adapter = load(CRYPTO_ADAPTER)
    bf_replay = load(BETFAIR_REPLAY)
    bf = load(BETFAIR)
    schedule = load(SCHEDULE)
    crypto = rank.get("ranked") or []
    crypto_best = crypto[0] if crypto else None

    habitats = [
        {
            "habitat": "crypto",
            "status": "ACTIVE_BASELINE",
            "killer_survivors": len(crypto),
            "best": crypto_best,
            "scheduler_adapter_status": crypto_adapter.get("status") or "NOT_RUN",
            "scheduler_events_appended": crypto_adapter.get("new_events_appended", 0),
            "adapter_attempted": crypto_adapter.get("attempted") or [],
            "note": "Existing crypto HUNTER/KILLER/ALLOCATOR remains unchanged; only fresh survivors can enter the shared EUR250 scheduler.",
        },
        {
            "habitat": "betfair_exchange",
            "status": bf.get("status") or "AWAITING_FEED",
            "replay_status": bf_replay.get("status") or "AWAITING_REPLAY",
            "replay_snapshots_seen": bf_replay.get("snapshots_seen", 0),
            "replay_survivors": bf_replay.get("survivors", 0),
            "valid_events_seen": bf.get("valid_events_seen", 0),
            "new_events_appended": bf.get("new_events_appended", 0),
            "orders_enabled": False,
        },
    ]

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "principle": "new habitats compete for the same EUR250 pool; no habitat replaces or bypasses existing KILLER gates",
        "habitats": habitats,
        "shared_capital_scheduler": {
            "status": schedule.get("status") or "NOT_RUN",
            "best_plan": schedule.get("best_plan"),
            "proof_window_span_days": schedule.get("proof_window_span_days", 0.0),
            "eligible_events": schedule.get("eligible_events", 0),
        },
        "safety": "research/shadow only; no orders, custody, transfers, signing or live-trading enablement",
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("habitat board refreshed")


if __name__ == "__main__":
    main()
