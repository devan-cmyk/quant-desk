"""Stress scenarios produce valid, genuinely-adverse data; the lab reports survival."""
from quant_desk.config import RiskLimits
from quant_desk.stress import scenarios as sc
from quant_desk.stress.lab import stress_test
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout


def _valid_ohlcv(df):
    assert (df["high"] >= df[["open", "close", "low"]].max(axis=1) - 1e-9).all()
    assert (df["low"] <= df[["open", "close", "high"]].min(axis=1) + 1e-9).all()


def test_flash_crash_lowers_prices_and_stays_valid(two_sessions):
    out, slip = sc.flash_crash(two_sessions, pct=0.10)
    assert slip is None
    _valid_ohlcv(out)
    assert out["low"].min() < two_sessions["low"].min()        # a deeper low was injected


def test_gap_down_shifts_last_session(two_sessions):
    out, _ = sc.gap_down(two_sessions, pct=0.05)
    et = two_sessions.index.tz_convert("America/New_York")
    last = et.date == et.date.max()
    assert out.loc[last, "close"].mean() < two_sessions.loc[last, "close"].mean()
    _valid_ohlcv(out)


def test_liquidity_drought_only_bumps_slippage(two_sessions):
    out, slip = sc.liquidity_drought(two_sessions, slippage_bps=40)
    assert slip == 40
    assert (out["close"].values == two_sessions["close"].values).all()   # path unchanged


def test_stress_lab_reports_all_scenarios(two_sessions):
    res = stress_test(two_sessions, OpeningRangeBreakout,
                      limits=RiskLimits(starting_equity=100_000, risk_per_trade_pct=0.01,
                                        max_daily_loss_pct=0.05, max_position_pct=0.5))
    names = {r["scenario"] for r in res["results"]}
    assert names == set(sc.SCENARIOS)
    assert "survived_all" in res and "worst_drawdown" in res
    for r in res["results"]:
        assert "survived" in r and isinstance(r["survived"], bool)
