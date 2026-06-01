"""Mean-reversion fires on a stretch beyond entry_z and targets the mean."""
import numpy as np
import pandas as pd

from quant_desk.strategies.mean_reversion import MeanReversion


def _series(closes):
    idx = pd.date_range("2024-06-03 09:30", periods=len(closes), freq="5min",
                        tz="America/New_York").tz_convert("UTC")
    c = np.asarray(closes, float)
    return pd.DataFrame({"open": c, "high": c + 0.1, "low": c - 0.1, "close": c,
                         "volume": np.full(len(c), 1000.0)}, index=idx)


def test_meanrev_long_on_oversold():
    # 20 bars around 100, then a sharp drop far below the mean → oversold long
    closes = [100 + np.sin(i / 3) * 0.2 for i in range(20)] + [98.0]
    df = _series(closes)
    sig = MeanReversion(lookback=20, entry_z=2.0).generate_signal(df)
    assert sig.side == "long"
    assert sig.target > sig.stop                     # target = mean (above), stop below
    assert "reversion" in sig.reason


def test_meanrev_flat_when_in_range():
    df = _series([100 + np.sin(i / 3) * 0.2 for i in range(21)])
    assert MeanReversion(lookback=20).generate_signal(df).side == "flat"


def test_conviction_grows_with_depth():
    # a deeper extreme must carry higher conviction than a shallow one (gradient for the filter)
    base = [100 + np.sin(i / 3) * 1.0 for i in range(20)]
    shallow = MeanReversion(lookback=20, entry_z=2.0).compute_signal(_series(base + [98.0]))
    deep = MeanReversion(lookback=20, entry_z=2.0).compute_signal(_series(base + [94.0]))
    assert shallow.side == deep.side == "long"
    assert deep.strength > shallow.strength


def test_conviction_filter_mechanism():
    from quant_desk.strategies.base import Strategy, Signal

    class _Fake(Strategy):
        def __init__(self, strength, min_strength=0.0):
            self._s, self.min_strength = strength, min_strength
        def compute_signal(self, w):
            return Signal("long", stop=1.0, target=2.0, strength=self._s)

    assert _Fake(0.3, min_strength=0.5).generate_signal(None).side == "flat"   # weak → dropped
    assert _Fake(0.8, min_strength=0.5).generate_signal(None).side == "long"   # strong → kept
    assert _Fake(0.3, min_strength=0.0).generate_signal(None).side == "long"   # filter off → kept
