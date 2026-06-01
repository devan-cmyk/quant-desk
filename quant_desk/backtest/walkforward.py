"""Walk-forward analysis — the honest test of an edge. Roll a window forward: optimize
params on an in-sample (IS) block, then evaluate the chosen params on the next, unseen
out-of-sample (OOS) block. Chain the OOS blocks into one continuous equity curve — that
OOS curve is the closest thing to 'what would have actually happened', free of the
in-sample overfit that makes any strategy look good on its own training data."""
from __future__ import annotations

import itertools

import pandas as pd

from ..config import RiskLimits
from ..logging import get
from ..risk.engine import RiskEngine
from ..strategies.base import Strategy
from .engine import run_backtest
from .metrics import compute_metrics

log = get("walkforward")
ET = "America/New_York"


def _param_combos(grid: dict) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))] or [{}]


def _slice(df: pd.DataFrame, sessions) -> pd.DataFrame:
    s = set(sessions)
    return df[[d in s for d in df.index.tz_convert(ET).date]]


def walk_forward(df: pd.DataFrame, strategy_cls: type[Strategy], param_grid: dict, *,
                 is_sessions: int = 15, oos_sessions: int = 5, metric: str = "total_return",
                 limits: RiskLimits | None = None, regime_filter=None) -> dict:
    limits = limits or RiskLimits()
    df = df.sort_index()
    sessions = sorted(set(df.index.tz_convert(ET).date))
    combos = _param_combos(param_grid)

    folds, oos_curves, oos_trades = [], [], []
    equity = limits.starting_equity
    i = 0
    while i + is_sessions + oos_sessions <= len(sessions):
        is_dates = sessions[i: i + is_sessions]
        oos_dates = sessions[i + is_sessions: i + is_sessions + oos_sessions]
        is_df, oos_df = _slice(df, is_dates), _slice(df, oos_dates)

        # 1. optimize on IS (each combo gets a fresh equity for a fair comparison)
        best, best_score = combos[0], float("-inf")
        for params in combos:
            r = RiskEngine(limits=limits, equity=limits.starting_equity)
            m = run_backtest(is_df, strategy_cls(**params), r, regime_filter=regime_filter)["metrics"]
            score = m.get(metric)
            if score is not None and score > best_score:
                best_score, best = score, params

        # 2. evaluate best on OOS, chaining equity forward
        r = RiskEngine(limits=limits, equity=equity)
        res = run_backtest(oos_df, strategy_cls(**best), r, regime_filter=regime_filter)
        equity = res["metrics"].get("end_equity", equity)
        oos_curves.append(res["equity"]); oos_trades.extend(res["trades"])
        folds.append({"is": [str(is_dates[0]), str(is_dates[-1])],
                      "oos": [str(oos_dates[0]), str(oos_dates[-1])],
                      "best_params": best, "is_score": round(best_score, 4),
                      "oos_return": round(res["metrics"].get("total_return", 0.0), 4),
                      "oos_trades": len(res["trades"])})
        i += oos_sessions

    if not oos_curves:
        return {"error": "not enough sessions for one fold", "folds": [], "oos_trades": []}
    oos_equity = pd.concat(oos_curves)
    oos_equity = oos_equity[~oos_equity.index.duplicated(keep="last")].sort_index()
    agg = compute_metrics(oos_equity, oos_trades)
    log.info("walkforward_done", folds=len(folds), oos_trades=len(oos_trades),
             oos_return=agg.get("total_return"))
    return {"folds": folds, "oos_equity": oos_equity, "oos_metrics": agg,
            "oos_trades": oos_trades, "n_folds": len(folds)}
