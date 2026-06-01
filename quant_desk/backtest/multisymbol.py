"""Multi-symbol walk-forward. An edge that's real shows up on more than one ticker. Runs
the same walk-forward across a basket, reports per-symbol OOS, and POOLS every OOS trade
across symbols so Monte-Carlo can judge the combined edge. data_fn is injectable so this is
testable offline (default: yfinance)."""
from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from ..logging import get
from ..strategies.base import Strategy
from .montecarlo import monte_carlo
from .walkforward import walk_forward

log = get("multisymbol")


def multi_symbol_walkforward(
    symbols: list[str], strategy_cls: type[Strategy], param_grid: dict, *,
    data_fn: Callable[[str], pd.DataFrame], regime_filter=None,
    is_sessions: int = 15, oos_sessions: int = 5, metric: str = "total_return",
    mc_sims: int = 5000,
) -> dict:
    per_symbol, pooled_pnls = [], []
    for sym in symbols:
        try:
            df = data_fn(sym)
        except Exception as e:                       # one bad symbol shouldn't kill the run
            per_symbol.append({"symbol": sym, "error": str(e)[:120]}); continue
        wf = walk_forward(df, strategy_cls, param_grid, regime_filter=regime_filter,
                          is_sessions=is_sessions, oos_sessions=oos_sessions, metric=metric)
        if wf.get("error"):
            per_symbol.append({"symbol": sym, "error": wf["error"]}); continue
        m = wf["oos_metrics"]
        per_symbol.append({
            "symbol": sym, "oos_return": round(m.get("total_return", 0.0), 4),
            "sharpe": m.get("sharpe"), "profit_factor": m.get("profit_factor"),
            "win_rate": m.get("win_rate"), "trades": m.get("num_trades", 0)})
        pooled_pnls.extend(t["pnl"] for t in wf["oos_trades"])

    good = [r for r in per_symbol if "error" not in r]
    summary = {
        "symbols_run": len(good), "symbols_failed": len(per_symbol) - len(good),
        "symbols_positive_oos": sum(1 for r in good if r["oos_return"] > 0),
        "pooled_oos_trades": len(pooled_pnls),
    }
    pooled_mc = monte_carlo(pooled_pnls, n_sims=mc_sims) if len(pooled_pnls) >= 3 else {"error": "too few pooled trades"}
    log.info("multisymbol_done", **summary)
    return {"per_symbol": per_symbol, "summary": summary, "pooled_monte_carlo": pooled_mc}
