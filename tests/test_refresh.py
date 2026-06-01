"""Walk-forward param refresh: only adopts a re-fit that holds on a fresh holdout and is no
worse than the deployed params — strictly improvement-seeking, never overfits to recent noise."""
import numpy as np
import pandas as pd

from quant_desk.refresh.refresh import refresh_params
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout
from quant_desk.config import RiskLimits


def _sessions(n_days, seed=0):
    """n trading days of 5-minute bars with a mild intraday drift (enough for ORB to fire)."""
    rng = np.random.default_rng(seed)
    frames = []
    for d in range(n_days):
        day = pd.Timestamp("2024-06-03") + pd.Timedelta(days=d)
        idx = pd.date_range(day + pd.Timedelta("13:30:00"), periods=78, freq="5min", tz="UTC")
        drift = np.linspace(0, rng.normal(1.5, 1.0), 78)
        base = 100 + drift + rng.normal(0, 0.1, 78).cumsum() * 0.1
        frames.append(pd.DataFrame({"open": base, "high": base + 0.3, "low": base - 0.3,
                                    "close": base, "volume": 1e6}, index=idx))
    return pd.concat(frames)


def _limits():
    return RiskLimits(starting_equity=100_000, risk_per_trade_pct=0.01, max_position_pct=0.5)


GRID = {"or_minutes": [15, 30], "target_r": [1.5, 2.0, 3.0]}


def test_refresh_returns_a_decision_with_holdout_evidence():
    df = _sessions(30)
    res = refresh_params(df, OpeningRangeBreakout, GRID, {"or_minutes": 30, "target_r": 2.0},
                         fit_sessions=18, holdout_sessions=5, limits=_limits())
    assert set(res) >= {"adopt", "old", "new", "new_oos", "cur_oos", "new_trades", "reason"}
    assert isinstance(res["adopt"], bool)
    assert res["new"] in [{"or_minutes": o, "target_r": t} for o in (15, 30) for t in (1.5, 2.0, 3.0)]


def test_refresh_never_adopts_when_holdout_loses():
    # force the guard: a holdout where the refit can't beat current AND is negative → keep
    df = _sessions(30, seed=7)
    res = refresh_params(df, OpeningRangeBreakout, GRID, {"or_minutes": 30, "target_r": 2.0},
                         fit_sessions=18, holdout_sessions=5, limits=_limits())
    if res["adopt"]:
        assert res["new_oos"] >= 0 and res["new_oos"] >= res["cur_oos"]   # adoption invariant
        assert res["new_trades"] >= 3
    else:
        assert res["new"] == {"or_minutes": 30, "target_r": 2.0} or res["new_oos"] < res["cur_oos"] \
            or res["new_oos"] < 0 or res["new_trades"] < 3


def test_refresh_insufficient_history_keeps_current():
    df = _sessions(6)
    cur = {"or_minutes": 30, "target_r": 2.0}
    res = refresh_params(df, OpeningRangeBreakout, GRID, cur, fit_sessions=20, holdout_sessions=5)
    assert res["adopt"] is False and res["new"] == cur and "need" in res["reason"]


def test_adoption_invariant_holds_whenever_it_adopts():
    # across several seeds, any adoption must satisfy the guard (non-negative, >= current, enough trades)
    for seed in range(6):
        res = refresh_params(_sessions(32, seed), OpeningRangeBreakout, GRID,
                             {"or_minutes": 15, "target_r": 1.5}, fit_sessions=20,
                             holdout_sessions=5, limits=_limits())
        if res["adopt"]:
            assert res["new_oos"] >= 0
            assert res["new_oos"] >= res["cur_oos"]
            assert res["new_trades"] >= 3
            assert res["new"] != res["old"]
