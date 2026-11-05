
import pytest

from magical_trade.models import (
    MarketSnapshot,
    Signal,
    Side,
    Trade,
)
from magical_trade.decision import evaluate
from magical_trade.risk import (
    RiskManager,
    BotRiskAccount,
    BotRiskPolicy,
)
from magical_trade.paper import PaperBroker
from magical_trade.live_guard import (
    LiveExecutionGuard,
    LiveTradingDisabled,
)
from magical_trade.market_data import parse_smartapi_quote


def make_trade(
    quantity=1,
    entry=100,
    stop=99,
    target=102,
):
    return Trade(
        symbol="NIFTY",
        side=Side.BUY,
        quantity=quantity,
        entry=entry,
        stop_loss=stop,
        target=target,
        risk_amount=abs(entry - stop) * quantity,
    )


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
    broker = PaperBroker(initial_capital=5000)
    result = broker.execute(make_trade())

    assert result["symbol"] == "NIFTY"
    assert result["side"] == "BUY"
    assert broker.cash < 5000
    assert result["status"] == "OPEN"


def test_paper_broker_rejects_invalid_risk_reward():
    broker = PaperBroker(initial_capital=5000)

    with pytest.raises(ValueError, match="2:1"):
        broker.execute(
            make_trade(entry=100, stop=99, target=101)
        )


def test_paper_broker_rejects_invalid_buy_stop():
    broker = PaperBroker(initial_capital=5000)

    with pytest.raises(ValueError):
        broker.execute(
            make_trade(entry=100, stop=101, target=103)
        )


def test_per_bot_risk_rejects_risk_above_one_percent():
    account = BotRiskAccount(
        bot_id="bot-a",
        allocated_capital=5000,
    )
    broker = PaperBroker(
        initial_capital=5000,
        risk_account=account,
        bot_id="bot-a",
    )

    with pytest.raises(ValueError, match="risk budget"):
        broker.execute(make_trade(quantity=48))


def test_per_bot_risk_allows_only_one_open_position():
    account = BotRiskAccount(
        bot_id="bot-a",
        allocated_capital=5000,
        policy=BotRiskPolicy(max_open_positions=1),
    )
    broker = PaperBroker(
        initial_capital=5000,
        risk_account=account,
        bot_id="bot-a",
    )

    broker.execute(make_trade())

    with pytest.raises(ValueError, match="Maximum open positions"):
        broker.execute(make_trade())


def test_paper_broker_rejects_mismatched_bot_account():
    account = BotRiskAccount(
        bot_id="bot-a",
        allocated_capital=5000,
    )

    with pytest.raises(ValueError, match="another bot"):
        PaperBroker(
            initial_capital=5000,
            risk_account=account,
            bot_id="bot-b",
        )


def test_daily_loss_limit_blocks_next_trade():
    account = BotRiskAccount(
        bot_id="bot-a",
        allocated_capital=1000,
    )
    broker = PaperBroker(
        initial_capital=1000,
        risk_account=account,
        bot_id="bot-a",
        slippage_bps=0,
    )

    result = broker.execute(make_trade(quantity=9))
    broker.close_position(
        result["position_id"],
        market_price=80,
        reason="TEST_LOSS",
    )

    assert account.daily_limit_reached

    with pytest.raises(ValueError, match="Daily loss limit"):
        broker.execute(make_trade())


def test_paper_position_close_records_net_pnl():
    broker = PaperBroker(
        initial_capital=5000,
        brokerage_per_order=5,
        slippage_bps=0,
    )
    opened = broker.execute(make_trade())
    closed = broker.close_position(
        opened["position_id"],
        market_price=102,
        reason="TEST_TARGET",
    )

    assert closed["status"] == "CLOSED"
    assert closed["fees"] == 10
    assert closed["gross_pnl"] == 2
    assert closed["net_pnl"] == -8


def test_monitor_positions_closes_at_target():
    broker = PaperBroker(
        initial_capital=5000,
        slippage_bps=0,
    )
    opened = broker.execute(make_trade())

    result = broker.monitor_positions({"NIFTY": 102})

    assert len(result["closed_positions"]) == 1
    assert result["closed_positions"][0]["position_id"] == opened["position_id"]
    assert result["closed_positions"][0]["reason"] == "TARGET"
    assert result["remaining_open_positions"] == 0


def test_monitor_positions_closes_at_stop_loss():
    broker = PaperBroker(
        initial_capital=5000,
        slippage_bps=0,
    )
    opened = broker.execute(make_trade())

    result = broker.monitor_positions({"NIFTY": 99})

    assert len(result["closed_positions"]) == 1
    assert result["closed_positions"][0]["position_id"] == opened["position_id"]
    assert result["closed_positions"][0]["reason"] == "STOP_LOSS"
    assert result["remaining_open_positions"] == 0


def test_monitor_positions_keeps_position_between_levels():
    broker = PaperBroker(
        initial_capital=5000,
        slippage_bps=0,
    )
    broker.execute(make_trade())

    result = broker.monitor_positions({"NIFTY": 100.5})

    assert result["closed_positions"] == []
    assert result["remaining_open_positions"] == 1


def test_monitor_positions_rejects_invalid_price():
    broker = PaperBroker(initial_capital=5000)
    broker.execute(make_trade())

    with pytest.raises(ValueError):
        broker.monitor_positions({"NIFTY": 0})


def test_live_trading_is_disabled():
    guard = LiveExecutionGuard()

    assert guard.enabled is False

    with pytest.raises(LiveTradingDisabled):
        guard.submit("NIFTY", "BUY", 1)


def test_market_quote_parses_valid_data():
    payload = {
        "data": {
            "fetched": [{
                "tradingSymbol": "NIFTY",
                "symbolToken": "99926000",
                "ltp": 22500.5,
                "open": 22400,
                "high": 22600,
                "low": 22350,
                "close": 22450,
                "volume": 100000,
            }]
        }
    }

    quote = parse_smartapi_quote(payload, "NIFTY")

    assert quote.symbol == "NIFTY"
    assert quote.ltp == 22500.5
    assert quote.volume == 100000


def test_market_quote_rejects_zero_ltp():
    payload = {
        "tradingSymbol": "NIFTY",
        "ltp": 0,
    }

    with pytest.raises(ValueError):
        parse_smartapi_quote(payload, "NIFTY")


def test_market_quote_rejects_wrong_symbol():
    payload = {
        "tradingSymbol": "BANKNIFTY",
        "ltp": 50000,
    }

    with pytest.raises(ValueError):
        parse_smartapi_quote(payload, "NIFTY")


def test_market_quote_rejects_multiple_records():
    payload = {
        "data": {
            "fetched": [
                {"tradingSymbol": "NIFTY", "ltp": 22500},
                {"tradingSymbol": "BANKNIFTY", "ltp": 50000},
            ]
        }
    }

    with pytest.raises(ValueError):
        parse_smartapi_quote(payload)
