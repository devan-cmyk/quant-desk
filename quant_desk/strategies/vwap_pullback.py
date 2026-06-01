"""VWAP Pullback — trade with the intraday trend on a pullback to VWAP.

Session VWAP = cum(typical·volume)/cum(volume). When price is trending above VWAP and a bar
dips back to (or through) VWAP but closes back above it with upward momentum, go long (stop
just below the pullback low/VWAP, target = entry + R·risk). Symmetric for shorts below VWAP.
Unlike ORB this can trade multiple times per session.
"""
from __future__ import annotations

import pandas as pd

from .base import Signal, Strategy

ET = "America/New_York"


class VWAPPullback(Strategy):
    name = "vwap"

    def __init__(self, target_r: float = 1.5, touch: float = 0.0007,
                 stop_buf: float = 0.0005, min_bars: int = 6):
        self.target_r = target_r
        self.touch = touch          # how near VWAP the bar's low/high must come
        self.stop_buf = stop_buf
        self.min_bars = min_bars

    def generate_signal(self, window: pd.DataFrame) -> Signal:
        idx_et = window.index.tz_convert(ET)
        session = idx_et[-1].date()
        today = window[idx_et.date == session]
        if len(today) < self.min_bars:
            return Signal()

        tp = (today["high"] + today["low"] + today["close"]) / 3.0
        vwap = (tp * today["volume"]).cumsum() / today["volume"].cumsum()
        vwap_now = float(vwap.iloc[-1])
        close = float(today["close"].iloc[-1]); prev = float(today["close"].iloc[-2])
        low = float(today["low"].iloc[-1]); high = float(today["high"].iloc[-1])

        # long: uptrend (close>VWAP), pulled back to VWAP (low near/through it), closing up
        if close > vwap_now and low <= vwap_now * (1 + self.touch) and close > prev:
            stop = min(low, vwap_now) * (1 - self.stop_buf)
            if stop < close:
                return Signal("long", stop=stop, target=close + self.target_r * (close - stop),
                              strength=min((close - vwap_now) / vwap_now / self.touch, 1.0),
                              reason="vwap pullback long")
        # short: downtrend (close<VWAP), pulled up to VWAP, closing down
        if close < vwap_now and high >= vwap_now * (1 - self.touch) and close < prev:
            stop = max(high, vwap_now) * (1 + self.stop_buf)
            if stop > close:
                return Signal("short", stop=stop, target=close - self.target_r * (stop - close),
                              strength=min((vwap_now - close) / vwap_now / self.touch, 1.0),
                              reason="vwap pullback short")
        return Signal()
