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
