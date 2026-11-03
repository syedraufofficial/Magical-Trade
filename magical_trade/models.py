from dataclasses import dataclass
from enum import Enum

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class Mode(str, Enum):
    PAPER = "PAPER"
    REAL = "REAL"

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
