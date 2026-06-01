"""The decision committee: hard risk gates + reasoned promote/paper/reject/retire."""
from quant_desk.council import committee


def _ev(**over):
    base = {
        "walkforward": {"oos_return": 0.02, "sharpe": 1.5, "profit_factor": 1.6, "num_trades": 30, "n_folds": 5},
        "montecarlo": {"prob_profit": 0.7, "prob_ruin": 0.0, "return_p50": 0.02, "maxdd_p95_worst": -0.05, "n_trades": 30},
        "stress": {"survived_all": True, "worst_drawdown": -0.03},
        "decay": {"status": "healthy", "recent_mean": 0.005, "trend": 0.0001},
    }
    for k, v in over.items():
        base[k] = {**base[k], **v}
    return base


def test_strong_strategy_promoted():
    d = committee.decide(_ev())
    assert d["decision"] == "promote"
    assert d["confidence"] > 0.5


def test_stress_failure_is_hard_reject():
    d = committee.decide(_ev(stress={"survived_all": False, "worst_drawdown": -0.4}))
    assert d["decision"] == "reject" and "HARD RISK GATE" in d["rationale"]


def test_high_ruin_is_hard_reject():
    d = committee.decide(_ev(montecarlo={"prob_ruin": 0.10}))
    assert d["decision"] == "reject"


def test_decayed_edge_retired():
    d = committee.decide(_ev(decay={"status": "retired"}))
    assert d["decision"] == "retire"


def test_thin_sample_paper_watch():
    d = committee.decide(_ev(walkforward={"num_trades": 10, "profit_factor": 1.1}))
    assert d["decision"] == "paper_watch"


def test_negative_oos_not_promoted():
    d = committee.decide(_ev(walkforward={"oos_return": -0.01, "profit_factor": 0.8}))
    assert d["decision"] in ("reject", "paper_watch")
    assert d["decision"] != "promote"
