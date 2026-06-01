"""Reconcile realized forward paper trades against the metrics the committee promoted.

The comparison is on SCALE-FREE terms — profit factor and the sign of expectancy — because
forward sizing differs from the backtest's, so dollar PnL isn't directly comparable. Profit
factor (gross win / gross loss) and "is the edge still positive?" are the honest comparables.

Drift is the institutional kill-signal: promoted with an edge, delivering none live.
"""
from __future__ import annotations

# how far below the promoted profit factor the realized one may fall before we call it drift
DRIFT_FRACTION = 0.6
# don't judge a pair until it has at least this many forward trades — small samples are noise
MIN_FORWARD_TRADES = 8


def _profit_factor(pnls: list[float]) -> float | None:
    wins = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    if losses == 0:
        return None            # no losing trades — undefined (treat as outperforming)
    return round(wins / losses, 3)


def reconcile_symbol(forward_pnls: list[float], expected_pf: float | None, *,
                     min_trades: int = MIN_FORWARD_TRADES,
                     drift_fraction: float = DRIFT_FRACTION) -> dict:
    """Classify one pair: ok | drift | insufficient_data, with the evidence behind it.

    forward_pnls : realized PnL of every closed forward trade for this pair (the blotter).
    expected_pf  : the profit factor the committee promoted on (None ⇒ no baseline to beat).
    """
    n = len(forward_pnls)
    realized_pf = _profit_factor(forward_pnls)
    realized_exp = round(sum(forward_pnls) / n, 2) if n else 0.0
    base = {"n": n, "realized_pf": realized_pf, "realized_expectancy": realized_exp,
            "expected_pf": expected_pf}

    if n < min_trades:
        return {**base, "status": "insufficient_data",
                "detail": f"only {n} forward trades (need {min_trades})"}

    # promoted with an edge but the live account is net-negative → the edge didn't show up
    if realized_exp <= 0:
        return {**base, "status": "drift",
                "detail": f"forward expectancy {realized_exp} ≤ 0 over {n} trades — edge absent live"}

    if expected_pf and expected_pf > 1.0:
        floor = max(1.0, round(expected_pf * drift_fraction, 3))
        # realized_pf is None only when there are no losses at all → outperforming, not drift
        if realized_pf is not None and realized_pf < floor:
            return {**base, "status": "drift",
                    "detail": f"forward PF {realized_pf} < {floor} ({int(drift_fraction*100)}% of "
                              f"promoted {expected_pf}) over {n} trades"}

    return {**base, "status": "ok",
            "detail": f"forward edge holds (PF {realized_pf}, exp {realized_exp}, n={n})"}


def _expected_pf_from_journal(journal, strategy: str, symbol: str) -> float | None:
    """Most recent committee decision's promoted profit factor for this pair, or None."""
    for row in journal.recent(500, kind="council_decision"):
        if row.get("strategy") == strategy and symbol in (row.get("symbols") or "").split(","):
            wf = (row.get("payload") or {}).get("evidence", {}).get("walkforward", {})
            return wf.get("profit_factor")
    return None


def reconcile_account(portfolio, journal, strategy: str, symbols: list[str], **kw) -> list[dict]:
    """Reconcile each symbol's forward blotter against its promoted baseline. Pure read —
    callers decide what to do with the verdicts (flag the registry, journal them, print)."""
    out = []
    for sym in symbols:
        # only THIS strategy's trades on the symbol (legacy untagged trades were all 'orb')
        pnls = [t["pnl"] for t in portfolio.blotter
                if t.get("symbol") == sym and (t.get("strategy") or "orb") == strategy]
        exp_pf = _expected_pf_from_journal(journal, strategy, sym)
        r = reconcile_symbol(pnls, exp_pf, **kw)
        out.append({"symbol": sym, "strategy": strategy, **r})
    return out
