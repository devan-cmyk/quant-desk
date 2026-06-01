"""Real-time decision loop: acts on the LATEST bar only (not a replay), is idempotent per bar
(no double-entry), holds swing positions across ticks, exits on max_hold, and routes through the
injected broker with a symbol."""
import numpy as np
import pandas as pd

from quant_desk.config import RiskLimits
from quant_desk.live.portfolio import PaperPortfolio
from quant_desk.live.realtime import live_tick
from quant_desk.strategies.base import Strategy, Signal
from quant_desk.execution.paper_broker import Fill


def _daily(n):
    idx = pd.date_range("2024-01-02", periods=n, freq="B", tz="UTC")
    c = np.linspace(100, 100 + n * 0.1, n)
    return pd.DataFrame({"open": c, "high": c + 0.2, "low": c - 0.2, "close": c, "volume": 1e6}, index=idx)


class _AlwaysLong(Strategy):
    name = "t"; intraday = False
    def __init__(self, max_hold_bars=3): self.max_hold_bars = max_hold_bars
    def compute_signal(self, w):
        c = float(w["close"].iloc[-1])
        return Signal("long", stop=c * 0.5, target=c * 2.0, strength=1.0)   # stop/target never hit → exits on max_hold


def _lim():
    return RiskLimits(starting_equity=100_000, risk_per_trade_pct=0.01, max_position_pct=1.0)


def _mandates():
    return [{"name": "t", "cls": _AlwaysLong, "symbols": ["AAA"], "params": {}}]


def test_enters_on_latest_bar_only():
    df = _daily(30); pf = PaperPortfolio(cash=100_000)
    res = live_tick(_mandates(), data_fn=lambda s: df, portfolio=pf, limits=_lim())
    assert len(pf.positions) == 1 and res["blotter_n"] == 0          # opened, held — not a replay of 30 bars
    assert pf.positions["t:AAA"]["entry_ts"] == df.index[-1].isoformat()   # entered on the LATEST bar


def test_idempotent_no_double_entry_on_unchanged_bar():
    df = _daily(30); pf = PaperPortfolio(cash=100_000)
    live_tick(_mandates(), data_fn=lambda s: df, portfolio=pf, limits=_lim())
    live_tick(_mandates(), data_fn=lambda s: df, portfolio=pf, limits=_lim())   # same bar again
    live_tick(_mandates(), data_fn=lambda s: df, portfolio=pf, limits=_lim())
    assert len(pf.positions) == 1 and len(pf.blotter) == 0          # still exactly one position, no churn


def test_swing_holds_across_ticks_then_max_hold_exit():
    pf = PaperPortfolio(cash=100_000); full = _daily(40)
    m = _mandates()  # max_hold_bars=3
    live_tick(m, data_fn=lambda s: full.iloc[:30], portfolio=pf, limits=_lim())   # enter on bar 29
    assert len(pf.positions) == 1
    live_tick(m, data_fn=lambda s: full.iloc[:31], portfolio=pf, limits=_lim())   # held 1 bar, no exit
    assert len(pf.positions) == 1 and len(pf.blotter) == 0
    live_tick(m, data_fn=lambda s: full.iloc[:33], portfolio=pf, limits=_lim())   # held 3 bars → max_hold exit
    assert any(t["reason"] == "max_hold" for t in pf.blotter)      # the hold was capped at max_hold_bars
    assert pf.blotter[-1]["entry_ts"] == full.index[29].isoformat()  # it was the bar-29 entry that capped


def test_routes_through_injected_broker_with_symbol():
    calls = []
    class _RecBroker:
        def fill(self, side, qty, ref_price, symbol=None):
            calls.append((side, qty, symbol)); return Fill(side, qty, ref_price, ref_price, 0.0)
    df = _daily(30); pf = PaperPortfolio(cash=100_000)
    live_tick(_mandates(), data_fn=lambda s: df, portfolio=pf, broker=_RecBroker(), limits=_lim())
    assert calls and calls[0][2] == "AAA"          # the symbol was passed to the broker (Alpaca needs it)
