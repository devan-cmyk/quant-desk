"""Event-loop backtester. Single symbol, intraday. Each bar:
  1. mark equity (realized + unrealized),
  2. manage an open position (stop / target intrabar, flatten at session close),
  3. if flat, ask the strategy for a signal and let the RISK ENGINE size/veto the entry.
Fills go through the PaperBroker (slippage + commission). Risk resets per session. Entries
are taken at bar close and managed from the next bar (no same-bar look-ahead)."""
from __future__ import annotations

import pandas as pd

from ..execution.paper_broker import PaperBroker
from ..logging import get
from ..risk.engine import RiskEngine
from ..strategies.base import Strategy
from .metrics import compute_metrics

log = get("backtest")
ET = "America/New_York"


def run_backtest(df: pd.DataFrame, strategy: Strategy, risk: RiskEngine,
                 broker: PaperBroker | None = None, regime_filter=None) -> dict:
    broker = broker or PaperBroker()
    strategy.initialize()
    df = df.sort_index()
    n = len(df)
    dates = df.index.tz_convert(ET).date

    pos = None                      # {side, qty, entry_fill, entry_commission, stop, target}
    trades: list[dict] = []
    curve_ts, curve_val = [], []
    prev_date = None

    for i in range(n):
        ts, bar = df.index[i], df.iloc[i]
        if dates[i] != prev_date:
            risk.reset_session()
            prev_date = dates[i]
        session_last = (i == n - 1) or (dates[i + 1] != dates[i])

        # 1. mark-to-market equity for the curve
        if pos:
            d = 1 if pos["side"] == "long" else -1
            equity_now = risk.equity + (bar["close"] - pos["entry_fill"]) * pos["qty"] * d
        else:
            equity_now = risk.equity
        curve_ts.append(ts); curve_val.append(equity_now)

        # 2. manage open position
        if pos:
            exit_price, reason = None, None
            if pos["side"] == "long":
                if bar["low"] <= pos["stop"]: exit_price, reason = pos["stop"], "stop"
                elif bar["high"] >= pos["target"]: exit_price, reason = pos["target"], "target"
            else:
                if bar["high"] >= pos["stop"]: exit_price, reason = pos["stop"], "stop"
                elif bar["low"] <= pos["target"]: exit_price, reason = pos["target"], "target"
            if exit_price is None and session_last:
                exit_price, reason = bar["close"], "eod"
            if exit_price is not None:
                f = broker.fill("sell" if pos["side"] == "long" else "buy", pos["qty"], exit_price)
                d = 1 if pos["side"] == "long" else -1
                pnl = (f.fill_price - pos["entry_fill"]) * pos["qty"] * d - f.commission - pos["entry_commission"]
                risk.on_trade_closed(pnl)
                trades.append({"entry_ts": pos["entry_ts"], "exit_ts": ts, "side": pos["side"],
                               "qty": pos["qty"], "entry": pos["entry_fill"], "exit": f.fill_price,
                               "reason": reason, "pnl": round(pnl, 2)})
                pos = None

        # 3. new entry (flat, not the session's last bar)
        if pos is None and not session_last:
            window = df.iloc[: i + 1]
            sig = strategy.generate_signal(window)
            # regime gate: veto signals that fight the prevailing trend (or fire in chop)
            if sig.side in ("long", "short") and regime_filter and not regime_filter.allows(window, sig.side):
                sig = sig.__class__(side="flat")
            if sig.side in ("long", "short") and sig.stop is not None:
                dec = risk.evaluate(entry=float(bar["close"]), stop=float(sig.stop))
                if dec.allowed:
                    f = broker.fill("buy" if sig.side == "long" else "sell", dec.qty, float(bar["close"]))
                    pos = {"side": sig.side, "qty": dec.qty, "entry_fill": f.fill_price,
                           "entry_commission": f.commission, "stop": float(sig.stop),
                           "target": float(sig.target), "entry_ts": ts}

    equity = pd.Series(curve_val, index=pd.DatetimeIndex(curve_ts), name="equity")
    metrics = compute_metrics(equity, trades)
    log.info("backtest_done", trades=len(trades), end_equity=round(float(equity.iloc[-1]), 2),
             sharpe=metrics.get("sharpe"))
    return {"equity": equity, "trades": trades, "metrics": metrics}
