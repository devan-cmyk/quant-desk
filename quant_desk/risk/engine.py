"""Risk engine — survivability first. Sizes positions off per-trade risk, halts the
session on the daily-loss cap, enforces an exposure cap and a consecutive-loss cooldown,
and exposes a hard kill switch. Strategies cannot bypass this; the engine vetoes entries."""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import RiskLimits, settings
from ..logging import get

log = get("risk")


@dataclass
class RiskDecision:
    allowed: bool
    qty: int = 0
    reason: str = ""


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None, equity: float | None = None):
        self.limits = limits or settings.risk
        self.start_equity = equity if equity is not None else self.limits.starting_equity
        self.equity = self.start_equity
        self.reset_session()
        self.kill_switch = False
        self.kill_reason = ""

    # ── session lifecycle ────────────────────────────────────────────────────
    def reset_session(self) -> None:
        self.day_pnl = 0.0
        self.consecutive_losses = 0
        self.halted_today = False

    def trip_kill_switch(self, reason: str) -> None:
        self.kill_switch = True
        self.kill_reason = reason
        log.error("kill_switch_tripped", reason=reason)

    # ── entry gate + sizing ──────────────────────────────────────────────────
    def evaluate(self, *, entry: float, stop: float) -> RiskDecision:
        if self.kill_switch:
            return RiskDecision(False, 0, f"kill_switch: {self.kill_reason}")
        if self.halted_today:
            return RiskDecision(False, 0, "daily_loss_halt")
        if self.consecutive_losses >= self.limits.max_consecutive_losses:
            return RiskDecision(False, 0, "consecutive_loss_cooldown")

        per_share_risk = abs(entry - stop)
        if per_share_risk <= 0:
            return RiskDecision(False, 0, "invalid_stop")
        risk_budget = self.equity * self.limits.risk_per_trade_pct
        qty = math.floor(risk_budget / per_share_risk)
        # exposure cap: notional <= max_position_pct of equity
        max_qty = math.floor((self.equity * self.limits.max_position_pct) / max(entry, 1e-9))
        qty = min(qty, max_qty)
        if qty <= 0:
            return RiskDecision(False, 0, "size_zero")
        return RiskDecision(True, qty, "ok")

    # ── outcome accounting ───────────────────────────────────────────────────
    def on_trade_closed(self, pnl: float) -> None:
        self.equity += pnl
        self.day_pnl += pnl
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
        if self.day_pnl <= -self.limits.max_daily_loss_pct * self.start_equity:
            self.halted_today = True
            log.warning("daily_loss_halt", day_pnl=round(self.day_pnl, 2))
