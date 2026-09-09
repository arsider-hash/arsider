# ARBBOT capped manual live-test runbook

Research-to-live bridge only. This document does not authorize execution and ARBBOT must never place orders, custody funds, sign transactions, store exchange credentials, or bypass manual approval.

## Candidate

Current research candidate class: market-neutral cross-venue funding spread. The only eligible candidate is the symbol and direction selected by a fresh `decision.json` in `READY_FOR_MANUAL_AUTHORIZATION` state when both global and funding KILLER verdicts are `SURVIVES_KILLER` for that exact same symbol and direction. Never use a previously named or historical candidate merely because it appeared in an older runbook or report.

## Hard preflight gate

Do not proceed unless ALL conditions are true at the moment of manual action:

1. `decision.json` is `READY_FOR_MANUAL_AUTHORIZATION`.
2. `killer_report.json` and `killer_funding_report.json` both say `SURVIVES_KILLER` for the same symbol and direction.
3. Candidate age is <= 300 seconds for this live-test preflight, stricter than the laboratory's 900-second research freshness limit.
4. Latest funding edge is positive and at least 50% of the rolling median positive edge.
5. Current funding direction matches the direction approved by KILLER.
6. Current adverse entry basis requires <= 1.5 funding periods to overcome at the current edge.
7. At least 3 valid shadow canaries exist, positive rate >= 0.67, cumulative shadow PnL > 0.
8. Both venues are operational for deposits, withdrawals, trading and the specific perpetual contract; no maintenance or obvious venue incident is known.
9. The user gives explicit manual authorization for this single capped test after seeing the fresh preflight snapshot.

Any failure means ABORT. No partial override.

## Test size

First live test cap: EUR 25 total capital maximum, approximately EUR 12.50 economic exposure per leg before venue-specific margin requirements. No leverage above 1x economic exposure for the first test. Do not scale during the test.

The purpose is execution validation, not income generation.

## Manual execution concept

Target structure: delta-neutral pair using the KILLER-approved direction, e.g. long one venue / short the other. Both legs must be opened manually as close together as practical. If the first leg fills and the second cannot be completed promptly at acceptable prices, close the first leg rather than carrying a directional position.

Before confirming either leg, manually record:
- timestamp
- quoted bid/ask or executable price on both venues
- intended notional per leg
- current funding rate and funding interval on both venues
- current cross-venue mark basis
- estimated taker fees

After fills, record actual fill prices and fees. The live test is successful only if the realized entry friction and subsequent funding/basis behavior remain inside the conservative model.

## Abort / kill conditions

Abort before entry if any preflight gate fails.

After entry, manually neutralize/exit the test if any of these occurs:
- one leg cannot be maintained or matched
- venue/API/UI malfunction makes position state uncertain
- effective delta becomes materially non-neutral
- adverse basis widens enough that estimated recovery exceeds 3 funding periods
- funding direction flips against the trade before the intended settlement and expected carry no longer covers modeled costs
- actual combined entry slippage + fees materially exceeds the 30 bps round-trip cost budget
- liquidation/margin buffer becomes uncomfortable even without directional intent
- withdrawal/trading restrictions or venue incident appears

No averaging down, no adding capital, no leverage increase, no second simultaneous candidate.

## Evidence to collect

For the first capped test collect one row containing:
- candidate key and direction
- decision/KILLER timestamps
- entry timestamps per venue
- quoted and actual fill prices
- notional per leg
- fees per leg
- funding actually received/paid
- mark/index basis at entry and exit
- holding time
- exit prices and fees
- realized net EUR PnL
- maximum observed basis excursion
- maximum observed delta mismatch
- any operational friction

Treat a positive result as one observation, not proof. Treat a negative or operationally messy result as first-class KILLER evidence.

## Scaling rule

Do not scale from EUR 25 after one positive test. Scaling requires repeated manual live observations with no material operational failure, stable direction, and realized net economics broadly consistent with the paper model. Any scaling decision requires a separate explicit user authorization.

## Boundary

ARBBOT remains read-only/research-only. The user performs every financial action manually and retains final control.