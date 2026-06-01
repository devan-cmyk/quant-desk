"""Opening Gap Fade — a contrarian open-auction strategy keyed off the OVERNIGHT gap.

When a session opens far from the prior session's close, that gap tends to partially fill:
fade it. A gap UP (open ≥ min_gap above prior close) is shorted toward the prior close; a gap
DOWN is bought. Entry is only in the first `entry_minutes` of the session and only while the
gap is still open (skip if price has already filled it). Stop is one `stop_k` gap-width beyond
the open (the gap extends), target is the prior close. One trade per session; the engine
flattens at the close.

Its signal source — the close→open gap — is orthogonal to the intraday breakout (ORB),
trend-pullback (VWAP) and z-score (mean-reversion) strategies, so it diversifies the basket.
"""
from __future__ import annotations

import pandas as pd

from .base import Signal, Strategy

ET = "America/New_York"


class GapFade(Strategy):
    name = "gapfade"

    def __init__(self, min_gap: float = 0.003, entry_minutes: int = 15, stop_k: float = 1.0,
                 min_strength: float = 0.0):
        self.min_gap = min_gap
        self.entry_minutes = entry_minutes
        self.stop_k = stop_k
        self.min_strength = min_strength
        self._session = None
        self._signaled = False

    def initialize(self, ctx=None) -> None:
        self._session, self._signaled = None, False

    def compute_signal(self, window: pd.DataFrame) -> Signal:
        if len(window) < 2:
            return Signal()
        idx_et = window.index.tz_convert(ET)
        dates = idx_et.date
        session = dates[-1]
        if session != self._session:                  # new session → reset
            self._session, self._signaled = session, False
        if self._signaled:
            return Signal()

        prior = [d for d in set(dates) if d < session]
        if not prior:                                  # need a prior session to measure the gap
            return Signal()
        prev_session = max(prior)
        prev_close = float(window["close"][dates == prev_session].iloc[-1])

        today = window[dates == session]
        open_ts, now_ts = today.index[0], today.index[-1]
        if now_ts > open_ts + pd.Timedelta(minutes=self.entry_minutes):   # past the entry window
            return Signal()

        today_open = float(today["open"].iloc[0])
        gap = today_open - prev_close
        gap_pct = gap / prev_close if prev_close else 0.0
        if abs(gap_pct) < self.min_gap:                # gap too small to fade
            return Signal()

        close = float(today["close"].iloc[-1])
        strength = min(abs(gap_pct) / self.min_gap, 1.0)

        if gap > 0:                                    # gap up → fade short toward prior close
            if close <= prev_close:                    # already filled → no edge left
                return Signal()
            self._signaled = True
            return Signal("short", stop=today_open + self.stop_k * gap, target=prev_close,
                          strength=strength, reason="fade gap up")
        else:                                          # gap down → fade long toward prior close
            if close >= prev_close:
                return Signal()
            self._signaled = True
            return Signal("long", stop=today_open + self.stop_k * gap, target=prev_close,
                          strength=strength, reason="fade gap down")
