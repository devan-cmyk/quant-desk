"""FastAPI dashboard for the forward paper account. Reads the persistent paper_state.json
and serves a single self-contained page (no build step). Read-only + paper-only: it shows
the account, it cannot trade."""
from __future__ import annotations

import json
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from ..backtest.montecarlo import monte_carlo
from ..config import settings

HERE = os.path.dirname(__file__)
app = FastAPI(title="quant-desk dashboard")


def _state_path() -> str:
    return os.environ.get("QD_PAPER_STATE") or os.path.expanduser("~/.quant-desk/paper_state.json")


def _state() -> dict:
    p = _state_path()
    if os.path.exists(p):
        return json.load(open(p))
    return {"start_equity": 100_000, "cash": 100_000, "positions": {}, "blotter": [],
            "equity_curve": [], "last_ts": None}


@app.get("/api/account")
def account() -> dict:
    s = _state()
    start = s.get("start_equity", 100_000)
    eq = s["equity_curve"][-1][1] if s.get("equity_curve") else s.get("cash", start)
    pnls = [t["pnl"] for t in s.get("blotter", [])]
    by: dict = {}
    for t in s.get("blotter", []):
        d = by.setdefault(t["symbol"], {"trades": 0, "pnl": 0.0, "wins": 0})
        d["trades"] += 1; d["pnl"] = round(d["pnl"] + t["pnl"], 2); d["wins"] += t["pnl"] > 0
    return {
        "trading_mode": settings.trading_mode, "live_locked": settings.trading_mode != "live",
        "start_equity": start, "equity": round(eq, 2), "cash": round(s.get("cash", start), 2),
        "total_return": eq / start - 1.0, "n_trades": len(pnls),
        "win_rate": (sum(p > 0 for p in pnls) / len(pnls)) if pnls else None,
        "open_positions": s.get("positions", {}), "by_symbol": by,
        "equity_curve": s.get("equity_curve", []), "blotter": list(reversed(s.get("blotter", [])))[:60],
        "monte_carlo": monte_carlo(pnls, starting_equity=start) if len(pnls) >= 3 else {"note": "need >=3 trades"},
        "last_ts": s.get("last_ts"),
    }


@app.get("/api/journal")
def journal(n: int = 30) -> dict:
    from ..archive.journal import Journal
    jr = Journal()
    rows = jr.recent(n)
    total = jr.count()
    jr.close()
    return {"total": total, "entries": [
        {"ts": r["ts"], "kind": r["kind"], "strategy": r["strategy"],
         "summary": r["summary"], "decision": r["decision"]} for r in rows]}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return open(os.path.join(HERE, "index.html")).read()
