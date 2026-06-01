"""Regime filter classification + engine-level veto wiring."""
import numpy as np
import pandas as pd

from quant_desk.backtest.engine import run_backtest
from quant_desk.config import RiskLimits
from quant_desk.regime.filter import RegimeFilter
from quant_desk.risk.engine import RiskEngine
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout


def _series(values):
    idx = pd.date_range("2024-06-03 09:30", periods=len(values), freq="5min", tz="UTC")
    return pd.DataFrame({"close": values}, index=idx)


def test_regime_classification():
    rf = RegimeFilter(fast=20, slow=50, slope_lookback=10)
    up = _series(100 + 0.1 * np.arange(60))           # steady uptrend
    down = _series(100 - 0.1 * np.arange(60))          # steady downtrend
    flat = _series(np.full(60, 100.0))                 # no trend → chop
    assert rf.regime(up) == "up"
    assert rf.regime(down) == "down"
    assert rf.regime(flat) == "chop"
    assert rf.allows(up, "long") and not rf.allows(up, "short")
    assert rf.allows(down, "short") and not rf.allows(down, "long")
    assert not rf.allows(flat, "long") and not rf.allows(flat, "short")


class _Stub:
    def __init__(self, ok): self.ok = ok
    def allows(self, window, side): return self.ok


def _risk():
    return RiskEngine(limits=RiskLimits(starting_equity=100_000, risk_per_trade_pct=0.01,
                                        max_daily_loss_pct=0.05, max_position_pct=0.5), equity=100_000)


def test_engine_veto_blocks_trade(breakout_session):
    # deny-all filter → the ORB long is vetoed → no trades
    res = run_backtest(breakout_session, OpeningRangeBreakout(), _risk(), regime_filter=_Stub(False))
    assert len(res["trades"]) == 0


def test_engine_allow_passes_trade(breakout_session):
    res = run_backtest(breakout_session, OpeningRangeBreakout(), _risk(), regime_filter=_Stub(True))
    assert len(res["trades"]) == 1     # same as no filter when allowed
