"""Cost-stress: re-deduct extra round-trip cost and ask whether the edge survives.
Fat edges shrug it off; thin high-frequency edges die. Wired as a committee HARD GATE."""
from quant_desk.council.cost import cost_stress, round_trip_cost
from quant_desk.council import committee


def _trades(pnls, entry=100.0, qty=10):
    return [{"entry": entry, "exit": entry + p / qty, "qty": qty, "pnl": p} for p in pnls]


def test_round_trip_cost_counts_both_sides():
    # 2 bps/side on entry+exit of $100×10 + $0.005/share ×2 sides
    c = round_trip_cost(100.0, 100.0, 10, slippage_bps=2.0, commission_per_share=0.005)
    assert abs(c - (2.0 / 1e4 * 10 * 200 + 0.005 * 10 * 2)) < 1e-9   # = 0.4 + 0.1 = 0.5


def test_fat_edge_survives_cost_doubling():
    # big per-trade pnl vs tiny cost → still positive under 2× costs
    cs = cost_stress(_trades([50, 60, -20, 55, -15]), multiplier=1.0,
                     slippage_bps=2.0, commission_per_share=0.005)
    assert cs["survives"] is True and cs["stressed_return"] > 0


def test_thin_high_frequency_edge_dies():
    # many trades, razor-thin net pnl → extra costs flip it negative
    cs = cost_stress(_trades([0.6, -0.5, 0.55, -0.5, 0.6, -0.5] * 8), multiplier=1.0,
                     slippage_bps=2.0, commission_per_share=0.005)
    assert cs["survives"] is False
    assert cs["stressed_pf"] is not None and cs["stressed_pf"] < 1.0


def test_empty_trades_survive_vacuously():
    cs = cost_stress([], multiplier=1.0)
    assert cs["survives"] is True and cs["n"] == 0


def test_cost_margin_closed_form():
    from quant_desk.council.cost import cost_margin, round_trip_cost
    tr = _trades([30, 30, 30, -10, -10, 30, 30, -10])     # base net = +120 (fat edge)
    total_rt = sum(round_trip_cost(t["entry"], t["exit"], t["qty"], 2.0, 0.005) for t in tr)
    m = cost_margin(tr, slippage_bps=2.0, commission_per_share=0.005)
    # margin = base_net / total_modeled_cost (closed-form, exact)
    assert abs(m["margin"] - round(120.0 / total_rt, 3)) < 1e-6
    assert m["margin"] > 1.0 and m["n"] == 8                       # fat edge clears the 2× gate
    assert m["cost_tolerance_x"] == round(1 + m["margin"], 2)


def test_thin_edge_has_margin_below_one_and_fails_gate():
    from quant_desk.council.cost import cost_margin, cost_stress
    # razor-thin: base net barely positive, many trades → low margin, fails 2× gate
    tr = _trades([0.4, -0.3, 0.4, -0.3, 0.4, -0.3] * 6)
    m = cost_margin(tr, slippage_bps=2.0, commission_per_share=0.005)
    assert m["margin"] is not None and m["margin"] < 1.0          # below the gate
    assert cost_stress(tr, multiplier=1.0, slippage_bps=2.0, commission_per_share=0.005)["survives"] is False


def test_negative_edge_has_nonpositive_margin():
    from quant_desk.council.cost import cost_margin
    tr = _trades([5, -25, 5, -25, 5, 5])                  # base net negative
    assert cost_margin(tr)["margin"] <= 0                 # already dead net of cost


def test_curve_is_monotonic_and_carries_margin():
    from quant_desk.council.cost import cost_curve
    cc = cost_curve(_trades([30, 30, -10, 30, -10, 30]), slippage_bps=2.0, commission_per_share=0.005)
    rets = [p["return"] for p in cc["points"]]
    assert rets == sorted(rets, reverse=True)             # more cost → lower return (monotonic)
    assert "margin" in cc and cc["cost_tolerance_x"] is not None


def test_output_is_json_serializable_native_types():
    # regression: numpy floats/bools from real backtest trades broke journaling (json.dumps)
    import json, numpy as np
    tr = [{"entry": np.float64(100.0), "exit": np.float64(100.5), "qty": np.int64(10),
           "pnl": np.float64(5.0)} for _ in range(6)]
    cs = cost_stress(tr, multiplier=1.0, slippage_bps=2.0, commission_per_share=0.005)
    json.dumps(cs)                                   # must not raise
    assert isinstance(cs["survives"], bool)          # native bool, not np.bool_


def _ev(cost, **over):
    base = {
        "walkforward": {"oos_return": 0.02, "sharpe": 1.5, "profit_factor": 1.6, "num_trades": 30, "n_folds": 5},
        "montecarlo": {"prob_profit": 0.7, "prob_ruin": 0.0, "maxdd_p95_worst": -0.05, "n_trades": 30},
        "stress": {"survived_all": True, "worst_drawdown": -0.03},
        "cost": cost,
        "decay": {"status": "healthy"},
    }
    base.update(over)
    return base


def test_cost_gate_hard_rejects_a_fragile_edge():
    # strong-looking strategy (would promote) but the edge dies under 2× costs → HARD reject
    d = committee.decide(_ev({"survives": False, "stressed_pf": 0.8, "stressed_return": -0.003}))
    assert d["decision"] == "reject" and "HARD COST GATE" in d["rationale"]


def test_cost_robust_edge_still_promotes():
    d = committee.decide(_ev({"survives": True, "stressed_pf": 1.2, "stressed_return": 0.004}))
    assert d["decision"] == "promote"


def test_missing_cost_is_back_compatible():
    # evidence without a 'cost' key (old records) must not be rejected by the new gate
    ev = _ev({}); del ev["cost"]
    assert committee.decide(ev)["decision"] == "promote"
