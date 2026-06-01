"""Edge-decay assessment + persistent registry (status changes, active set, retirement)."""
from quant_desk.monitor.decay import assess_folds, monitor_universe
from quant_desk.monitor.registry import Registry
from quant_desk.strategies.opening_range_breakout import OpeningRangeBreakout


def _folds(rets):
    return [{"oos_return": r} for r in rets]


def test_assess_healthy_watch_retired():
    assert assess_folds(_folds([0.01, 0.012, 0.011, 0.013]))["status"] == "healthy"
    # still positive recently but clearly declining → watch
    assert assess_folds(_folds([0.05, 0.03, 0.02, 0.012]))["status"] == "watch"
    # recent gone negative → retired
    assert assess_folds(_folds([0.02, 0.005, -0.01, -0.02]))["status"] == "retired"
    # too few folds
    assert assess_folds(_folds([0.01, 0.02]))["status"] == "insufficient_data"


def test_registry_change_detection_and_active(tmp_path):
    p = str(tmp_path / "reg.json")
    reg = Registry(path=p)
    # first assessment: AAA healthy, BBB retired
    ch1 = reg.update("orb", [{"symbol": "AAA", "status": "healthy", "recent_mean": 0.01},
                             {"symbol": "BBB", "status": "retired", "recent_mean": -0.02}])
    assert ch1 == []                                   # no prior state → no changes
    assert reg.active("orb") == ["AAA"]                # BBB retired, excluded
    assert reg.is_retired("orb", "BBB")
    # AAA decays on the next run → a change event
    ch2 = reg.update("orb", [{"symbol": "AAA", "status": "retired", "recent_mean": -0.01}])
    assert ch2 == [{"symbol": "AAA", "from": "healthy", "to": "retired"}]
    assert reg.active("orb") == []
    # persistence round-trip
    reg.save()
    reg2 = Registry.load(p)
    assert reg2.is_retired("orb", "AAA") and reg2.is_retired("orb", "BBB")


def test_committee_verdict_gates_the_runner(tmp_path):
    p = str(tmp_path / "reg.json")
    reg = Registry(path=p)
    reg.set_verdict("orb", "SPY", "promote", "validated")
    reg.set_verdict("orb", "AAPL", "retire", "edge decayed")
    reg.set_verdict("orb", "TSLA", "reject", "fails crisis")
    reg.set_verdict("orb", "QQQ", "paper_watch", "marginal")
    assert reg.verdict("orb", "SPY") == "promote"
    assert not reg.is_blocked("orb", "SPY")           # promoted → tradeable
    assert not reg.is_blocked("orb", "QQQ")           # paper_watch → tradeable
    assert reg.is_blocked("orb", "AAPL")              # retired → blocked
    assert reg.is_blocked("orb", "TSLA")              # rejected → blocked
    reg.update("orb", [{"symbol": "IWM", "status": "retired", "recent_mean": -0.01}])
    assert reg.is_blocked("orb", "IWM")               # decay-retired also blocks
    reg.save()
    assert Registry.load(p).is_blocked("orb", "AAPL")  # persists


def test_monitor_universe_runs(multi_session):
    res = monitor_universe(["AAA", "BBB"], OpeningRangeBreakout,
                           {"or_minutes": [30], "target_r": [1.5, 2.0]},
                           data_fn=lambda s: multi_session, is_sessions=2, oos_sessions=2, recent_k=2)
    assert {r["symbol"] for r in res} == {"AAA", "BBB"}
    assert all("status" in r for r in res)
