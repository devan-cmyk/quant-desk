"""Synthetic intraday OHLCV so unit tests never touch the network."""
import numpy as np
import pandas as pd
import pytest


def make_session(date: str, closes, freq: str = "5min", wig: float = 0.1) -> pd.DataFrame:
    idx = pd.date_range(f"{date} 09:30", periods=len(closes), freq=freq,
                        tz="America/New_York").tz_convert("UTC")
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": c + wig, "low": c - wig, "close": c,
                         "volume": np.full(len(c), 1000.0)}, index=idx)


# OR (09:30-09:55) range ~[99.9,100.9]; breakout long at 10:05; climbs to target ~103.6
BREAKOUT_UP = [100, 100.5, 100.2, 100.8, 100.3, 100.6, 100.7, 101.6, 102.4, 103.0, 103.6, 103.8]


@pytest.fixture
def breakout_session():
    return make_session("2024-06-03", BREAKOUT_UP)


@pytest.fixture
def two_sessions():
    a = make_session("2024-06-03", BREAKOUT_UP)
    b = make_session("2024-06-04", BREAKOUT_UP)
    return pd.concat([a, b])
