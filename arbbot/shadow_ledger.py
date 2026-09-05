#!/usr/bin/env python3
"""
ARBBOT shadow ledger.

Records a conservative paper canary whenever a candidate has reached the
pre-live gate. This creates an auditable record of whether ARBBOT's own
selection policy would have kept producing positive net paper outcomes.

No live orders. No credentials. No funds.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DECISION = DATA / "decision.json"
DEPTH = DATA / "depth_validation.json"
LEDGER = DATA / "shadow_trades.csv"
SUMMARY = DATA / "shadow_summary.json"

FIELDS = [
    "recorded_at_utc", "signal_id", "strategy", "label", "direction",
    "source_edge_bps", "paper_capital", "paper_pnl", "source"
]

def load_rows():
    if not LEDGER.exists():
        return []
    with LEDGER.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))

def append(row):
    exists = LEDGER.exists()
    with LEDGER.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(row)

def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = load_rows()

    if not DECISION.exists():
        SUMMARY.write_text(json.dumps({"generated_at_utc": now, "trades": len(rows), "reason": "decision missing"}, indent=2), encoding="utf-8")
        return

    d = json.loads(DECISION.read_text(encoding="utf-8"))
    selected = d.get("selected") or {}
    state = d.get("state")

    # Record canaries once the base research gates are strong enough to reach VALIDATE/READY.
    if state in {"VALIDATE", "READY_FOR_MANUAL_AUTHORIZATION"} and selected:
        strategy = selected.get("strategy") or ""
        label = selected.get("label") or ""
        signal_id = f"{strategy}|{label}|{selected.get('last_seen_utc','')}"
        seen = {r.get("signal_id") for r in rows}

        if signal_id not in seen:
            capital = 100.0
            edge = float(selected.get("latest_edge_bps") or 0)
            pnl = None
            source = "latest_stressed_edge_50pct_realization"

            # Prefer the depth simulation when it belongs to the same cross-venue signal.
            if DEPTH.exists():
                try:
                    dv = json.loads(DEPTH.read_text(encoding="utf-8"))
                    same = (
                        (dv.get("selected") or {}).get("strategy") == strategy
                        and (dv.get("selected") or {}).get("label") == label
                    )
                    row100 = next((x for x in (dv.get("rows") or []) if x.get("total_budget") == 100), None)
                    if same and row100:
                        pnl = float(row100["paper_pnl"])
                        edge = float(row100["paper_pnl_bps_on_total_capital"])
                        source = "depth_vwap_after_fees"
                except Exception:
                    pass

            if pnl is None:
                # Deliberately realize only half the already-stressed edge.
                pnl = capital * edge / 10000 * 0.5

            rec = {
                "recorded_at_utc": now,
                "signal_id": signal_id,
                "strategy": strategy,
                "label": label,
                "direction": selected.get("direction") or "",
                "source_edge_bps": f"{edge:.6f}",
                "paper_capital": f"{capital:.2f}",
                "paper_pnl": f"{pnl:.6f}",
                "source": source,
            }
            append(rec)
            rows.append(rec)

    grouped = {}
    for r in rows:
        key = f"{r['strategy']}|{r['label']}"
        grouped.setdefault(key, []).append(r)

    ranking = []
    for key, rs in grouped.items():
        pnls = [float(x["paper_pnl"]) for x in rs]
        ranking.append({
            "key": key,
            "count": len(rs),
            "positive_count": sum(x > 0 for x in pnls),
            "positive_rate": round(sum(x > 0 for x in pnls) / len(pnls), 4),
            "cumulative_paper_pnl": round(sum(pnls), 6),
            "median_paper_pnl": round(median(pnls), 6),
            "last_recorded_at_utc": rs[-1]["recorded_at_utc"],
        })
    ranking.sort(key=lambda x: (x["positive_rate"], x["count"], x["cumulative_paper_pnl"]), reverse=True)

    SUMMARY.write_text(json.dumps({
        "generated_at_utc": now,
        "total_shadow_trades": len(rows),
        "best": ranking[0] if ranking else None,
        "ranked": ranking,
        "warning": "Shadow PnL is still simulated and is not proof of live fill performance."
    }, indent=2), encoding="utf-8")
    print(f"shadow trades={len(rows)}")

if __name__ == "__main__":
    main()
