"""Re-fit a promoted pair's params on the most recent window, guarded by a holdout.

Procedure (a single most-recent-window fold):
  1. take the last (fit_sessions + holdout_sessions) sessions
  2. grid-search params on the fit window (in-sample), pick the best on `metric`
  3. evaluate the new params AND the params currently in use on the holdout
  4. adopt the new params only if, on the holdout, they (a) trade enough, (b) are non-negative,
     and (c) are no worse than what's deployed.
Otherwise keep the current params. The refresh can only improve the holdout outcome or hold —
it can never adopt a param set that fails out-of-sample.
"""
from __future__ import annotations

import pandas as pd

from ..backtest.engine import run_backtest
from ..backtest.walkforward import _param_combos, _slice, ET
from ..config import RiskLimits
from ..risk.engine import RiskEngine
from ..strategies.base import Strategy

MIN_HOLDOUT_TRADES = 3          # don't deploy params that barely trade on recent data


def _holdout_metrics(df, strategy_cls, params, regime_filter, limits, metric):
    r = RiskEngine(limits=limits, equity=limits.starting_equity)
    m = run_backtest(df, strategy_cls(**(params or {})), r, regime_filter=regime_filter)["metrics"]
    return m.get(metric, 0.0) or 0.0, m.get("num_trades", 0) or 0


def refresh_params(df: pd.DataFrame, strategy_cls: type[Strategy], param_grid: dict,
                   current_params: dict, *, fit_sessions: int = 20, holdout_sessions: int = 5,
                   metric: str = "total_return", regime_filter=None,
                   limits: RiskLimits | None = None) -> dict:
    limits = limits or RiskLimits()
    df = df.sort_index()
    sessions = sorted(set(df.index.tz_convert(ET).date))
    need = fit_sessions + holdout_sessions
    if len(sessions) < need:
        return {"adopt": False, "reason": f"need {need} sessions, have {len(sessions)}",
                "old": current_params, "new": current_params}

    recent = sessions[-need:]
    fit_df = _slice(df, recent[:fit_sessions])
    hold_df = _slice(df, recent[fit_sessions:])

    # 1+2. optimize on the fit window (fresh equity per combo for a fair comparison)
    best, best_score = (current_params or {}), float("-inf")
    for params in _param_combos(param_grid):
        r = RiskEngine(limits=limits, equity=limits.starting_equity)
        m = run_backtest(fit_df, strategy_cls(**params), r, regime_filter=regime_filter)["metrics"]
        s = m.get(metric)
        if s is not None and s > best_score:
            best_score, best = s, params

    # 3. score new vs currently-deployed params on the untouched holdout
    new_oos, new_trades = _holdout_metrics(hold_df, strategy_cls, best, regime_filter, limits, metric)
    cur_oos, _ = _holdout_metrics(hold_df, strategy_cls, current_params, regime_filter, limits, metric)

    # 4. adopt only if it trades enough, holds OOS, and is no worse than what's deployed
    adopt = (best != (current_params or {}) and new_trades >= MIN_HOLDOUT_TRADES
             and new_oos >= 0 and new_oos >= cur_oos)
    reason = ("refreshed — holdout improved/held" if adopt
              else "kept — refit failed holdout guard" if best != (current_params or {})
              else "kept — already optimal")
    return {"adopt": adopt, "old": current_params or {}, "new": best,
            "new_oos": round(float(new_oos), 4), "cur_oos": round(float(cur_oos), 4),
            "new_trades": int(new_trades), "reason": reason}
