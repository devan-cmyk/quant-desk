"""Stress lab — run a strategy through every synthetic crisis and report whether it SURVIVES
(max drawdown stays above a ruin threshold) and how much each scenario degrades it vs
baseline. The point isn't returns; it's knowing your tail before capital is ever at risk."""
from __future__ import annotations

import pandas as pd

from ..backtest.engine import run_backtest
from ..config import RiskLimits
from ..execution.paper_broker import PaperBroker
from ..logging import get
from ..risk.engine import RiskEngine
from ..strategies.base import Strategy
from .scenarios import SCENARIOS

log = get("stress")


def stress_test(df: pd.DataFrame, strategy_cls: type[Strategy], *, params: dict | None = None,
                regime_filter=None, limits: RiskLimits | None = None,
                ruin_drawdown: float = 0.25, scenarios: dict | None = None) -> dict:
    limits = limits or RiskLimits()
    params = params or {}
    scenarios = scenarios or SCENARIOS

    results = []
    for name, fn in scenarios.items():
        sdf, slip = fn(df)
        broker = PaperBroker(slippage_bps=slip) if slip is not None else PaperBroker()
        risk = RiskEngine(limits=limits, equity=limits.starting_equity)
        res = run_backtest(sdf, strategy_cls(**params), risk, broker=broker, regime_filter=regime_filter)
        m = res["metrics"]
        worst = min((t["pnl"] for t in res["trades"]), default=0.0)
        dd = m.get("max_drawdown", 0.0)
        results.append({
            "scenario": name,
            "total_return": round(m.get("total_return", 0.0), 4),
            "max_drawdown": round(dd, 4),
            "worst_trade": round(worst, 2),
            "trades": m.get("num_trades", 0),
            "survived": dd > -ruin_drawdown,
        })

    base_ret = next((r["total_return"] for r in results if r["scenario"] == "baseline"), 0.0)
    worst_dd = min(r["max_drawdown"] for r in results)
    survived_all = all(r["survived"] for r in results)
    log.info("stress_done", survived_all=survived_all, worst_dd=worst_dd)
    return {"results": results, "baseline_return": base_ret, "worst_drawdown": worst_dd,
            "survived_all": survived_all, "ruin_drawdown": ruin_drawdown}
