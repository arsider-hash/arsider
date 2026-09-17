#!/usr/bin/env python3
"""Chronological one-pool capital scheduler for the EUR100 challenge.

This module answers a deliberately narrow question: with one fixed EUR250 pool,
pre-positioned before opportunities appear, which executable-shadow events could
actually have been taken without double-spending capital?

It models venue-specific pre-allocation, overlapping locks, release time, missed
opportunities due to occupied capital, human-time budget, and the rule that a
third venue must materially improve the result. Profits are NOT compounded into
available capital inside the test window, which keeps the simulation conservative.

Research/shadow only. It never moves money or places orders.
"""
from __future__ import annotations

import itertools
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opportunity_event import is_scheduler_eligible, parse_ts, validate_event

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
EVENTS = DATA / "opportunity_events.jsonl"
OUT = DATA / "capital_schedule.json"

STARTING_CAPITAL_EUR = 250.0
WINDOW_DAYS = 30
MAX_HUMAN_MINUTES = 60.0
PREFERRED_MAX_VENUES = 2
HARD_MAX_VENUES = 3
THIRD_VENUE_MIN_ABSOLUTE_GAIN_EUR = 10.0
THIRD_VENUE_MIN_RELATIVE_GAIN = 0.20
ALLOCATION_QUANTUM_EUR = 5.0
MAX_LEVELS_PER_VENUE = 7
MAX_ACTIVE_VENUES_FOR_SEARCH = 8


def load_events():
    rows = []
    rejected = []
    if not EVENTS.exists():
        return rows, rejected
    for idx, line in enumerate(EVENTS.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except Exception:
            rejected.append({"line": idx, "errors": ["invalid_json"]})
            continue
        errors = validate_event(event)
        if errors:
            rejected.append({"line": idx, "event_id": event.get("event_id"), "errors": errors})
            continue
        rows.append(event)
    rows.sort(key=lambda e: parse_ts(e["observed_at_utc"]))
    return rows, rejected


def _ceil_quantum(value):
    return math.ceil(float(value) / ALLOCATION_QUANTUM_EUR) * ALLOCATION_QUANTUM_EUR


def search_levels(events):
    counts = Counter()
    observed = defaultdict(set)
    for e in events:
        for venue, amount in (e.get("required_preallocation_eur") or {}).items():
            counts[venue] += 1
            observed[venue].add(min(STARTING_CAPITAL_EUR, _ceil_quantum(amount)))
    venues = [v for v, _ in counts.most_common(MAX_ACTIVE_VENUES_FOR_SEARCH)]
    levels = {}
    for venue in venues:
        vals = sorted(observed[venue])
        if len(vals) > MAX_LEVELS_PER_VENUE:
            # Keep low, median-ish and high observed requirements rather than
            # inventing arbitrary capital splits.
            picks = {vals[0], vals[-1]}
            for i in range(1, MAX_LEVELS_PER_VENUE - 1):
                pos = round(i * (len(vals) - 1) / (MAX_LEVELS_PER_VENUE - 1))
                picks.add(vals[pos])
            vals = sorted(picks)
        levels[venue] = vals
    return venues, levels


def generate_plans(events):
    venues, levels = search_levels(events)
    yielded = set()
    for size in range(1, min(HARD_MAX_VENUES, len(venues)) + 1):
        for subset in itertools.combinations(venues, size):
            choices = [levels[v] for v in subset]
            for amounts in itertools.product(*choices):
                total = round(sum(amounts), 8)
                if total > STARTING_CAPITAL_EUR + 1e-9:
                    continue
                plan = tuple(sorted((v, float(a)) for v, a in zip(subset, amounts)))
                if plan in yielded:
                    continue
                yielded.add(plan)
                yield dict(plan)


def simulate_plan(events, allocation, window_start=None, window_end=None):
    locks = []
    accepted = []
    missed = Counter()
    net = 0.0
    human = 0.0
    locked_eur_seconds = 0.0

    def release(now):
        nonlocal locks
        locks = [x for x in locks if x["release_at"] > now]

    def free_by_venue(now):
        release(now)
        used = defaultdict(float)
        for lock in locks:
            for venue, amount in lock["amounts"].items():
                used[venue] += amount
        return {v: allocation.get(v, 0.0) - used.get(v, 0.0) for v in allocation}

    for e in events:
        ts = parse_ts(e["observed_at_utc"])
        if window_start and ts < window_start:
            continue
        if window_end and ts > window_end:
            continue
        if not is_scheduler_eligible(e):
            missed["ineligible"] += 1
            continue
        req = {k: float(v) for k, v in e["required_preallocation_eur"].items()}
        if any(v not in allocation for v in req):
            missed["venue_not_preallocated"] += 1
            continue
        free = free_by_venue(ts)
        if any(free.get(v, 0.0) + 1e-9 < amount for v, amount in req.items()):
            missed["capital_busy"] += 1
            continue
        event_human = float(e.get("human_minutes") or 0.0)
        if human + event_human > MAX_HUMAN_MINUTES + 1e-9:
            missed["human_time_budget"] += 1
            continue
        lock_seconds = float(e["lock_seconds"])
        release_at = ts + timedelta(seconds=lock_seconds)
        locks.append({"release_at": release_at, "amounts": req, "event_id": e["event_id"]})
        event_net = float(e["expected_net_eur"])
        net += event_net
        human += event_human
        locked_eur_seconds += sum(req.values()) * lock_seconds
        accepted.append({
            "event_id": e["event_id"],
            "observed_at_utc": e["observed_at_utc"],
            "release_at_utc": release_at.isoformat(),
            "habitat": e["habitat"],
            "strategy": e["strategy"],
            "label": e["label"],
            "required_preallocation_eur": req,
            "expected_net_eur": event_net,
            "human_minutes": event_human,
        })

    total_preallocated = sum(allocation.values())
    avg_locked = locked_eur_seconds / max(1.0, WINDOW_DAYS * 86400.0)
    return {
        "preallocation_eur": {k: round(v, 2) for k, v in sorted(allocation.items())},
        "venue_count": len(allocation),
        "total_preallocated_eur": round(total_preallocated, 2),
        "idle_unallocated_eur": round(STARTING_CAPITAL_EUR - total_preallocated, 2),
        "accepted_events": len(accepted),
        "net_eur": round(net, 6),
        "human_minutes": round(human, 3),
        "average_locked_capital_eur": round(avg_locked, 3),
        "missed": dict(missed),
        "accepted": accepted,
    }


def _plan_sort_key(result):
    # Maximise actual shadow NET first; then minimise complexity, stranded cash
    # and human work. No risk score is smuggled into this layer.
    return (
        result["net_eur"],
        -result["venue_count"],
        -result["total_preallocated_eur"],
        -result["human_minutes"],
    )


def choose_best(results):
    if not results:
        return None, None, None
    two_or_less = [r for r in results if r["venue_count"] <= PREFERRED_MAX_VENUES]
    three = [r for r in results if r["venue_count"] == 3]
    best_two = max(two_or_less, key=_plan_sort_key) if two_or_less else None
    best_three = max(three, key=_plan_sort_key) if three else None

    chosen = best_two or best_three
    if best_three and best_two:
        absolute_gain = best_three["net_eur"] - best_two["net_eur"]
        relative_gain = absolute_gain / max(1e-9, abs(best_two["net_eur"])) if best_two["net_eur"] else float("inf")
        if absolute_gain >= THIRD_VENUE_MIN_ABSOLUTE_GAIN_EUR and relative_gain >= THIRD_VENUE_MIN_RELATIVE_GAIN:
            chosen = best_three
    elif best_three and not best_two:
        chosen = best_three
    return chosen, best_two, best_three


def main():
    now = datetime.now(timezone.utc)
    events, rejected = load_events()
    eligible = [e for e in events if is_scheduler_eligible(e)]

    if not eligible:
        payload = {
            "generated_at_utc": now.isoformat(timespec="seconds"),
            "status": "NO_EXECUTABLE_EVENTS",
            "starting_capital_eur": STARTING_CAPITAL_EUR,
            "window_days": WINDOW_DAYS,
            "eligible_events": 0,
            "rejected_input_events": len(rejected),
            "best_plan": None,
            "proof_window_span_days": 0.0,
            "third_venue_rule": {
                "absolute_gain_eur_min": THIRD_VENUE_MIN_ABSOLUTE_GAIN_EUR,
                "relative_gain_min": THIRD_VENUE_MIN_RELATIVE_GAIN,
            },
            "safety": "shadow accounting only; no live orders or fund movement",
        }
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("capital scheduler: no executable-shadow events")
        return

    latest = parse_ts(eligible[-1]["observed_at_utc"])
    window_start = latest - timedelta(days=WINDOW_DAYS)
    window_events = [e for e in eligible if parse_ts(e["observed_at_utc"]) >= window_start]
    first_ts = parse_ts(window_events[0]["observed_at_utc"]) if window_events else latest
    span_days = max(0.0, (latest - first_ts).total_seconds() / 86400.0)

    results = [simulate_plan(window_events, p, window_start, latest) for p in generate_plans(window_events)]
    chosen, best_two, best_three = choose_best(results)

    payload = {
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "status": "SIMULATED" if chosen else "NO_FEASIBLE_PREALLOCATION",
        "starting_capital_eur": STARTING_CAPITAL_EUR,
        "window_days": WINDOW_DAYS,
        "window_end_utc": latest.isoformat(),
        "window_start_utc": window_start.isoformat(),
        "proof_window_span_days": round(span_days, 4),
        "eligible_events": len(window_events),
        "rejected_input_events": len(rejected),
        "plans_tested": len(results),
        "best_plan": chosen,
        "best_plan_max_2_venues": best_two,
        "best_plan_3_venues": best_three,
        "third_venue_rule": {
            "absolute_gain_eur_min": THIRD_VENUE_MIN_ABSOLUTE_GAIN_EUR,
            "relative_gain_min": THIRD_VENUE_MIN_RELATIVE_GAIN,
            "principle": "a third account/venue is accepted only if both material-gain thresholds are met",
        },
        "conservatism": [
            "profits are not compounded into available capital",
            "capital must be preallocated before an event appears",
            "overlapping locks cannot double-spend the same venue balance",
            "KILLER must SURVIVE and evidence tier must be executable_shadow",
            "human-time budget is capped at 60 minutes per 30-day test window",
        ],
        "safety": "shadow accounting only; no live orders or fund movement",
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"capital scheduler: plans={len(results)} best_net={chosen['net_eur'] if chosen else None}")


if __name__ == "__main__":
    main()
