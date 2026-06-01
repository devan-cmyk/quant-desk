"""Provider abstraction. Every data source conforms to DataProvider so strategies and
backtests never depend on a vendor. OHLCV is the normalized contract: a tz-aware DataFrame
indexed by timestamp with columns [open, high, low, close, volume]."""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


def OHLCV(df: pd.DataFrame) -> pd.DataFrame:
    """Validate + normalize a frame to the OHLCV contract."""
    missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV missing columns: {missing}")
    out = df[OHLCV_COLUMNS].copy()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    return out


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def bars(self, symbol: str, *, interval: str, lookback_days: int) -> pd.DataFrame:
        """Return normalized OHLCV for `symbol`. interval e.g. '1d','5m','1m'."""
        raise NotImplementedError
