"""Edge-decay detection. An edge isn't real because a backtest liked it once — it's real
while it keeps working out-of-sample, and it dies quietly. We read the SEQUENCE of
walk-forward OOS fold returns and classify the current health. This reacts to realized
OOS reality; it never optimizes, so it cannot overfit.

  healthy  — recent OOS positive and not strongly declining → keep trading
  watch    — recent OOS still positive but trending down → on notice
  retired  — recent OOS has gone negative → pull it (the edge is gone)
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from ..backtest.walkforward import walk_forward
from ..logging import get
from ..strategies.base import Strategy

log = get("monitor.decay")


def assess_folds(folds: list[dict], *, recent_k: int = 3, floor: float = 0.0,
                 trend_thresh: float = 0.002) -> dict:
    rets = [f.get("oos_return", 0.0) for f in folds]
    n = len(rets)
    if n < max(recent_k, 3):
        return {"status": "insufficient_data", "n_folds": n}
    recent_mean = float(np.mean(rets[-recent_k:]))
    slope = float(np.polyfit(range(n), rets, 1)[0])    # OOS-return trend across folds
    if recent_mean < floor:
        status = "retired"
    elif slope < -trend_thresh:
        status = "watch"
    else:
        status = "healthy"
    return {"status": status, "recent_mean": round(recent_mean, 4),
            "trend": round(slope, 5), "n_folds": n}


def monitor_universe(symbols: list[str], strategy_cls: type[Strategy], param_grid: dict, *,
                     data_fn: Callable[[str], pd.DataFrame], regime_filter=None,
                     is_sessions: int = 15, oos_sessions: int = 5,
                     recent_k: int = 3) -> list[dict]:
    out = []
    for sym in symbols:
        try:
            df = data_fn(sym)
        except Exception as e:
            out.append({"symbol": sym, "status": "error", "note": str(e)[:80]}); continue
        wf = walk_forward(df, strategy_cls, param_grid, regime_filter=regime_filter,
                          is_sessions=is_sessions, oos_sessions=oos_sessions)
        if wf.get("error"):
            out.append({"symbol": sym, "status": "insufficient_data"}); continue
        a = assess_folds(wf["folds"], recent_k=recent_k)
        a["symbol"] = sym
        a["oos_return"] = round(wf["oos_metrics"].get("total_return", 0.0), 4)
        out.append(a)
    log.info("monitor_done", symbols=len(symbols),
             retired=sum(r["status"] == "retired" for r in out))
    return out
