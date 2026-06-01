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


def make_ohlc(date: str, rows, freq: str = "5min") -> pd.DataFrame:
    """Explicit OHLC rows = list of (open, high, low, close); volume uniform."""
    idx = pd.date_range(f"{date} 09:30", periods=len(rows), freq=freq,
                        tz="America/New_York").tz_convert("UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1000.0
    return df


# uptrend above VWAP, then a deep-wick bar dips to VWAP and the next bar closes back up
VWAP_PULLBACK_ROWS = [
    (100.0, 100.2, 99.9, 100.1), (100.1, 100.4, 100.0, 100.3), (100.3, 100.6, 100.2, 100.5),
    (100.5, 100.8, 100.4, 100.7), (100.7, 101.0, 100.6, 100.9), (100.9, 101.2, 100.8, 101.1),
    (101.1, 101.3, 101.0, 101.2),
    (101.2, 101.3, 100.4, 100.7),   # pullback: deep low to VWAP, closes down
    (100.7, 101.2, 100.5, 101.1),   # bounce: low near VWAP, closes up & above VWAP -> LONG
    (101.1, 101.6, 101.0, 101.5),   # continues up toward target
    (101.5, 101.9, 101.4, 101.8),
]


@pytest.fixture
def vwap_session():
    return make_ohlc("2024-06-03", VWAP_PULLBACK_ROWS)


@pytest.fixture
def multi_session():
    """8 ORB-friendly sessions for walk-forward (needs IS+OOS sessions)."""
    days = [f"2024-06-{d:02d}" for d in (3, 4, 5, 6, 7, 10, 11, 12)]
    return pd.concat([make_session(d, BREAKOUT_UP) for d in days])
