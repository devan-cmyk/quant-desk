"""Monte-Carlo distribution behaves sanely on known inputs."""
from quant_desk.backtest.montecarlo import monte_carlo


def test_all_winners_high_profit_prob():
    mc = monte_carlo([100, 120, 90, 110, 105] * 4, starting_equity=100_000, n_sims=2000)
    assert mc["prob_profit"] == 1.0
    assert mc["prob_ruin"] == 0.0
    assert mc["return_p50"] > 0
    assert mc["return_p05"] <= mc["return_p50"] <= mc["return_p95"]


def test_all_losers_ruin():
    # losses big enough to breach the 20% ruin drawdown with 100k start
    mc = monte_carlo([-3000] * 20, starting_equity=100_000, n_sims=1000, ruin_drawdown=0.20)
    assert mc["prob_profit"] == 0.0
    assert mc["prob_ruin"] == 1.0
    assert mc["return_p50"] < 0


def test_too_few_trades():
    assert "error" in monte_carlo([10, -5], n_sims=100)
