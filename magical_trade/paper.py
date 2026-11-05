
"""Paper broker with optional per-bot risk enforcement."""

from dataclasses import dataclass, field
from typing import Dict
from uuid import uuid4
import math

from .models import Trade, Side


@dataclass
class PaperPosition:
    position_id: str
    symbol: str
    side: Side
    quantity: int
    entry_price: float
    stop_loss: float
    target: float
    entry_fees: float
    current_price: float
    status: str = "OPEN"
    bot_id: str = "default"


@dataclass
class PaperBroker:
    initial_capital: float = 5000.0
    brokerage_per_order: float = 0.0
    slippage_bps: float = 5.0
    risk_account: object = None
    bot_id: str = "default"

    cash: float = field(init=False)
    trades: list = field(default_factory=list)
    positions: Dict[str, PaperPosition] = field(default_factory=dict)
    closed_positions: list = field(default_factory=list)

    def __post_init__(self):
        if (
            not math.isfinite(self.initial_capital)
            or not math.isfinite(self.brokerage_per_order)
            or not math.isfinite(self.slippage_bps)
            or self.initial_capital <= 0
            or self.brokerage_per_order < 0
            or self.slippage_bps < 0
            or self.slippage_bps >= 10000
        ):
            raise ValueError("Invalid paper account configuration")

        if not self.bot_id:
            raise ValueError("Bot ID is required")

        if self.risk_account is not None:
            if self.risk_account.bot_id != self.bot_id:
                raise ValueError("Risk account belongs to another bot")
            if self.risk_account.allocated_capital != self.initial_capital:
                raise ValueError("Paper capital must match bot allocation")

        self.cash = float(self.initial_capital)

    def _slipped_price(self, price: float, side: Side) -> float:
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Price must be finite and positive")

        slip = price * self.slippage_bps / 10000.0
        return price + slip if side == Side.BUY else price - slip

    @property
    def used_capital(self) -> float:
        return sum(
            p.entry_price * p.quantity
            for p in self.positions.values()
            if p.status == "OPEN"
        )

    @property
    def unrealized_pnl(self) -> float:
        return sum(
            self._position_pnl(p)
            for p in self.positions.values()
            if p.status == "OPEN"
        )

    @property
    def equity(self) -> float:
        return self.cash + self.used_capital + self.unrealized_pnl

    def execute(self, trade: Trade):
        if not isinstance(trade, Trade):
            raise TypeError("Expected a Trade object")

        if not isinstance(trade.side, Side):
            raise ValueError("Invalid trade side")

        if not isinstance(trade.quantity, int) or trade.quantity <= 0:
            raise ValueError("Quantity must be a positive integer")

        prices = (trade.entry, trade.stop_loss, trade.target)
        if not all(math.isfinite(p) and p > 0 for p in prices):
            raise ValueError("Trade prices must be finite and positive")

        if not trade.symbol:
            raise ValueError("Trade symbol is required")

        if trade.side == Side.BUY:
            if not trade.stop_loss < trade.entry < trade.target:
                raise ValueError("BUY requires stop < entry < target")
        else:
            if not trade.target < trade.entry < trade.stop_loss:
                raise ValueError("SELL requires target < entry < stop")

        risk_per_unit = abs(trade.entry - trade.stop_loss)
        reward_per_unit = abs(trade.target - trade.entry)
        risk_reward = reward_per_unit / risk_per_unit

        if risk_reward < 2.0:
            raise ValueError("Minimum risk/reward must be 2:1")

        fill = self._slipped_price(trade.entry, trade.side)
        fee = self.brokerage_per_order
        required = fill * trade.quantity + fee

        if required > self.cash:
            raise ValueError("Insufficient paper cash")

        # Include entry slippage and fees in the risk budget.
        planned_risk = (
            abs(fill - trade.stop_loss) * trade.quantity + fee
        )

        if self.risk_account is not None:
            allowed, reason = self.risk_account.can_open(
                planned_risk,
                risk_reward,
            )
            if not allowed:
                raise ValueError(reason)

        position_id = str(uuid4())

        position = PaperPosition(
            position_id=position_id,
            symbol=trade.symbol,
            side=trade.side,
            quantity=trade.quantity,
            entry_price=fill,
            stop_loss=trade.stop_loss,
            target=trade.target,
            entry_fees=fee,
            current_price=fill,
            bot_id=self.bot_id,
        )

        # Register risk only after all other entry checks pass.
        if self.risk_account is not None:
            allowed, reason = self.risk_account.record_open(
                planned_risk,
                risk_reward,
            )
            if not allowed:
                raise ValueError(reason)

        self.cash -= required
        self.positions[position_id] = position

        record = {
            "position_id": position_id,
            "bot_id": self.bot_id,
            "symbol": trade.symbol,
            "side": trade.side.value,
            "qty": trade.quantity,
            "fill": round(fill, 4),
            "fees": fee,
            "planned_risk": planned_risk,
            "risk_reward": risk_reward,
            "status": "OPEN",
        }

        self.trades.append(record)
        return record

    def update_price(self, position_id: str, market_price: float):
        position = self.positions.get(position_id)

        if position is None or position.status != "OPEN":
            raise ValueError("Open paper position not found")

        if not math.isfinite(market_price) or market_price <= 0:
            raise ValueError("Market price must be finite and positive")

        position.current_price = float(market_price)

        if self.risk_account is not None:
            self.risk_account.update_unrealized_pnl(
                self.unrealized_pnl
            )

        return {
            "position_id": position_id,
            "unrealized_pnl": self._position_pnl(position),
            "status": position.status,
        }

    def _position_pnl(self, position: PaperPosition) -> float:
        if position.side == Side.BUY:
            return (
                position.current_price - position.entry_price
            ) * position.quantity

        return (
            position.entry_price - position.current_price
        ) * position.quantity

    def close_position(
        self,
        position_id: str,
        market_price: float,
        reason: str = "MANUAL",
    ):
        position = self.positions.get(position_id)

        if position is None or position.status != "OPEN":
            raise ValueError("Open paper position not found")

        if not math.isfinite(market_price) or market_price <= 0:
            raise ValueError("Exit price must be finite and positive")

        exit_side = (
            Side.SELL if position.side == Side.BUY else Side.BUY
        )
        exit_fill = self._slipped_price(market_price, exit_side)
        exit_fee = self.brokerage_per_order

        gross_pnl = (
            (exit_fill - position.entry_price) * position.quantity
            if position.side == Side.BUY
            else (position.entry_price - exit_fill) * position.quantity
        )

        net_pnl = gross_pnl - position.entry_fees - exit_fee

        self.cash += (
            position.entry_price * position.quantity + gross_pnl - exit_fee
        )

        position.current_price = exit_fill
        position.status = "CLOSED"

        result = {
            "position_id": position_id,
            "bot_id": self.bot_id,
            "symbol": position.symbol,
            "side": position.side.value,
            "quantity": position.quantity,
            "entry_price": position.entry_price,
            "exit_price": exit_fill,
            "gross_pnl": gross_pnl,
            "fees": position.entry_fees + exit_fee,
            "net_pnl": net_pnl,
            "reason": reason,
            "status": "CLOSED",
        }

        self.closed_positions.append(result)

        if self.risk_account is not None:
            self.risk_account.record_close(net_pnl)

        return result
