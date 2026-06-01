"""yfinance provider (free, no API key). Caches to parquet so repeated backtests don't
re-hit the network. Intraday history on yfinance is limited (≈60 days for <1d intervals)."""
from __future__ import annotations

import os
import time

import pandas as pd

from ..config import settings
from ..logging import get
from .provider import DataProvider, OHLCV

log = get("data.yfinance")


class YFinanceProvider(DataProvider):
    name = "yfinance"

    def __init__(self, cache_dir: str | None = None, ttl_seconds: int = 3600):
        self.cache_dir = cache_dir or settings.data_dir
        self.ttl = ttl_seconds
        os.makedirs(self.cache_dir, exist_ok=True)

    def _cache_path(self, symbol: str, interval: str, lookback_days: int) -> str:
        return os.path.join(self.cache_dir, f"{symbol}_{interval}_{lookback_days}d.parquet")

    def bars(self, symbol: str, *, interval: str = "5m", lookback_days: int = 30) -> pd.DataFrame:
        path = self._cache_path(symbol, interval, lookback_days)
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < self.ttl:
            log.info("cache_hit", symbol=symbol, interval=interval, path=path)
            return OHLCV(pd.read_parquet(path))

        import yfinance as yf
        log.info("fetch", symbol=symbol, interval=interval, lookback_days=lookback_days)
        raw = yf.download(symbol, period=f"{lookback_days}d", interval=interval,
                          auto_adjust=True, progress=False, threads=False)
        if raw is None or raw.empty:
            raise RuntimeError(f"no data for {symbol} {interval}")
        if isinstance(raw.columns, pd.MultiIndex):       # yfinance multi-symbol shape
            raw.columns = raw.columns.get_level_values(0)
        raw = raw.rename(columns=str.lower)
        df = OHLCV(raw)
        df.to_parquet(path)
        return df
