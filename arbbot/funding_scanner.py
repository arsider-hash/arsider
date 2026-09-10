#!/usr/bin/env python3
"""
ARBBOT funding-rate + cross-venue basis scout.
Read-only public market data only.

Builds a dynamic liquid universe of USDT perpetuals shared by Bitget and Gate,
then compares normalized funding and contemporaneous mark-price basis.
The universe is re-discovered on every run so HUNTER follows current listings
instead of a hard-coded BTC/ETH/SOL subset.

Funding candidates are also probed against public order books at small-capital
sizes. These executable-entry diagnostics are best-effort research evidence:
they never promote a candidate by themselves and failures remain conservative.

Legacy CSV column names are retained for backward compatibility. Basis history
is stored separately so old funding_history.csv files remain readable.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
LATEST = DATA / "funding_latest.json"
HISTORY = DATA / "funding_history.csv"
BASIS_HISTORY = DATA / "funding_basis_history.csv"

CORE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
MAX_DYNAMIC_SYMBOLS = 40
MIN_SHARED_NOTIONAL_24H_USDT = 2_000_000.0
ROUND_TRIP_COST_BPS = 30.0
WATCH_SPREAD_BPS_PER_8H = 2.0
DEPTH_BUDGETS_EUR = [25, 50, 100, 250, 500, 1000]

FIELDS = [
    "timestamp_utc", "symbol", "direction",
    "binance_rate", "binance_interval_hours",
    "bybit_rate", "bybit_interval_hours",
    "spread_bps_per_hour", "spread_bps_per_8h",
    "rough_annualized_pct", "breakeven_8h_periods",
    "candidate"
]
BASIS_FIELDS = [
    "timestamp_utc", "symbol", "direction", "spread_bps_per_8h",
    "aligned_basis_bps", "adverse_basis_bps",
    "periods_to_overcome_adverse_basis", "candidate"
]


def get_json(url: str, retries: int = 3):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "arsider-arbbot/1.3",
    })
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(1.25 * (attempt + 1))
    raise RuntimeError(str(last))


def q(url, **params):
    return url + "?" + urllib.parse.urlencode(params)


def normalize_symbol(s: str) -> str:
    return str(s or "").upper().replace("_", "").replace("-", "")


def gate_contract(symbol: str) -> str:
    """Return Gate's contract identifier, safely encoded for URL path use."""
    contract = symbol.replace("USDT", "_USDT")
    return urllib.parse.quote(contract, safe="")


def bitget_liquid_universe() -> dict[str, float]:
    d = get_json(q(
        "https://api.bitget.com/api/v2/mix/market/tickers",
        productType="USDT-FUTURES",
    ))
    if d.get("code") != "00000" or not isinstance(d.get("data"), list):
        raise RuntimeError(f"Bitget ticker universe error: {d}")
    out = {}
    for x in d["data"]:
        symbol = normalize_symbol(x.get("symbol"))
        if not symbol.endswith("USDT"):
            continue
        try:
            qv = float(x.get("usdtVolume") or x.get("quoteVolume") or 0.0)
            if qv <= 0:
                qv = float(x.get("baseVolume") or 0.0) * float(x.get("lastPr") or 0.0)
        except Exception:
            qv = 0.0
        out[symbol] = max(0.0, qv)
    return out


def gate_liquid_universe() -> dict[str, float]:
    d = get_json("https://api.gateio.ws/api/v4/futures/usdt/tickers")
    if not isinstance(d, list):
        raise RuntimeError(f"Gate ticker universe error: {d}")
    out = {}
    for x in d:
        symbol = normalize_symbol(x.get("contract"))
        if not symbol.endswith("USDT"):
            continue
        try:
            qv = float(x.get("volume_24h_quote") or 0.0)
            if qv <= 0:
                qv = float(x.get("volume_24h_base") or 0.0) * float(x.get("last") or 0.0)
        except Exception:
            qv = 0.0
        out[symbol] = max(0.0, qv)
    return out


def discover_symbols():
    diagnostics = {"mode": "dynamic_shared_liquid_universe", "errors": []}
    try:
        bg = bitget_liquid_universe()
        gt = gate_liquid_universe()
        shared = set(bg) & set(gt)
        ranked = sorted(shared, key=lambda s: min(bg.get(s, 0.0), gt.get(s, 0.0)), reverse=True)
        liquid = [s for s in ranked if min(bg.get(s, 0.0), gt.get(s, 0.0)) >= MIN_SHARED_NOTIONAL_24H_USDT]
        selected = liquid[:MAX_DYNAMIC_SYMBOLS]
        for s in reversed(CORE_SYMBOLS):
            if s in shared and s not in selected:
                selected.insert(0, s)
        selected = selected[:MAX_DYNAMIC_SYMBOLS]
        diagnostics.update({
            "bitget_symbol_count": len(bg), "gate_symbol_count": len(gt),
            "shared_symbol_count": len(shared), "liquid_shared_symbol_count": len(liquid),
            "selected_symbol_count": len(selected),
            "min_shared_notional_24h_usdt": MIN_SHARED_NOTIONAL_24H_USDT,
            "max_dynamic_symbols": MAX_DYNAMIC_SYMBOLS,
            "selected": [{"symbol": s, "bitget_notional_24h_usdt": round(bg.get(s,0),2), "gate_notional_24h_usdt": round(gt.get(s,0),2), "shared_notional_floor_usdt": round(min(bg.get(s,0),gt.get(s,0)),2)} for s in selected],
        })
        if selected:
            return selected, diagnostics
        diagnostics["errors"].append("dynamic universe empty; using core fallback")
    except Exception as exc:
        diagnostics["errors"].append(str(exc))
    diagnostics["mode"] = "core_fallback"
    diagnostics["selected_symbol_count"] = len(CORE_SYMBOLS)
    diagnostics["selected"] = [{"symbol": s} for s in CORE_SYMBOLS]
    return list(CORE_SYMBOLS), diagnostics


def bitget(symbol: str) -> dict:
    d = get_json(q("https://api.bitget.com/api/v3/market/current-fund-rate", category="USDT-FUTURES", symbol=symbol))
    if d.get("code") != "00000" or not d.get("data"):
        raise RuntimeError(f"Bitget funding error: {d}")
    x = d["data"][0]
    p = get_json(q("https://api.bitget.com/api/v2/mix/market/symbol-price", productType="USDT-FUTURES", symbol=symbol))
    if p.get("code") != "00000" or not p.get("data"):
        raise RuntimeError(f"Bitget price error: {p}")
    px = p["data"][0]
    return {"venue":"Bitget USDT perpetual","symbol":symbol,"funding_rate":float(x.get("fundingRate") or 0),"interval_hours":float(x.get("fundingRateInterval") or 8),"next_funding_time":int(x.get("nextUpdate") or 0),"mark_price":float(px.get("markPrice") or 0),"index_price":float(px.get("indexPrice") or 0),"market_price":float(px.get("price") or 0),"price_timestamp_ms":int(px.get("ts") or 0)}


def gate(symbol: str) -> dict:
    contract = gate_contract(symbol)
    d = get_json(f"https://api.gateio.ws/api/v4/futures/usdt/contracts/{contract}")
    if not isinstance(d, dict) or not d.get("name"):
        raise RuntimeError(f"Gate funding error: {d}")
    interval_hours = float(d.get("funding_interval") or 28800) / 3600.0
    if interval_hours <= 0 or interval_hours > 24:
        interval_hours = 8.0
    return {"venue":"Gate USDT perpetual","symbol":symbol,"funding_rate":float(d.get("funding_rate") or 0),"interval_hours":interval_hours,"next_funding_time":int(float(d.get("funding_next_apply") or 0)*1000),"indicative_funding_rate":float(d.get("funding_rate_indicative") or 0),"mark_price":float(d.get("mark_price") or 0),"index_price":float(d.get("index_price") or 0),"last_price":float(d.get("last_price") or 0),"quanto_multiplier":float(d.get("quanto_multiplier") or 1.0)}


def _levels(raw):
    out=[]
    for x in raw or []:
        try:
            if isinstance(x,dict): price=float(x.get("p") or x.get("price") or 0); size=float(x.get("s") or x.get("size") or x.get("qty") or 0)
            else: price=float(x[0]); size=float(x[1])
            if price>0 and size>0: out.append((price,size))
        except Exception: continue
    return out


def bitget_book(symbol: str):
    d=get_json(q("https://api.bitget.com/api/v2/mix/market/merge-depth",productType="USDT-FUTURES",symbol=symbol,precision="scale0",limit="50")); data=d.get("data") if isinstance(d,dict) else None
    if d.get("code")!="00000" or not isinstance(data,dict): raise RuntimeError(f"Bitget orderbook error: {d}")
    return {"bids":_levels(data.get("bids")),"asks":_levels(data.get("asks"))}


def gate_book(symbol: str, multiplier: float):
    contract = symbol.replace("USDT", "_USDT")
    d=get_json(q("https://api.gateio.ws/api/v4/futures/usdt/order_book",contract=contract,limit=50,with_id="true"))
    if not isinstance(d,dict): raise RuntimeError(f"Gate orderbook error: {d}")
    def convert(raw): return [(p,s*multiplier) for p,s in _levels(raw)]
    return {"bids":convert(d.get("bids")),"asks":convert(d.get("asks"))}


def vwap_for_notional(levels,target_usdt):
    remaining=float(target_usdt); cost=0.0; qty=0.0
    for price,base_qty in levels:
        available=price*base_qty; take=min(remaining,available)
        if take<=0: continue
        qtake=take/price; cost+=take; qty+=qtake; remaining-=take
        if remaining<=1e-9: break
    if remaining>1e-6 or qty<=0: return None
    return cost/qty


def executable_probe(symbol,direction,edge_bps,gate_multiplier):
    result={"mode":"public_orderbook_best_effort","budgets_eur_approx_usdt":DEPTH_BUDGETS_EUR,"rows":[],"errors":[],"can_promote_candidate":False}
    try: bg=bitget_book(symbol)
    except Exception as exc: result["errors"].append(f"Bitget: {exc}"); bg=None
    try: gt=gate_book(symbol,gate_multiplier)
    except Exception as exc: result["errors"].append(f"Gate: {exc}"); gt=None
    if not bg or not gt: return result
    short_bg=direction.startswith("short Bitget"); bg_side=bg["bids"] if short_bg else bg["asks"]; gt_side=gt["asks"] if short_bg else gt["bids"]; direction_sign=1.0 if short_bg else -1.0
    for budget in DEPTH_BUDGETS_EUR:
        leg_notional=budget*0.5; bg_px=vwap_for_notional(bg_side,leg_notional); gt_px=vwap_for_notional(gt_side,leg_notional); executable=bg_px is not None and gt_px is not None
        raw_basis=aligned_basis=adverse=periods=None
        if executable:
            raw_basis=(bg_px/gt_px-1.0)*10000; aligned_basis=raw_basis*direction_sign; adverse=max(0.0,-aligned_basis); periods=adverse/edge_bps if edge_bps>0 else None
        result["rows"].append({"total_budget_eur_approx":budget,"leg_notional_usdt_approx":round(leg_notional,2),"depth_sufficient_both_legs":executable,"bitget_entry_vwap":None if bg_px is None else round(bg_px,10),"gate_entry_vwap":None if gt_px is None else round(gt_px,10),"aligned_executable_entry_basis_bps":None if aligned_basis is None else round(aligned_basis,4),"adverse_executable_entry_basis_bps":None if adverse is None else round(adverse,4),"funding_periods_to_overcome_adverse_executable_basis":None if periods is None else round(periods,3)})
    return result


def ensure_history():
    if not HISTORY.exists():
        with HISTORY.open("w",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=FIELDS).writeheader()
    if not BASIS_HISTORY.exists():
        with BASIS_HISTORY.open("w",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=BASIS_FIELDS).writeheader()


def append_history(rows,basis_rows):
    ensure_history()
    with HISTORY.open("a",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=FIELDS).writerows(rows)
    with BASIS_HISTORY.open("a",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=BASIS_FIELDS).writerows(basis_rows)


def main():
    ts=datetime.now(timezone.utc).isoformat(timespec="seconds"); rows=[]; basis_rows=[]; detailed=[]; errors=[]; symbols,universe=discover_symbols()
    for symbol in symbols:
        try:
            a=bitget(symbol); b=gate(symbol); a_per_hour=a["funding_rate"]/a["interval_hours"]; b_per_hour=b["funding_rate"]/b["interval_hours"]; spread_per_hour=a_per_hour-b_per_hour; spread_8h=spread_per_hour*8*10000; edge=abs(spread_8h)
            direction="short Bitget / long Gate" if spread_per_hour>0 else "long Bitget / short Gate"; breakeven=(ROUND_TRIP_COST_BPS/edge) if edge>0 else None; candidate=edge>=WATCH_SPREAD_BPS_PER_8H
            bg_mark=a["mark_price"]; gt_mark=b["mark_price"]; raw_basis=(bg_mark/gt_mark-1)*10000 if bg_mark>0 and gt_mark>0 else None; sign=1.0 if direction.startswith("short Bitget") else -1.0; aligned=None if raw_basis is None else raw_basis*sign; adverse=None if aligned is None else max(0.0,-aligned); periods=None if adverse is None or edge<=0 else adverse/edge
            row={"timestamp_utc":ts,"symbol":symbol,"direction":direction,"binance_rate":f'{a["funding_rate"]:.10f}',"binance_interval_hours":f'{a["interval_hours"]:.4f}',"bybit_rate":f'{b["funding_rate"]:.10f}',"bybit_interval_hours":f'{b["interval_hours"]:.4f}',"spread_bps_per_hour":f'{spread_per_hour*10000:.6f}',"spread_bps_per_8h":f'{spread_8h:.6f}',"rough_annualized_pct":f'{spread_per_hour*24*365*100:.4f}',"breakeven_8h_periods":"" if breakeven is None else f'{breakeven:.3f}',"candidate":"YES" if candidate else "NO"}; rows.append(row)
            basis_rows.append({"timestamp_utc":ts,"symbol":symbol,"direction":direction,"spread_bps_per_8h":f'{edge:.6f}',"aligned_basis_bps":"" if aligned is None else f'{aligned:.6f}',"adverse_basis_bps":"" if adverse is None else f'{adverse:.6f}',"periods_to_overcome_adverse_basis":"" if periods is None else f'{periods:.6f}',"candidate":"YES" if candidate else "NO"})
            detail=dict(row); detail.update({"venue_a":a,"venue_b":b,"venue_a_name":"Bitget","venue_b_name":"Gate","round_trip_cost_assumption_bps":ROUND_TRIP_COST_BPS,"cross_venue_basis":{"bitget_minus_gate_mark_bps":None if raw_basis is None else round(raw_basis,4),"aligned_with_funding_trade_bps":None if aligned is None else round(aligned,4),"adverse_entry_basis_bps":None if adverse is None else round(adverse,4),"funding_periods_to_overcome_adverse_entry_basis":None if periods is None else round(periods,3),"interpretation":"Positive aligned basis favours the funding direction at entry; negative is adverse. Future basis can widen or reverse, so this is a risk diagnostic, not expected PnL."},"warning":"Funding can change before settlement. Mark basis and public order-book entry diagnostics are research evidence only; liquidation, collateral, fee-tier, venue, transfer and actual fill risk remain incompletely modeled."})
            if candidate: detail["executable_entry_probe"]=executable_probe(symbol,direction,edge,b["quanto_multiplier"])
            detailed.append(detail)
        except Exception as exc: errors.append({"symbol":symbol,"error":str(exc)})
    append_history(rows,basis_rows); candidates=[d for d in detailed if d.get("candidate")=="YES"]; candidates.sort(key=lambda x:abs(float(x["spread_bps_per_8h"])),reverse=True)
    out={"generated_at_utc":ts,"mode":"paper_read_only","venues":["Bitget","Gate"],"universe":universe,"depth_probe_budgets_eur":DEPTH_BUDGETS_EUR,"depth_probe_policy":"best-effort diagnostics only; cannot promote a candidate","candidate_count":len(candidates),"best":candidates[0] if candidates else None,"candidates":candidates,"errors":errors,"assumptions":{"round_trip_cost_bps":ROUND_TRIP_COST_BPS,"watch_spread_bps_per_8h":WATCH_SPREAD_BPS_PER_8H},"hard_boundary":"Research only; no order placement, custody or transaction signing."}
    LATEST.write_text(json.dumps(out,indent=2),encoding="utf-8"); print(f"Funding scan complete: {len(candidates)} candidates, {len(errors)} errors.")


if __name__=="__main__": main()
