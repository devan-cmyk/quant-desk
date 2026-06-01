"""ORB emits a long only after the opening range, on the breakout bar."""
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout


def test_orb_signals_long_after_breakout(breakout_session):
    strat = OpeningRangeBreakout(or_minutes=30, target_r=2.0)
    strat.initialize()
    first_signal_idx, sig = None, None
    for i in range(1, len(breakout_session) + 1):
        s = strat.generate_signal(breakout_session.iloc[:i])
        if s.side != "flat":
            first_signal_idx, sig = i - 1, s
            break
    assert sig is not None and sig.side == "long"
    # breakout is the 10:05 bar (index 7): after the 30-min OR window
    assert first_signal_idx == 7
    assert sig.stop < sig.target               # long: stop below, target above
    assert sig.target > breakout_session["close"].iloc[7]


def test_orb_one_signal_per_session(breakout_session):
    strat = OpeningRangeBreakout()
    strat.initialize()
    n = sum(strat.generate_signal(breakout_session.iloc[:i]).side != "flat"
            for i in range(1, len(breakout_session) + 1))
    assert n == 1
