
from dataclasses import dataclass, field
from typing import Dict, Optional
from uuid import uuid4

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


@dataclass
class PaperBroker:
    initial_capital: float = 5000.0
    brokerage_per_order: float = 0.0
    slippage_bps: float = 5.0

    cash: float = field(init=False)
    trades: list = field(default_factory=list)
    positions: Dict[str, PaperPosition] = field(default_factory=dict)
    closed_positions: list = field(default_factory=list)

    def __post_init__(self):
        if (
            self.initial_capital <= 0
            or self.brokerage_per_order < 0
            or self.slippage_bps < 0
        ):
            raise ValueError("Invalid paper account configuration")

        self.cash = float(self.initial_capital)

    def _slipped_price(self, price: float, side: Side) -> float:
        if price <= 0:
            raise ValueError("Price must be positive")

        slip = price * self.slippage_bps / 10000.0

        if side == Side.BUY:
            return price + slip

        return price - slip

    @property
    def used_capital(self) -> float:
        return sum(
            position.entry_price * position.quantity
            for position in self.positions.values()
            if position.status == "OPEN"
        )

    @property
    def unrealized_pnl(self) -> float:
        total = 0.0

        for position in self.positions.values():
            if position.status != "OPEN":
                continue

            if position.side == Side.BUY:
                total += (
                    position.current_price - position.entry_price
                ) * position.quantity
            else:
                total += (
                    position.entry_price - position.current_price
                ) * position.quantity

        return total

    @property
    def equity(self) -> float:
        return self.cash + self.used_capital + self.unrealized_pnl

    def execute(self, trade: Trade):
        if not isinstance(trade, Trade):
            raise TypeError("Expected a Trade object")

        if trade.quantity <= 0:
            raise ValueError("Quantity must be positive")

        if trade.entry <= 0:
            raise ValueError("Entry price must be positive")

        if trade.side not in (Side.BUY, Side.SELL):
            raise ValueError("Unsupported trade side")

        fill = self._slipped_price(trade.entry, trade.side)
        fee = self.brokerage_per_order
        required = fill * trade.quantity + fee

        if required > self.cash:
            raise ValueError("Insufficient paper cash")

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
        )

        self.cash -= required
        self.positions[position_id] = position

        record = {
            "position_id": position_id,
            "symbol": trade.symbol,
            "side": trade.side.value,
            "qty": trade.quantity,
            "fill": round(fill, 4),
            "fees": fee,
            "status": "OPEN",
        }

        self.trades.append(record)
        return record

    def update_price(self, position_id: str, market_price: float):
        position = self.positions.get(position_id)

        if position is None or position.status != "OPEN":
            raise ValueError("Open paper position not found")

        if market_price <= 0:
            raise ValueError("Market price must be positive")

        position.current_price = float(market_price)

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

        if market_price <= 0:
            raise ValueError("Exit price must be positive")

        exit_side = (
            Side.SELL if position.side == Side.BUY else Side.BUY
        )

        exit_fill = self._slipped_price(market_price, exit_side)
        exit_fee = self.brokerage_per_order

        gross_pnl = self._position_pnl(
            PaperPosition(
                position_id=position.position_id,
                symbol=position.symbol,
                side=position.side,
                quantity=position.quantity,
                entry_price=position.entry_price,
                stop_loss=position.stop_loss,
                target=position.target,
                entry_fees=position.entry_fees,
                current_price=exit_fill,
            )
        )

        net_pnl = gross_pnl - position.entry_fees - exit_fee

        # Release reserved capital and apply the position's net P&L.
        self.cash += (
            position.entry_price * position.quantity + net_pnl
        )

        position.current_price = exit_fill
        position.status = "CLOSED"

        result = {
            "position_id": position_id,
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
        return result
