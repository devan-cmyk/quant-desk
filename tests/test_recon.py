"""Forward/backtest reconciliation — the live-truth feedback loop. Scale-free comparison
(profit factor + expectancy sign); drift feeds the same gate as committee reject/decay."""
from quant_desk.recon.reconcile import reconcile_symbol, reconcile_account
from quant_desk.monitor.registry import Registry


def test_insufficient_data_never_flags():
    r = reconcile_symbol([10, -5, 8], expected_pf=2.0, min_trades=8)
    assert r["status"] == "insufficient_data"
    assert r["n"] == 3


def test_edge_holds_is_ok():
    # promoted PF 2.0; forward delivers ~2.0 and positive expectancy over enough trades
    pnls = [20, 20, 20, 20, 20, -10, -10, -10]      # PF = 100/30 ≈ 3.33, exp +11.25
    r = reconcile_symbol(pnls, expected_pf=2.0, min_trades=8)
    assert r["status"] == "ok"
    assert r["realized_pf"] > 1.0 and r["realized_expectancy"] > 0


def test_negative_expectancy_is_drift():
    # promoted with an edge but the live account is net-negative → drift
    pnls = [5, 5, 5, -20, -20, 5, 5, -10]           # sum = -25 < 0
    r = reconcile_symbol(pnls, expected_pf=1.8, min_trades=8)
    assert r["status"] == "drift"
    assert "edge absent" in r["detail"]


def test_pf_far_below_promoted_is_drift():
    # positive expectancy but PF collapsed well under 60% of the promoted 3.0
    pnls = [12, 12, 12, 12, -10, -10, -10, -15]     # wins 48 / losses 45 → PF ~1.07, exp +0.38
    r = reconcile_symbol(pnls, expected_pf=3.0, min_trades=8, drift_fraction=0.6)
    assert r["status"] == "drift"
    assert r["realized_pf"] < 3.0 * 0.6


def test_no_losses_outperforms_not_drift():
    r = reconcile_symbol([5, 5, 5, 5, 5, 5, 5, 5], expected_pf=2.0, min_trades=8)
    assert r["realized_pf"] is None          # no losing trades → undefined PF
    assert r["status"] == "ok"


def test_drift_feeds_the_gate(tmp_path):
    reg = Registry(path=str(tmp_path / "reg.json"))
    reg.set_verdict("orb", "SPY", "promote", "validated")
    assert not reg.is_blocked("orb", "SPY")          # committee-approved, no forward data yet
    reg.set_forward("orb", "SPY", "drift", "edge absent live")
    assert reg.forward("orb", "SPY") == "drift"
    assert reg.is_blocked("orb", "SPY")              # drift blocks even a promoted pair
    reg.set_forward("orb", "SPY", "ok", "edge holds")
    assert not reg.is_blocked("orb", "SPY")          # recovered → tradeable again


class _PF:
    def __init__(self, blotter): self.blotter = blotter


class _JR:
    def __init__(self, rows): self._rows = rows
    def recent(self, n, kind=None):
        return [r for r in self._rows if not kind or r.get("kind") == kind][:n]


def test_reconcile_separates_strategies_on_same_symbol():
    # SPY traded by BOTH strategies in one account; reconcile must attribute each strategy's
    # trades to itself (orb edge holds, meanrev drifts) — not blend them.
    blotter = [{"symbol": "SPY", "strategy": "orb", "pnl": p} for p in [20,20,20,20,-8,-8,-8,-8]] \
        + [{"symbol": "SPY", "strategy": "meanrev", "pnl": p} for p in [5,5,-25,-25,5,5,-12,5]]
    jr = _JR([])
    orb = reconcile_account(_PF(blotter), jr, "orb", ["SPY"])[0]
    mr = reconcile_account(_PF(blotter), jr, "meanrev", ["SPY"])[0]
    assert orb["status"] == "ok" and orb["realized_expectancy"] > 0      # orb's own trades
    assert mr["status"] == "drift" and mr["realized_expectancy"] < 0     # meanrev's own trades


def test_reconcile_account_pulls_expected_from_journal():
    blotter = [{"symbol": "SPY", "pnl": p} for p in [5, 5, 5, -20, -20, 5, 5, -10]] \
        + [{"symbol": "QQQ", "pnl": 10} for _ in range(8)]
    jr = _JR([{"kind": "council_decision", "strategy": "orb", "symbols": "SPY",
               "payload": {"evidence": {"walkforward": {"profit_factor": 1.8}}}}])
    out = reconcile_account(_PF(blotter), jr, "orb", ["SPY", "QQQ"])
    by = {r["symbol"]: r for r in out}
    assert by["SPY"]["status"] == "drift" and by["SPY"]["expected_pf"] == 1.8
    assert by["QQQ"]["status"] == "ok" and by["QQQ"]["expected_pf"] is None  # no baseline, all wins
