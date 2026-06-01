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
