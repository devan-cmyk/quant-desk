"""quant-desk — a modular, paper-only-by-default quantitative trading research toolkit.

Spine: data-provider abstraction → pluggable strategies → realistic backtest → risk engine →
simulated paper broker, with a cost-aware validation gauntlet and live execution locked behind a
hard triple-lock. Nothing here can place a live order by default.

This module is the STABLE public API — import from `quant_desk`, not from internal submodules,
which may move. Example::

    from quant_desk import YFinanceProvider, OpeningRangeBreakout, RiskEngine, run_backtest
    df = YFinanceProvider().bars("SPY", interval="5m", lookback_days=30)
    res = run_backtest(df, OpeningRangeBreakout(), RiskEngine())
    print(res["metrics"]["sharpe"], len(res["trades"]))
"""
from __future__ import annotations

__version__ = "0.1.0"

# ── strategy framework ──────────────────────────────────────────────────────
from .strategies.base import Signal, Strategy
from .strategies import (REGISTRY, OpeningRangeBreakout, VWAPPullback, MeanReversion,
                         DailyMeanReversion, GapFade)
# ── data ────────────────────────────────────────────────────────────────────
from .data.provider import DataProvider, OHLCV
from .data.yfinance_provider import YFinanceProvider
# ── backtest / validation ───────────────────────────────────────────────────
from .backtest.engine import run_backtest
from .backtest.walkforward import walk_forward
from .backtest.metrics import compute_metrics
from .council.evaluate import evaluate            # the cost-aware committee gauntlet
# ── risk / execution ────────────────────────────────────────────────────────
from .risk.engine import RiskEngine, RiskDecision
from .config import RiskLimits, settings
from .execution.paper_broker import PaperBroker, Fill
from .execution.live_guard import assert_live_allowed, LiveTradingLocked
# ── live (real-time decision loop) ──────────────────────────────────────────
from .live.portfolio import PaperPortfolio
from .live.realtime import live_tick

__all__ = [
    "__version__",
    # framework
    "Strategy", "Signal", "REGISTRY",
    "OpeningRangeBreakout", "VWAPPullback", "MeanReversion", "DailyMeanReversion", "GapFade",
    # data
    "DataProvider", "OHLCV", "YFinanceProvider",
    # backtest / validation
    "run_backtest", "walk_forward", "compute_metrics", "evaluate",
    # risk / execution
    "RiskEngine", "RiskDecision", "RiskLimits", "settings",
    "PaperBroker", "Fill", "assert_live_allowed", "LiveTradingLocked",
    # live
    "PaperPortfolio", "live_tick",
]
