"""Risk engine: sizing, exposure cap, daily-loss halt, cooldown, kill switch."""
from quant_desk.config import RiskLimits
from quant_desk.risk.engine import RiskEngine


def _engine():
    lim = RiskLimits(starting_equity=100_000, risk_per_trade_pct=0.01, max_daily_loss_pct=0.02,
                     max_position_pct=0.20, max_consecutive_losses=3)
    return RiskEngine(limits=lim, equity=100_000)


def test_position_sizing_uses_per_trade_risk():
    r = _engine()
    # risk budget = 1% * 100k = 1000; per-share risk = 10.00 -> 100 shares
    # (notional 100*100=10k < 20% exposure cap of 20k, so risk-based sizing binds)
    dec = r.evaluate(entry=100.0, stop=90.0)
    assert dec.allowed and dec.qty == 100


def test_exposure_cap_limits_size():
    r = _engine()
    # tiny stop would size huge; exposure cap = 20% * 100k / 100 = 200 shares
    dec = r.evaluate(entry=100.0, stop=99.99)
    assert dec.qty == 200


def test_daily_loss_halt():
    r = _engine()
    r.on_trade_closed(-2500)          # > 2% of 100k -> halt
    assert r.halted_today
    assert not r.evaluate(entry=100, stop=99).allowed


def test_consecutive_loss_cooldown():
    r = _engine()
    for _ in range(3):
        r.on_trade_closed(-100)
    assert not r.evaluate(entry=100, stop=99).allowed   # 3 losses -> cooldown
    r.on_trade_closed(+50)                                # a win resets the streak
    assert r.evaluate(entry=100, stop=99).allowed


def test_kill_switch():
    r = _engine()
    r.trip_kill_switch("test")
    assert not r.evaluate(entry=100, stop=99).allowed
