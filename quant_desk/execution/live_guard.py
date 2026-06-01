"""LIVE TRADING TRIPLE-LOCK. Live execution is impossible unless ALL THREE hold:
  1. env:    QD_ALLOW_LIVE_ENV=1                 (deliberate shell action)
  2. config: settings.allow_live = True          (deliberate config action)
  3. runtime: unlock_token == settings.live_unlock_token (non-empty, passed at call time)
Any live broker MUST call assert_live_allowed() before sending an order. The paper broker
never trades live, so it never needs this. Default posture: paper-only, fail-secure."""
from __future__ import annotations

import os

from ..config import settings
from ..logging import get

log = get("live_guard")


class LiveTradingLocked(RuntimeError):
    pass


def assert_live_allowed(unlock_token: str | None = None) -> None:
    if settings.trading_mode != "live":
        raise LiveTradingLocked("trading_mode is not 'live' (paper-only)")
    if os.environ.get("QD_ALLOW_LIVE_ENV") != "1":
        raise LiveTradingLocked("env lock not set (QD_ALLOW_LIVE_ENV != 1)")
    if not settings.allow_live:
        raise LiveTradingLocked("config lock not set (allow_live is False)")
    if not settings.live_unlock_token or unlock_token != settings.live_unlock_token:
        raise LiveTradingLocked("runtime risk-unlock token missing or mismatched")
    log.warning("live_trading_unlocked")  # audited — should be rare and deliberate
