"""Portfolio allocation: diversification-aware risk weights + the per-trade risk scale.
Robust on short samples (no covariance optimizer); equal weights reproduce prior sizing."""
import numpy as np
import pandas as pd

from quant_desk.portfolio.allocate import (session_returns, correlation_matrix, allocate,
                                           regime_session_labels)
from quant_desk.risk.engine import RiskEngine
from quant_desk.config import RiskLimits


def _trades(day_pnls):  # {("2024-06-03"): pnl}
    return [{"exit_ts": pd.Timestamp(d, tz="UTC"), "pnl": p} for d, p in day_pnls.items()]


def test_session_returns_aggregates_by_day():
    tr = [{"exit_ts": pd.Timestamp("2024-06-03 14:00", tz="UTC"), "pnl": 100.0},
          {"exit_ts": pd.Timestamp("2024-06-03 15:30", tz="UTC"), "pnl": -40.0},
          {"exit_ts": pd.Timestamp("2024-06-04 14:00", tz="UTC"), "pnl": 50.0}]
    s = session_returns(tr, starting_equity=100_000)
    assert len(s) == 2
    assert abs(s.iloc[0] - 60 / 100_000) < 1e-9       # 100 - 40 netted on day 1


def test_correlated_pair_is_downweighted():
    # A and B move together (redundant); C is independent → C should get more weight than A or B
    rng = np.random.default_rng(0)
    days = pd.date_range("2024-01-01", periods=40, freq="D")
    a = pd.Series(rng.normal(0, 0.01, 40), index=days)
    b = a + pd.Series(rng.normal(0, 0.0005, 40), index=days)    # ~ A
    c = pd.Series(rng.normal(0, 0.01, 40), index=days)          # independent
    res = allocate({"s:A": a, "s:B": b, "s:C": c})
    w = res["weights"]
    assert res["method"].startswith("inverse-vol")
    assert w["s:C"] > w["s:A"] and w["s:C"] > w["s:B"]          # the diversifier gets more
    assert abs(sum(w.values()) - 1.0) < 1e-6                    # weights normalized


def test_equal_weight_fallback_on_thin_history():
    days = pd.date_range("2024-01-01", periods=4, freq="D")     # < MIN_OBS
    res = allocate({"s:A": pd.Series([0.01]*4, index=days), "s:B": pd.Series([0.0]*4, index=days)})
    assert "equal" in res["method"]
    assert res["weights"]["s:A"] == res["weights"]["s:B"] == 0.5
    assert res["scales"]["s:A"] == 1.0                          # equal → no sizing change


def test_single_pair_is_full_weight():
    res = allocate({"s:A": pd.Series([0.01, 0.02])})
    assert res["weights"] == {"s:A": 1.0} and res["scales"]["s:A"] == 1.0


def test_regime_tilt_favours_the_edge_that_earns_in_the_current_regime():
    # two uncorrelated pairs over 40 days; A earns only in 'chop' days, B only in 'trend' days
    days = pd.date_range("2024-01-01", periods=40, freq="D")
    labels = {d.date(): ("chop" if i % 2 == 0 else "trend") for i, d in enumerate(days)}
    a = pd.Series([0.02 if labels[d.date()] == "chop" else -0.001 for d in days], index=[d.date() for d in days])
    b = pd.Series([0.02 if labels[d.date()] == "trend" else -0.001 for d in days], index=[d.date() for d in days])
    base = allocate({"s:A": a, "s:B": b})
    chop = allocate({"s:A": a, "s:B": b}, regime_labels=labels, current_regime="chop")
    trend = allocate({"s:A": a, "s:B": b}, regime_labels=labels, current_regime="trend")
    # in chop, A (the chop earner) is tilted up vs its unconditional weight; in trend, down
    assert chop["weights"]["s:A"] > base["weights"]["s:A"]
    assert trend["weights"]["s:A"] < base["weights"]["s:A"]
    assert chop["current_regime"] == "chop" and chop["tilts"]["s:A"] > chop["tilts"]["s:B"]


def test_regime_tilt_is_bounded_and_neutral_when_thin():
    days = pd.date_range("2024-01-01", periods=12, freq="D")
    idx = [d.date() for d in days]
    a = pd.Series([0.01] * 12, index=idx); b = pd.Series([0.005] * 12, index=idx)
    labels = {d: "trend" for d in idx}          # only 1 regime present, < REGIME_MIN_OBS for 'chop'
    res = allocate({"s:A": a, "s:B": b}, regime_labels=labels, current_regime="chop")
    assert all(t == 1.0 for t in res["tilts"].values())   # no chop history → neutral, falls back


def test_regime_session_labels_trend_vs_chop():
    from quant_desk.regime.filter import RegimeFilter
    # a steadily rising series → recent sessions classify 'trend'
    idx = pd.date_range("2024-06-03 13:30", periods=60 * 60, freq="5min", tz="UTC")
    up = np.arange(len(idx), dtype=float) * 0.01 + 100           # plain array → no index misalignment
    df = pd.DataFrame({"open": up, "high": up + 0.1, "low": up - 0.1, "close": up, "volume": 1e6}, index=idx)
    labels = regime_session_labels(df, RegimeFilter())
    assert set(labels.values()) <= {"trend", "chop"}
    assert labels[max(labels)] == "trend"       # the latest session is trending


def test_risk_scale_multiplies_position_size():
    lim = RiskLimits(starting_equity=100_000, risk_per_trade_pct=0.01, max_position_pct=5.0)
    r = RiskEngine(limits=lim, equity=100_000)
    base = r.evaluate(entry=100.0, stop=99.0).qty                # $1000 risk / $1 = 1000
    half = r.evaluate(entry=100.0, stop=99.0, risk_scale=0.5).qty
    dbl = r.evaluate(entry=100.0, stop=99.0, risk_scale=2.0).qty
    assert base == 1000 and half == 500 and dbl == 2000
