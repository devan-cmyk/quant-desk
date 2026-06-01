"""Data provider: OHLCV normalization contract + retry/backoff on transient failures.
All offline — the network call (_download) is stubbed, so no yfinance/network dependency."""
import numpy as np
import pandas as pd
import pytest

from quant_desk.data.provider import OHLCV, OHLCV_COLUMNS
from quant_desk.data.yfinance_provider import YFinanceProvider


def _raw(n=10, multiindex=False, tz=False):
    idx = pd.date_range("2024-06-03 13:30", periods=n, freq="5min", tz=("UTC" if tz else None))
    cols = ["Open", "High", "Low", "Close", "Volume"]
    data = {c: np.linspace(100, 101, n) for c in cols}
    df = pd.DataFrame(data, index=idx)
    if multiindex:                                       # yfinance single-symbol download shape
        df.columns = pd.MultiIndex.from_product([cols, ["SPY"]])
    return df


# ── OHLCV contract ────────────────────────────────────────────────────────────
def test_ohlcv_normalizes_and_localizes():
    out = OHLCV(_raw().rename(columns=str.lower))
    assert list(out.columns) == OHLCV_COLUMNS
    assert out.index.tz is not None                      # naive index → localized to UTC
    assert out.index.is_monotonic_increasing


def test_ohlcv_rejects_missing_columns():
    with pytest.raises(ValueError, match="missing columns"):
        OHLCV(pd.DataFrame({"open": [1.0]}))


def test_ohlcv_dedupes_index_keeping_last():
    df = _raw(3).rename(columns=str.lower)
    df = pd.concat([df, df.iloc[[-1]]])                  # duplicate the last timestamp
    assert len(OHLCV(df)) == 3


# ── retry / backoff ─────────────────────────────────────────────────────────────
def test_succeeds_first_try_and_caches(tmp_path, monkeypatch):
    p = YFinanceProvider(cache_dir=str(tmp_path), backoff_seconds=0)
    monkeypatch.setattr(p, "_download", lambda *a, **k: _raw(multiindex=True))
    df = p.bars("SPY", interval="5m", lookback_days=5)
    assert list(df.columns) == OHLCV_COLUMNS             # MultiIndex flattened + lowercased
    assert (tmp_path / "SPY_5m_5d.parquet").exists()     # cached for next time


def test_retries_then_succeeds(tmp_path, monkeypatch):
    p = YFinanceProvider(cache_dir=str(tmp_path), retries=3, backoff_seconds=0)
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return _raw()
    monkeypatch.setattr(p, "_download", flaky)
    df = p.bars("SPY", interval="5m", lookback_days=5)
    assert calls["n"] == 3 and len(df) == 10             # recovered on the 3rd attempt


def test_raises_after_exhausting_retries(tmp_path, monkeypatch):
    p = YFinanceProvider(cache_dir=str(tmp_path), retries=3, backoff_seconds=0)
    monkeypatch.setattr(p, "_download", lambda *a, **k: pd.DataFrame())   # always empty
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        p.bars("SPY", interval="5m", lookback_days=5)
