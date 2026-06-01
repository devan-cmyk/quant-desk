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

    def __init__(self, cache_dir: str | None = None, ttl_seconds: int = 3600,
                 retries: int = 3, backoff_seconds: float = 1.0):
        self.cache_dir = cache_dir or settings.data_dir
        self.ttl = ttl_seconds
        self.retries = max(1, retries)
        self.backoff_seconds = backoff_seconds
        os.makedirs(self.cache_dir, exist_ok=True)

    def _cache_path(self, symbol: str, interval: str, lookback_days: int) -> str:
        return os.path.join(self.cache_dir, f"{symbol}_{interval}_{lookback_days}d.parquet")

    def _download(self, symbol: str, interval: str, lookback_days: int) -> pd.DataFrame:
        """The raw network call — isolated so it can be retried (and stubbed in tests)."""
        import yfinance as yf
        return yf.download(symbol, period=f"{lookback_days}d", interval=interval,
                           auto_adjust=True, progress=False, threads=False)

    def bars(self, symbol: str, *, interval: str = "5m", lookback_days: int = 30) -> pd.DataFrame:
        path = self._cache_path(symbol, interval, lookback_days)
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < self.ttl:
            log.info("cache_hit", symbol=symbol, interval=interval, path=path)
            return OHLCV(pd.read_parquet(path))

        # retry transient failures / empty responses with exponential backoff
        raw, last = None, ""
        for attempt in range(1, self.retries + 1):
            log.info("fetch", symbol=symbol, interval=interval, lookback_days=lookback_days, attempt=attempt)
            try:
                raw = self._download(symbol, interval, lookback_days)
                if raw is not None and not raw.empty:
                    break
                last = "empty response"
            except Exception as e:                       # transient network/vendor errors
                last = str(e)[:120]
            raw = None
            if attempt < self.retries:
                log.warning("fetch_retry", symbol=symbol, attempt=attempt, reason=last)
                time.sleep(self.backoff_seconds * 2 ** (attempt - 1))
        if raw is None:
            raise RuntimeError(f"no data for {symbol} {interval} after {self.retries} attempts: {last}")

        if isinstance(raw.columns, pd.MultiIndex):       # yfinance multi-symbol shape
            raw.columns = raw.columns.get_level_values(0)
        raw = raw.rename(columns=str.lower)
        df = OHLCV(raw)
        df.to_parquet(path)
        return df
