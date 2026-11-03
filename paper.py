from dataclasses import dataclass, field
from .models import Trade

@dataclass
class PaperBroker:
    initial_capital: float = 5000.0
    brokerage_per_order: float = 0.0
    slippage_bps: float = 5.0
    cash: float = field(init=False)
    trades: list = field(default_factory=list)

    def __post_init__(self):
        if self.initial_capital <= 0 or self.brokerage_per_order < 0 or self.slippage_bps < 0:
            raise ValueError("Invalid paper account configuration")
        self.cash = float(self.initial_capital)

    def execute(self, trade: Trade):
        slip = trade.entry * self.slippage_bps / 10000
        fill = trade.entry + slip if trade.side.value == "BUY" else trade.entry - slip
        cost = fill * trade.quantity + self.brokerage_per_order
        if trade.side.value == "BUY" and cost > self.cash:
            raise ValueError("Insufficient paper cash")
        if trade.side.value == "BUY":
            self.cash -= cost
        self.trades.append({"symbol": trade.symbol, "side": trade.side.value, "qty": trade.quantity,
                            "fill": round(fill, 4), "fees": self.brokerage_per_order})
        return self.trades[-1]
