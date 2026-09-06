#!/usr/bin/env python3
"""ARBBOT adversarial KILLER. Read-only research/falsification; never executes trades."""
from __future__ import annotations
import csv, json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median
ROOT=Path(__file__).resolve().parent; DATA=ROOT/'data'
DECISION=DATA/'decision.json'; CAPITAL_RANK=DATA/'capital_rank.json'; VALIDATION=DATA/'validation.json'; DEPTH_VALIDATION=DATA/'depth_validation.json'; SHADOW_SUMMARY=DATA/'shadow_summary.json'; FUNDING_BASIS_HISTORY=DATA/'funding_basis_history.csv'
TARGET_STRATEGY=os.environ.get('KILLER_STRATEGY','').strip(); OUT=DATA/os.environ.get('KILLER_OUT','killer_report.json')
FAST_STRATEGIES={'cex_cross_spot','eu_cross_spot','cex_triangle','eur_triangle','stable_dislocation','stable_eur_dislocation'}; DEPTH_STRATEGIES={'cex_cross_spot','eu_cross_spot'}
MAX_STALENESS_SECONDS=900; MIN_USEFUL_DEPTH_BUDGET=250; MIN_FUNDING_BASIS_SAMPLES=4; FUNDING_BASIS_LOOKBACK_HOURS=48; MAX_MEDIAN_ADVERSE_BASIS_PERIODS=3.0

def load_json(p):
 try:return json.loads(p.read_text()) if p.exists() else None
 except:return None

def same_route(doc,s):
 x=(doc or {}).get('selected') or {}; return x.get('strategy')==s.get('strategy') and x.get('label')==s.get('label')
def selected_candidate():
 if TARGET_STRATEGY:
  ranked=(load_json(CAPITAL_RANK) or {}).get('ranked') or []
  matches=[x for x in ranked if x.get('strategy')==TARGET_STRATEGY]
  return max(matches,key=lambda x:(float(x.get('economic_relevance_score') or 0),float(x.get('research_score') or 0)),default=None)
 d=load_json(DECISION) or {}
 return d.get('selected') or (load_json(CAPITAL_RANK) or {}).get('best')
def parse_ts(v):
 try:
  d=datetime.fromisoformat(str(v).replace('Z','+00:00')); return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
 except:return None
def age_seconds(v):
 d=parse_ts(v); return None if not d else max(0,(datetime.now(timezone.utc)-d.astimezone(timezone.utc)).total_seconds())
def add(c,n,s,d,severity='hard'):c.append({'check':n,'status':s,'severity':severity,'detail':d})
def funding_basis_samples(symbol):
 if not FUNDING_BASIS_HISTORY.exists():return []
 cutoff=datetime.now(timezone.utc)-timedelta(hours=FUNDING_BASIS_LOOKBACK_HOURS); out=[]
 try:
  for r in csv.DictReader(FUNDING_BASIS_HISTORY.open()):
   if r.get('symbol')!=symbol:continue
   ts=parse_ts(r.get('timestamp_utc'))
   if not ts or ts<cutoff:continue
   try: out.append({'direction':r.get('direction',''),'aligned_basis_bps':float(r.get('aligned_basis_bps') or 0),'adverse_periods':float(r.get('periods_to_overcome_adverse_basis') or 0)})
   except:pass
 except:return []
 return out

def main():
 now=datetime.now(timezone.utc).isoformat(timespec='seconds'); s=selected_candidate()
 if not s:
  OUT.write_text(json.dumps({'generated_at_utc':now,'verdict':'NO_CANDIDATE','selected':None,'checks':[],'hard_failures':[],'insufficient_evidence':['no selected candidate'],'target_strategy':TARGET_STRATEGY or None},indent=2)); return
 c=[]; strategy=s.get('strategy'); obs=int(s.get('observations') or 0); pos=int(s.get('positive_observations') or 0); persistence=float(s.get('persistence') or 0); med=float(s.get('median_positive_edge_bps') or 0); latest=float(s.get('latest_edge_bps') or 0); relevance=float(s.get('economic_relevance_score') or 0)
 age=age_seconds(s.get('last_seen_utc')); add(c,'freshness','INSUFFICIENT' if age is None else 'FAIL' if age>MAX_STALENESS_SECONDS else 'PASS','candidate timestamp missing or invalid' if age is None else f'candidate age {age:.0f}s')
 add(c,'sample_presence','PASS' if obs>0 else 'FAIL',f'{obs} observations')
 add(c,'positive_edge_evidence','PASS' if pos>0 and med>0 else 'FAIL',f'positive_observations={pos}, median_positive_edge_bps={med:.4f}')
 add(c,'persistence','PASS' if persistence>0 else 'FAIL',f'persistence={persistence:.3f}')
 add(c,'latest_edge_sign','PASS' if latest>0 else 'WARN',f'latest_edge_bps={latest:.4f}',severity='soft')
 add(c,'economic_relevance','PASS' if relevance>0 else 'WARN',f'economic_relevance_score={relevance:.2f}',severity='soft')
 v=load_json(VALIDATION)
 if strategy in FAST_STRATEGIES:add(c,'burst_validation','INSUFFICIENT' if not v or not same_route(v,s) else 'PASS' if v.get('verdict')=='SURVIVES_BURST' else 'FAIL','no matching burst validation' if not v or not same_route(v,s) else f"verdict={v.get('verdict')}")
 if strategy=='stable_dislocation':add(c,'verified_exit_path','INSUFFICIENT','peg deviation is not executable profit until a concrete redemption/convergence exit path, fees and settlement friction are verified')
 depth=load_json(DEPTH_VALIDATION)
 if strategy in DEPTH_STRATEGIES:
  if not depth or not same_route(depth,s):add(c,'depth_validation','INSUFFICIENT','no matching depth validation'); add(c,'multi_size_capacity','INSUFFICIENT','no matching multi-size depth curve')
  elif depth.get('state')!='PASS':add(c,'depth_validation','FAIL',f"state={depth.get('state')}")
  else:
   add(c,'depth_validation','PASS','order-book depth PASS'); cap=depth.get('capacity') or {}; mb=int(cap.get('max_positive_budget') or 0); add(c,'multi_size_capacity','PASS' if mb>=MIN_USEFUL_DEPTH_BUDGET else 'FAIL',f'positive through budget={mb}; need at least {MIN_USEFUL_DEPTH_BUDGET}')
 if strategy=='funding_spread':
  x=funding_basis_samples(s.get('label'))
  if len(x)<MIN_FUNDING_BASIS_SAMPLES:add(c,'funding_basis_persistence','INSUFFICIENT',f'only {len(x)} basis samples; need {MIN_FUNDING_BASIS_SAMPLES}')
  else:
   mp=median([z['adverse_periods'] for z in x]); ma=median([z['aligned_basis_bps'] for z in x]); rate=sum(z['direction']==s.get('direction','') for z in x)/len(x)
   add(c,'funding_basis_persistence','FAIL' if mp>MAX_MEDIAN_ADVERSE_BASIS_PERIODS else 'PASS',f'{len(x)} samples; median adverse basis costs {mp:.2f} funding periods; median aligned basis={ma:.3f} bps')
   add(c,'funding_direction_stability','PASS' if rate>=.5 else 'WARN',f'latest funding direction matches {rate:.0%} of basis samples',severity='soft')
 sh=load_json(SHADOW_SUMMARY) or {}; key=f"{s.get('strategy')}|{s.get('label')}"; item=next((x for x in sh.get('ranked',[]) if x.get('key')==key),None)
 if item:
  count=int(item.get('count') or 0); rate=float(item.get('positive_rate') or 0); pnl=float(item.get('cumulative_paper_pnl') or 0); add(c,'shadow_evidence','PASS' if count>=3 and rate>=.67 and pnl>0 else 'WARN',f'count={count}, positive_rate={rate:.3f}, cumulative_paper_pnl={pnl:.6f}',severity='soft')
 else:add(c,'shadow_evidence','INSUFFICIENT','no matching shadow history',severity='soft')
 hf=[x['detail'] for x in c if x['severity']=='hard' and x['status']=='FAIL']; ie=[x['detail'] for x in c if x['severity']=='hard' and x['status']=='INSUFFICIENT']; verdict='REJECTED' if hf else 'INSUFFICIENT_EVIDENCE' if ie else 'SURVIVES_KILLER'
 OUT.write_text(json.dumps({'generated_at_utc':now,'verdict':verdict,'selected':s,'target_strategy':TARGET_STRATEGY or None,'checks':c,'hard_failures':hf,'insufficient_evidence':ie,'policy':{'max_staleness_seconds':MAX_STALENESS_SECONDS,'min_useful_depth_budget':MIN_USEFUL_DEPTH_BUDGET,'min_funding_basis_samples':MIN_FUNDING_BASIS_SAMPLES,'funding_basis_lookback_hours':FUNDING_BASIS_LOOKBACK_HOURS,'max_median_adverse_basis_periods':MAX_MEDIAN_ADVERSE_BASIS_PERIODS,'principle':'assume false until execution evidence survives adversarial checks'},'hard_boundary':'Research/falsification only; no live execution or custody.'},indent=2)); print(f'KILLER {verdict}: {strategy} {s.get("label")} -> {OUT.name}')
if __name__=='__main__':main()
