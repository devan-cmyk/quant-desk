"""Gate alerting: diff transitions (pure), feed persistence, idempotent snapshotting."""
from quant_desk.alerts.gate_alerts import gate_state, diff_gate, run_alerts, AlertFeed
from quant_desk.monitor.registry import Registry


def test_diff_flags_newly_blocked_high_severity():
    prev = {"orb:SPY": {"blocked": False, "verdict": "promote", "reason": ""}}
    curr = {"orb:SPY": {"blocked": True, "verdict": "promote", "reason": "forward drift"}}
    ev = diff_gate(prev, curr)
    assert len(ev) == 1 and ev[0]["kind"] == "blocked" and ev[0]["severity"] == "high"
    assert "drift" in ev[0]["message"]


def test_diff_flags_cleared_and_new_approved():
    prev = {"orb:SPY": {"blocked": True, "verdict": "retire", "reason": "x"}}
    curr = {"orb:SPY": {"blocked": False, "verdict": "promote", "reason": ""},
            "vwap:QQQ": {"blocked": False, "verdict": "promote", "reason": ""},      # brand new
            "orb:AAPL": {"blocked": True, "verdict": "reject", "reason": "overfit"}}  # new+blocked: silent
    ev = {e["pair"]: e for e in diff_gate(prev, curr)}
    assert ev["orb:SPY"]["kind"] == "cleared"
    assert ev["vwap:QQQ"]["kind"] == "approved"
    assert "orb:AAPL" not in ev                       # a new pair that's already blocked isn't urgent


def test_no_change_no_alerts():
    s = {"orb:SPY": {"blocked": False, "verdict": "promote", "reason": ""}}
    assert diff_gate(s, s) == []


def test_high_severity_sorted_first():
    prev = {"a:X": {"blocked": True, "verdict": "retire", "reason": ""},
            "b:Y": {"blocked": False, "verdict": "promote", "reason": ""}}
    curr = {"a:X": {"blocked": False, "verdict": "promote", "reason": ""},   # cleared (info)
            "b:Y": {"blocked": True, "verdict": "promote", "reason": "drift"}}  # blocked (high)
    ev = diff_gate(prev, curr)
    assert ev[0]["severity"] == "high"


def test_run_alerts_is_idempotent_and_records(tmp_path, monkeypatch):
    monkeypatch.setenv("QD_ALERT_MACOS", "0")                  # never pop a desktop notification
    monkeypatch.setenv("QD_ALERTS", str(tmp_path / "alerts.json"))
    snap = str(tmp_path / "snap.json")
    reg = Registry(path=str(tmp_path / "reg.json"))
    reg.set_verdict("orb", "QQQ", "promote", "ok")            # one approved, tradeable pair

    first = run_alerts(reg, snapshot_path=snap, notify=False)
    assert len(first) == 1 and first[0]["kind"] == "approved"
    assert len(AlertFeed().recent()) == 1
    # nothing changed → re-running raises no new alerts (snapshot advanced)
    assert run_alerts(reg, snapshot_path=snap, notify=False) == []

    reg.set_forward("orb", "QQQ", "drift", "edge absent live")  # now it blocks
    ev = run_alerts(reg, snapshot_path=snap, notify=False)
    assert len(ev) == 1 and ev[0]["kind"] == "blocked" and ev[0]["severity"] == "high"


def test_gate_state_reason_mapping(tmp_path):
    reg = Registry(path=str(tmp_path / "reg.json"))
    reg.set_verdict("orb", "NVDA", "reject", "Sharpe 4.0 on 21 trades — overfit")
    st = gate_state(reg)["orb:NVDA"]
    assert st["blocked"] is True and "overfit" in st["reason"]
