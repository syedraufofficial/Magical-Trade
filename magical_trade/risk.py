from dataclasses import dataclass
from .models import Signal, Trade

@dataclass
class RiskManager:
    max_daily_loss: float = 100.0
    max_risk_per_trade: float = 50.0
    max_positions: int = 1
    daily_realized_pnl: float = 0.0
    open_positions: int = 0

    def size_trade(self, signal: Signal, quantity: int, lot_size: int = 1):
        if quantity <= 0 or lot_size <= 0 or quantity % lot_size:
            raise ValueError("Quantity must be a positive multiple of lot size")
        if self.daily_realized_pnl <= -self.max_daily_loss:
            raise ValueError("Daily loss limit reached")
        if self.open_positions >= self.max_positions:
            raise ValueError("Maximum open positions reached")
        risk_per_unit = abs(signal.entry - signal.stop_loss)
        risk = risk_per_unit * quantity
        if risk <= 0 or risk > self.max_risk_per_trade:
            raise ValueError("Trade risk exceeds configured per-trade limit")
        return Trade(signal.symbol, signal.side, quantity, signal.entry, signal.stop_loss, signal.target, risk)
