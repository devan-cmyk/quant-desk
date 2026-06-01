"""Parameter-robustness: is the edge a plateau or an overfit spike?

Walk-forward picks the BEST params per fold and validates only those — so it can't tell a robust
edge (a whole neighborhood of params works out-of-sample) from an overfit one (only the cherry-
picked combo works, its neighbors lose). This evaluates the ENTIRE parameter grid on the recent
out-of-sample holdout and reports the fraction profitable. A high fraction = a plateau (trust it);
a low fraction = a fragile spike (overfit risk). This is the classic curve-fitting detector the
committee was missing.
"""
from __future__ import annotations

import statistics

import pandas as pd

from ..config import RiskLimits
from ..risk.engine import RiskEngine
from ..strategies.base import Strategy
from .engine import run_backtest
from .walkforward import ET, _param_combos, _slice


def parameter_robustness(df: pd.DataFrame, strategy_cls: type[Strategy], param_grid: dict, *,
                         holdout_sessions: int = 60, regime_filter=None,
                         limits: RiskLimits | None = None, broker=None) -> dict:
    """Run every param combo over the most recent `holdout_sessions` (out-of-sample) and report
    how much of the grid is profitable. frac_profitable ≥ 0.5 ⇒ robust plateau; low ⇒ overfit spike."""
    limits = limits or RiskLimits()
    combos = _param_combos(param_grid)
    if len(combos) < 2:
        return {"frac_profitable": None, "n_combos": len(combos), "robust": True,
                "detail": "single combo — sensitivity n/a"}
    df = df.sort_index()
    sessions = sorted(set(df.index.tz_convert(ET).date))
    if len(sessions) < holdout_sessions + 5:
        return {"frac_profitable": None, "n_combos": len(combos), "robust": True,
                "detail": f"need {holdout_sessions + 5} sessions, have {len(sessions)}"}
    hold_df = _slice(df, sessions[-holdout_sessions:])

    rets = []
    for params in combos:
        r = RiskEngine(limits=limits, equity=limits.starting_equity)
        m = run_backtest(hold_df, strategy_cls(**params), r, broker=broker, regime_filter=regime_filter)["metrics"]
        rets.append(float(m.get("total_return", 0.0) or 0.0))
    pos = sum(x > 0 for x in rets)
    frac = round(pos / len(rets), 3)
    return {"frac_profitable": frac, "n_combos": len(rets),
            "median_return": round(statistics.median(rets), 4),
            "best_return": round(max(rets), 4), "worst_return": round(min(rets), 4),
            "robust": frac >= 0.5,
            "detail": f"{pos}/{len(rets)} of the grid profitable OOS "
                      f"({'plateau' if frac >= 0.5 else 'fragile spike — overfit risk'})"}
