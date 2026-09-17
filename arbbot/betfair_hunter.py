#!/usr/bin/env python3
"""Fail-closed Betfair habitat intake for ARBBOT.

The first version intentionally does not authenticate, place bets, or scrape a
private account. It accepts only normalized executable-shadow events produced by
an external/replay feed, validates them against the common opportunity contract,
and merges new event IDs into the shared chronological ledger.

This lets us build/test the multi-habitat lab before installing anything on the
Lenovo. A future local edge-node adapter can write the same inbox format.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from opportunity_event import validate_event

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEFAULT_INBOX = DATA / "betfair_inbox.jsonl"
EVENTS = DATA / "opportunity_events.jsonl"
OUT = DATA / "betfair_latest.json"


def read_jsonl(path):
    rows = []
    bad = []
    if not path.exists():
        return rows, bad
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            bad.append({"line": line_no, "errors": ["invalid_json"]})
    return rows, bad


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
            continue
    return ids


def append_events(rows):
    if not rows:
        return
    DATA.mkdir(exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inbox = Path(os.environ.get("BETFAIR_EVENT_SOURCE", str(DEFAULT_INBOX)))
    rows, bad_json = read_jsonl(inbox)
    valid = []
    rejected = list(bad_json)

    for row in rows:
        errors = []
        if row.get("habitat") != "betfair_exchange":
            errors.append("habitat_must_be_betfair_exchange")
        errors.extend(validate_event(row))
        if errors:
            rejected.append({"event_id": row.get("event_id"), "errors": errors})
        else:
            valid.append(row)

    seen = existing_ids()
    new_rows = [r for r in valid if r["event_id"] not in seen]
    append_events(new_rows)

    payload = {
        "generated_at_utc": now,
        "habitat": "betfair_exchange",
        "status": "INGESTED_SHADOW_EVENTS" if valid else "AWAITING_FEED",
        "inbox_path": str(inbox),
        "valid_events_seen": len(valid),
        "new_events_appended": len(new_rows),
        "rejected_events": len(rejected),
        "rejections": rejected[:50],
        "mode": "normalized_replay_or_edge_node_intake",
        "live_credentials_used": False,
        "orders_enabled": False,
        "note": (
            "No Betfair opportunity is invented when no feed exists. A future Lenovo adapter may write "
            "the same normalized event schema after observing public/authorized market data."
        ),
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"betfair habitat: {payload['status']} valid={len(valid)} new={len(new_rows)}")


if __name__ == "__main__":
    main()
