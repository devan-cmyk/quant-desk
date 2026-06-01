"""evaluate — the full validation battery → council verdict, in one call. Runs walk-forward
(out-of-sample), Monte-Carlo on the OOS trades, the synthetic stress lab, and edge-decay
assessment; assembles the evidence packet; the committee decides; the decision is recorded
to the append-only journal. This is the strategy-promotion gate: nothing is promoted on a
backtest alone (AQROS Section 0)."""
from __future__ import annotations

import pandas as pd

from ..backtest.montecarlo import monte_carlo
from ..backtest.walkforward import walk_forward
from ..config import RiskLimits
from ..logging import get
from ..monitor.decay import assess_folds
from ..stress.lab import stress_test as run_stress
from ..strategies.base import Strategy
from . import committee

log = get("council.evaluate")


def evaluate(df: pd.DataFrame, strategy_cls: type[Strategy], param_grid: dict, *,
             regime_filter=None, limits: RiskLimits | None = None,
             is_sessions: int = 15, oos_sessions: int = 5, symbol: str | None = None) -> dict:
    limits = limits or RiskLimits()
    # asset-class-aware costs: crypto is fills + gated at realistic (~30bps) costs, not equity 2bps
    from ..costs import cost_profile
    from ..execution.paper_broker import PaperBroker
    prof = cost_profile(symbol) if symbol else {"slippage_bps": None, "commission_per_share": None,
                                                "asset_class": "equity"}
    broker = (PaperBroker(slippage_bps=prof["slippage_bps"], commission_per_share=prof["commission_per_share"])
              if symbol else None)
    wf = walk_forward(df, strategy_cls, param_grid, regime_filter=regime_filter,
                      is_sessions=is_sessions, oos_sessions=oos_sessions, broker=broker)
    if wf.get("error"):
        return {"error": wf["error"]}
    m = wf["oos_metrics"]
    pnls = [t["pnl"] for t in wf["oos_trades"]]
    mc = monte_carlo(pnls) if len(pnls) >= 3 else {"prob_ruin": None, "maxdd_p95_worst": None, "n_trades": len(pnls)}
    best = wf["folds"][-1]["best_params"] if wf.get("folds") else {}
    stress = run_stress(df, strategy_cls, params=best, regime_filter=regime_filter, limits=limits)
    decay = assess_folds(wf["folds"])
    # parameter robustness: is the edge a plateau or an overfit spike? (same asset-class costs)
    from ..backtest.sensitivity import parameter_robustness
    sens = parameter_robustness(df, strategy_cls, param_grid, regime_filter=regime_filter,
                                limits=limits, broker=broker, holdout_sessions=oos_sessions)
    # cost-stress + margin-of-safety, at the ASSET-CLASS cost (crypto edges face crypto costs).
    from .cost import cost_stress, cost_margin
    ckw = {"slippage_bps": prof["slippage_bps"], "commission_per_share": prof["commission_per_share"]}
    cost = cost_stress(wf["oos_trades"], multiplier=1.0, **ckw)
    cost.update({k: cost_margin(wf["oos_trades"], **ckw)[k] for k in ("margin", "cost_tolerance_x")})
    cost["asset_class"] = prof["asset_class"]

    evidence = {
        "params": best,
        "walkforward": {"oos_return": m.get("total_return"), "sharpe": m.get("sharpe"),
                        "profit_factor": m.get("profit_factor"), "num_trades": m.get("num_trades", 0),
                        "n_folds": wf.get("n_folds")},
        "montecarlo": {"prob_profit": mc.get("prob_profit"), "prob_ruin": mc.get("prob_ruin"),
                       "return_p50": mc.get("return_p50"), "maxdd_p95_worst": mc.get("maxdd_p95_worst"),
                       "n_trades": mc.get("n_trades")},
        "stress": {"survived_all": stress["survived_all"], "worst_drawdown": stress["worst_drawdown"]},
        "cost": cost,
        "sensitivity": sens,
        "decay": decay,
    }
    verdict = committee.decide(evidence)
    log.info("evaluate_done", decision=verdict["decision"], confidence=verdict["confidence"])
    return {"evidence": evidence, "council": verdict}
