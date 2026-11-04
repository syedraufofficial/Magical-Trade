import pytest

from magical_trade.models import MarketSnapshot, Signal, Side, Trade
from magical_trade.decision import evaluate
from magical_trade.risk import RiskManager
from magical_trade.paper import PaperBroker
from magical_trade.live_guard import LiveExecutionGuard, LiveTradingDisabled


def test_bullish_signal_is_generated():
    snapshot = MarketSnapshot(
        symbol="NIFTY",
        ltp=220,
        bid=219.9,
        ask=220.1,
        vwap=219,
        sma_fast=220,
        sma_slow=218,
        volume_ratio=2.0,
        oi_change_pct=3.0,
        volatility_pct=1.0,
    )

    signal, message = evaluate(snapshot)

    assert signal is not None
    assert signal.side == Side.BUY
    assert signal.target > signal.entry


def test_wide_spread_is_rejected():
    snapshot = MarketSnapshot(
        symbol="NIFTY",
        ltp=220,
        bid=210,
        ask=230,
        vwap=219,
        sma_fast=220,
        sma_slow=218,
    )

    signal, message = evaluate(snapshot)

    assert signal is None
    assert "Spread too wide" in message


def test_risk_manager_rejects_excessive_risk():
    signal = Signal(
        symbol="NIFTY",
        side=Side.BUY,
        confidence=80,
        entry=100,
        stop_loss=90,
        target=120,
        rationale=("Test signal",),
    )

    manager = RiskManager(max_risk_per_trade=50)

    with pytest.raises(ValueError):
        manager.size_trade(signal, quantity=10)


def test_paper_broker_executes_trade():
    trade = Trade(
        symbol="NIFTY",
        side=Side.BUY,
        quantity=1,
        entry=100,
        stop_loss=99,
        target=102,
        risk_amount=1,
    )

    broker = PaperBroker(initial_capital=5000)
    result = broker.execute(trade)

    assert result["symbol"] == "NIFTY"
    assert result["side"] == "BUY"
    assert broker.cash < 5000


def test_live_trading_is_disabled():
    guard = LiveExecutionGuard()

    assert guard.enabled is False

    with pytest.raises(LiveTradingDisabled):
        guard.submit("NIFTY", "BUY", 1)
