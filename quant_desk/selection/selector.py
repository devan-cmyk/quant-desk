"""Symbol selection — the edge is real only on the right names (4/6 in our basket). This
ranks a universe by trailing walk-forward OOS and returns the symbols that clear a bar
(positive OOS + min profit-factor + min trades). The paper runner trades ONLY these. Re-run
it periodically so the traded universe adapts as edges decay."""
from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from ..logging import get
from ..strategies.base import Strategy
from ..backtest.multisymbol import multi_symbol_walkforward

log = get("selection")


def select_symbols(symbols: list[str], strategy_cls: type[Strategy], param_grid: dict, *,
                   data_fn: Callable[[str], pd.DataFrame], regime_filter=None,
                   min_profit_factor: float = 1.1, min_trades: int = 10,
                   is_sessions: int = 15, oos_sessions: int = 5) -> dict:
    res = multi_symbol_walkforward(symbols, strategy_cls, param_grid, data_fn=data_fn,
                                   regime_filter=regime_filter, is_sessions=is_sessions,
                                   oos_sessions=oos_sessions, mc_sims=1)
    ranking = []
    for r in res["per_symbol"]:
        if "error" in r:
            ranking.append({**r, "qualified": False}); continue
        pf = r["profit_factor"]
        # pf is None when there were no losing trades (all wins) — that PASSES the PF bar
        pf_ok = (pf is None and r["trades"] > 0) or (pf is not None and pf >= min_profit_factor)
        qualified = (r["oos_return"] > 0) and pf_ok and (r["trades"] >= min_trades)
        ranking.append({**r, "qualified": qualified})
    # sort by profit factor desc; all-wins (None) rank at the top
    ranking.sort(key=lambda x: (float("inf") if x.get("profit_factor") is None and "error" not in x
                                else (x.get("profit_factor") or 0.0)), reverse=True)
    qualified = [r["symbol"] for r in ranking if r.get("qualified")]
    log.info("selection_done", universe=len(symbols), qualified=len(qualified))
    return {"qualified": qualified, "ranking": ranking}
