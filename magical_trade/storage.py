
"""Persistent SQLite storage for Magic Trade paper trading."""

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any


def _json_default(value: Any):
    if isinstance(value, Enum):
        return value.value

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if is_dataclass(value):
        return asdict(value)

    raise TypeError(
        f"Unsupported JSON value: {type(value).__name__}"
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        default=_json_default,
        sort_keys=True,
        allow_nan=False,
    )


class TradeStorage:
    """Transactional persistent storage for paper accounts and audit data."""

    SCHEMA_VERSION = 1

    def __init__(self, database_path="data/magic_trade.db"):
        self.database_path = Path(database_path)

        if str(self.database_path) != ":memory:":
            self.database_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=15,
        )

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")

        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")

            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_info (
                    version INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bots (
                    bot_id TEXT PRIMARY KEY,
                    allocated_capital REAL NOT NULL,
                    current_equity REAL NOT NULL,
                    status TEXT NOT NULL,
                    retirement_reason TEXT,
                    trading_day TEXT NOT NULL,
                    daily_realized_pnl REAL NOT NULL,
                    daily_unrealized_pnl REAL NOT NULL,
                    open_positions INTEGER NOT NULL,
                    policy_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    position_id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    position_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(bot_id) REFERENCES bots(bot_id)
                );

                CREATE TABLE IF NOT EXISTS trades (
                    position_id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trade_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(bot_id) REFERENCES bots(bot_id)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(bot_id) REFERENCES bots(bot_id)
                );

                CREATE INDEX IF NOT EXISTS idx_positions_bot
                    ON positions(bot_id, status);

                CREATE INDEX IF NOT EXISTS idx_trades_bot
                    ON trades(bot_id, updated_at);

                CREATE INDEX IF NOT EXISTS idx_events_bot
                    ON audit_events(bot_id, created_at);
                """
            )

            row = connection.execute(
                "SELECT version FROM schema_info LIMIT 1"
            ).fetchone()

            if row is None:
                connection.execute(
                    "INSERT INTO schema_info(version) VALUES (?)",
                    (self.SCHEMA_VERSION,),
                )
            elif row["version"] != self.SCHEMA_VERSION:
                raise RuntimeError(
                    "Unsupported database schema version. "
                    "A controlled migration is required."
                )

    @staticmethod
    def _validate_number(value, field_name):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} must be numeric")

        if not math.isfinite(number):
            raise ValueError(f"{field_name} must be finite")

        return number

    def save_account_snapshot(self, risk_account, paper_broker):
        """Save one bot's risk state and paper positions atomically."""

        if risk_account.bot_id != paper_broker.bot_id:
            raise ValueError("Risk account and paper broker bot IDs differ")

        if risk_account.allocated_capital != paper_broker.initial_capital:
            raise ValueError("Allocated capital does not match paper broker")

        if risk_account.open_positions != sum(
            1
            for position in paper_broker.positions.values()
            if position.status == "OPEN"
        ):
            raise ValueError("Risk position count does not match broker")

        policy = asdict(risk_account.policy)

        account_values = {
            "allocated_capital": self._validate_number(
                risk_account.allocated_capital,
                "Allocated capital",
            ),
            "current_equity": self._validate_number(
                risk_account.current_equity,
                "Current equity",
            ),
            "daily_realized_pnl": self._validate_number(
                risk_account.daily_realized_pnl,
                "Daily realized P&L",
            ),
            "daily_unrealized_pnl": self._validate_number(
                risk_account.daily_unrealized_pnl,
                "Daily unrealized P&L",
            ),
        }

        now = datetime.now().astimezone().isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO bots (
                    bot_id, allocated_capital, current_equity,
                    status, retirement_reason, trading_day,
                    daily_realized_pnl, daily_unrealized_pnl,
                    open_positions, policy_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id) DO UPDATE SET
                    allocated_capital=excluded.allocated_capital,
                    current_equity=excluded.current_equity,
                    status=excluded.status,
                    retirement_reason=excluded.retirement_reason,
                    trading_day=excluded.trading_day,
                    daily_realized_pnl=excluded.daily_realized_pnl,
                    daily_unrealized_pnl=excluded.daily_unrealized_pnl,
                    open_positions=excluded.open_positions,
                    policy_json=excluded.policy_json,
                    updated_at=excluded.updated_at
                """,
                (
                    risk_account.bot_id,
                    account_values["allocated_capital"],
                    account_values["current_equity"],
                    risk_account.status.value,
                    risk_account.retirement_reason,
                    risk_account.trading_day.isoformat(),
                    account_values["daily_realized_pnl"],
                    account_values["daily_unrealized_pnl"],
                    risk_account.open_positions,
                    _json_dumps(policy),
                    now,
                ),
            )

            for position in paper_broker.positions.values():
                position_data = asdict(position)

                connection.execute(
                    """
                    INSERT INTO positions (
                        position_id, bot_id, symbol,
                        status, position_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(position_id) DO UPDATE SET
                        status=excluded.status,
                        position_json=excluded.position_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        position.position_id,
                        risk_account.bot_id,
                        position.symbol,
                        position.status,
                        _json_dumps(position_data),
                        now,
                    ),
                )

            for trade in paper_broker.trades:
                position_id = trade.get("position_id")

                if not position_id:
                    raise ValueError(
                        "Paper trade is missing its position ID"
                    )

                connection.execute(
                    """
                    INSERT INTO trades (
                        position_id, bot_id, symbol,
                        status, trade_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(position_id) DO UPDATE SET
                        status=excluded.status,
                        trade_json=excluded.trade_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        position_id,
                        risk_account.bot_id,
                        trade["symbol"],
                        trade["status"],
                        _json_dumps(trade),
                        now,
                    ),
                )

            for event in risk_account.audit_log:
                event_json = _json_dumps(event)
                event_id = hashlib.sha256(
                    (
                        risk_account.bot_id
                        + event_json
                    ).encode("utf-8")
                ).hexdigest()

                connection.execute(
                    """
                    INSERT OR IGNORE INTO audit_events (
                        event_id, bot_id, event_type,
                        event_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        risk_account.bot_id,
                        str(event.get("event", "UNKNOWN")),
                        event_json,
                        now,
                    ),
                )

        return True

    def get_bot(self, bot_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM bots WHERE bot_id = ?",
                (bot_id,),
            ).fetchone()

        return dict(row) if row else None

    def list_positions(self, bot_id, status=None):
        query = """
            SELECT position_json
            FROM positions
            WHERE bot_id = ?
        """
        params = [bot_id]

        if status is not None:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY updated_at DESC"

        with self._connect() as connection:
            rows = connection.execute(
                query,
                params,
            ).fetchall()

        return [
            json.loads(row["position_json"])
            for row in rows
        ]

    def list_trades(self, bot_id, limit=500):
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 10000
        ):
            raise ValueError("Invalid trade history limit")

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT trade_json
                FROM trades
                WHERE bot_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (bot_id, limit),
            ).fetchall()

        return [
            json.loads(row["trade_json"])
            for row in rows
        ]

    def list_audit_events(self, bot_id, limit=500):
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 10000
        ):
            raise ValueError("Invalid audit history limit")

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_json
                FROM audit_events
                WHERE bot_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (bot_id, limit),
            ).fetchall()

        return [
            json.loads(row["event_json"])
            for row in rows
        ]

    def close(self):
        """Connections are short-lived; retained for API compatibility."""
        return None
