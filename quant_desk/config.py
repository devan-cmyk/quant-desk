"""Configuration — paper-only by default. Live trading requires the triple-lock
(see execution.live_guard): env flag + config flag + a runtime risk-unlock token."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RiskLimits(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QD_RISK_")
    starting_equity: float = 100_000.0
    risk_per_trade_pct: float = 0.005      # 0.5% of equity risked per trade
    max_daily_loss_pct: float = 0.02       # halt the day at -2%
    max_position_pct: float = 0.20         # single position <= 20% of equity (notional)
    max_consecutive_losses: int = 3        # then cooldown for the session
    commission_per_share: float = 0.005
    slippage_bps: float = 2.0              # 2 bps per side


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QD_", env_file=".env", extra="ignore")
    # ── trading mode (SAFE DEFAULT) ──────────────────────────────────────────
    trading_mode: str = Field(default="paper", pattern="^(paper|live)$")
    allow_live: bool = False               # config-level live consent (lock #2)
    live_unlock_token: str = ""            # must match runtime token (lock #3)
    data_dir: str = "data/cache"
    log_level: str = "INFO"
    risk: RiskLimits = Field(default_factory=RiskLimits)


settings = Settings()
