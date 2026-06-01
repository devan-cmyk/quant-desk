"""Opening Range Breakout (ORB) — a canonical intraday strategy.

The first `or_minutes` of each session define the opening range [OR_low, OR_high]. After
that window, the first bar that closes beyond the range triggers a trade in that direction
(stop at the opposite range edge, target = entry ± target_R × range). One trade per session;
the engine flattens at the close.
"""
from __future__ import annotations

import pandas as pd

from .base import Signal, Strategy

ET = "America/New_York"


class OpeningRangeBreakout(Strategy):
    name = "orb"

    def __init__(self, or_minutes: int = 30, target_r: float = 2.0):
        self.or_minutes = or_minutes
        self.target_r = target_r
        self._session = None
        self._signaled = False

    def initialize(self, ctx=None) -> None:
        self._session, self._signaled = None, False

    def generate_signal(self, window: pd.DataFrame) -> Signal:
        if len(window) < 2:
            return Signal()
        idx_et = window.index.tz_convert(ET)
        session = idx_et[-1].date()
        if session != self._session:                 # new session → reset
            self._session, self._signaled = session, False
        if self._signaled:
            return Signal()

        today = window[idx_et.date == session]
        if today.empty:
            return Signal()
        open_ts = today.index[0]
        or_end = open_ts + pd.Timedelta(minutes=self.or_minutes)
        or_bars = today[today.index <= or_end]
        now_ts = today.index[-1]
        if now_ts <= or_end or len(or_bars) < 1:      # still inside the opening range
            return Signal()

        or_high, or_low = float(or_bars["high"].max()), float(or_bars["low"].min())
        rng = max(or_high - or_low, 1e-9)
        close = float(today["close"].iloc[-1])

        if close > or_high:
            self._signaled = True
            return Signal("long", stop=or_low, target=close + self.target_r * rng,
                          strength=min((close - or_high) / rng, 1.0), reason="break above OR")
        if close < or_low:
            self._signaled = True
            return Signal("short", stop=or_high, target=close - self.target_r * rng,
                          strength=min((or_low - close) / rng, 1.0), reason="break below OR")
        return Signal()
