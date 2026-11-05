
import json

import pytest

from magical_trade.models import Side, Trade
from magical_trade.paper import PaperBroker
from magical_trade.risk import BotRiskAccount, BotRiskPolicy
from magical_trade.storage import TradeStorage


def make_paper_account():
    bot_id = "storage-test-bot"

    risk_account = BotRiskAccount(
        bot_id=bot_id,
        allocated_capital=5000.0,
        policy=BotRiskPolicy(
            risk_per_trade_pct=1.0,
            daily_loss_limit_pct=15.0,
            max_open_positions=1,
            min_risk_reward=2.0,
        ),
    )

    paper = PaperBroker(
        initial_capital=5000.0,
        risk_account=risk_account,
        bot_id=bot_id,
    )

    return risk_account, paper


def test_save_and_reload_bot_account(tmp_path):
    database = tmp_path / "magic_trade.db"
    risk_account, paper = make_paper_account()

    storage = TradeStorage(database)

    assert storage.save_account_snapshot(
        risk_account,
        paper,
    )

    # Reopen the database using a new storage instance.
    reopened = TradeStorage(database)

    saved_bot = reopened.get_bot("storage-test-bot")

    assert saved_bot is not None
    assert saved_bot["bot_id"] == "storage-test-bot"
    assert saved_bot["allocated_capital"] == 5000.0
    assert saved_bot["current_equity"] == 5000.0
    assert saved_bot["status"] == "ACTIVE"
    assert saved_bot["open_positions"] == 0

    saved_policy = json.loads(saved_bot["policy_json"])

    assert saved_policy["risk_per_trade_pct"] == 1.0
    assert saved_policy["daily_loss_limit_pct"] == 15.0


def test_save_and_reload_open_paper_position(tmp_path):
    database = tmp_path / "positions.db"
    risk_account, paper = make_paper_account()

    paper.execute(
        Trade(
            symbol="TEST",
            side=Side.BUY,
            quantity=1,
            entry=100.0,
            stop_loss=98.0,
            target=104.0,
            risk_amount=2.0,
        )
    )

    storage = TradeStorage(database)
    storage.save_account_snapshot(risk_account, paper)

    reopened = TradeStorage(database)

    positions = reopened.list_positions(
        "storage-test-bot",
        status="OPEN",
    )

    assert len(positions) == 1
    assert positions[0]["symbol"] == "TEST"
    assert positions[0]["side"] == "BUY"
    assert positions[0]["quantity"] == 1
    assert positions[0]["status"] == "OPEN"


def test_save_and_reload_trade_history(tmp_path):
    database = tmp_path / "trades.db"
    risk_account, paper = make_paper_account()

    paper.execute(
        Trade(
            symbol="TEST",
            side=Side.BUY,
            quantity=1,
            entry=100.0,
            stop_loss=98.0,
            target=104.0,
            risk_amount=2.0,
        )
    )

    storage = TradeStorage(database)
    storage.save_account_snapshot(risk_account, paper)

    reopened = TradeStorage(database)
    trades = reopened.list_trades("storage-test-bot")

    assert len(trades) == 1
    assert trades[0]["symbol"] == "TEST"
    assert trades[0]["side"] == "BUY"
    assert trades[0]["status"] == "OPEN"


def test_save_and_reload_audit_events(tmp_path):
    database = tmp_path / "audit.db"
    risk_account, paper = make_paper_account()

    paper.execute(
        Trade(
            symbol="TEST",
            side=Side.BUY,
            quantity=1,
            entry=100.0,
            stop_loss=98.0,
            target=104.0,
            risk_amount=2.0,
        )
    )

    storage = TradeStorage(database)
    storage.save_account_snapshot(risk_account, paper)

    reopened = TradeStorage(database)
    events = reopened.list_audit_events("storage-test-bot")

    assert len(events) >= 1
    assert any(
        event["event"] == "POSITION_OPENED"
        for event in events
    )


def test_repeated_snapshot_does_not_duplicate_audit_events(tmp_path):
    database = tmp_path / "duplicate-events.db"
    risk_account, paper = make_paper_account()

    paper.execute(
        Trade(
            symbol="TEST",
            side=Side.BUY,
            quantity=1,
            entry=100.0,
            stop_loss=98.0,
            target=104.0,
            risk_amount=2.0,
        )
    )

    storage = TradeStorage(database)

    storage.save_account_snapshot(risk_account, paper)
    storage.save_account_snapshot(risk_account, paper)

    events = storage.list_audit_events("storage-test-bot")

    assert len(events) == 1


def test_storage_rejects_mismatched_bot_ids(tmp_path):
    risk_account, paper = make_paper_account()
    paper.bot_id = "different-bot"

    storage = TradeStorage(tmp_path / "mismatch.db")

    with pytest.raises(ValueError):
        storage.save_account_snapshot(risk_account, paper)


def test_storage_rejects_mismatched_open_position_count(tmp_path):
    risk_account, paper = make_paper_account()

    paper.execute(
        Trade(
            symbol="TEST",
            side=Side.BUY,
            quantity=1,
            entry=100.0,
            stop_loss=98.0,
            target=104.0,
            risk_amount=2.0,
        )
    )

    risk_account.open_positions = 0

    storage = TradeStorage(tmp_path / "count-mismatch.db")

    with pytest.raises(ValueError):
        storage.save_account_snapshot(risk_account, paper)


def test_history_limit_must_be_valid(tmp_path):
    storage = TradeStorage(tmp_path / "limits.db")

    with pytest.raises(ValueError):
        storage.list_trades("storage-test-bot", limit=0)

    with pytest.raises(ValueError):
        storage.list_audit_events("storage-test-bot", limit=10001)
