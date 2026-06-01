"""Forward/backtest reconciliation — the feedback loop that keeps the committee honest.

A strategy can pass walk-forward + Monte-Carlo + stress and still be overfit; the only
verdict that can't be gamed is what it actually does in forward paper trading. This module
compares each promoted pair's REALIZED forward expectancy against the metrics the committee
promoted it on, and flags drift when the live edge fails to show up. The gate then blocks a
drifted pair just as it blocks a rejected or decayed one (AQROS Section 12: live truth > backtest).
"""
from .reconcile import reconcile_symbol, reconcile_account

__all__ = ["reconcile_symbol", "reconcile_account"]
