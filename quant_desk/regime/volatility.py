"""Volatility circuit-breaker — "don't catch a falling knife."

Mean-reversion's one failure mode (empirically: 2020 COVID crash, where it lost while surviving
the 2008 grind) is the VELOCITY of a vol blow-up, not the depth of a drawdown. This measures
short-window realized vol against a longer baseline; when the ratio spikes past `max_ratio`, the
regime is unstable and reversion entries are suppressed. It says nothing about trend direction
(that's RegimeFilter) — it's a pure "is volatility abnormally exploding right now?" gate.
"""
from __future__ import annotations

import pandas as pd


def vol_ratio(window: pd.DataFrame, short: int = 10, long: int = 100) -> float | None:
    """short-window realized vol ÷ long-window baseline vol (of close-to-close returns).
    None when there isn't enough history to judge."""
    c = window["close"]
    if len(c) < long + 1:
        return None
    r = c.pct_change().dropna()
    lv = float(r.iloc[-long:].std())
    if lv <= 0:
        return None
    return float(r.iloc[-short:].std()) / lv


def vol_spike(window: pd.DataFrame, *, short: int = 10, long: int = 100,
              max_ratio: float = 2.0) -> bool:
    """True when realized volatility is abnormally elevated (a crash/blow-up regime) — the
    signal to suppress new mean-reversion entries. Fail-open: not enough history → not a spike."""
    vr = vol_ratio(window, short, long)
    return vr is not None and vr > max_ratio
