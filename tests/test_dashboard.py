"""Dashboard API assembles the account view from the persisted paper state."""
import json

from quant_desk.dashboard.app import account


def test_account_assembles_view(tmp_path, monkeypatch):
    state = {
        "start_equity": 100_000, "cash": 100_250,
        "positions": {"SPY": {"side": "long", "qty": 10, "entry": 500, "stop": 495, "target": 510}},
        "blotter": [
            {"symbol": "SPY", "side": "long", "qty": 10, "entry": 500, "exit": 505, "reason": "target",
             "pnl": 50.0, "entry_ts": "2024-06-03T13:30:00", "exit_ts": "2024-06-03T15:00:00"},
            {"symbol": "MSFT", "side": "long", "qty": 5, "entry": 400, "exit": 398, "reason": "stop",
             "pnl": -10.0, "entry_ts": "2024-06-04T13:30:00", "exit_ts": "2024-06-04T14:00:00"},
            {"symbol": "SPY", "side": "long", "qty": 8, "entry": 502, "exit": 506, "reason": "eod",
             "pnl": 32.0, "entry_ts": "2024-06-05T13:30:00", "exit_ts": "2024-06-05T15:55:00"},
        ],
        "equity_curve": [["2024-06-03T15:00:00", 100050], ["2024-06-05T15:55:00", 100250]],
        "last_ts": "2024-06-05T15:55:00",
    }
    p = tmp_path / "paper_state.json"
    json.dump(state, open(p, "w"))
    monkeypatch.setenv("QD_PAPER_STATE", str(p))

    a = account()
    assert a["live_locked"] is True              # paper-only default
    assert a["n_trades"] == 3
    assert a["equity"] == 100250
    assert set(a["by_symbol"]) == {"SPY", "MSFT"}
    assert a["by_symbol"]["SPY"]["trades"] == 2 and a["by_symbol"]["SPY"]["wins"] == 2
    assert a["monte_carlo"]["n_trades"] == 3     # >=3 trades → MC runs
    assert len(a["open_positions"]) == 1


def test_gate_surfaces_the_three_kill_paths(tmp_path, monkeypatch):
    from quant_desk.monitor.registry import Registry
    from quant_desk.dashboard.app import gate
    p = tmp_path / "registry.json"
    monkeypatch.setenv("QD_REGISTRY", str(p))
    reg = Registry.load()
    reg.set_verdict("orb", "SPY", "promote", "validated")              # committee-clear
    reg.set_verdict("orb", "QQQ", "promote", "validated")
    reg.set_forward("orb", "QQQ", "drift", "edge absent live")          # but forward-drifted
    reg.set_verdict("orb", "AAPL", "promote", "validated")
    reg.update("orb", [{"symbol": "AAPL", "status": "retired", "recent_mean": -0.01}])  # decay-retired
    reg.save()

    g = gate()
    by = {r["symbol"]: r for r in g["pairs"]}
    assert by["SPY"]["blocked"] is False and "SPY" in g["tradeable"]
    assert by["QQQ"]["blocked"] is True and by["QQQ"]["forward"] == "drift"   # drift blocks
    assert by["AAPL"]["blocked"] is True and by["AAPL"]["decay"] == "retired" # decay blocks
    assert g["n_blocked"] == 2 and g["tradeable"] == ["SPY"]
