
"""Long-only paper broker with mandatory per-bot risk enforcement."""

from dataclasses import dataclass, field
from typing import Dict
from uuid import uuid4
import math

from .models import Trade, Side
from .risk import BotRiskAccount, BotRiskPolicy


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

        try:
            valid_values = all(
                math.isfinite(float(value))
                for value in values
            )
        except (TypeError, ValueError):
            valid_values = False

        if not valid_values:
            raise ValueError("Paper account values must be finite")

        self.initial_capital = float(self.initial_capital)
        self.brokerage_per_order = float(self.brokerage_per_order)
        self.slippage_bps = float(self.slippage_bps)

        if (
            self.initial_capital <= 0
            or self.brokerage_per_order < 0
            or self.slippage_bps < 0
            or self.slippage_bps >= 10000
        ):
            raise ValueError("Invalid paper account configuration")

        if not isinstance(self.bot_id, str) or not self.bot_id.strip():
            raise ValueError("Bot ID is required")

        # Never allow a paper broker to operate without risk controls.
        if self.risk_account is None:
            self.risk_account = BotRiskAccount(
                bot_id=self.bot_id,
                allocated_capital=self.initial_capital,
                policy=BotRiskPolicy(),
            )

        if not isinstance(self.risk_account, BotRiskAccount):
            raise TypeError("A valid BotRiskAccount is required")

        if self.risk_account.bot_id != self.bot_id:
            raise ValueError("Risk account belongs to another bot")

        if (
            self.risk_account.allocated_capital
            != self.initial_capital
        ):
            raise ValueError("Paper capital must match bot allocation")

        if self.risk_account.status.value != "ACTIVE":
            raise ValueError("Paper bot is not active")

        self.cash = self.initial_capital

    def _slipped_price(self, price: float, side: Side) -> float:
        try:
            price = float(price)
        except (TypeError, ValueError):
            raise ValueError("Price must be numeric") from None

        if not math.isfinite(price) or price <= 0:
            raise ValueError("Price must be finite and positive")

        slip = price * self.slippage_bps / 10000.0

        return price + slip if side == Side.BUY else price - slip

    @property
    def used_capital(self) -> float:
        return sum(
            position.entry_price * position.quantity
            for position in self.positions.values()
            if position.status == "OPEN"
        )

    @property
    def unrealized_pnl(self) -> float:
        return sum(
            self._position_pnl(position)
            for position in self.positions.values()
            if position.status == "OPEN"
        )

    @property
    def risk_unrealized_pnl(self) -> float:
        return sum(
            self._position_pnl(position)
            - position.entry_fees
            - self.brokerage_per_order
            for position in self.positions.values()
            if position.status == "OPEN"
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

        if not isinstance(trade.symbol, str) or not trade.symbol.strip():
            raise ValueError("Trade symbol is required")

        try:
            prices = tuple(
                float(price)
                for price in (
                    trade.entry,
                    trade.stop_loss,
                    trade.target,
                )
            )
        except (TypeError, ValueError):
            raise ValueError("Trade prices must be numeric") from None

        if not all(
            math.isfinite(price) and price > 0
            for price in prices
        ):
            raise ValueError("Trade prices must be finite and positive")

        entry, stop_loss, target = prices

        if not stop_loss < entry < target:
            raise ValueError("BUY requires stop < entry < target")

        risk_per_unit = entry - stop_loss
        reward_per_unit = target - entry
        risk_reward = reward_per_unit / risk_per_unit

        if risk_reward < self.risk_account.policy.min_risk_reward:
            raise ValueError("Minimum risk/reward is 2:1")

        fill = self._slipped_price(entry, Side.BUY)
        fee = self.brokerage_per_order
        required = fill * trade.quantity + fee

        if required > self.cash:
            raise ValueError("Insufficient paper cash")

        estimated_exit = self._slipped_price(
            stop_loss,
            Side.SELL,
        )

        planned_risk = (
            (fill - estimated_exit) * trade.quantity
            + fee
            + self.brokerage_per_order
        )

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
            stop_loss=stop_loss,
            target=target,
            entry_fees=fee,
            current_price=fill,
            bot_id=self.bot_id,
        )

        # Register risk before changing cash or creating the position.
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

        try:
            market_price = float(market_price)
        except (TypeError, ValueError):
            raise ValueError("Market price must be numeric") from None

        if not math.isfinite(market_price) or market_price <= 0:
            raise ValueError("Market price must be finite and positive")

        position.current_price = market_price

        self.risk_account.update_unrealized_pnl(
            self.risk_unrealized_pnl
        )

        return {
            "position_id": position_id,
            "unrealized_pnl": self._position_pnl(position),
            "status": position.status,
            "daily_loss_limit_reached": (
                self.risk_account.daily_limit_reached
            ),
        }

    def monitor_positions(self, market_prices: dict):
        """Mark positions and close paper stops/targets at observed prices.

        The caller must supply validated, fresh market prices.
        This method does not itself establish quote freshness.
        """

        if not isinstance(market_prices, dict):
            raise TypeError(
                "Market prices must be a symbol-to-price dictionary"
            )

        validated_prices = {}

        for symbol, price in market_prices.items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("Invalid market price symbol")

            try:
                price = float(price)
            except (TypeError, ValueError):
                raise ValueError("Market prices must be numeric") from None

            if not math.isfinite(price) or price <= 0:
                raise ValueError(
                    "Market prices must be finite and positive"
                )

            validated_prices[symbol] = price

        updated_count = 0

        for position in self.positions.values():
            if (
                position.status == "OPEN"
                and position.symbol in validated_prices
            ):
                position.current_price = validated_prices[position.symbol]
                updated_count += 1

        self.risk_account.update_unrealized_pnl(
            self.risk_unrealized_pnl
        )

        closed = []

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
            "updated_positions": updated_count,
            "closed_positions": closed,
            "remaining_open_positions": sum(
                1
                for position in self.positions.values()
                if position.status == "OPEN"
            ),
            "daily_loss_limit_reached": (
                self.risk_account.daily_limit_reached
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

        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Close reason is required")

        exit_fill = self._slipped_price(market_price, Side.SELL)
        exit_fee = self.brokerage_per_order

        gross_pnl = (
            exit_fill - position.entry_price
        ) * position.quantity

        net_pnl = gross_pnl - position.entry_fees - exit_fee

        new_cash = (
            self.cash
            + position.entry_price * position.quantity
            + gross_pnl
            - exit_fee
        )

        if not math.isfinite(new_cash):
            raise ValueError("Invalid paper cash calculation")

        remaining_unrealized = (
            self.risk_unrealized_pnl
            - self._position_pnl(position)
            + position.entry_fees
            + self.brokerage_per_order
        )

        # Validate and update risk accounting before finalizing the close.
        self.risk_account.record_close(
            net_pnl,
            remaining_unrealized_pnl=remaining_unrealized,
        )

        self.cash = new_cash
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

        for record in self.trades:
            if record["position_id"] == position_id:
                record["status"] = "CLOSED"
                record["exit_price"] = exit_fill
                record["net_pnl"] = net_pnl
                record["reason"] = reason
                break

        return result
