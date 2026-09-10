#!/usr/bin/env python3
"""
ARBBOT persistence scoreboard.

Rejects one-off quote noise and ranks repeated paper signals over a rolling
window. Sources currently include global CEX, wide cross-CEX, EU CEX, Solana
and funding.

Funding observations are time-bucketed so faster polling improves freshness
without turning highly autocorrelated snapshots into fake independent evidence.
Funding ranking is also current-direction aware so a symbol cannot remain a
strong watch merely by mixing evidence from opposite funding regimes.

A candidate must also have a current observation to remain watch/strong_watch.
Historical persistence is retained for diagnostics, but stale routes are
explicitly degraded to noise so HUNTER does not spend validation budget on a
signal that is no longer present.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "scoreboard.json"
LOOKBACK_HOURS = 48
FUNDING_EVIDENCE_BUCKET_MINUTES = 15
FUNDING_MIN_CURRENT_DIRECTION_STABILITY = 0.50
CURRENT_SIGNAL_MAX_AGE_SECONDS = 900


def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def pct(xs, p):
    if not xs:
        return None
    ys = sorted(xs)
    idx = min(len(ys) - 1, max(0, round((len(ys) - 1) * p)))
    return ys[idx]


def bucket_key(ts, minutes):
    minute = (ts.minute // minutes) * minutes
    return ts.replace(minute=minute, second=0, microsecond=0)


def load_generic_history(filename, cutoff):
    path = DATA / filename
    groups = defaultdict(list)
    if not path.exists():
        return groups
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts = parse_ts(r.get("timestamp_utc", ""))
            if not ts or ts < cutoff:
                continue
            strategy = r.get("strategy", "")
            if not strategy or strategy.endswith("_error"):
                continue
            try:
                edge = float(r["stressed_bps"])
            except Exception:
                continue
            label = r.get("key") or "?"
            groups[f"{strategy}|{label}"].append({
                "ts": ts,
                "edge": edge,
                "candidate": r.get("candidate") == "YES",
                "strategy": strategy,
                "label": label,
                "direction": r.get("direction", ""),
                "venue": r.get("venue", ""),
            })
    return groups


def load_solana(cutoff):
    path = DATA / "history.csv"
    groups = defaultdict(list)
    if not path.exists():
        return groups
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts = parse_ts(r.get("timestamp_utc", ""))
            if not ts or ts < cutoff:
                continue
            try:
                edge = float(r["stressed_bps"])
            except Exception:
                continue
            label = f"{r.get('buy_dex','?')}->{r.get('sell_dex','?')}"
            groups[f"solana_cross_dex|{label}"].append({
                "ts": ts,
                "edge": edge,
                "candidate": r.get("candidate") == "YES",
                "strategy": "solana_cross_dex",
                "label": label,
                "direction": label,
                "venue": "Solana",
            })
    return groups


def load_funding(cutoff):
    path = DATA / "funding_history.csv"
    groups = defaultdict(list)
    bucketed = {}
    if not path.exists():
        return groups
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts = parse_ts(r.get("timestamp_utc", ""))
            if not ts or ts < cutoff:
                continue
            try:
                edge = abs(float(r["spread_bps_per_8h"]))
            except Exception:
                continue
            label = r.get("symbol", "?")
            key = f"funding_spread|{label}"
            obs = {
                "ts": ts,
                "edge": edge,
                "candidate": r.get("candidate") == "YES",
                "strategy": "funding_spread",
                "label": label,
                "direction": r.get("direction", ""),
                "venue": "Bitget<->Gate",
            }
            # Keep the latest snapshot in each 15-minute bucket. This preserves
            # current-regime sensitivity while preventing 2-5 minute polling from
            # multiplying statistical evidence.
            b = bucket_key(ts, FUNDING_EVIDENCE_BUCKET_MINUTES)
            slot = (key, b)
            prev = bucketed.get(slot)
            if prev is None or ts > prev["ts"]:
                bucketed[slot] = obs
    for (key, _), obs in bucketed.items():
        groups[key].append(obs)
    return groups


def score_group(key, obs, now=None):
    now = now or datetime.now(timezone.utc)
    obs = sorted(obs, key=lambda x: x["ts"])
    latest = obs[-1]
    latest_age_seconds = max(0.0, (now - latest["ts"].astimezone(timezone.utc)).total_seconds())
    current_signal_fresh = latest_age_seconds <= CURRENT_SIGNAL_MAX_AGE_SECONDS

    # Funding spread direction can flip while the absolute spread stays large.
    # For ranking purposes, only observations aligned with the CURRENT direction
    # are allowed to contribute to persistence/magnitude. We still retain total
    # observations and expose direction stability as a diagnostic. This is a
    # tightening/noise-rejection change: it cannot manufacture new candidates.
    scoring_obs = obs
    current_direction_stability = None
    if latest["strategy"] == "funding_spread":
        current_direction = latest.get("direction", "")
        aligned = [x for x in obs if x.get("direction", "") == current_direction]
        current_direction_stability = len(aligned) / len(obs) if obs else 0.0
        scoring_obs = aligned

    xs = [x["edge"] for x in scoring_obs]
    positives = [x for x in scoring_obs if x["candidate"] and x["edge"] > 0]
    positive_edges = [x["edge"] for x in positives]
    persistence = len(positives) / len(obs) if obs else 0

    repeated = len(obs) >= 4 and len(positives) >= 3
    med = median(positive_edges) if positive_edges else 0.0
    p90 = pct(positive_edges, 0.90) or 0.0

    magnitude = min(1.0, max(0.0, med) / 20.0)
    sample = min(1.0, len(obs) / 12.0)
    research_score = 100 * (0.55 * persistence + 0.25 * magnitude + 0.20 * sample)

    classification = "noise"
    direction_ok = (
        latest["strategy"] != "funding_spread"
        or current_direction_stability is not None
        and current_direction_stability >= FUNDING_MIN_CURRENT_DIRECTION_STABILITY
    )
    if current_signal_fresh and repeated and direction_ok and persistence >= 0.70 and med > 0:
        classification = "strong_watch"
    elif current_signal_fresh and repeated and direction_ok and persistence >= 0.40 and med > 0:
        classification = "watch"

    result = {
        "key": key,
        "strategy": latest["strategy"],
        "label": latest["label"],
        "direction": latest["direction"],
        "venue": latest["venue"],
        "observations": len(obs),
        "positive_observations": len(positives),
        "persistence": round(persistence, 4),
        "median_positive_edge_bps": round(med, 4),
        "p90_positive_edge_bps": round(p90, 4),
        "max_edge_bps": round(max(xs), 4) if xs else None,
        "latest_edge_bps": round(latest["edge"], 4),
        "research_score": round(research_score, 2),
        "classification": classification,
        "last_seen_utc": latest["ts"].isoformat(),
        "latest_age_seconds": round(latest_age_seconds, 1),
        "current_signal_fresh": current_signal_fresh,
    }
    if latest["strategy"] == "funding_spread":
        result["current_direction_stability"] = round(current_direction_stability or 0.0, 4)
        result["current_direction_observations"] = len(scoring_obs)
        result["direction_stability_required_for_watch"] = FUNDING_MIN_CURRENT_DIRECTION_STABILITY
    return result


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)

    merged = defaultdict(list)
    sources = [
        load_generic_history("market_history.csv", cutoff),
        load_generic_history("wide_cex_history.csv", cutoff),
        load_generic_history("eu_history.csv", cutoff),
        load_solana(cutoff),
        load_funding(cutoff),
    ]
    for source in sources:
        for k, v in source.items():
            merged[k].extend(v)

    ranked = [score_group(k, v, now=now) for k, v in merged.items()]
    ranked.sort(
        key=lambda x: (
            x["classification"] == "strong_watch",
            x["classification"] == "watch",
            x["current_signal_fresh"],
            x["research_score"],
        ),
        reverse=True,
    )

    out = {
        "generated_at_utc": now.isoformat(timespec="seconds"),
        "lookback_hours": LOOKBACK_HOURS,
        "funding_evidence_bucket_minutes": FUNDING_EVIDENCE_BUCKET_MINUTES,
        "funding_min_current_direction_stability": FUNDING_MIN_CURRENT_DIRECTION_STABILITY,
        "current_signal_max_age_seconds": CURRENT_SIGNAL_MAX_AGE_SECONDS,
        "strong_watch_count": sum(x["classification"] == "strong_watch" for x in ranked),
        "watch_count": sum(x["classification"] == "watch" for x in ranked),
        "stale_candidate_count": sum(not x["current_signal_fresh"] for x in ranked),
        "best": ranked[0] if ranked else None,
        "ranked": ranked,
        "interpretation": (
            "This is a noise-rejection research score, not a forecast or guarantee. "
            "Funding evidence is time-bucketed to avoid pseudo-replication from faster polling, "
            "funding ranking uses only observations aligned with the current direction so opposite "
            "regimes cannot inflate persistence or magnitude, and stale routes cannot remain "
            "watch/strong_watch after their current signal disappears. Only repeated, current "
            "signals are promoted. Live profitability still requires execution-specific fee, "
            "slippage, latency, capital and risk validation."
        ),
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    if ranked:
        b = ranked[0]
        print(
            f"BEST {b['classification']} {b['key']} "
            f"score={b['research_score']:.1f} persistence={b['persistence']:.2f} "
            f"fresh={b['current_signal_fresh']}"
        )
    else:
        print("No history yet.")


if __name__ == "__main__":
    main()
