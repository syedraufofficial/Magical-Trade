
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    app_name: str = "Magical Trade"
    paper_initial_capital: float = 5000.0

    # Per-bot risk policy
    risk_per_trade_pct: float = 1.0
    daily_loss_limit_pct: float = 15.0
    max_positions_per_bot: int = 1

    # Temporary compatibility settings for existing modules
    max_daily_loss: float = 750.0
    max_risk_per_trade: float = 50.0
    max_positions: int = 1

    min_confidence: float = 55.0
    min_risk_reward: float = 2.0
    max_spread_pct: float = 1.5

    # Real trading remains disabled
    real_execution_enabled: bool = False

    def __post_init__(self):
        if self.paper_initial_capital <= 0:
            raise ValueError("Paper capital must be positive")
        if not 0 < self.risk_per_trade_pct <= 100:
            raise ValueError("Invalid per-trade risk percentage")
        if not 0 < self.daily_loss_limit_pct <= 15:
            raise ValueError("Daily loss limit cannot exceed 15%")
        if self.max_positions_per_bot < 1:
            raise ValueError("Invalid maximum positions")
        if self.min_risk_reward < 2.0:
            raise ValueError("Minimum risk/reward must be 2:1")
        if self.real_execution_enabled:
            raise ValueError("Real trading is disabled")

    @classmethod
    def from_env(cls):
        return cls(
            paper_initial_capital=float(
                os.getenv("PAPER_INITIAL_CAPITAL", "5000")
            ),
            risk_per_trade_pct=float(
                os.getenv("RISK_PER_TRADE_PCT", "1")
            ),
            daily_loss_limit_pct=float(
                os.getenv("DAILY_LOSS_LIMIT_PCT", "15")
            ),
            max_positions_per_bot=int(
                os.getenv("MAX_POSITIONS_PER_BOT", "1")
            ),
            max_daily_loss=float(
                os.getenv("MAX_DAILY_LOSS", "750")
            ),
            max_risk_per_trade=float(
                os.getenv("MAX_RISK_PER_TRADE", "50")
            ),
            max_positions=int(
                os.getenv("MAX_POSITIONS", "1")
            ),
        )
