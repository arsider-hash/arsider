# ARBBOT AUTOPILOT POLICY

The user does not need to choose among strategies.

ARBBOT does the filtering and selects one best candidate at a time.

## Automatic states

### WAIT
No action. Keep collecting data.

### VALIDATE
The signal is repeated enough to justify deeper execution-specific paper testing.
Still no money, wallet, exchange login, or trading credential.

### READY_FOR_MANUAL_AUTHORIZATION
The signal has passed the research gates strongly enough that ARBBOT can prepare one
small, capped live-test plan.

This state does **not** place a trade.

## Hard boundary

ARBBOT may:
- collect public market data;
- calculate spreads and carry signals;
- rank strategies;
- reject noise;
- choose one best candidate;
- build execution-specific paper tests;
- prepare a live-test specification.

ARBBOT must not:
- hold or custody user money;
- store a seed phrase or wallet private key;
- approve withdrawals;
- sign a transaction on the user's behalf;
- place or enable live orders without explicit user authorization.

The user should not have to make strategy-selection decisions. The remaining human step,
if the system ever reaches a live phase, is authorization of the capital/risk boundary.
