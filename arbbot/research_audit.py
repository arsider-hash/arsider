#!/usr/bin/env python3
"""ARBBOT research-quality audit.

Read-only diagnostic layer. It never promotes candidates, changes strategy gates,
places orders, signs transactions, or moves funds. It makes hidden weaknesses
visible: stale feeds, KILLER disagreement, missing multi-size execution evidence,
and economically trivial small-capital outcomes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "research_audit.json"
MAX_FEED_AGE_SECONDS = 900
REQUIRED_BUDGETS = [25, 50, 100, 250, 500, 1000]
FEEDS = {
    "health.json": "unified_lab_utc",
    "market_latest.json": "generated_at_utc",
    "eu_latest.json": "generated_at_utc",
    "funding_latest.json": "generated_at_utc",
    "latest.json": "generated_at_utc",
    "yield_latest.json": "generated_at_utc",
    "scoreboard.json": "generated_at_utc",
    "capital_rank.json": "generated_at_utc",
    "validation.json": "generated_at_utc",
    "depth_validation.json": "generated_at_utc",
    "killer_report.json": "generated_at_utc",
    "killer_funding_report.json": "generated_at_utc",
    "shadow_summary.json": "generated_at_utc",
    "decision.json": "generated_at_utc",
}


def load(name):
    p = DATA / name
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except Exception:
        return None


def parse_ts(value):
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def age_seconds(value, now):
    d = parse_ts(value)
    return None if not d else max(0.0, (now - d.astimezone(timezone.utc)).total_seconds())


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def funding_probe(doc, symbol, direction):
    for obj in walk(doc or {}):
        if obj.get("symbol") == symbol and obj.get("direction") == direction:
            probe = obj.get("executable_entry_probe")
            if isinstance(probe, dict):
                return probe
    return None


def main():
    now = datetime.now(timezone.utc)
    anomalies = []
    feed_health = {}
    for name, field in FEEDS.items():
        doc = load(name)
        stamp = (doc or {}).get(field)
        age = age_seconds(stamp, now)
        status = "missing" if doc is None else "timestamp_missing" if age is None else "stale" if age > MAX_FEED_AGE_SECONDS else "fresh"
        feed_health[name] = {"status": status, "age_seconds": None if age is None else round(age, 1), "timestamp_field": field, "timestamp": stamp}
        if status != "fresh":
            anomalies.append({"type": "feed_health", "severity": "hard" if name in {"funding_latest.json", "killer_report.json", "decision.json"} else "warning", "detail": f"{name}: {status}"})

    killer = load("killer_report.json") or {}
    fkiller = load("killer_funding_report.json") or {}
    ks = killer.get("selected") or {}
    fs = fkiller.get("selected") or {}
    if ks and fs and ks.get("strategy") == "funding_spread":
        same = (ks.get("strategy"), ks.get("label"), ks.get("direction")) == (fs.get("strategy"), fs.get("label"), fs.get("direction"))
        if not same or killer.get("verdict") != fkiller.get("verdict"):
            anomalies.append({"type": "killer_divergence", "severity": "hard", "detail": {"primary": {"selected": ks, "verdict": killer.get("verdict")}, "funding": {"selected": fs, "verdict": fkiller.get("verdict")}}})

    multi_size = None
    if ks.get("strategy") == "funding_spread" and ks.get("label"):
        probe = funding_probe(load("funding_latest.json"), ks.get("label"), ks.get("direction"))
        rows = (probe or {}).get("rows") or []
        by_budget = {int(float(r.get("total_budget_eur_approx") or 0)): r for r in rows}
        multi_size = {}
        for budget in REQUIRED_BUDGETS:
            row = by_budget.get(budget)
            sufficient = bool(row and row.get("depth_sufficient_both_legs"))
            periods = None if not row else row.get("funding_periods_to_overcome_adverse_executable_basis")
            multi_size[str(budget)] = {"present": row is not None, "depth_sufficient_both_legs": sufficient, "recovery_periods": periods}
            if row is None or not sufficient:
                anomalies.append({"type": "funding_capacity", "severity": "warning" if budget > 250 else "hard", "detail": f"EUR {budget} executable probe missing/insufficient for {ks.get('label')}"})

    rank = load("capital_rank.json") or {}
    best = rank.get("best")
    economics = None
    if best:
        economics = {}
        for budget in [100, 250, 500, 1000]:
            e = (best.get("paper_economics") or {}).get(str(budget)) or {}
            payoff = e.get("paper_daily_carry_if_persistence_continues", e.get("paper_profit_per_event_at_median_edge"))
            economics[str(budget)] = payoff
        ref = economics.get("250")
        if ref is not None and float(ref) < 0.25:
            anomalies.append({"type": "economic_triviality", "severity": "warning", "detail": f"best candidate paper payoff at EUR 250 is only EUR {float(ref):.4f} on its reference cadence"})

    out = {
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "mode": "read_only_research_audit",
        "can_promote_candidate": False,
        "feed_health": feed_health,
        "killer_alignment": {"primary_verdict": killer.get("verdict"), "funding_verdict": fkiller.get("verdict"), "primary_selected": ks, "funding_selected": fs},
        "funding_multi_size_execution": multi_size,
        "best_candidate_small_capital_payoff": economics,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "safety": "Diagnostic only. An audit PASS cannot create READY and cannot bypass KILLER or manual authorization."
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"research audit anomalies={len(anomalies)}")


if __name__ == "__main__":
    main()
