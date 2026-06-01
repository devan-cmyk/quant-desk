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


def test_sub_threshold_profit_factor_cannot_be_promoted():
    # the meanrev:NVDA case: positive OOS but PF 1.12 < 1.3 → Quant says paper_watch.
    # Risk-clean evidence used to let RiskOfficer + Contrarian outvote to 'promote'; the
    # edge-quality ceiling now caps it at paper_watch.
    d = committee.decide(_ev(walkforward={"oos_return": 0.002, "sharpe": 0.7,
                                          "profit_factor": 1.12, "num_trades": 42}))
    assert d["decision"] == "paper_watch"
    assert "edge quality" in d["rationale"]


def test_losing_oos_is_capped_to_reject_not_traded():
    # the meanrev:AAPL case: negative OOS (PF 0.39) → Quant rejects. Even with clean risk and no
    # overfit tells, it must NOT land on paper_watch (which the runner trades) — cap to reject.
    d = committee.decide(_ev(walkforward={"oos_return": -0.007, "sharpe": -0.3,
                                          "profit_factor": 0.39, "num_trades": 30}))
    assert d["decision"] == "reject"


def test_genuine_edge_still_promotes():
    # a real edge (PF 1.5, positive OOS → Quant promotes) is untouched by the ceiling
    d = committee.decide(_ev(walkforward={"oos_return": 0.0027, "profit_factor": 1.5, "num_trades": 29}))
    assert d["decision"] == "promote"
