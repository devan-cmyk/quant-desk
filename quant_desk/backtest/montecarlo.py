"""Monte-Carlo robustness on a trade-PnL sequence. A single backtest gives ONE path; its
Sharpe/return can be luck. We resample the trade outcomes thousands of times to get the
DISTRIBUTION of what could have happened — return percentiles, drawdown percentiles,
P(profit), and risk-of-ruin. This is how you tell a real edge from a lucky sequence.

  method='bootstrap' — sample trades WITH replacement (tests magnitude/luck of outcomes)
  method='shuffle'   — permute trade ORDER (tests path/sequence dependence)
"""
from __future__ import annotations

import numpy as np


def monte_carlo(trade_pnls, starting_equity: float = 100_000.0, *, n_sims: int = 5000,
                method: str = "bootstrap", ruin_drawdown: float = 0.20, seed: int = 7) -> dict:
    pnls = np.asarray([float(x) for x in trade_pnls], dtype=float)
    n = len(pnls)
    if n < 3:
        return {"error": "need >= 3 trades", "n_trades": n}
    rng = np.random.default_rng(seed)

    finals, maxdds, sharpes = np.empty(n_sims), np.empty(n_sims), np.empty(n_sims)
    ruined = 0
    for i in range(n_sims):
        sample = (rng.choice(pnls, size=n, replace=True) if method == "bootstrap"
                  else rng.permutation(pnls))
        curve = starting_equity + np.concatenate([[0.0], np.cumsum(sample)])
        finals[i] = curve[-1] / starting_equity - 1.0
        dd = (curve / np.maximum.accumulate(curve) - 1.0).min()
        maxdds[i] = dd
        sharpes[i] = sample.mean() / sample.std() if sample.std() > 0 else 0.0
        if dd <= -ruin_drawdown:
            ruined += 1

    def pct(a, p):
        return float(np.percentile(a, p))

    return {
        "n_trades": n, "n_sims": n_sims, "method": method, "ruin_drawdown": ruin_drawdown,
        "return_p05": pct(finals, 5), "return_p50": pct(finals, 50), "return_p95": pct(finals, 95),
        "maxdd_p50": pct(maxdds, 50), "maxdd_p95_worst": pct(maxdds, 5),   # 5th pct = a bad-case DD
        "prob_profit": float((finals > 0).mean()),
        "prob_ruin": float(ruined / n_sims),
        "trade_sharpe_median": pct(sharpes, 50),
        "expectancy": float(pnls.mean()),
    }
