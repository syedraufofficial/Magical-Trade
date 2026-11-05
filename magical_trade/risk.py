
from dataclasses import dataclass, field
from typing import Dict, Optional
from datetime import date

from magical_trade.models import BotStatus


@dataclass
class BotRiskPolicy:
    risk_per_trade_pct: float = 1.0
    daily_loss_limit_pct: float = 15.0
    max_open_positions: int = 1
    min_risk_reward: float = 2.0

    def __post_init__(self):
        if not 0 < self.risk_per_trade_pct <= 100:
            raise ValueError("Invalid risk per trade")
        if not 0 < self.daily_loss_limit_pct <= 15:
            raise ValueError("Daily loss cannot exceed 15%")
        if self.max_open_positions < 1:
            raise ValueError("At least one position limit is required")
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
    trading_day: date = field(default_factory=date.today)
    audit_log: list = field(default_factory=list)

    def __post_init__(self):
        if self.allocated_capital <= 0:
            raise ValueError("Allocated capital must be positive")
        if self.current_equity is None:
            self.current_equity = self.allocated_capital

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
        if self.status != BotStatus.ACTIVE:
            return False, "Bot is not active"

        if self.daily_limit_reached:
            return False, "Daily loss limit reached"

        if self.open_positions >= self.policy.max_open_positions:
            return False, "Maximum open positions reached"

        if planned_risk <= 0:
            return False, "Invalid planned risk"

        if planned_risk > self.risk_per_trade_amount:
            return False, "Planned risk exceeds this bot's trade risk budget"

        if risk_reward < self.policy.min_risk_reward:
            return False, "Risk/reward is below the required minimum"

        if self.current_equity <= 0:
            self.retire("Allocated capital exhausted")
            return False, "Bot permanently retired"

        return True, "Risk checks passed"

    def record_open(self, planned_risk: float, risk_reward: float = 2.0):
        allowed, reason = self.can_open(planned_risk, risk_reward)
        if not allowed:
            return False, reason

        self.open_positions += 1
        self.audit_log.append({
            "event": "POSITION_OPENED",
            "planned_risk": planned_risk,
            "risk_reward": risk_reward,
        })
        return True, "Position registered"

    def update_unrealized_pnl(self, pnl: float):
        self.daily_unrealized_pnl = float(pnl)
        self._check_daily_limit()

    def record_close(self, net_pnl: float):
        if self.open_positions > 0:
            self.open_positions -= 1

        self.daily_realized_pnl += float(net_pnl)
        self.daily_unrealized_pnl = 0.0
        self.current_equity += float(net_pnl)

        self.audit_log.append({
            "event": "POSITION_CLOSED",
            "net_pnl": float(net_pnl),
        })

        self._check_daily_limit()

        if self.current_equity <= 0:
            self.retire("Allocated capital exhausted")

    def _check_daily_limit(self):
        if self.daily_limit_reached:
            self.audit_log.append({
                "event": "DAILY_LOSS_LIMIT_REACHED",
                "daily_pnl": self.total_daily_pnl,
                "limit": self.daily_loss_limit_amount,
            })

    def retire(self, reason: str):
        self.status = BotStatus.RETIRED
        self.retirement_reason = reason
        self.audit_log.append({
            "event": "BOT_RETIRED",
            "reason": reason,
        })

    def reset_daily_pnl(self, new_day: date):
        if self.open_positions:
            raise ValueError(
                "Close all positions before resetting daily risk"
            )

        if new_day <= self.trading_day:
            raise ValueError("New trading day must be later")

        self.trading_day = new_day
        self.daily_realized_pnl = 0.0
        self.daily_unrealized_pnl = 0.0
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
