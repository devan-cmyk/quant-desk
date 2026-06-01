"""Synthetic crisis scenarios — inject the market breaks that actually blow up accounts and
see if a strategy survives. Each scenario returns (stressed_df, slippage_bps): price-path
shocks transform the bars; liquidity shocks leave the path and widen fills. Capital
preservation > optimism: we want to know the tail, not pretend it away.

Every transform preserves OHLCV validity (high>=max(o,c,l), low<=min(o,c,h))."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _fix(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    return df


def baseline(df: pd.DataFrame):
    return df.copy(), None


def flash_crash(df: pd.DataFrame, at: float = 0.5, pct: float = 0.08, dur: int = 3):
    """A sharp V: a `pct` plunge over `dur` bars that recovers halfway — tests stop slippage
    and whether a single bar wrecks the account."""
    df = df.copy(); n = len(df)
    k = int(n * at)
    factors = np.linspace(1 - pct, 1 - pct / 2, dur)
    for j, f in enumerate(factors):
        i = min(k + j, n - 1)
        for c in ("open", "high", "low", "close"):
            df.iloc[i, df.columns.get_loc(c)] *= f
    return _fix(df), None


def vol_spike(df: pd.DataFrame, at: float = 0.4, mult: float = 3.0, dur: int = 12):
    """Widen intrabar excursions by `mult` over a window — fatter wicks trip more stops."""
    df = df.copy(); n = len(df)
    k = int(n * at)
    for i in range(k, min(k + dur, n)):
        c = df.iloc[i]["close"]
        df.iloc[i, df.columns.get_loc("high")] = c + (df.iloc[i]["high"] - c) * mult
        df.iloc[i, df.columns.get_loc("low")] = c - (c - df.iloc[i]["low"]) * mult
    return _fix(df), None


def gap_down(df: pd.DataFrame, pct: float = 0.05):
    """Shift the latest session down by `pct` (overnight gap) — tests overnight/gap risk that
    blows through stops."""
    df = df.copy()
    et = df.index.tz_convert("America/New_York")
    last_day = et.date.max()
    mask = et.date == last_day
    for c in ("open", "high", "low", "close"):
        df.loc[mask, c] *= (1 - pct)
    return _fix(df), None


def liquidity_drought(df: pd.DataFrame, slippage_bps: float = 40.0):
    """Path unchanged; fills get brutal (20x normal slippage) — tests execution under a
    spread explosion / liquidity vacuum."""
    return df.copy(), slippage_bps


SCENARIOS = {
    "baseline": baseline,
    "flash_crash": flash_crash,
    "vol_spike": vol_spike,
    "gap_down": gap_down,
    "liquidity_drought": liquidity_drought,
}
