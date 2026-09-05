# ARBBOT LAB

The project is now a read-only opportunity laboratory rather than a single arbitrage script.

## Active research lanes

1. **Solana cross-DEX** — quoted USDC -> SOL -> USDC round trips across selected DEXes.
2. **Cross-exchange funding** — normalised Binance/Bybit perpetual funding spreads.
3. **CEX cross-spot** — best ask on one venue versus best bid on the other for BTC, ETH and SOL.
4. **CEX triangular arbitrage** — Binance top-of-book USDT/BTC/ETH and USDT/BTC/SOL cycles.
5. **Spot-perp basis** — spot versus perpetual premium/discount on Binance and Bybit.
6. **Stablecoin dislocations** — USDC/USDT and FDUSD/USDT where listed.
7. **Persistence scoreboard** — rejects isolated spikes and ranks only repeated signals.

## Design rule

Everything is read-only. No exchange credentials, API trading keys, wallet seed, private key, signing or order placement exists in this codebase.

## Why the scoreboard matters

A single profitable-looking quote is usually worthless. The scoreboard reviews the last 48 hours and promotes a lane only when positive readings repeat.

A `strong_watch` is **not** permission to trade. It means the signal has survived the first noise filter and deserves execution-specific validation.

## Before any live-money phase

A live prototype would require, at minimum:

- account-specific fee schedules;
- executable order-book depth for the intended size;
- latency and fill-probability measurement;
- funding-interval and basis-risk validation;
- transfer/rebalancing costs;
- hard capital limits;
- kill switches;
- isolated credentials with no withdrawal permission where supported;
- a separate wallet/account and explicit user authorization.

No live-money component is currently present.
