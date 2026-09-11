#!/usr/bin/env python3
"""Persist compact falsification memory for recurring ARBBOT candidates.

Read-only with respect to markets. It never promotes candidates, changes gates,
or executes anything. It records repeated KILLER failures so historically large
edges cannot silently reset their reputation every scan.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "opportunity_graveyard.json"
REPORTS = (DATA / "killer_report.json", DATA / "killer_funding_report.json")


def load(path: Path):
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def reason_list(report):
    reasons = []
    for x in report.get("hard_failures") or []:
        if x and x not in reasons:
            reasons.append(str(x))
    for x in report.get("insufficient_evidence") or []:
        if x and x not in reasons:
            reasons.append(str(x))
    return reasons


def main():
    DATA.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state = load(OUT)
    entries = state.get("entries") if isinstance(state.get("entries"), dict) else {}

    seen = set()
    for path in REPORTS:
        report = load(path)
        selected = report.get("selected") or {}
        strategy = selected.get("strategy")
        label = selected.get("label")
        if not strategy or not label:
            continue
        key = f"{strategy}|{label}"
        # Primary and dedicated KILLER can describe the same candidate in one
        # snapshot. Count a snapshot once, while retaining the stricter verdict.
        if key in seen:
            continue
        seen.add(key)

        verdict = str(report.get("verdict") or "UNKNOWN")
        entry = entries.get(key) or {
            "strategy": strategy,
            "label": label,
            "snapshots": 0,
            "survives": 0,
            "rejected": 0,
            "insufficient": 0,
            "consecutive_non_survivals": 0,
            "reason_counts": {},
        }
        entry["snapshots"] = int(entry.get("snapshots") or 0) + 1
        if verdict == "SURVIVES_KILLER":
            entry["survives"] = int(entry.get("survives") or 0) + 1
            entry["consecutive_non_survivals"] = 0
        elif verdict == "REJECTED":
            entry["rejected"] = int(entry.get("rejected") or 0) + 1
            entry["consecutive_non_survivals"] = int(entry.get("consecutive_non_survivals") or 0) + 1
        else:
            entry["insufficient"] = int(entry.get("insufficient") or 0) + 1
            entry["consecutive_non_survivals"] = int(entry.get("consecutive_non_survivals") or 0) + 1

        for reason in reason_list(report):
            counts = entry.setdefault("reason_counts", {})
            counts[reason] = int(counts.get(reason) or 0) + 1

        entry.update({
            "last_verdict": verdict,
            "last_seen_utc": selected.get("last_seen_utc"),
            "last_latest_edge_bps": selected.get("latest_edge_bps"),
            "last_median_positive_edge_bps": selected.get("median_positive_edge_bps"),
            "last_persistence": selected.get("persistence"),
            "last_reasons": reason_list(report),
            "updated_at_utc": now,
        })
        entries[key] = entry

    OUT.write_text(json.dumps({
        "generated_at_utc": now,
        "mode": "falsification_memory_only",
        "can_promote_candidate": False,
        "entries": entries,
        "note": "Historical failure memory is diagnostic evidence only. It cannot loosen gates or create READY.",
    }, indent=2))


if __name__ == "__main__":
    main()
