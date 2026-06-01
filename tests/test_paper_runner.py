"""Forward paper runner: processes bars, trades, persists, and is incremental (last_ts)."""
from quant_desk.config import RiskLimits
from quant_desk.live.paper_runner import run_forward, run_forward_multi
from quant_desk.live.portfolio import PaperPortfolio
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout


def _limits():
    return RiskLimits(starting_equity=100_000, risk_per_trade_pct=0.01, max_daily_loss_pct=0.05,
                      max_position_pct=0.5)


def test_paper_run_trades_and_persists(two_sessions, tmp_path):
    pf = PaperPortfolio(start_equity=100_000, cash=100_000)
    res = run_forward(["AAA"], OpeningRangeBreakout, data_fn=lambda s: two_sessions,
                      portfolio=pf, limits=_limits(), max_bars=None)
    assert res["bars_processed"] == len(two_sessions)
    assert res["blotter_n"] == 2                 # one ORB trade per session, both flattened
    assert pf.last_ts is not None

    # save/load roundtrip keeps the account intact
    p = tmp_path / "state.json"
    pf.save(str(p))
    pf2 = PaperPortfolio.load(str(p))
    assert pf2.cash == pf.cash and pf2.blotter == pf.blotter and pf2.last_ts == pf.last_ts


def test_paper_run_uses_per_symbol_params(two_sessions):
    pf = PaperPortfolio(start_equity=100_000, cash=100_000)
    res = run_forward(["AAA"], OpeningRangeBreakout, data_fn=lambda s: two_sessions,
                      portfolio=pf, limits=_limits(),
                      params_by_symbol={"AAA": {"or_minutes": 30, "target_r": 1.0}})
    assert res["bars_processed"] == len(two_sessions)
    assert res["blotter_n"] >= 1                  # runs + trades with the supplied params


def test_multi_strategy_share_one_account_and_are_tagged(two_sessions):
    # two mandates (distinct strategy names) on the same symbol in ONE account: each holds its
    # own position, every trade is tagged with its strategy, attribution stays separable.
    pf = PaperPortfolio(start_equity=100_000, cash=100_000)
    mandates = [
        {"name": "orb", "cls": OpeningRangeBreakout, "symbols": ["AAA"], "params": {}},
        {"name": "orb2", "cls": OpeningRangeBreakout, "symbols": ["AAA"], "params": {}},
    ]
    res = run_forward_multi(mandates, data_fn=lambda s: two_sessions, portfolio=pf, limits=_limits())
    tags = {t["strategy"] for t in pf.blotter}
    assert tags == {"orb", "orb2"}                          # both strategies traded, tagged
    assert res["blotter_n"] == 4                            # 2 sessions × 2 strategies
    # position keys are composite so the two never collide on the symbol
    assert all(":" in k for k in pf.positions) or not pf.positions


def test_legacy_single_strategy_blotter_untagged_is_back_compatible(two_sessions):
    # the run_forward wrapper (no name) keeps the old bare-symbol keying + empty tag
    pf = PaperPortfolio(start_equity=100_000, cash=100_000)
    run_forward(["AAA"], OpeningRangeBreakout, data_fn=lambda s: two_sessions,
                portfolio=pf, limits=_limits())
    assert all(t["strategy"] == "" for t in pf.blotter)     # untagged, as before


def test_swing_position_persists_across_runs_and_caps_at_max_hold():
    # a swing strategy (intraday=False) must hold its position ACROSS incremental runs and only
    # exit after max_hold_bars — not get EOD-flattened like an intraday strategy.
    import numpy as np, pandas as pd
    from quant_desk.strategies.base import Strategy, Signal

    class _SwingOnce(Strategy):
        name = "sw"; intraday = False
        def __init__(self, max_hold_bars=4): self.max_hold_bars = max_hold_bars
        def compute_signal(self, w):
            # fire only on the very first bar of history (stateless) so it never re-enters later
            if len(w) > 1: return Signal()
            return Signal("long", stop=1.0, target=1e9, strength=1.0)   # stop/target never hit

    idx = pd.date_range("2024-01-02", periods=8, freq="B", tz="UTC")
    c = np.linspace(100, 100.7, 8)
    df = pd.DataFrame({"open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": 1e6}, index=idx)
    mandates = [{"name": "sw", "cls": _SwingOnce, "symbols": ["AAA"], "params": {}}]
    pf = PaperPortfolio(start_equity=100_000, cash=100_000)

    # run 1: only the first 3 bars exist → enters and is STILL HOLDING (not flattened)
    r1 = run_forward_multi(mandates, data_fn=lambda s: df.iloc[:3], portfolio=pf, limits=_limits())
    assert len(pf.positions) == 1 and r1["blotter_n"] == 0      # held across the run, no exit

    # run 2: the rest of the bars arrive → exits at max_hold_bars (4 bars after entry)
    r2 = run_forward_multi(mandates, data_fn=lambda s: df, portfolio=pf, limits=_limits())
    assert len(pf.positions) == 0 and pf.blotter[-1]["reason"] == "max_hold"


def test_paper_run_is_incremental(two_sessions):
    pf = PaperPortfolio(start_equity=100_000, cash=100_000)
    run_forward(["AAA"], OpeningRangeBreakout, data_fn=lambda s: two_sessions,
                portfolio=pf, limits=_limits())
    # second run over the same data processes no new bars (last_ts advanced)
    res2 = run_forward(["AAA"], OpeningRangeBreakout, data_fn=lambda s: two_sessions,
                       portfolio=pf, limits=_limits())
    assert res2["bars_processed"] == 0
