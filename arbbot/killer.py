#!/usr/bin/env python3
"""ARBBOT adversarial KILLER. Read-only research/falsification; never executes trades."""
from __future__ import annotations
import csv, json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DECISION = DATA / 'decision.json'
CAPITAL_RANK = DATA / 'capital_rank.json'
VALIDATION = DATA / 'validation.json'
DEPTH_VALIDATION = DATA / 'depth_validation.json'
SHADOW_SUMMARY = DATA / 'shadow_summary.json'
FUNDING_BASIS_HISTORY = DATA / 'funding_basis_history.csv'
FUNDING_LATEST = DATA / 'funding_latest.json'
TARGET_STRATEGY = os.environ.get('KILLER_STRATEGY', '').strip()
OUT = DATA / os.environ.get('KILLER_OUT', 'killer_report.json')
SELECTION_MODE = os.environ.get('KILLER_SELECTION', 'allocator').strip().lower()
FAST_STRATEGIES = {'cex_cross_spot', 'eu_cross_spot', 'cex_triangle', 'eur_triangle', 'stable_dislocation', 'stable_eur_dislocation'}
DEPTH_STRATEGIES = {'cex_cross_spot', 'eu_cross_spot'}
MAX_STALENESS_SECONDS = 900
MIN_CANDIDATE_OBSERVATIONS = 6
MIN_CANDIDATE_PERSISTENCE = 0.70
MIN_USEFUL_DEPTH_BUDGET = 250
MIN_FUNDING_BASIS_SAMPLES = 4
FUNDING_BASIS_LOOKBACK_HOURS = 48
MAX_MEDIAN_ADVERSE_BASIS_PERIODS = 3.0
MIN_FUNDING_LATEST_TO_MEDIAN_RATIO = 0.25
MIN_FUNDING_DIRECTION_STABILITY = 0.50
FUNDING_EVIDENCE_BUCKET_MINUTES = 15
FUNDING_EXECUTION_REFERENCE_BUDGET = 250


def load_json(p):
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except Exception:
        return None


def same_route(doc, s):
    x = (doc or {}).get('selected') or {}
    return x.get('strategy') == s.get('strategy') and x.get('label') == s.get('label')


def selected_candidate():
    if TARGET_STRATEGY:
        ranked = (load_json(CAPITAL_RANK) or {}).get('ranked') or []
        matches = [x for x in ranked if x.get('strategy') == TARGET_STRATEGY]
        if SELECTION_MODE == 'latest_edge':
            return max(matches, key=lambda x: (float(x.get('latest_edge_bps') or 0), float(x.get('economic_relevance_score') or 0), float(x.get('research_score') or 0)), default=None)
        return max(matches, key=lambda x: (float(x.get('economic_relevance_score') or 0), float(x.get('research_score') or 0)), default=None)
    d = load_json(DECISION) or {}
    return d.get('selected') or (load_json(CAPITAL_RANK) or {}).get('best')


def parse_ts(v):
    try:
        d = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def age_seconds(v):
    d = parse_ts(v)
    return None if not d else max(0, (datetime.now(timezone.utc) - d.astimezone(timezone.utc)).total_seconds())


def add(c, n, s, d, severity='hard'):
    c.append({'check': n, 'status': s, 'severity': severity, 'detail': d})


def bucket_key(ts, minutes):
    minute = (ts.minute // minutes) * minutes
    return ts.replace(minute=minute, second=0, microsecond=0)


def funding_basis_samples(symbol):
    if not FUNDING_BASIS_HISTORY.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FUNDING_BASIS_LOOKBACK_HOURS)
    slots = {}
    try:
        for r in csv.DictReader(FUNDING_BASIS_HISTORY.open()):
            if r.get('symbol') != symbol:
                continue
            ts = parse_ts(r.get('timestamp_utc'))
            if not ts or ts < cutoff:
                continue
            try:
                obs = {
                    'ts': ts,
                    'direction': r.get('direction', ''),
                    'aligned_basis_bps': float(r.get('aligned_basis_bps') or 0),
                    'adverse_periods': float(r.get('periods_to_overcome_adverse_basis') or 0),
                }
                slot = bucket_key(ts, FUNDING_EVIDENCE_BUCKET_MINUTES)
                prev = slots.get(slot)
                if prev is None or ts > prev['ts']:
                    slots[slot] = obs
            except Exception:
                pass
    except Exception:
        return []
    return [slots[k] for k in sorted(slots)]


def walk_objects(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_objects(value)


def funding_execution_probe(symbol, direction):
    doc = load_json(FUNDING_LATEST)
    if not doc:
        return None, 'funding_latest.json missing or invalid'
    generated = parse_ts(doc.get('generated_at_utc'))
    if not generated:
        return None, 'funding_latest timestamp missing or invalid'
    age = max(0, (datetime.now(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds())
    if age > MAX_STALENESS_SECONDS:
        return None, f'funding executable probe stale: age={age:.0f}s'
    for obj in walk_objects(doc):
        if obj.get('symbol') != symbol or obj.get('direction') != direction:
            continue
        probe = obj.get('executable_entry_probe')
        if not isinstance(probe, dict):
            continue
        rows = probe.get('rows') or []
        row = next((r for r in rows if int(float(r.get('total_budget_eur_approx') or 0)) == FUNDING_EXECUTION_REFERENCE_BUDGET), None)
        if row:
            return row, None
    return None, f'no matching executable-entry probe at EUR {FUNDING_EXECUTION_REFERENCE_BUDGET} for {symbol} {direction}'


def main():
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    s = selected_candidate()
    if not s:
        OUT.write_text(json.dumps({'generated_at_utc': now, 'verdict': 'NO_CANDIDATE', 'selected': None, 'checks': [], 'hard_failures': [], 'insufficient_evidence': ['no selected candidate'], 'target_strategy': TARGET_STRATEGY or None, 'selection_mode': SELECTION_MODE}, indent=2))
        return

    c = []
    strategy = s.get('strategy')
    obs = int(s.get('observations') or 0)
    pos = int(s.get('positive_observations') or 0)
    persistence = float(s.get('persistence') or 0)
    med = float(s.get('median_positive_edge_bps') or 0)
    latest = float(s.get('latest_edge_bps') or 0)
    relevance = float(s.get('economic_relevance_score') or 0)

    age = age_seconds(s.get('last_seen_utc'))
    add(c, 'freshness', 'INSUFFICIENT' if age is None else 'FAIL' if age > MAX_STALENESS_SECONDS else 'PASS', 'candidate timestamp missing or invalid' if age is None else f'candidate age {age:.0f}s')
    add(c, 'sample_presence', 'PASS' if obs >= MIN_CANDIDATE_OBSERVATIONS else 'INSUFFICIENT', f'{obs} observations; need at least {MIN_CANDIDATE_OBSERVATIONS}')
    add(c, 'positive_edge_evidence', 'PASS' if pos > 0 and med > 0 else 'FAIL', f'positive_observations={pos}, median_positive_edge_bps={med:.4f}')
    add(c, 'persistence', 'PASS' if persistence >= MIN_CANDIDATE_PERSISTENCE else 'INSUFFICIENT', f'persistence={persistence:.3f}; need at least {MIN_CANDIDATE_PERSISTENCE:.2f}')
    add(c, 'latest_edge_sign', 'PASS' if latest > 0 else 'WARN', f'latest_edge_bps={latest:.4f}', severity='soft')
    add(c, 'economic_relevance', 'PASS' if relevance > 0 else 'WARN', f'economic_relevance_score={relevance:.2f}', severity='soft')

    v = load_json(VALIDATION)
    if strategy in FAST_STRATEGIES:
        add(c, 'burst_validation', 'INSUFFICIENT' if not v or not same_route(v, s) else 'PASS' if v.get('verdict') == 'SURVIVES_BURST' else 'FAIL', 'no matching burst validation' if not v or not same_route(v, s) else f"verdict={v.get('verdict')}")
    if strategy == 'stable_dislocation':
        add(c, 'verified_exit_path', 'INSUFFICIENT', 'peg deviation is not executable profit until a concrete redemption/convergence exit path, fees and settlement friction are verified')

    depth = load_json(DEPTH_VALIDATION)
    if strategy in DEPTH_STRATEGIES:
        if not depth or not same_route(depth, s):
            add(c, 'depth_validation', 'INSUFFICIENT', 'no matching depth validation')
            add(c, 'multi_size_capacity', 'INSUFFICIENT', 'no matching multi-size depth curve')
        elif depth.get('state') != 'PASS':
            add(c, 'depth_validation', 'FAIL', f"state={depth.get('state')}")
        else:
            add(c, 'depth_validation', 'PASS', 'order-book depth PASS')
            cap = depth.get('capacity') or {}
            mb = int(cap.get('max_positive_budget') or 0)
            add(c, 'multi_size_capacity', 'PASS' if mb >= MIN_USEFUL_DEPTH_BUDGET else 'FAIL', f'positive through budget={mb}; need at least {MIN_USEFUL_DEPTH_BUDGET}')

    if strategy == 'funding_spread':
        ratio = (latest / med) if med > 0 else 0.0
        add(c, 'funding_regime_decay', 'PASS' if ratio >= MIN_FUNDING_LATEST_TO_MEDIAN_RATIO else 'INSUFFICIENT', f'latest/median edge ratio={ratio:.3f}; latest={latest:.3f} bps/8h, median={med:.3f}; require >= {MIN_FUNDING_LATEST_TO_MEDIAN_RATIO:.2f} to rule out sharp edge decay')
        x = funding_basis_samples(s.get('label'))
        if len(x) < MIN_FUNDING_BASIS_SAMPLES:
            add(c, 'funding_basis_persistence', 'INSUFFICIENT', f'only {len(x)} independent {FUNDING_EVIDENCE_BUCKET_MINUTES}m basis buckets; need {MIN_FUNDING_BASIS_SAMPLES}')
        else:
            mp = median([z['adverse_periods'] for z in x])
            ma = median([z['aligned_basis_bps'] for z in x])
            rate = sum(z['direction'] == s.get('direction', '') for z in x) / len(x)
            add(c, 'funding_basis_persistence', 'FAIL' if mp > MAX_MEDIAN_ADVERSE_BASIS_PERIODS else 'PASS', f'{len(x)} independent {FUNDING_EVIDENCE_BUCKET_MINUTES}m buckets; median adverse basis costs {mp:.2f} funding periods; median aligned basis={ma:.3f} bps')
            add(c, 'funding_direction_stability', 'PASS' if rate >= MIN_FUNDING_DIRECTION_STABILITY else 'INSUFFICIENT', f'latest funding direction matches {rate:.0%} of independent basis buckets; require >= {MIN_FUNDING_DIRECTION_STABILITY:.0%}')

        probe, probe_error = funding_execution_probe(s.get('label'), s.get('direction'))
        if probe_error:
            add(c, 'funding_executable_entry', 'INSUFFICIENT', probe_error)
        else:
            depth_ok = bool(probe.get('depth_sufficient_both_legs'))
            periods = float(probe.get('funding_periods_to_overcome_adverse_executable_basis') or 0)
            adverse_bps = float(probe.get('adverse_executable_entry_basis_bps') or 0)
            if not depth_ok:
                add(c, 'funding_executable_entry', 'FAIL', f'EUR {FUNDING_EXECUTION_REFERENCE_BUDGET} depth insufficient on at least one leg')
            elif periods <= 0:
                add(c, 'funding_executable_entry', 'INSUFFICIENT', f'EUR {FUNDING_EXECUTION_REFERENCE_BUDGET} executable basis recovery period missing/invalid')
            else:
                add(c, 'funding_executable_entry', 'FAIL' if periods > MAX_MEDIAN_ADVERSE_BASIS_PERIODS else 'PASS', f'EUR {FUNDING_EXECUTION_REFERENCE_BUDGET} executable adverse basis={adverse_bps:.3f} bps, recovery={periods:.2f} funding periods; require <= {MAX_MEDIAN_ADVERSE_BASIS_PERIODS:.2f}')

    sh = load_json(SHADOW_SUMMARY) or {}
    key = f"{s.get('strategy')}|{s.get('label')}"
    item = next((x for x in sh.get('ranked', []) if x.get('key') == key), None)
    if item:
        count = int(item.get('count') or 0)
        rate = float(item.get('positive_rate') or 0)
        pnl = float(item.get('cumulative_paper_pnl') or 0)
        add(c, 'shadow_evidence', 'PASS' if count >= 3 and rate >= .67 and pnl > 0 else 'WARN', f'count={count}, positive_rate={rate:.3f}, cumulative_paper_pnl={pnl:.6f}', severity='soft')
    else:
        add(c, 'shadow_evidence', 'INSUFFICIENT', 'no matching shadow history', severity='soft')

    hf = [x['detail'] for x in c if x['severity'] == 'hard' and x['status'] == 'FAIL']
    ie = [x['detail'] for x in c if x['severity'] == 'hard' and x['status'] == 'INSUFFICIENT']
    verdict = 'REJECTED' if hf else 'INSUFFICIENT_EVIDENCE' if ie else 'SURVIVES_KILLER'
    OUT.write_text(json.dumps({
        'generated_at_utc': now,
        'verdict': verdict,
        'selected': s,
        'target_strategy': TARGET_STRATEGY or None,
        'selection_mode': SELECTION_MODE,
        'checks': c,
        'hard_failures': hf,
        'insufficient_evidence': ie,
        'policy': {
            'max_staleness_seconds': MAX_STALENESS_SECONDS,
            'min_candidate_observations': MIN_CANDIDATE_OBSERVATIONS,
            'min_candidate_persistence': MIN_CANDIDATE_PERSISTENCE,
            'min_useful_depth_budget': MIN_USEFUL_DEPTH_BUDGET,
            'min_funding_basis_samples': MIN_FUNDING_BASIS_SAMPLES,
            'funding_basis_lookback_hours': FUNDING_BASIS_LOOKBACK_HOURS,
            'funding_evidence_bucket_minutes': FUNDING_EVIDENCE_BUCKET_MINUTES,
            'max_median_adverse_basis_periods': MAX_MEDIAN_ADVERSE_BASIS_PERIODS,
            'min_funding_latest_to_median_ratio': MIN_FUNDING_LATEST_TO_MEDIAN_RATIO,
            'min_funding_direction_stability': MIN_FUNDING_DIRECTION_STABILITY,
            'funding_execution_reference_budget_eur': FUNDING_EXECUTION_REFERENCE_BUDGET,
            'principle': 'assume false until execution evidence survives adversarial checks',
        },
        'hard_boundary': 'Research/falsification only; no live execution or custody.',
    }, indent=2))
    print(f'KILLER {verdict}: {strategy} {s.get("label")} -> {OUT.name}')


if __name__ == '__main__':
    main()
