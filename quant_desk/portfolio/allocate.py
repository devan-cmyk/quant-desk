"""Diversification-aware risk allocation across promoted pairs.

Method (transparent, robust on short samples — deliberately NOT a covariance optimizer):
  base weight  ∝ 1 / volatility            (risk parity — equalize each edge's risk)
  × penalty    ∝ 1 / (1 + avg |corr| to others)   (down-weight redundant edges)
then floor/cap and renormalize. With one pair, or too little shared history, it falls back
to equal weight. The output feeds the runner as a per-pair risk SCALE (weight ÷ equal-weight,
clamped) — so equal weights leave sizing exactly as before.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ET = "America/New_York"
MIN_OBS = 8                     # need at least this many shared sessions to trust correlation
MIN_WEIGHT, MAX_WEIGHT = 0.05, 0.40
SCALE_LO, SCALE_HI = 0.25, 2.0  # clamp the per-trade risk multiplier — never blow up sizing


def session_returns(trades: list[dict], starting_equity: float = 100_000.0) -> pd.Series:
    """Per-session return stream from a trade list: each day's summed PnL / starting equity."""
    by_day: dict = {}
    for t in trades:
        ts = pd.Timestamp(t["exit_ts"])
        d = (ts.tz_convert(ET) if ts.tzinfo else ts).date()
        by_day[d] = by_day.get(d, 0.0) + t["pnl"]
    if not by_day:
        return pd.Series(dtype=float)
    return (pd.Series(by_day) / starting_equity).sort_index()


def correlation_matrix(returns_by_pair: dict[str, pd.Series]) -> pd.DataFrame:
    """Align the pairs' return streams on the session calendar (non-trade day = 0 return)
    and return the Pearson correlation matrix."""
    if not returns_by_pair:
        return pd.DataFrame()
    frame = pd.DataFrame(returns_by_pair).fillna(0.0)
    return frame.corr()


def allocate(returns_by_pair: dict[str, pd.Series], *, min_obs: int = MIN_OBS) -> dict:
    """Return {weights, scales, corr, method, n_obs}. weights sum to 1; scales are the
    per-pair risk multipliers the runner applies (1.0 == unchanged sizing)."""
    pairs = list(returns_by_pair)
    n = len(pairs)
    if n == 0:
        return {"weights": {}, "scales": {}, "corr": {}, "method": "none", "n_obs": 0}
    if n == 1:
        return {"weights": {pairs[0]: 1.0}, "scales": {pairs[0]: 1.0},
                "corr": {pairs[0]: {pairs[0]: 1.0}}, "method": "single pair", "n_obs": 0}

    frame = pd.DataFrame(returns_by_pair).fillna(0.0)
    corr = frame.corr()
    if len(frame) < min_obs:
        weights = {p: 1.0 / n for p in pairs}
        method = f"equal (only {len(frame)} shared sessions < {min_obs})"
    else:
        vol = frame.std().replace(0.0, np.nan)
        inv_vol = (1.0 / vol).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        avg_abs_corr = (corr.abs().sum(axis=1) - 1.0) / (n - 1)     # mean |corr| to the others
        penalty = 1.0 / (1.0 + avg_abs_corr)
        raw = inv_vol * penalty
        if raw.sum() <= 0:
            raw = pd.Series(1.0, index=pairs)
        w = raw / raw.sum()
        w = w.clip(lower=MIN_WEIGHT, upper=MAX_WEIGHT)
        weights = (w / w.sum()).to_dict()
        method = "inverse-vol × diversification penalty"

    equal = 1.0 / n
    scales = {p: round(float(np.clip(weights[p] / equal, SCALE_LO, SCALE_HI)), 3) for p in pairs}
    return {"weights": {p: round(float(weights[p]), 4) for p in pairs}, "scales": scales,
            "corr": corr.round(3).to_dict(), "method": method, "n_obs": int(len(frame))}
