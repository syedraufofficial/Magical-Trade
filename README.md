# Magical-Trade

Safety-first starter platform for Indian options research and paper trading.

## Current release status

- Streamlit dashboard with manual/demo market snapshots
- Transparent baseline trend/spread signal filter
- Risk sizing with per-trade, daily-loss and open-position controls
- Paper broker with configurable starting cash, slippage and fees
- Live execution **hard-disabled**; Angel One adapter is an unconfigured interface
- Unit tests for signal filters, risk controls, paper fills and live fail-closed behavior

This is a software scaffold, not a profitable strategy or investment recommendation. It does not claim predictive accuracy. No live market feed or broker order placement is implemented yet.

## Setup

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

## Test

```bash
pytest -q
```

## Safety rules

1. Paper trading is the only executable mode in this release.
2. Live execution is denied in code, regardless of environment variables.
3. Do not commit Angel One API keys, passwords, PINs, TOTP seeds, session tokens or `.env` files.
4. Do not use a manual/demo snapshot as a live signal.
5. Validate the strategy on historical, out-of-sample and forward-paper data before considering any live integration.

## Planned modules

Angel One SmartAPI market-data adapter, option-chain/Greeks analytics, OI and institutional-flow analytics, persistent trade journal, backtesting with costs, monitoring and a separately reviewed manual-approval execution service.
