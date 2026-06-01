"""Regime filter — a composable trend/chop gate, independent of any strategy. It classifies
the current state from EMA structure + slope and vetoes signals that fight the prevailing
trend (and blocks everything in chop). Strategies stay pure; the backtest/live engine applies
the filter before accepting a signal, so it works for every strategy uniformly.

regime():  'up' | 'down' | 'chop'
allows():  long only in 'up', short only in 'down', nothing in 'chop'
"""
from __future__ import annotations

import pandas as pd


class RegimeFilter:
    def __init__(self, fast: int = 20, slow: int = 50, slope_lookback: int = 10,
                 min_slope_bps: float = 1.0):
        self.fast = fast
        self.slow = slow
        self.slope_lookback = slope_lookback
        self.min_slope = min_slope_bps / 1e4   # bps → fraction

    def regime(self, window: pd.DataFrame) -> str:
        close = window["close"]
        if len(close) < max(self.slow, self.slope_lookback + 1):
            return "chop"
        ef = close.ewm(span=self.fast, adjust=False).mean()
        es = close.ewm(span=self.slow, adjust=False).mean()
        slope = es.iloc[-1] / es.iloc[-1 - self.slope_lookback] - 1.0
        if ef.iloc[-1] > es.iloc[-1] and slope > self.min_slope:
            return "up"
        if ef.iloc[-1] < es.iloc[-1] and slope < -self.min_slope:
            return "down"
        return "chop"

    def allows(self, window: pd.DataFrame, side: str) -> bool:
        r = self.regime(window)
        return (side == "long" and r == "up") or (side == "short" and r == "down")
