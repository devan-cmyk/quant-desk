"""Opening Gap Fade: fades the overnight gap toward the prior close, within the entry window,
only while the gap is still open. Signal source is the close→open gap (orthogonal basket edge)."""
import numpy as np
import pandas as pd

from quant_desk.strategies.gap_fade import GapFade


def _two_sessions(prev_close, today_open, today_path):
    """Session 1 ending at prev_close, then session 2 opening at today_open following today_path."""
    bars = []
    d1 = pd.date_range("2024-06-03 13:30", periods=78, freq="5min", tz="UTC")
    c1 = np.linspace(prev_close - 0.5, prev_close, 78)
    bars.append(pd.DataFrame({"open": c1, "high": c1 + 0.1, "low": c1 - 0.1, "close": c1,
                              "volume": 1e6}, index=d1))
    d2 = pd.date_range("2024-06-04 13:30", periods=len(today_path), freq="5min", tz="UTC")
    o2 = np.array(today_path, float)
    op = np.concatenate([[today_open], o2[:-1]])           # each bar opens at the prior close
    bars.append(pd.DataFrame({"open": op, "high": np.maximum(op, o2) + 0.1,
                              "low": np.minimum(op, o2) - 0.1, "close": o2, "volume": 1e6}, index=d2))
    return pd.concat(bars)


def test_fades_gap_up_short_toward_prior_close():
    df = _two_sessions(100.0, 101.0, [101.0, 100.9, 100.8])   # +1% gap up, still open
    sig = GapFade(min_gap=0.003, entry_minutes=30).generate_signal(df)
    assert sig.side == "short"
    assert sig.target == 100.0 and sig.stop > 101.0           # target prior close, stop above
    assert "gap up" in sig.reason


def test_fades_gap_down_long():
    df = _two_sessions(100.0, 99.0, [99.0, 99.1, 99.2])       # -1% gap down
    sig = GapFade(min_gap=0.003, entry_minutes=30).generate_signal(df)
    assert sig.side == "long" and sig.target == 100.0 and sig.stop < 99.0


def test_no_trade_when_gap_too_small():
    df = _two_sessions(100.0, 100.1, [100.1, 100.05])         # 0.1% gap < 0.3% threshold
    assert GapFade(min_gap=0.003).generate_signal(df).side == "flat"


def test_no_trade_when_gap_already_filled():
    df = _two_sessions(100.0, 101.0, [101.0, 100.5, 99.9])    # gapped up but already back below close
    assert GapFade(min_gap=0.003, entry_minutes=30).generate_signal(df).side == "flat"


def test_no_trade_outside_entry_window():
    # gap up but we're already 60min past the open → past the 15min entry window
    path = [101.0] + [100.9] * 20                             # 21 bars ≈ 100 min into session
    df = _two_sessions(100.0, 101.0, path)
    assert GapFade(min_gap=0.003, entry_minutes=15).generate_signal(df).side == "flat"


def test_one_trade_per_session():
    s = GapFade(min_gap=0.003, entry_minutes=60)
    df = _two_sessions(100.0, 101.0, [101.0, 100.9, 100.8])
    assert s.generate_signal(df).side == "short"
    assert s.generate_signal(df).side == "flat"              # already signaled this session


def test_flat_on_first_session_no_prior():
    df = _two_sessions(100.0, 101.0, [101.0])
    only_first = df[df.index.date == pd.Timestamp("2024-06-03").date()]
    assert GapFade().generate_signal(only_first).side == "flat"   # no prior session to gap from
