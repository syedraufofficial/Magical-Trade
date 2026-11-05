
"""Per-bot risk controls for Magic Trade."""

from dataclasses import dataclass, field
from datetime import date, datetime
from math import isfinite
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from magical_trade.models import BotStatus


INDIA_TZ = ZoneInfo("Asia/Kolkata")


def india_today() -> date:
    return datetime.now(INDIA_TZ).date()


@dataclass
class BotRiskPolicy:
    risk_per_trade_pct: float = 1.0
    daily_loss_limit_pct: float = 15.0
    max_open_positions: int = 1
    min_risk_reward: float = 2.0

    def __post_init__(self):
        values = (
            self.risk_per_trade_pct,
            self.daily_loss_limit_pct,
            self.min_risk_reward,
        )

        if not all(isfinite(float(v)) for v in values):
            raise ValueError("Risk policy values must be finite")

        if not 0 < self.risk_per_trade_pct <= 100:
            raise ValueError("Invalid risk per trade")

        if not 0 < self.daily_loss_limit_pct <= 15:
            raise ValueError("Daily loss cannot exceed 15%")

        if (
            not isinstance(self.max_open_positions, int)
            or isinstance(self.max_open_positions, bool)
            or self.max_open_positions < 1
        ):
            raise ValueError("Invalid maximum open positions")

        if self.min_risk_reward < 2.0:
            raise ValueError("Minimum risk/reward must be 2:1")


@dataclass
class BotRiskAccount:
    bot_id: str
    allocated_capital: float
    policy: BotRiskPolicy = field(default_factory=BotRiskPolicy)
    current_equity: Optional[float] = None
    daily_realized_pnl: float = 0.0
    daily_unrealized_pnl: float = 0.0
    open_positions: int = 0
    status: BotStatus = BotStatus.ACTIVE
    retirement_reason: Optional[str] = None
    trading_day: date = field(default_factory=india_today)
    audit_log: list = field(default_factory=list)
    _daily_limit_event_logged: bool = field(
        default=False,
        init=False,
        repr=False,
    )

    def __post_init__(self):
        if not isinstance(self.bot_id, str) or not self.bot_id.strip():
            raise ValueError("Bot ID is required")

        if (
            not isfinite(float(self.allocated_capital))
            or self.allocated_capital <= 0
        ):
            raise ValueError("Allocated capital must be finite and positive")

        if self.current_equity is None:
            self.current_equity = float(self.allocated_capital)

        if (
            not isfinite(float(self.current_equity))
            or self.current_equity < 0
        ):
            raise ValueError("Invalid current equity")

        if self.open_positions < 0:
            raise ValueError("Open positions cannot be negative")

        if self.current_equity <= 0:
            self.retire("Allocated capital exhausted")

    @property
    def daily_loss_limit_amount(self):
        return (
            self.allocated_capital
            * self.policy.daily_loss_limit_pct
            / 100.0
        )

    @property
    def total_daily_pnl(self):
        return self.daily_realized_pnl + self.daily_unrealized_pnl

    @property
    def daily_limit_reached(self):
        return self.total_daily_pnl <= -self.daily_loss_limit_amount

    @property
    def risk_per_trade_amount(self):
        return (
            self.allocated_capital
            * self.policy.risk_per_trade_pct
            / 100.0
        )

    def can_open(self, planned_risk: float, risk_reward: float = 2.0):
        try:
            planned_risk = float(planned_risk)
            risk_reward = float(risk_reward)
        except (TypeError, ValueError):
            return False, "Invalid risk values"

        if not isfinite(planned_risk) or not isfinite(risk_reward):
            return False, "Risk values must be finite"

        if self.status != BotStatus.ACTIVE:
            return False, "Bot is not active"

        if self.current_equity <= 0:
            self.retire("Allocated capital exhausted")
            return False, "Bot permanently retired"

        if self.daily_limit_reached:
            self._check_daily_limit()
            return False, "Daily loss limit reached"

        if self.open_positions >= self.policy.max_open_positions:
            return False, "Maximum open positions reached"

        if planned_risk <= 0:
            return False, "Invalid planned risk"

        if planned_risk > self.risk_per_trade_amount:
            return (
                False,
                "Planned risk exceeds this bot's trade risk budget",
            )

        if risk_reward < self.policy.min_risk_reward:
            return False, "Risk/reward is below the required minimum"

        return True, "Risk checks passed"

    def record_open(self, planned_risk: float, risk_reward: float = 2.0):
        allowed, reason = self.can_open(planned_risk, risk_reward)

        if not allowed:
            return False, reason

        self.open_positions += 1
        self.audit_log.append({
            "event": "POSITION_OPENED",
            "planned_risk": float(planned_risk),
            "risk_reward": float(risk_reward),
        })

        return True, "Position registered"

    def update_unrealized_pnl(self, pnl: float):
        pnl = float(pnl)

        if not isfinite(pnl):
            raise ValueError("Unrealized P&L must be finite")

        self.daily_unrealized_pnl = pnl
        self._check_daily_limit()

        return self.daily_limit_reached

    def record_close(
        self,
        net_pnl: float,
        remaining_unrealized_pnl: float = 0.0,
    ):
        net_pnl = float(net_pnl)
        remaining_unrealized_pnl = float(remaining_unrealized_pnl)

        if not isfinite(net_pnl):
            raise ValueError("Net P&L must be finite")

        if not isfinite(remaining_unrealized_pnl):
            raise ValueError("Remaining unrealized P&L must be finite")

        if self.open_positions <= 0:
            raise ValueError("No registered open position to close")

        self.open_positions -= 1
        self.daily_realized_pnl += net_pnl
        self.daily_unrealized_pnl = remaining_unrealized_pnl
        self.current_equity += net_pnl

        self.audit_log.append({
            "event": "POSITION_CLOSED",
            "net_pnl": net_pnl,
            "remaining_unrealized_pnl": remaining_unrealized_pnl,
        })

        self._check_daily_limit()

        if self.current_equity <= 0:
            self.retire("Allocated capital exhausted")

        return self.current_equity

    def _check_daily_limit(self):
        if (
            self.daily_limit_reached
            and not self._daily_limit_event_logged
        ):
            self._daily_limit_event_logged = True
            self.audit_log.append({
                "event": "DAILY_LOSS_LIMIT_REACHED",
                "daily_pnl": self.total_daily_pnl,
                "limit": self.daily_loss_limit_amount,
            })

    def retire(self, reason: str):
        if self.status == BotStatus.RETIRED:
            return

        self.status = BotStatus.RETIRED
        self.retirement_reason = str(reason)

        self.audit_log.append({
            "event": "BOT_RETIRED",
            "reason": self.retirement_reason,
        })

    def reset_daily_pnl(self, new_day: date):
        if self.status == BotStatus.RETIRED:
            raise ValueError("Retired bots cannot resume trading")

        if self.open_positions:
            raise ValueError(
                "Close all positions before resetting daily risk"
            )

        if not isinstance(new_day, date):
            raise ValueError("Trading day must be a date")

        if new_day <= self.trading_day:
            raise ValueError("New trading day must be later")

        self.trading_day = new_day
        self.daily_realized_pnl = 0.0
        self.daily_unrealized_pnl = 0.0
        self._daily_limit_event_logged = False

        self.audit_log.append({
            "event": "DAILY_RISK_RESET",
            "trading_day": new_day.isoformat(),
        })


class BotRiskRegistry:
    def __init__(self):
        self.accounts: Dict[str, BotRiskAccount] = {}

    def register(
        self,
        bot_id: str,
        allocated_capital: float,
        policy: Optional[BotRiskPolicy] = None,
    ):
        if not isinstance(bot_id, str) or not bot_id.strip():
            raise ValueError("Bot ID is required")

        if bot_id in self.accounts:
            raise ValueError("Bot ID already exists")

        account = BotRiskAccount(
            bot_id=bot_id,
            allocated_capital=allocated_capital,
            policy=policy or BotRiskPolicy(),
        )

        self.accounts[bot_id] = account
        return account

    def get(self, bot_id: str):
        return self.accounts.get(bot_id)


class RiskManager:
    """Backward-compatible trade sizing check."""

    def __init__(self, max_risk_per_trade=50.0):
        if (
            not isfinite(float(max_risk_per_trade))
            or max_risk_per_trade <= 0
        ):
            raise ValueError("Maximum risk must be finite and positive")

        self.max_risk_per_trade = float(max_risk_per_trade)

    def size_trade(self, signal, quantity=1):
        if (
            not isinstance(quantity, int)
            or isinstance(quantity, bool)
            or quantity <= 0
        ):
            raise ValueError("Quantity must be a positive integer")

        risk_per_unit = abs(signal.entry - signal.stop_loss)
        total_risk = risk_per_unit * quantity

        if not isfinite(total_risk):
            raise ValueError("Trade risk must be finite")

        if total_risk > self.max_risk_per_trade:
            raise ValueError("Trade risk exceeds maximum allowed")

        return quantity
