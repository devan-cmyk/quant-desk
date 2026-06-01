"""Real-time decision loop — the CORRECT forward-execution cycle.

The contrast that matters: run_forward_multi REPLAYS a timeline of historical bars (fine for
simulation, wrong for live — it would route orders for stale signals). live_tick instead makes
ONE decision on the single LATEST bar per symbol: manage open positions against it, then
evaluate a new entry on it — broker-agnostic (local sim by default, AlpacaBroker if armed).

Idempotent per bar: re-running on an unchanged bar never double-trades (an open position blocks
re-entry; last_acted blocks re-entry after a same-bar exit). Swing positions persist across ticks
and exit on stop/target/max_hold; intraday positions exit on stop/target (intraday EOD-flatten in
real time needs a market-close trigger — out of scope; those strategies are benched anyway).

CONTRACT: invoke when the latest bar is COMPLETE (e.g. after the close for daily) — exactly the
cadence the launchd agents already use. Acting on an in-progress bar = a partial signal.
"""
from __future__ import annotations

import signal
import time
from collections.abc import Callable

import pandas as pd

from ..config import RiskLimits
from ..execution.paper_broker import PaperBroker
from ..logging import get
from ..risk.engine import RiskEngine
from .portfolio import PaperPortfolio

log = get("realtime")
ET = "America/New_York"


def live_tick(mandates: list[dict], *, data_fn: Callable[[str], pd.DataFrame],
              portfolio: PaperPortfolio, broker=None, limits: RiskLimits | None = None,
              max_gross: float = 1.0) -> dict:
    """One real-time decision cycle on the latest bar per symbol. Returns the actions taken."""
    broker = broker or PaperBroker()
    limits = limits or RiskLimits()
    risk = RiskEngine(limits=limits, equity=portfolio.equity())
    actions, marks = [], {}

    for m in mandates:
        name, rf, scales = m.get("name", ""), m.get("regime_filter"), m.get("risk_scales") or {}
        params = m.get("params") or {}
        for sym in m["symbols"]:
            df = data_fn(sym).sort_index()
            if df is None or df.empty:
                continue
            i = len(df) - 1
            ts, bar = df.index[i], df.iloc[i]
            marks[sym] = float(bar["close"])
            key = f"{name}:{sym}" if name else sym
            strat = m["cls"](**params.get(sym, {})); strat.initialize()

            # 1. manage this pair's open position against the latest bar
            if key in portfolio.positions:
                p = portfolio.positions[key]
                exit_price, reason = None, None
                if p["side"] == "long":
                    if bar["low"] <= p["stop"]: exit_price, reason = p["stop"], "stop"
                    elif bar["high"] >= p["target"]: exit_price, reason = p["target"], "target"
                else:
                    if bar["high"] >= p["stop"]: exit_price, reason = p["stop"], "stop"
                    elif bar["low"] <= p["target"]: exit_price, reason = p["target"], "target"
                if exit_price is None and not strat.intraday and strat.max_hold_bars:
                    try:
                        held = i - df.index.get_loc(pd.Timestamp(p["entry_ts"]))
                    except KeyError:
                        held = strat.max_hold_bars
                    if held >= strat.max_hold_bars:
                        exit_price, reason = float(bar["close"]), "max_hold"
                if exit_price is not None:
                    f = broker.fill("sell" if p["side"] == "long" else "buy", p["qty"], exit_price, symbol=sym)
                    pnl = portfolio.close(key, f.fill_price, f.commission, ts, reason)
                    risk.on_trade_closed(pnl)
                    actions.append({"ts": ts.isoformat(), "symbol": sym, "strategy": name,
                                    "act": f"close/{reason}", "pnl": round(pnl, 2)})

            # 2. evaluate a NEW entry on the latest bar — once per bar (idempotent)
            if key not in portfolio.positions and portfolio.last_acted.get(key) != ts.isoformat():
                sig = strat.generate_signal(df)
                if sig.side in ("long", "short") and rf and not rf.allows(df, sig.side):
                    sig = sig.__class__(side="flat")
                if sig.side in ("long", "short") and sig.stop is not None:
                    dec = risk.evaluate(entry=float(bar["close"]), stop=float(sig.stop),
                                        risk_scale=scales.get(sym, 1.0))
                    notional = dec.qty * float(bar["close"])
                    if dec.allowed and (portfolio.gross_exposure(marks) + notional) <= max_gross * risk.equity:
                        f = broker.fill("buy" if sig.side == "long" else "sell", dec.qty, float(bar["close"]), symbol=sym)
                        portfolio.open(sym, sig.side, dec.qty, f.fill_price, f.commission,
                                       float(sig.stop), float(sig.target), ts, strategy=name)
                        portfolio.last_acted[key] = ts.isoformat()   # don't re-enter this same bar
                        actions.append({"ts": ts.isoformat(), "symbol": sym, "strategy": name,
                                        "act": f"open/{sig.side}", "qty": dec.qty})

    if marks:
        latest = max((df.index[-1] for df in (data_fn(s) for m in mandates for s in m["symbols"])
                      if df is not None and not df.empty), default=None)
        portfolio.snapshot(latest or pd.Timestamp.utcnow().tz_localize("UTC"), marks)
        portfolio.last_ts = (latest or pd.Timestamp.utcnow()).isoformat()
    eq = portfolio.equity(marks)
    log.info("live_tick", actions=len(actions), equity=round(eq, 2), open=len(portfolio.positions))
    return {"equity": round(eq, 2), "actions": actions, "open_positions": portfolio.positions,
            "blotter_n": len(portfolio.blotter)}


def live_loop(mandates: list[dict], *, data_fn, portfolio: PaperPortfolio, on_tick=None,
              interval_seconds: float = 300.0, max_ticks: int | None = None, **tick_kw) -> dict:
    """Poll live_tick on a cadence until stopped (SIGINT/SIGTERM) or max_ticks reached. on_tick
    persists/reports after each cycle. A thin driver — the launchd-cadence `live-tick` is the
    lighter-weight alternative for daily strategies."""
    stop = {"v": False}

    def _stop(*_): stop["v"] = True
    try:
        signal.signal(signal.SIGINT, _stop); signal.signal(signal.SIGTERM, _stop)
    except (ValueError, OSError):
        pass                                      # not in main thread (e.g. tests) — fine
    n = 0
    while not stop["v"] and (max_ticks is None or n < max_ticks):
        res = live_tick(mandates, data_fn=data_fn, portfolio=portfolio, **tick_kw)
        if on_tick:
            on_tick(res)
        n += 1
        if (max_ticks is not None and n >= max_ticks) or stop["v"]:
            break
        time.sleep(interval_seconds)
    return {"ticks": n}
