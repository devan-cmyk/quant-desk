"""The public API is a stability contract for toolkit consumers — these pin it so an internal
refactor can't silently break `from quant_desk import ...`."""
import numpy as np
import pandas as pd

import quant_desk as qd


def test_version_and_all_exported():
    assert isinstance(qd.__version__, str) and qd.__version__.count(".") >= 1
    # every name promised in __all__ is actually importable from the top level
    for name in qd.__all__:
        assert hasattr(qd, name), f"public export missing: {name}"


def test_core_surface_present():
    for name in ["Strategy", "Signal", "REGISTRY", "run_backtest", "walk_forward", "evaluate",
                 "RiskEngine", "RiskLimits", "PaperBroker", "YFinanceProvider", "DataProvider",
                 "OHLCV", "PaperPortfolio", "live_tick", "assert_live_allowed"]:
        assert name in qd.__all__ and hasattr(qd, name)


def test_paper_only_default_via_public_api():
    # the safety posture is reachable + correct from the public surface
    assert qd.settings.trading_mode == "paper"
    import pytest
    with pytest.raises(qd.LiveTradingLocked):
        qd.assert_live_allowed("anything")


def test_backtest_composes_through_public_api_offline():
    # an external consumer wires provider→strategy→risk→backtest with only public names, no network
    idx = pd.date_range("2024-06-03 13:30", periods=120, freq="5min", tz="UTC")
    c = 100 + np.sin(np.arange(120) / 7) * 2
    df = qd.OHLCV(pd.DataFrame({"open": c, "high": c + 0.2, "low": c - 0.2, "close": c,
                                "volume": 1e6}, index=idx))
    res = qd.run_backtest(df, qd.MeanReversion(lookback=20), qd.RiskEngine())
    assert set(res) == {"equity", "trades", "metrics"}
    assert "sharpe" in res["metrics"]
