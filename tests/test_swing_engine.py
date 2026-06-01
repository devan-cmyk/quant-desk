"""Swing mode: the engine holds a position across multiple bars (no EOD flatten) and exits on
stop/target or after max_hold_bars. Intraday strategies are unaffected (default intraday=True)."""
import numpy as np
import pandas as pd

from quant_desk.backtest.engine import run_backtest
from quant_desk.risk.engine import RiskEngine
from quant_desk.config import RiskLimits
from quant_desk.strategies.base import Strategy, Signal
from quant_desk.strategies.daily_mean_reversion import DailyMeanReversion


def _daily(closes):
    idx = pd.date_range("2024-01-02", periods=len(closes), freq="B", tz="UTC")   # business days
    c = np.asarray(closes, float)
    return pd.DataFrame({"open": c, "high": c + 0.2, "low": c - 0.2, "close": c,
                         "volume": 1e6}, index=idx)


class _EnterOnceLong(Strategy):
    """Fires a long on the first bar, then never again — to observe the hold mechanics."""
    name = "t"
    intraday = False
    def __init__(self, max_hold_bars=3, stop=90.0, target=200.0):
        self.max_hold_bars = max_hold_bars; self._fired = False
        self._stop, self._target = stop, target
    def initialize(self, ctx=None): self._fired = False
    def compute_signal(self, w):
        if self._fired or len(w) < 1: return Signal()
        self._fired = True
        return Signal("long", stop=self._stop, target=self._target, strength=1.0)


def _lim():
    return RiskLimits(starting_equity=100_000, risk_per_trade_pct=0.01, max_position_pct=1.0)


def test_swing_holds_then_exits_on_max_hold():
    # flat-ish prices so neither stop(90) nor target(200) hits → exit must be max_hold
    df = _daily([100 + 0.1 * i for i in range(10)])
    res = run_backtest(df, _EnterOnceLong(max_hold_bars=3), RiskEngine(limits=_lim()))
    assert len(res["trades"]) == 1
    t = res["trades"][0]
    assert t["reason"] == "max_hold"
    held_bars = list(df.index).index(t["exit_ts"]) - list(df.index).index(t["entry_ts"])
    assert held_bars == 3                       # held exactly max_hold_bars, NOT flattened EOD


def test_swing_exits_on_target_across_days():
    df = _daily([100, 101, 102, 250, 104, 105])   # spikes through target=200 on day 4
    res = run_backtest(df, _EnterOnceLong(max_hold_bars=10, target=200.0), RiskEngine(limits=_lim()))
    assert res["trades"][0]["reason"] == "target"


def test_intraday_strategy_still_eod_flattens():
    # an intraday version of the same strategy must flatten same-bar (one bar = one session here)
    class _Intraday(_EnterOnceLong):
        intraday = True
    df = _daily([100 + 0.1 * i for i in range(6)])
    res = run_backtest(df, _Intraday(), RiskEngine(limits=_lim()))
    assert all(t["reason"] == "eod" for t in res["trades"])   # never holds overnight


def test_daily_mean_reversion_is_swing_and_holds():
    # a deep dip then recovery — dmr should enter long and hold across days (reason != 'eod' same bar)
    closes = [100 + np.sin(i / 4) * 1.0 for i in range(40)] + [94.0, 95, 96, 97, 98, 99, 100]
    res = run_backtest(_daily(closes), DailyMeanReversion(lookback=20, entry_z=1.5, max_hold_bars=5),
                       RiskEngine(limits=_lim()))
    assert not DailyMeanReversion().intraday
    if res["trades"]:
        t = res["trades"][0]
        held = list(_daily(closes).index).index(t["exit_ts"]) - list(_daily(closes).index).index(t["entry_ts"])
        assert held >= 1                        # genuinely held across at least one day
