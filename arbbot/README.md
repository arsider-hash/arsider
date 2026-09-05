# ARBBOT

Hands-off, read-only Solana arbitrage experiment.

This folder is intentionally isolated from the rest of the repository.

## Current phase

Every scheduled run simulates round trips:

`100 USDC -> SOL on DEX A -> USDC on DEX B`

across:

- Raydium CLMM
- Orca Whirlpool
- Meteora DLMM

The scanner uses Jupiter's keyless API access. It does not connect a wallet, hold a seed phrase, sign a transaction or move funds.

Results are written to:

- `data/latest.json` - most recent sweep
- `data/history.csv` - cumulative observations

A 20 bps execution haircut is subtracted from the quoted round-trip edge. This is deliberately conservative, but a positive paper result is still not proof that the trade could actually be executed profitably.

## Promotion rule

No live-money component should be added until the paper history shows repeated positive stressed edges rather than isolated quote noise.
