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


def test_decay_update_preserves_verdict_and_forward(tmp_path):
    # regression: the decay monitor (update) must NOT wipe committee verdict / forward recon,
    # because in the live loop it runs AFTER review + reconcile on the same pair.
    reg = Registry(path=str(tmp_path / "reg.json"))
    reg.set_verdict("orb", "SPY", "promote", "validated")
    reg.set_forward("orb", "SPY", "ok", "edge holds")
    reg.update("orb", [{"symbol": "SPY", "status": "healthy", "recent_mean": 0.01}])
    assert reg.verdict("orb", "SPY") == "promote"     # verdict survived the decay update
    assert reg.forward("orb", "SPY") == "ok"          # forward recon survived too
    assert reg.data["orb:SPY"]["status"] == "healthy" # and decay status was written


def test_validated_params_persist_and_survive_decay_update(tmp_path):
    p = str(tmp_path / "reg.json")
    reg = Registry(path=p)
    reg.set_verdict("orb", "SPY", "promote", "validated")
    reg.set_params("orb", "SPY", {"or_minutes": 30, "target_r": 2.0})
    # the decay monitor (update) must not clobber the validated params
    reg.update("orb", [{"symbol": "SPY", "status": "healthy", "recent_mean": 0.01}])
    reg.save()
    assert Registry.load(p).params("orb", "SPY") == {"or_minutes": 30, "target_r": 2.0}
    assert reg.params("orb", "MSFT") == {}            # unknown pair → empty (backtest uses defaults)


def test_probation_halves_size_until_forward_confirmed(tmp_path):
    reg = Registry(path=str(tmp_path / "reg.json"))
    reg.set_verdict("meanrev", "IWM", "promote", "validated")
    reg.set_allocation("meanrev", "IWM", 0.25, 1.4)        # allocator gave it risk 1.4×
    # freshly promoted, never reconciled → unproven → probation → half the allocated size
    assert not reg.is_confirmed("meanrev", "IWM")
    assert reg.effective_scale("meanrev", "IWM") == 0.7    # 1.4 × 0.5
    # still on probation while forward evidence is thin
    reg.set_forward("meanrev", "IWM", "probation", "only 4 forward trades")
    assert reg.effective_scale("meanrev", "IWM") == 0.7
    # forward edge CONFIRMED ('ok') → graduates to full allocated size
    reg.set_forward("meanrev", "IWM", "ok", "forward edge holds")
    assert reg.is_confirmed("meanrev", "IWM")
    assert reg.effective_scale("meanrev", "IWM") == 1.4
    # but if it later DRIFTS, is_blocked stops it entirely (not just sized down)
    reg.set_forward("meanrev", "IWM", "drift", "edge absent live")
    assert reg.is_blocked("meanrev", "IWM")


def test_monitor_universe_runs(multi_session):
    res = monitor_universe(["AAA", "BBB"], OpeningRangeBreakout,
                           {"or_minutes": [30], "target_r": [1.5, 2.0]},
                           data_fn=lambda s: multi_session, is_sessions=2, oos_sessions=2, recent_k=2)
    assert {r["symbol"] for r in res} == {"AAA", "BBB"}
    assert all("status" in r for r in res)
