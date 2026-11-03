from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
    app_name: str = "Magical Trade"
    paper_initial_capital: float = 5000.0
    max_daily_loss: float = 100.0
    max_risk_per_trade: float = 50.0
    max_positions: int = 1
    min_confidence: float = 55.0
    min_risk_reward: float = 2.0
    max_spread_pct: float = 1.5
    real_execution_enabled: bool = False

    @classmethod
    def from_env(cls):
        # Live execution intentionally cannot be enabled by an environment flag.
        return cls(
            paper_initial_capital=float(os.getenv("PAPER_INITIAL_CAPITAL", "5000")),
            max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "100")),
            max_risk_per_trade=float(os.getenv("MAX_RISK_PER_TRADE", "50")),
            max_positions=int(os.getenv("MAX_POSITIONS", "1")),
        )
