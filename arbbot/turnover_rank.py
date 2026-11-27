#!/usr/bin/env python3
"""Rank executable-shadow events by net EUR per capital-hour.

Research only. This module never places orders, moves funds, signs, or holds credentials.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from opportunity_event import validate_event

ROOT=Path(__file__).resolve().parent
DATA=ROOT/"data"
INBOX=DATA/"opportunity_events.jsonl"
OUT=DATA/"turnover_rank.json"
CAPITAL=250.0
TARGET_MONTHLY=100.0

def load_events():
    if not INBOX.exists(): return []
    out=[]
    for line in INBOX.read_text(encoding="utf-8").splitlines():
        try:
            e=json.loads(line)
            if not validate_event(e): out.append(e)
        except Exception: pass
    return out

def main():
    ranked=[]
    for e in load_events():
        locked=sum(float(x) for x in (e.get("required_preallocation_eur") or {}).values())
        seconds=max(float(e.get("lock_seconds") or 0),1.0)
        net=float(e.get("expected_net_eur") or 0)
        if locked<=0 or locked>CAPITAL or net<=0: continue
        capital_hours=locked*seconds/3600.0
        eur_per_capital_hour=net/capital_hours
        monthly_capacity=eur_per_capital_hour*CAPITAL*24*30
        x=dict(e)
        x.update({
          "locked_capital_eur":round(locked,6),
          "capital_hours":round(capital_hours,6),
          "net_eur_per_capital_hour":round(eur_per_capital_hour,9),
          "idealized_monthly_capacity_eur":round(monthly_capacity,2),
          "target_100_idealized_possible":monthly_capacity>=TARGET_MONTHLY,
        })
        ranked.append(x)
    ranked.sort(key=lambda x:x["net_eur_per_capital_hour"],reverse=True)
    payload={
      "generated_at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
      "capital_eur":CAPITAL,
      "target_monthly_net_eur":TARGET_MONTHLY,
      "ranked":ranked,
      "best":ranked[0] if ranked else None,
      "warning":"Idealized capacity is a triage ceiling, not expected profit. Chronological scheduler/KILLER evidence remains authoritative.",
      "safety":"Research/shadow only; no live execution."
    }
    OUT.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print(f"turnover rank: {len(ranked)} eligible events")

if __name__=="__main__": main()
