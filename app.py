import streamlit as st
from magical_trade.config import Settings
from magical_trade.models import MarketSnapshot
from magical_trade.decision import evaluate
from magical_trade.paper import PaperBroker

st.set_page_config(page_title="Magical Trade", layout="wide")
st.title("🪄 Magical Trade")
st.caption("Indian options research dashboard · Paper trading only · Live execution disabled")
settings = Settings.from_env()
if "paper" not in st.session_state:
    st.session_state.paper = PaperBroker(settings.paper_initial_capital)

st.subheader("Market snapshot (manual/demo input)")
with st.form("snapshot"):
    c1, c2, c3 = st.columns(3)
    symbol = c1.text_input("Instrument", "NIFTY")
    ltp = c1.number_input("LTP", min_value=0.0, value=100.0)
    bid = c2.number_input("Bid", min_value=0.0, value=99.9)
    ask = c2.number_input("Ask", min_value=0.0, value=100.1)
    vwap = c3.number_input("VWAP", min_value=0.0, value=99.0)
    fast = c3.number_input("Fast SMA", min_value=0.0, value=100.0)
    slow = c3.number_input("Slow SMA", min_value=0.0, value=98.0)
    volume = c1.number_input("Volume ratio", min_value=0.0, value=1.6)
    oi = c2.number_input("OI change %", value=2.5)
    vol = c3.number_input("Volatility % (optional)", min_value=0.0, value=1.0)
    submitted = st.form_submit_button("Evaluate snapshot")
if submitted:
    snap = MarketSnapshot(symbol, ltp, bid, ask, vwap, fast, slow, oi, volume, vol)
    signal, message = evaluate(snap, settings.min_confidence, settings.min_risk_reward, settings.max_spread_pct)
    st.session_state.signal = signal
    st.info(message)
    if signal:
        st.success(f"{signal.side.value} {signal.symbol} · Confidence {signal.confidence:.1f}%")
        st.write({"entry": signal.entry, "stop_loss": signal.stop_loss, "target": signal.target,
                  "rationale": signal.rationale})

st.divider()
st.subheader("Paper account")
st.metric("Paper cash", f"₹{st.session_state.paper.cash:,.2f}")
st.caption("This starter UI does not fetch live prices or submit broker orders.")
st.subheader("Execution safety")
st.error("REAL TRADING DISABLED. No live order can be sent by this build.")
