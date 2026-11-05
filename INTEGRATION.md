# Magic Trade intelligence module integration

## What this bundle contains
- `magical_trade/intelligence.py`: pure-Python DOM snapshot validation, executed-volume delta, Black-Scholes Greeks, EOD participant aggregation, weighted CE/PE candidate scoring, paper P&L accounting, and whole-lot risk sizing.
- `tests/test_intelligence.py`: deterministic unit tests for those functions.

## Install into the existing repository
Copy `magical_trade/intelligence.py` into the existing `magical_trade/` folder and `tests/test_intelligence.py` into `tests/`. Do not replace `app.py`, `config.py`, `risk.py`, `paper.py`, or `angel_one.py` with these files.

Run `python -m pytest -q` from the repository root.

## Important integration boundary
This module deliberately does not connect to Angel One WebSocket/depth feeds, does not download NSE participant reports, and does not send broker orders. The existing read-only Angel One adapter currently supplies LTP and historical candles. Before automatic live signal generation, a separately tested adapter must provide correctly timestamped NIFTY futures/option quotes, option-chain OI/IV, and permitted depth/trade-flow data. Do not populate these inputs with mock/demo values in live mode.

NSE participant categories are aggregate end-of-day data. They are not real-time client identities or client-tagged order flow. Black-Scholes Greeks are model estimates and depend on accurate spot, strike, expiry, IV and rate inputs.

## Safety defaults
- Live execution remains disabled. This module has no broker-order method.
- Paper starting balance defaults to INR 5,000.
- Whole-lot sizing returns zero when even one lot breaches the configured INR 50 risk cap.
- The current repository's daily loss guard remains INR 100 and should be wired into any paper order controller before deployment.
- The weighted score is a setup-quality heuristic, not a probability of profit. Validate with historical, out-of-sample and forward paper tests before considering any live use.
