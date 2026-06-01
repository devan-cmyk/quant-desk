"""Bollinger Mean Reversion — fade intraday extremes back to the session mean. When price
stretches `entry_z` standard deviations from its rolling mean, trade the reversion (long
when oversold, short when overbought), target the mean, stop a further `stop_k` σ out.
Pairs naturally with the regime filter inverted — but kept pure here; the engine/regime
layer decides when to enable it."""
from __future__ import annotations

import pandas as pd

from .base import Signal, Strategy


class MeanReversion(Strategy):
    name = "meanrev"

    def __init__(self, lookback: int = 20, entry_z: float = 2.0, stop_k: float = 1.0):
        self.lookback = lookback
        self.entry_z = entry_z
        self.stop_k = stop_k

    def generate_signal(self, window: pd.DataFrame) -> Signal:
        if len(window) < self.lookback + 1:
            return Signal()
        c = window["close"]
        ma = float(c.iloc[-self.lookback:].mean())
        sd = float(c.iloc[-self.lookback:].std())
        if sd <= 0:
            return Signal()
        close = float(c.iloc[-1])
        z = (close - ma) / sd
        if z <= -self.entry_z:                         # oversold → revert up
            stop = close - self.stop_k * sd
            return Signal("long", stop=stop, target=ma, strength=min(abs(z) / self.entry_z, 1.0),
                          reason="mean reversion (oversold)")
        if z >= self.entry_z:                          # overbought → revert down
            stop = close + self.stop_k * sd
            return Signal("short", stop=stop, target=ma, strength=min(abs(z) / self.entry_z, 1.0),
                          reason="mean reversion (overbought)")
        return Signal()
