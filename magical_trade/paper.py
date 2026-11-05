
"""Long-only paper broker with per-bot risk enforcement."""

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
        values = (
            self.initial_capital,
            self.brokerage_per_order,
            self.slippage_bps,
        )

        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError("Paper account values must be finite")

        if (
            self.initial_capital <= 0
            or self.brokerage_per_order < 0
            or self.slippage_bps < 0
            or self.slippage_bps >= 10000
        ):
            raise ValueError("Invalid paper account configuration")

        if not isinstance(self.bot_id, str) or not self.bot_id.strip():
            raise ValueError("Bot ID is required")

        if self.risk_account is not None:
            if self.risk_account.bot_id != self.bot_id:
                raise ValueError("Risk account belongs to another bot")

            if self.risk_account.allocated_capital != self.initial_capital:
                raise ValueError("Paper capital must match bot allocation")

        self.cash = float(self.initial_capital)

    def _slipped_price(self, price: float, side: Side) -> float:
        price = float(price)

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
    def risk_unrealized_pnl(self) -> float:
        return sum(
            self._position_pnl(p)
            - p.entry_fees
            - self.brokerage_per_order
            for p in self.positions.values()
            if p.status == "OPEN"
        )

    @property
    def equity(self) -> float:
        return self.cash + self.used_capital + self.unrealized_pnl

    def execute(self, trade: Trade):
        if not isinstance(trade, Trade):
            raise TypeError("Expected a Trade object")

        if trade.side != Side.BUY:
            raise ValueError("Paper broker supports BUY positions only")

        if (
            not isinstance(trade.quantity, int)
            or isinstance(trade.quantity, bool)
            or trade.quantity <= 0
        ):
            raise ValueError("Quantity must be a positive integer")

        prices = (trade.entry, trade.stop_loss, trade.target)

        if not all(
            math.isfinite(float(p)) and float(p) > 0
            for p in prices
        ):
            raise ValueError("Trade prices must be finite and positive")

        if not isinstance(trade.symbol, str) or not trade.symbol.strip():
            raise ValueError("Trade symbol is required")

        if not trade.stop_loss < trade.entry < trade.target:
            raise ValueError("BUY requires stop < entry < target")

        risk_per_unit = trade.entry - trade.stop_loss
        reward_per_unit = trade.target - trade.entry
        risk_reward = reward_per_unit / risk_per_unit

        if risk_reward < 2.0:
            raise ValueError("Minimum risk/reward must be 2:1")

        fill = self._slipped_price(trade.entry, Side.BUY)
        fee = self.brokerage_per_order
        required = fill * trade.quantity + fee

        if required > self.cash:
            raise ValueError("Insufficient paper cash")

        estimated_exit = self._slipped_price(
            trade.stop_loss,
            Side.SELL,
        )
        planned_risk = (
            (fill - estimated_exit) * trade.quantity
            + fee
            + self.brokerage_per_order
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
            side=Side.BUY,
            quantity=trade.quantity,
            entry_price=fill,
            stop_loss=trade.stop_loss,
            target=trade.target,
            entry_fees=fee,
            current_price=fill,
            bot_id=self.bot_id,
        )

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
            "side": "BUY",
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

        market_price = float(market_price)

        if not math.isfinite(market_price) or market_price <= 0:
            raise ValueError("Market price must be finite and positive")

        position.current_price = market_price

        if self.risk_account is not None:
            self.risk_account.update_unrealized_pnl(
                self.risk_unrealized_pnl
            )

        return {
            "position_id": position_id,
            "unrealized_pnl": self._position_pnl(position),
            "status": position.status,
        }

    def monitor_positions(self, market_prices: dict):
        """Update prices and automatically close triggered paper positions.

        market_prices maps each instrument symbol to its latest observed price.
        This method must be called repeatedly by the paper-trading runner.
        """
        if not isinstance(market_prices, dict):
            raise TypeError("Market prices must be a symbol-to-price dictionary")

        validated_prices = {}

        for symbol, price in market_prices.items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("Invalid market price symbol")

            price = float(price)

            if not math.isfinite(price) or price <= 0:
                raise ValueError("Market prices must be finite and positive")

            validated_prices[symbol] = price

        # First mark every matching open position to market.
        for position in self.positions.values():
            if (
                position.status == "OPEN"
                and position.symbol in validated_prices
            ):
                position.current_price = validated_prices[position.symbol]

        if self.risk_account is not None:
            self.risk_account.update_unrealized_pnl(
                self.risk_unrealized_pnl
            )

        closed = []

        # Then close triggered positions using the observed market price.
        for position in list(self.positions.values()):
            if position.status != "OPEN":
                continue

            if position.symbol not in validated_prices:
                continue

            price = validated_prices[position.symbol]

            if price <= position.stop_loss:
                result = self.close_position(
                    position.position_id,
                    price,
                    reason="STOP_LOSS",
                )
                closed.append(result)

            elif price >= position.target:
                result = self.close_position(
                    position.position_id,
                    price,
                    reason="TARGET",
                )
                closed.append(result)

        return {
            "updated_positions": sum(
                1
                for p in self.positions.values()
                if p.symbol in validated_prices
            ),
            "closed_positions": closed,
            "remaining_open_positions": sum(
                1 for p in self.positions.values()
                if p.status == "OPEN"
            ),
        }

    def _position_pnl(self, position: PaperPosition) -> float:
        return (
            position.current_price - position.entry_price
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

        exit_fill = self._slipped_price(market_price, Side.SELL)
        exit_fee = self.brokerage_per_order

        gross_pnl = (
            exit_fill - position.entry_price
        ) * position.quantity

        net_pnl = gross_pnl - position.entry_fees - exit_fee

        self.cash += (
            position.entry_price * position.quantity
            + gross_pnl
            - exit_fee
        )

        position.current_price = exit_fill
        position.status = "CLOSED"

        result = {
            "position_id": position_id,
            "bot_id": self.bot_id,
            "symbol": position.symbol,
            "side": "BUY",
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
            self.risk_account.record_close(
                net_pnl,
                remaining_unrealized_pnl=self.risk_unrealized_pnl,
            )

        return result
