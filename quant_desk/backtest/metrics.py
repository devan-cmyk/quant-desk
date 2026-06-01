"""Performance metrics from an equity curve + trade list. Institutional core set; more
(Ulcer, VaR/CVaR, recovery factor) bolt on the same way."""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def compute_metrics(equity: pd.Series, trades: list[dict]) -> dict:
    out: dict = {"num_trades": len(trades)}
    if len(equity) < 2:
        return {**out, "note": "insufficient data"}

    out["start_equity"] = float(equity.iloc[0])
    out["end_equity"] = float(equity.iloc[-1])
    out["total_return"] = float(equity.iloc[-1] / equity.iloc[0] - 1)

    daily = equity.resample("1D").last().dropna()
    rets = daily.pct_change().dropna()
    if len(rets) > 1 and rets.std() > 0:
        out["sharpe"] = float(rets.mean() / rets.std() * np.sqrt(TRADING_DAYS))
        downside = rets[rets < 0].std()
        out["sortino"] = float(rets.mean() / downside * np.sqrt(TRADING_DAYS)) if downside and downside > 0 else None
    else:
        out["sharpe"] = out["sortino"] = None

    dd = equity / equity.cummax() - 1.0
    out["max_drawdown"] = float(dd.min())

    span_seconds = (equity.index[-1] - equity.index[0]).total_seconds()
    years = span_seconds / (365.25 * 86400)
    # annualizing a sub-few-week window is meaningless (and explodes numerically) — skip it
    if years >= 0.05 and out["total_return"] > -1:
        out["cagr"] = float((1 + out["total_return"]) ** (1 / years) - 1)
        out["calmar"] = float(out["cagr"] / abs(out["max_drawdown"])) if out["max_drawdown"] < 0 else None
    else:
        out["cagr"] = out["calmar"] = None

    if trades:
        pnls = np.array([t["pnl"] for t in trades], float)
        wins, losses = pnls[pnls > 0], pnls[pnls < 0]
        out["win_rate"] = float(len(wins) / len(pnls))
        out["expectancy"] = float(pnls.mean())
        out["profit_factor"] = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None
        out["avg_win"] = float(wins.mean()) if len(wins) else 0.0
        out["avg_loss"] = float(losses.mean()) if len(losses) else 0.0
    return out
