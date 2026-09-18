#!/usr/bin/env python3
"""Strict Betfair Exchange replay adapter for the EUR100 challenge.

Input is normalized market-book snapshots, not account data. For each snapshot
the adapter looks only for a narrow, mechanically checkable pattern: a complete
set of mutually exclusive outcomes whose stressed BACK prices still imply a
guaranteed positive payoff after commission.

The adapter deliberately worsens every best-back price by two Betfair ticks,
caps stakes by displayed size, requires an explicit market-close timestamp, and
uses one Betfair balance as pre-allocation. Passing rows become executable-shadow
events for the chronological capital scheduler.

No login, API key, bets, orders, custody or transfers.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

from opportunity_event import validate_event

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEFAULT_SOURCE = DATA / "betfair_market_replay.jsonl"
INBOX = DATA / "betfair_inbox.jsonl"
OUT = DATA / "betfair_replay_latest.json"

REFERENCE_BUDGET_EUR = 250.0
COMMISSION_RATE = 0.045
ADVERSE_TICKS = 2
SETTLEMENT_BUFFER_SECONDS = 1800.0
MIN_NET_EUR = 0.05
MIN_NET_BPS_ON_STAKE = 2.0
MANUAL_MINUTES_PER_MARKET = 2.0


def parse_ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def read_jsonl(path):
    rows, bad = [], []
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


def betfair_ladder():
    bands = [
        ("1.01", "2.00", "0.01"),
        ("2.02", "3.00", "0.02"),
        ("3.05", "4.00", "0.05"),
        ("4.10", "6.00", "0.10"),
        ("6.20", "10.00", "0.20"),
        ("10.50", "20.00", "0.50"),
        ("21.00", "30.00", "1.00"),
        ("32.00", "50.00", "2.00"),
        ("55.00", "100.00", "5.00"),
        ("110.00", "1000.00", "10.00"),
    ]
    prices = []
    for start, end, step in bands:
        x, e, s = Decimal(start), Decimal(end), Decimal(step)
        while x <= e:
            prices.append(float(x))
            x += s
    return prices


LADDER = betfair_ladder()


def floor_to_ladder(price):
    eligible = [x for x in LADDER if x <= float(price) + 1e-12]
    return eligible[-1] if eligible else None


def worsen_back_price(price, ticks=ADVERSE_TICKS):
    p = floor_to_ladder(price)
    if p is None:
        return None
    idx = LADDER.index(p)
    idx = max(0, idx - int(ticks))
    return LADDER[idx]


def existing_inbox_ids():
    ids = set()
    if not INBOX.exists():
        return ids
    for line in INBOX.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("event_id"):
                ids.add(row["event_id"])
        except Exception:
            pass
    return ids


def append_inbox(rows):
    if not rows:
        return
    DATA.mkdir(exist_ok=True)
    with INBOX.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


def evaluate_snapshot(s):
    errors = []
    observed = parse_ts(s.get("observed_at_utc"))
    close = parse_ts(s.get("market_close_utc"))
    if not observed:
        errors.append("invalid_observed_at_utc")
    if not close or (observed and close <= observed):
        errors.append("invalid_market_close_utc")
    if s.get("complete_outcome_set") is not True:
        errors.append("outcome_set_not_explicitly_complete")

    market_id = str(s.get("market_id") or "").strip()
    if not market_id:
        errors.append("missing_market_id")

    selections = s.get("selections")
    if not isinstance(selections, list) or len(selections) < 2:
        errors.append("need_at_least_two_outcomes")
        selections = []

    parsed = []
    seen_ids = set()
    for sel in selections:
        sid = str(sel.get("selection_id") or "").strip()
        try:
            price = float(sel.get("best_back_price"))
            size = float(sel.get("best_back_size_eur"))
        except Exception:
            errors.append(f"invalid_price_or_size_{sid or 'unknown'}")
            continue
        if not sid or sid in seen_ids:
            errors.append("missing_or_duplicate_selection_id")
            continue
        seen_ids.add(sid)
        if price <= 1.0 or size <= 0:
            errors.append(f"nonpositive_liquidity_{sid}")
            continue
        stressed = worsen_back_price(price)
        if stressed is None or stressed <= 1.0:
            errors.append(f"cannot_stress_price_{sid}")
            continue
        parsed.append({
            "selection_id": sid,
            "name": sel.get("name"),
            "raw_price": price,
            "stressed_price": stressed,
            "available_size_eur": size,
        })

    if errors:
        return None, errors

    q = sum(1.0 / x["stressed_price"] for x in parsed)
    if q >= 1.0:
        return None, [f"no_surebet_after_{ADVERSE_TICKS}_tick_stress:q={q:.8f}"]

    # Dutch stakes: stake_i = T*(1/odds_i)/q. Cap T so every leg fits the
    # displayed available-to-back size after stress.
    max_total = min(
        x["available_size_eur"] * q * x["stressed_price"] for x in parsed
    )
    total_stake = min(REFERENCE_BUDGET_EUR, max_total)
    if total_stake <= 0:
        return None, ["zero_executable_stake"]

    stakes = []
    for x in parsed:
        stake = total_stake * (1.0 / x["stressed_price"]) / q
        stakes.append({**x, "stake_eur": stake})

    guaranteed_return = total_stake / q
    gross_profit = guaranteed_return - total_stake
    commission = max(0.0, gross_profit) * COMMISSION_RATE
    net = gross_profit - commission
    net_bps = net / total_stake * 10000.0 if total_stake else 0.0
    if net < MIN_NET_EUR:
        return None, [f"net_below_min_eur:{net:.6f}"]
    if net_bps < MIN_NET_BPS_ON_STAKE:
        return None, [f"net_below_min_bps:{net_bps:.4f}"]

    lock_seconds = (close - observed).total_seconds() + SETTLEMENT_BUFFER_SECONDS
    event = {
        "event_id": f"betfair|complete_back_dutch|{market_id}|{s.get('observed_at_utc')}",
        "observed_at_utc": s.get("observed_at_utc"),
        "habitat": "betfair_exchange",
        "strategy": "complete_back_dutch",
        "label": s.get("market_name") or market_id,
        "direction": "back every mutually-exclusive exhaustive outcome at stressed prices",
        "required_preallocation_eur": {"Betfair": round(total_stake, 6)},
        "lock_seconds": round(lock_seconds, 3),
        "expected_net_eur": round(net, 8),
        "human_minutes": MANUAL_MINUTES_PER_MARKET,
        "human_minutes_basis": "planning_assumption_single_market_multi_leg_authorization",
        "killer_verdict": "SURVIVES_KILLER",
        "evidence_tier": "executable_shadow",
        "source": "betfair_replay_complete_outcome_dutch_after_two_tick_stress_and_commission",
        "evidence": {
            "market_id": market_id,
            "market_type": s.get("market_type"),
            "commission_rate": COMMISSION_RATE,
            "adverse_ticks_each_leg": ADVERSE_TICKS,
            "raw_snapshot_selection_count": len(parsed),
            "stressed_inverse_odds_sum": round(q, 10),
            "total_stake_eur": round(total_stake, 6),
            "guaranteed_return_eur": round(guaranteed_return, 6),
            "gross_profit_eur": round(gross_profit, 6),
            "commission_eur": round(commission, 6),
            "net_bps_on_stake": round(net_bps, 4),
            "legs": [
                {
                    "selection_id": x["selection_id"],
                    "name": x["name"],
                    "raw_price": x["raw_price"],
                    "stressed_price": x["stressed_price"],
                    "available_size_eur": x["available_size_eur"],
                    "stake_eur": round(x["stake_eur"], 6),
                }
                for x in stakes
            ],
        },
    }
    validation = validate_event(event)
    if validation:
        return None, ["event_validation:" + ",".join(validation)]
    return event, []


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source = Path(os.environ.get("BETFAIR_REPLAY_SOURCE", str(DEFAULT_SOURCE)))
    rows, bad_json = read_jsonl(source)
    accepted = []
    rejected = list(bad_json)

    for idx, row in enumerate(rows, 1):
        event, errors = evaluate_snapshot(row)
        if event:
            accepted.append(event)
        else:
            rejected.append({
                "line": idx,
                "market_id": row.get("market_id"),
                "observed_at_utc": row.get("observed_at_utc"),
                "errors": errors,
            })

    seen = existing_inbox_ids()
    new_rows = [x for x in accepted if x["event_id"] not in seen]
    append_inbox(new_rows)

    payload = {
        "generated_at_utc": now,
        "status": "REPLAY_SURVIVORS_FOUND" if accepted else ("AWAITING_REPLAY" if not rows else "NO_REPLAY_SURVIVORS"),
        "source": str(source),
        "snapshots_seen": len(rows),
        "survivors": len(accepted),
        "new_events_written_to_betfair_inbox": len(new_rows),
        "rejected": len(rejected),
        "rejection_sample": rejected[:25],
        "policy": {
            "commission_rate": COMMISSION_RATE,
            "adverse_ticks_each_leg": ADVERSE_TICKS,
            "reference_budget_eur": REFERENCE_BUDGET_EUR,
            "min_net_eur": MIN_NET_EUR,
            "min_net_bps_on_stake": MIN_NET_BPS_ON_STAKE,
            "complete_outcome_set_required": True,
            "displayed_liquidity_cap_required": True,
            "market_close_required_for_capital_lock": True,
        },
        "orders_enabled": False,
        "live_credentials_used": False,
        "safety": "historical/replay research only; no betting or fund movement",
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"betfair replay: {payload['status']} survivors={len(accepted)} new={len(new_rows)}")


if __name__ == "__main__":
    main()
