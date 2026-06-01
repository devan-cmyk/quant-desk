"""Parameter robustness — distinguishes a plateau (real edge) from an overfit spike, and the
committee downgrades a parameter-fragile strategy. The classic curve-fitting detector."""
import numpy as np
import pandas as pd

from quant_desk.backtest.sensitivity import parameter_robustness
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout
from quant_desk.council import committee


def _sessions(n_days, seed=0):
    rng = np.random.default_rng(seed)
    frames = []
    for d in range(n_days):
        day = pd.Timestamp("2024-01-02") + pd.Timedelta(days=d)
        idx = pd.date_range(day + pd.Timedelta("13:30:00"), periods=78, freq="5min", tz="UTC")
        base = 100 + np.linspace(0, rng.normal(1.0, 1.5), 78) + rng.normal(0, 0.1, 78).cumsum() * 0.1
        frames.append(pd.DataFrame({"open": base, "high": base + 0.3, "low": base - 0.3,
                                    "close": base, "volume": 1e6}, index=idx))
    return pd.concat(frames)


def test_robustness_reports_grid_fraction():
    df = _sessions(80)
    r = parameter_robustness(df, OpeningRangeBreakout,
                             {"or_minutes": [15, 30], "target_r": [1.5, 2.0, 3.0]}, holdout_sessions=60)
    assert r["n_combos"] == 6
    assert r["frac_profitable"] is None or 0.0 <= r["frac_profitable"] <= 1.0
    assert "robust" in r and isinstance(r["robust"], bool)


def test_single_combo_is_not_flagged():
    # a 1-combo grid can't be parameter-fragile — sensitivity is n/a, robust=True
    r = parameter_robustness(_sessions(80), OpeningRangeBreakout, {"or_minutes": [30]})
    assert r["robust"] is True and r["frac_profitable"] is None


def test_insufficient_history_is_safe():
    r = parameter_robustness(_sessions(20), OpeningRangeBreakout,
                             {"or_minutes": [15, 30]}, holdout_sessions=60)
    assert r["robust"] is True and "need" in r["detail"]


def _ev(sens):
    return {
        "walkforward": {"oos_return": 0.02, "sharpe": 1.5, "profit_factor": 1.6, "num_trades": 30},
        "montecarlo": {"prob_ruin": 0.0, "maxdd_p95_worst": -0.05, "n_trades": 30},
        "stress": {"survived_all": True, "worst_drawdown": -0.03},
        "cost": {"survives": True, "stressed_pf": 1.4, "stressed_return": 0.01},
        "sensitivity": sens,
        "decay": {"status": "healthy"},
    }


def test_committee_downgrades_parameter_fragile_edge():
    # robust plateau → promotes; fragile spike (only 25% of grid OOS-profitable) → capped to paper_watch
    robust = committee.decide(_ev({"frac_profitable": 0.83, "robust": True}))
    fragile = committee.decide(_ev({"frac_profitable": 0.25, "robust": False}))
    assert robust["decision"] == "promote"
    assert fragile["decision"] == "paper_watch"
    assert "parameter-fragile" in fragile["rationale"] or any(
        "parameter-fragile" in r for v in fragile["votes"] for r in v["reasons"])
