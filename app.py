
import streamlit as st

from magical_trade.config import Settings
from magical_trade.models import MarketSnapshot
from magical_trade.decision import evaluate
from magical_trade.paper import PaperBroker
from magical_trade.risk import BotRiskAccount, BotRiskPolicy
from magical_trade.angel_one import AngelOneAdapter
from magical_trade.instruments import (
    load_instrument_master,
    filter_nifty50_stock_options,
)
from magical_trade.nifty50_universe import load_nifty50_symbols


# ==========================================
# PAGE CONFIGURATION
# ==========================================

st.set_page_config(
    page_title="Magic Trade",
    layout="wide",
)

st.title("🪄 Magic Trade")
st.caption(
    "Indian market intelligence · Paper trading · "
    "Angel One read-only data · Real execution disabled"
)

settings = Settings.from_env()


# ==========================================
# PAPER ACCOUNT WITH PER-BOT RISK
# ==========================================

st.sidebar.header("Paper Trading Configuration")

requested_capital = st.sidebar.number_input(
    "Paper capital (₹)",
    min_value=1000.0,
    max_value=1000000.0,
    value=float(settings.paper_initial_capital),
    step=1000.0,
)

if "paper" not in st.session_state:
    bot_id = "paper-main"

    risk_policy = BotRiskPolicy(
        risk_per_trade_pct=settings.risk_per_trade_pct,
        daily_loss_limit_pct=settings.daily_loss_limit_pct,
        max_open_positions=settings.max_positions_per_bot,
        min_risk_reward=settings.min_risk_reward,
    )

    risk_account = BotRiskAccount(
        bot_id=bot_id,
        allocated_capital=requested_capital,
        policy=risk_policy,
    )

    st.session_state.risk_account = risk_account

    st.session_state.paper = PaperBroker(
        initial_capital=requested_capital,
        risk_account=risk_account,
        bot_id=bot_id,
    )

paper = st.session_state.paper
risk_account = st.session_state.risk_account

if requested_capital != risk_account.allocated_capital:
    st.sidebar.warning(
        "Capital is locked for this paper account. "
        "Changing the input does not change allocated capital."
    )

if "angel" not in st.session_state:
    st.session_state.angel = None

if "angel_quote" not in st.session_state:
    st.session_state.angel_quote = None


# ==========================================
# ANGEL ONE CONNECTION - READ ONLY
# ==========================================

st.divider()
st.header("Angel One connection")

st.info(
    "Read-only market data connection. "
    "This application does not place, modify or cancel "
    "broker orders."
)

if st.button("Connect Angel One", type="primary"):
    try:
        required = [
            "ANGEL_API_KEY",
            "ANGEL_CLIENT_CODE",
            "ANGEL_PIN",
            "ANGEL_TOTP_SECRET",
        ]

        credentials = {
            key: st.secrets[key]
            for key in required
            if key in st.secrets
        }

        if len(credentials) != len(required):
            st.error(
                "Angel One credentials are incomplete. "
                "Configure all four values in Streamlit Secrets."
            )
        else:
            adapter = AngelOneAdapter(credentials)
            adapter.connect()

            st.session_state.angel = adapter
            st.session_state.angel_quote = None

            st.success("Angel One authenticated successfully.")

    except Exception as exc:
        st.session_state.angel = None
        st.error(f"Connection failed: {exc}")


if st.session_state.angel is not None:
    st.success("Angel One connected")

    st.subheader("Live market quote")

    exchange = st.selectbox(
        "Exchange",
        ["NSE", "BSE", "NFO", "BFO"],
        index=0,
    )

    symbol = st.text_input(
        "Trading symbol",
        "NIFTY",
    )

    token = st.text_input(
        "Angel One symbol token",
        "99926000",
    )

    if st.button("Fetch live quote"):
        try:
            quote = st.session_state.angel.get_ltp_quote(
                exchange,
                symbol.strip(),
                token.strip(),
            )

            st.session_state.angel_quote = quote
            st.success("Quote received from Angel One.")

        except Exception as exc:
            st.session_state.angel_quote = None
            st.error(f"Quote request failed: {exc}")

    quote = st.session_state.angel_quote

    if quote is not None:
        st.metric(
            "Reported LTP",
            f"₹{quote.ltp:,.2f}",
        )

        col1, col2, col3 = st.columns(3)

        col1.metric("Open", f"₹{quote.open:,.2f}")
        col2.metric("High", f"₹{quote.high:,.2f}")
        col3.metric("Low", f"₹{quote.low:,.2f}")

        st.write("Symbol:", quote.symbol)
        st.write("Token:", quote.token)
        st.write("Volume:", quote.volume)
        st.write(
            "Exchange time:",
            quote.exchange_time or "Not supplied",
        )

        freshness = (
            st.session_state.angel.get_quote_freshness()
        )

        st.write("Quote freshness:", freshness)

        st.caption(
            "A displayed quote is not automatically approved "
            "for paper execution. Freshness validation is required."
        )


# ==========================================
# HISTORICAL CANDLE DATA - READ ONLY
# ==========================================

st.divider()
st.header("Historical Market Candles")

if st.session_state.angel is not None:

    candle_exchange = st.selectbox(
        "Candle exchange",
        ["NSE", "NFO", "BSE", "BFO", "MCX"],
        key="candle_exchange",
    )

    candle_token = st.text_input(
        "Candle instrument token",
        "99926000",
        key="candle_token",
    )

    candle_interval = st.selectbox(
        "Candle interval",
        [
            "ONE_MINUTE",
            "THREE_MINUTE",
            "FIVE_MINUTE",
            "TEN_MINUTE",
            "FIFTEEN_MINUTE",
            "THIRTY_MINUTE",
            "ONE_HOUR",
            "ONE_DAY",
        ],
        index=2,
    )

    from_date = st.text_input(
        "From date (YYYY-MM-DD HH:MM)",
        "2026-11-03 09:15",
    )

    to_date = st.text_input(
        "To date (YYYY-MM-DD HH:MM)",
        "2026-11-03 15:30",
    )

    if st.button("Fetch historical candles"):
        try:
            candles = (
                st.session_state.angel.get_historical_candles(
                    exchange=candle_exchange,
                    token=candle_token.strip(),
                    fromdate=from_date.strip(),
                    todate=to_date.strip(),
                    interval=candle_interval,
                )
            )

            if candles:
                import pandas as pd

                candle_df = pd.DataFrame(
                    [
                        {
                            "Time": candle.timestamp,
                            "Open": candle.open,
                            "High": candle.high,
                            "Low": candle.low,
                            "Close": candle.close,
                            "Volume": candle.volume,
                        }
                        for candle in candles
                    ]
                )

                st.success(
                    f"Received {len(candles)} historical candles."
                )

                st.dataframe(
                    candle_df,
                    use_container_width=True,
                )

            else:
                st.warning("Angel One returned no candles.")

        except Exception as exc:
            st.error(f"Historical candle request failed: {exc}")

else:
    st.info("Connect Angel One to fetch historical candles.")


# ==========================================
# NIFTY 50 UNIVERSE AND STOCK OPTIONS
# ==========================================

st.divider()
st.header("NIFTY 50 Stocks & Stock Options")

st.caption(
    "Constituent and contract data from NSE and Angel One's "
    "instrument master. No orders are placed here."
)


@st.cache_data(ttl=3600)
def get_nifty50_data():
    return load_nifty50_symbols()


@st.cache_data(ttl=3600)
def get_instrument_data():
    return load_instrument_master()


if st.button("Load NIFTY 50 Stocks & Options"):
    try:
        with st.spinner("Loading NIFTY 50 constituents..."):
            nifty50_symbols = get_nifty50_data()

        with st.spinner("Loading Angel One instrument master..."):
            instrument_records = get_instrument_data()

        stock_options = filter_nifty50_stock_options(
            instrument_records,
            nifty50_symbols,
        )

        st.session_state.nifty50_symbols = nifty50_symbols
        st.session_state.nifty50_stock_options = stock_options

        st.success("NIFTY 50 data loaded successfully.")

    except Exception as exc:
        st.error(f"Data loading failed: {exc}")


if "nifty50_symbols" in st.session_state:
    symbols = st.session_state.nifty50_symbols
    options = st.session_state.nifty50_stock_options

    col1, col2 = st.columns(2)

    col1.metric("NIFTY 50 Constituents", len(symbols))
    col2.metric("Stock Option Contracts", len(options))

    st.subheader("NIFTY 50 Constituents")
    st.write(", ".join(symbols))

    if options:
        available_stocks = sorted({
            item["name"] for item in options
        })

        selected_stock = st.selectbox(
            "Select NIFTY 50 stock",
            available_stocks,
        )

        selected_options = [
            {
                "Trading Symbol": item["symbol"],
                "Expiry": item["expiry"],
                "Option Type": (
                    "CE" if item["symbol"].endswith("CE")
                    else "PE"
                ),
                "Token": item["token"],
                "Lot Size": item["lotsize"],
            }
            for item in options
            if item["name"] == selected_stock
        ]

        st.table(selected_options)

        st.subheader("Live Option Price")

        contract_map = {
            item["symbol"]: item
            for item in options
            if item["name"] == selected_stock
        }

        selected_contract_symbol = st.selectbox(
            "Select option contract for live price",
            sorted(contract_map.keys()),
        )

        selected_contract = contract_map[
            selected_contract_symbol
        ]

        if st.button("Fetch Live Option LTP"):
            if st.session_state.angel is None:
                st.warning("Connect Angel One first.")
            else:
                try:
                    quote = st.session_state.angel.get_ltp_quote(
                        "NFO",
                        selected_contract["symbol"],
                        selected_contract["token"],
                    )

                    st.metric(
                        "Reported Option LTP",
                        f"₹{quote.ltp:,.2f}",
                    )

                    st.caption(
                        f"Contract: {selected_contract['symbol']} "
                        f"| Token: {selected_contract['token']}"
                    )

                except Exception as exc:
                    st.error(
                        f"Live option quote failed: {exc}"
                    )

    else:
        st.warning("No matching NIFTY 50 stock options found.")


# ==========================================
# MARKET SNAPSHOT - MANUAL / DEMO ONLY
# ==========================================

st.divider()
st.header("Market snapshot (manual/demo input)")

st.warning(
    "Demo signals are for research only. "
    "They cannot be sent to the paper broker."
)

with st.form("snapshot"):
    c1, c2, c3 = st.columns(3)

    symbol = c1.text_input("Instrument", "NIFTY")
    ltp = c1.number_input(
        "LTP",
        min_value=0.0,
        value=100.0,
    )

    bid = c2.number_input(
        "Bid",
        min_value=0.0,
        value=99.9,
    )

    ask = c2.number_input(
        "Ask",
        min_value=0.0,
        value=100.1,
    )

    vwap = c3.number_input(
        "VWAP",
        min_value=0.0,
        value=99.0,
    )

    fast = c3.number_input(
        "Fast SMA",
        min_value=0.0,
        value=100.0,
    )

    slow = c3.number_input(
        "Slow SMA",
        min_value=0.0,
        value=98.0,
    )

    volume = c1.number_input(
        "Volume ratio",
        min_value=0.0,
        value=1.6,
    )

    oi = c2.number_input(
        "OI change %",
        value=2.5,
    )

    vol = c3.number_input(
        "Volatility %",
        min_value=0.0,
        value=1.0,
    )

    submitted = st.form_submit_button(
        "Evaluate demo snapshot"
    )

if submitted:
    try:
        snap = MarketSnapshot(
            symbol,
            ltp,
            bid,
            ask,
            vwap,
            fast,
            slow,
            oi,
            volume,
            vol,
        )

        signal, message = evaluate(
            snap,
            settings.min_confidence,
            settings.min_risk_reward,
            settings.max_spread_pct,
        )

        st.info(message)

        if signal:
            st.success(
                f"DEMO SIGNAL: {signal.side.value} "
                f"{signal.symbol} · "
                f"Confidence {signal.confidence:.1f}%"
            )

            st.write({
                "entry": signal.entry,
                "stop_loss": signal.stop_loss,
                "target": signal.target,
                "rationale": signal.rationale,
            })

    except Exception as exc:
        st.error(f"Snapshot evaluation failed: {exc}")


# ==========================================
# PAPER ACCOUNT AND BOT RISK MONITOR
# ==========================================

st.divider()
st.header("Paper account and bot risk")

col1, col2, col3 = st.columns(3)

col1.metric(
    "Paper cash",
    f"₹{paper.cash:,.2f}",
)

col2.metric(
    "Account equity",
    f"₹{paper.equity:,.2f}",
)

col3.metric(
    "Unrealized P&L",
    f"₹{paper.unrealized_pnl:,.2f}",
)

st.subheader("Bot risk controls")

col1, col2, col3 = st.columns(3)

col1.metric(
    "Risk per trade",
    f"₹{risk_account.risk_per_trade_amount:,.2f}",
)

col2.metric(
    "Daily loss limit",
    f"₹{risk_account.daily_loss_limit_amount:,.2f}",
)

col3.metric(
    "Open positions",
    f"{risk_account.open_positions}/"
    f"{risk_account.policy.max_open_positions}",
)

st.write("Bot ID:", risk_account.bot_id)
st.write("Bot status:", risk_account.status.value)

st.write(
    "Today's net P&L:",
    f"₹{risk_account.total_daily_pnl:,.2f}",
)

if risk_account.daily_limit_reached:
    st.error(
        "DAILY LOSS LIMIT REACHED — NEW TRADES BLOCKED."
    )

elif risk_account.status.value != "ACTIVE":
    st.error("BOT RETIRED — TRADING BLOCKED.")

else:
    st.success("Per-bot risk checks are active.")

st.caption(
    "Risk controls do not guarantee that losses cannot exceed "
    "configured limits. Market gaps, slippage and data delays "
    "can increase losses."
)


# ==========================================
# EXECUTION SAFETY
# ==========================================

st.divider()
st.header("Execution safety")

st.error(
    "REAL TRADING DISABLED. No live broker order can be sent "
    "by this build."
)

st.info(
    "Automatic paper execution is not enabled yet. "
    "It will remain disabled until market-data validation, "
    "persistent recovery and risk-control tests are completed."
)
