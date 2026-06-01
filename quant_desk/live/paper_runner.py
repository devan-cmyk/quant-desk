"""Forward PAPER-trading runner. Processes new bars across the selected symbols as a single
portfolio: manage open positions (stop/target/EOD flatten), then open new ones gated by the
strategy → regime filter → risk engine → gross-exposure cap, filling through the PaperBroker.
Stateful + persistent, so running it on a schedule grows one continuous paper account.

PAPER ONLY. Live execution is impossible here — there is no live broker wired and any future
one must pass execution.live_guard. This forward-tests an edge before it could ever go live."""
from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from ..config import RiskLimits
from ..execution.paper_broker import PaperBroker
from ..logging import get
from ..risk.engine import RiskEngine
from ..strategies.base import Strategy
from .portfolio import PaperPortfolio

log = get("paper_runner")
ET = "America/New_York"


def run_forward(symbols: list[str], strategy_cls: type[Strategy], *,
                data_fn: Callable[[str], pd.DataFrame], portfolio: PaperPortfolio,
                params_by_symbol: dict[str, dict] | None = None, regime_filter=None,
                limits: RiskLimits | None = None, broker: PaperBroker | None = None,
                max_bars: int | None = None, max_gross: float = 1.0,
                strategy_name: str = "") -> dict:
    """Single-strategy convenience wrapper over run_forward_multi (back-compatible)."""
    return run_forward_multi(
        [{"name": strategy_name, "cls": strategy_cls, "symbols": symbols,
          "params": params_by_symbol or {}, "regime_filter": regime_filter}],
        data_fn=data_fn, portfolio=portfolio, limits=limits, broker=broker,
        max_bars=max_bars, max_gross=max_gross)


def run_forward_multi(mandates: list[dict], *, data_fn: Callable[[str], pd.DataFrame],
                      portfolio: PaperPortfolio, limits: RiskLimits | None = None,
                      broker: PaperBroker | None = None, max_bars: int | None = None,
                      max_gross: float = 1.0) -> dict:
    """Forward-trade several strategies in ONE shared paper account. Each mandate is
    {name, cls, symbols, params, regime_filter?}. Positions are keyed strategy:symbol so two
    strategies can hold the same symbol as distinct logical positions; one risk engine and the
    gross-exposure cap govern the whole account (shared capital — the real portfolio model)."""
    limits = limits or RiskLimits()
    broker = broker or PaperBroker()
    # build per-mandate strategy instances (each symbol trades with its validated params)
    mlist = []
    all_symbols: set[str] = set()
    for m in mandates:
        pbs = m.get("params") or {}
        strat = {s: m["cls"](**pbs.get(s, {})) for s in m["symbols"]}
        for s in m["symbols"]:
            strat[s].initialize()
        mlist.append({"name": m.get("name", ""), "symbols": m["symbols"], "strat": strat,
                      "regime": m.get("regime_filter")})
        all_symbols |= set(m["symbols"])

    data = {s: data_fn(s).sort_index() for s in all_symbols}
    timeline = sorted(set().union(*[set(df.index) for df in data.values()])) if data else []
    last = pd.Timestamp(portfolio.last_ts) if portfolio.last_ts else None
    timeline = [t for t in timeline if last is None or t > last]
    if max_bars:
        timeline = timeline[-max_bars:]

    risk = RiskEngine(limits=limits, equity=portfolio.equity())
    actions, prev_date = [], None

    for ts in timeline:
        d_et = ts.tz_convert(ET).date()
        if d_et != prev_date:
            risk.reset_session(); prev_date = d_et
        marks = {}

        for md in mlist:
            name, rf = md["name"], md["regime"]
            for sym in md["symbols"]:
                df = data[sym]
                if ts not in df.index:
                    continue
                i = df.index.get_loc(ts)
                bar = df.iloc[i]
                marks[sym] = float(bar["close"])
                session_last = (i == len(df) - 1) or (df.index[i + 1].tz_convert(ET).date() != d_et)
                key = f"{name}:{sym}" if name else sym

                # 1. manage an open position (this mandate's own position on the symbol)
                if key in portfolio.positions:
                    p = portfolio.positions[key]
                    exit_price, reason = None, None
                    if p["side"] == "long":
                        if bar["low"] <= p["stop"]: exit_price, reason = p["stop"], "stop"
                        elif bar["high"] >= p["target"]: exit_price, reason = p["target"], "target"
                    else:
                        if bar["high"] >= p["stop"]: exit_price, reason = p["stop"], "stop"
                        elif bar["low"] <= p["target"]: exit_price, reason = p["target"], "target"
                    if exit_price is None and session_last:
                        exit_price, reason = float(bar["close"]), "eod"
                    if exit_price is not None:
                        f = broker.fill("sell" if p["side"] == "long" else "buy", p["qty"], exit_price)
                        pnl = portfolio.close(key, f.fill_price, f.commission, ts, reason)
                        risk.on_trade_closed(pnl)
                        actions.append({"ts": ts.isoformat(), "symbol": sym, "strategy": name,
                                        "act": f"close/{reason}", "pnl": round(pnl, 2)})

                # 2. open a new position
                if key not in portfolio.positions and not session_last:
                    window = df.iloc[: i + 1]
                    sig = md["strat"][sym].generate_signal(window)
                    if sig.side in ("long", "short") and rf and not rf.allows(window, sig.side):
                        continue
                    if sig.side in ("long", "short") and sig.stop is not None:
                        dec = risk.evaluate(entry=float(bar["close"]), stop=float(sig.stop))
                        notional = dec.qty * float(bar["close"])
                        if dec.allowed and (portfolio.gross_exposure(marks) + notional) <= max_gross * risk.equity:
                            f = broker.fill("buy" if sig.side == "long" else "sell", dec.qty, float(bar["close"]))
                            portfolio.open(sym, sig.side, dec.qty, f.fill_price, f.commission,
                                           float(sig.stop), float(sig.target), ts, strategy=name)
                            actions.append({"ts": ts.isoformat(), "symbol": sym, "strategy": name,
                                            "act": f"open/{sig.side}", "qty": dec.qty})

        if marks:
            portfolio.snapshot(ts, marks)
        portfolio.last_ts = ts.isoformat()

    eq = portfolio.equity(marks if timeline else None)
    log.info("paper_run_done", bars=len(timeline), equity=round(eq, 2),
             open=len(portfolio.positions), trades=len(portfolio.blotter))
    return {"bars_processed": len(timeline), "equity": round(eq, 2),
            "realized_cash": round(portfolio.cash, 2), "open_positions": portfolio.positions,
            "actions": actions, "blotter_n": len(portfolio.blotter)}
