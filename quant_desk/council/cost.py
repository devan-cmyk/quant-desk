"""Cost-stress: does the validated edge survive HIGHER trading costs than modeled?

The backtest already deducts slippage + commission, so OOS pnl is net. But a thin, high-
frequency edge (small per-trade margin × many trades) flips negative under any cost mis-
estimate. This re-deducts an extra `multiplier`× the modeled round-trip cost from every OOS
trade and asks whether the edge is still positive — a margin-of-safety check scaled by exactly
what makes an edge fragile: how much it trades and how thin its per-trade margin is.
"""
from __future__ import annotations

from ..config import settings


def round_trip_cost(entry: float, exit_: float, qty: int,
                    slippage_bps: float, commission_per_share: float) -> float:
    """The modeled round-trip cost of a trade: slippage on both fills + commission both sides."""
    slip = slippage_bps / 1e4 * qty * (abs(entry) + abs(exit_))     # per-side slippage, entry+exit
    comm = commission_per_share * qty * 2
    return slip + comm


def cost_stress(trades: list[dict], *, multiplier: float = 1.0,
                slippage_bps: float | None = None, commission_per_share: float | None = None,
                starting_equity: float = 100_000.0) -> dict:
    """Re-deduct `multiplier`× the modeled round-trip cost from each trade (multiplier=1.0 ⇒
    total 2× costs) and recompute the edge. Returns stressed return/profit-factor and whether
    the edge survives. Trades need entry/exit/qty/pnl (fields the backtest already records)."""
    sb = settings.risk.slippage_bps if slippage_bps is None else slippage_bps
    cps = settings.risk.commission_per_share if commission_per_share is None else commission_per_share
    if not trades:
        return {"stressed_return": 0.0, "stressed_pf": None, "survives": True,
                "extra_cost": 0.0, "n": 0}
    total = gross_w = gross_l = extra = 0.0
    for t in trades:
        rt = round_trip_cost(t.get("entry", 0.0), t.get("exit", t.get("entry", 0.0)),
                             t.get("qty", 0), sb, cps)
        extra += multiplier * rt
        spnl = t["pnl"] - multiplier * rt
        total += spnl
        if spnl > 0:
            gross_w += spnl
        else:
            gross_l += -spnl
    # cast to native Python types — evidence is journaled as JSON (numpy types aren't serializable)
    pf = round(float(gross_w / gross_l), 3) if gross_l > 0 else None
    return {"stressed_return": round(float(total) / starting_equity, 4), "stressed_pf": pf,
            "survives": bool(total > 0), "extra_cost": round(float(extra), 2), "n": len(trades)}
