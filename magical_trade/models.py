
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime, timezone


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Mode(str, Enum):
    PAPER = "PAPER"
    REAL = "REAL"


class BotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    QUARANTINED = "QUARANTINED"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    ltp: float
    bid: float
    ask: float
    vwap: float = 0.0
    sma_fast: float = 0.0
    sma_slow: float = 0.0
    oi_change_pct: float = 0.0
    volume_ratio: float = 1.0
    volatility_pct: float = 0.0


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: Side
    confidence: float
    entry: float
    stop_loss: float
    target: float
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class Trade:
    symbol: str
    side: Side
    quantity: int
    entry: float
    stop_loss: float
    target: float
    risk_amount: float


@dataclass
class BotIdentity:
    bot_id: str
    strategy_name: str
    mode: Mode = Mode.PAPER
    status: BotStatus = BotStatus.ACTIVE
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    retirement_reason: Optional[str] = None


@dataclass
class PaperPosition:
    position_id: str
    bot_id: str
    symbol: str
    side: Side
    quantity: int
    entry_price: float
    stop_loss: float
    target: float
    opened_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    current_price: float = 0.0
    status: OrderStatus = OrderStatus.OPEN
    realized_pnl: float = 0.0
    fees: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        if self.current_price <= 0:
            return 0.0

        if self.side == Side.BUY:
            return (
                self.current_price - self.entry_price
            ) * self.quantity

        return (
            self.entry_price - self.current_price
        ) * self.quantity


@dataclass
class BotDailyStats:
    bot_id: str
    starting_capital: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    trades_taken: int = 0
    losses: int = 0
    daily_loss_limit_pct: float = 15.0

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def daily_loss_limit_amount(self) -> float:
        return self.starting_capital * (
            self.daily_loss_limit_pct / 100.0
        )

    @property
    def daily_limit_reached(self) -> bool:
        return self.total_pnl <= -self.daily_loss_limit_amount
