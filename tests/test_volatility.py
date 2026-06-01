"""Volatility circuit-breaker — suppresses mean-reversion entries during a vol blow-up
('don't catch a falling knife'). Fail-open when history is thin."""
import numpy as np
import pandas as pd

from quant_desk.regime.volatility import vol_spike, vol_ratio
from quant_desk.strategies.daily_mean_reversion import DailyMeanReversion


def _frame(closes):
    idx = pd.date_range("2023-01-02", periods=len(closes), freq="B", tz="UTC")
    c = np.asarray(closes, float)
    return pd.DataFrame({"open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": 1e6}, index=idx)


def test_no_spike_in_calm_market():
    rng = np.random.default_rng(0)
    calm = 100 + np.cumsum(rng.normal(0, 0.1, 130))      # low, steady vol
    assert vol_spike(_frame(calm), max_ratio=2.0) is False


def test_spike_detected_when_recent_vol_explodes():
    rng = np.random.default_rng(1)
    calm = 100 + np.cumsum(rng.normal(0, 0.1, 110))      # 110 calm bars
    crash = calm[-1] + np.cumsum(rng.normal(-1.5, 3.0, 10))   # 10 violent bars
    assert vol_spike(_frame(np.concatenate([calm, crash])), short=10, long=100, max_ratio=2.0) is True
    assert vol_ratio(_frame(np.concatenate([calm, crash]))) > 2.0


def test_fail_open_on_thin_history():
    assert vol_spike(_frame([100.0] * 30)) is False       # < long+1 bars → not a spike
    assert vol_ratio(_frame([100.0] * 30)) is None


def test_dmr_breaker_suppresses_oversold_entry_during_spike():
    rng = np.random.default_rng(2)
    calm = 100 + np.cumsum(rng.normal(0, 0.1, 110))
    # a violent oversold plunge: deeply negative z AND a vol explosion
    plunge = list(calm) + list(calm[-1] + np.cumsum(rng.normal(-2.0, 4.0, 8)))
    df = _frame(plunge)
    raw = DailyMeanReversion(lookback=20, entry_z=1.5, max_vol_ratio=None).compute_signal(df)
    gated = DailyMeanReversion(lookback=20, entry_z=1.5, max_vol_ratio=1.8).compute_signal(df)
    assert raw.side == "long"          # without the breaker it would buy the falling knife
    assert gated.side == "flat"        # with the breaker it stands aside
