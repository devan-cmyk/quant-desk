"""PaperPortfolio — a stateful, multi-symbol PAPER account. Realized equity lives in
`cash`; equity = cash + unrealized. Positions, a trade blotter, and the last-processed
timestamp persist to JSON so a scheduled runner continues the same account across runs.
No real money, ever — this is the forward-test surface."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

import pandas as pd


@dataclass
class Position:
    side: str
    qty: int
    entry: float
    stop: float
    target: float
    entry_ts: str


@dataclass
class PaperPortfolio:
    start_equity: float = 100_000.0
    cash: float = 100_000.0                 # realized equity
    positions: dict = field(default_factory=dict)   # symbol -> Position(dict)
    blotter: list = field(default_factory=list)
    last_ts: str | None = None
    equity_curve: list = field(default_factory=list)  # [[iso_ts, equity], ...]

    # ── valuation ────────────────────────────────────────────────────────────
    def equity(self, marks: dict[str, float] | None = None) -> float:
        eq = self.cash
        for sym, p in self.positions.items():
            mk = (marks or {}).get(sym, p["entry"])
            d = 1 if p["side"] == "long" else -1
            eq += (mk - p["entry"]) * p["qty"] * d
        return eq

    def gross_exposure(self, marks: dict[str, float] | None = None) -> float:
        return sum((marks or {}).get(s, p["entry"]) * p["qty"] for s, p in self.positions.items())

    # ── mutation ─────────────────────────────────────────────────────────────
    def open(self, sym, side, qty, fill, commission, stop, target, ts):
        self.cash -= commission
        self.positions[sym] = asdict(Position(side, qty, fill, stop, target, ts.isoformat()))

    def close(self, sym, fill, commission, ts, reason) -> float:
        p = self.positions.pop(sym)
        d = 1 if p["side"] == "long" else -1
        pnl = (fill - p["entry"]) * p["qty"] * d - commission
        self.cash += pnl
        self.blotter.append({"symbol": sym, "side": p["side"], "qty": p["qty"], "entry": p["entry"],
                             "exit": round(fill, 4), "reason": reason, "pnl": round(pnl, 2),
                             "entry_ts": p["entry_ts"], "exit_ts": ts.isoformat()})
        return pnl

    def snapshot(self, ts, marks):
        self.equity_curve.append([ts.isoformat(), round(self.equity(marks), 2)])

    # ── persistence ──────────────────────────────────────────────────────────
    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(asdict(self), open(path, "w"), indent=2)

    @classmethod
    def load(cls, path: str, start_equity: float = 100_000.0) -> "PaperPortfolio":
        if os.path.exists(path):
            return cls(**json.load(open(path)))
        return cls(start_equity=start_equity, cash=start_equity)
