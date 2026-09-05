# ARBBOT Funding Scout

Read-only companion experiment to the Solana paper scanner.

It compares public perpetual-funding snapshots for BTC, ETH and SOL across Binance USD-M and Bybit linear markets.

No account login, API secret, wallet or order placement is used.

The output is written to `data/funding_latest.json`.

A funding-rate difference is only a research signal. Real carry depends on fee schedules, basis, funding-interval alignment, margin requirements, liquidation risk, venue/counterparty risk and the cost of moving capital.
