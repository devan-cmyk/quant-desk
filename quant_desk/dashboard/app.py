"""FastAPI dashboard for the forward paper account.

Reads the persistent paper_state.json and serves a single self-contained page.
The dashboard is read-only and paper-only; it cannot place trades. Hosted instances
can be protected with QD_DASH_USER / QD_DASH_PASS HTTP Basic credentials.
"""
from __future__ import annotations

import base64
import hmac
import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..backtest.montecarlo import monte_carlo
from ..config import settings

HERE = os.path.dirname(__file__)
app = FastAPI(title="quant-desk dashboard")


def _dashboard_credentials() -> tuple[str, str]:
    return os.environ.get("QD_DASH_USER", ""), os.environ.get("QD_DASH_PASS", "")


@app.middleware("http")
async def require_dashboard_auth(request: Request, call_next):
    # Railway/other platform health checks must remain unauthenticated.
    if request.url.path == "/healthz":
        return await call_next(request)

    username, password = _dashboard_credentials()
    if not username or not password:
        # Local development stays frictionless; production is configured with both vars.
        return await call_next(request)

    auth = request.headers.get("Authorization", "")
    supplied_user = supplied_pass = ""
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:], validate=True).decode("utf-8")
            supplied_user, supplied_pass = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            pass

    valid = hmac.compare_digest(supplied_user, username) and hmac.compare_digest(supplied_pass, password)
    if not valid:
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="quant-desk"'},
            content="Authentication required",
        )
    return await call_next(request)


def _state_path() -> str:
    return os.environ.get("QD_PAPER_STATE") or os.path.expanduser("~/.quant-desk/paper_state.json")


def _state() -> dict:
    p = _state_path()
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {"start_equity": 100_000, "cash": 100_000, "positions": {}, "blotter": [],
            "equity_curve": [], "last_ts": None}


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"status": "ok", "mode": settings.trading_mode, "live_locked": settings.trading_mode != "live"}


@app.get("/api/account")
def account() -> dict:
    s = _state()
    start = s.get("start_equity", 100_000)
    eq = s["equity_curve"][-1][1] if s.get("equity_curve") else s.get("cash", start)
    pnls = [t["pnl"] for t in s.get("blotter", [])]
    by: dict = {}
    by_strat: dict = {}
    for t in s.get("blotter", []):
        d = by.setdefault(t["symbol"], {"trades": 0, "pnl": 0.0, "wins": 0})
        d["trades"] += 1; d["pnl"] = round(d["pnl"] + t["pnl"], 2); d["wins"] += t["pnl"] > 0
        sk = t.get("strategy") or "orb"
        g = by_strat.setdefault(sk, {"trades": 0, "pnl": 0.0, "wins": 0})
        g["trades"] += 1; g["pnl"] = round(g["pnl"] + t["pnl"], 2); g["wins"] += t["pnl"] > 0
    return {
        "trading_mode": settings.trading_mode, "live_locked": settings.trading_mode != "live",
        "start_equity": start, "equity": round(eq, 2), "cash": round(s.get("cash", start), 2),
        "total_return": eq / start - 1.0, "n_trades": len(pnls),
        "win_rate": (sum(p > 0 for p in pnls) / len(pnls)) if pnls else None,
        "open_positions": s.get("positions", {}), "by_symbol": by, "by_strategy": by_strat,
        "equity_curve": s.get("equity_curve", []), "blotter": list(reversed(s.get("blotter", [])))[:60],
        "monte_carlo": monte_carlo(pnls, starting_equity=start) if len(pnls) >= 3 else {"note": "need >=3 trades"},
        "last_ts": s.get("last_ts"),
    }


@app.get("/api/gate")
def gate() -> dict:
    """The promotion gate with independent kill-paths and effective trade scale."""
    from ..monitor.registry import Registry
    reg = Registry.load()
    rows = []
    for key, e in sorted(reg.data.items()):
        strat, _, sym = key.partition(":")
        blocked = reg.is_blocked(strat, sym)
        rows.append({
            "strategy": strat, "symbol": sym,
            "verdict": e.get("verdict"), "verdict_rationale": e.get("verdict_rationale"),
            "decay": e.get("status"), "recent_mean": e.get("recent_mean"),
            "forward": e.get("forward"), "forward_detail": e.get("forward_detail"),
            "weight": e.get("weight"), "risk_scale": e.get("risk_scale"),
            "effective_scale": None if blocked else reg.effective_scale(strat, sym),
            "blocked": blocked, "updated": e.get("updated"),
        })
    tradeable = [f"{r['strategy']}:{r['symbol']}" for r in rows
                 if not r["blocked"] and r["verdict"] in ("promote", "paper_watch")]
    return {"pairs": rows, "tradeable": tradeable,
            "n_blocked": sum(r["blocked"] for r in rows), "n_total": len(rows)}


@app.get("/api/allocation")
def allocation() -> dict:
    from ..archive.journal import Journal
    jr = Journal()
    rows = jr.recent(1, kind="allocation")
    jr.close()
    if not rows:
        return {"present": False}
    r = rows[0]
    p = r.get("payload") or {}
    return {"present": True, "ts": r["ts"], "method": r.get("decision"),
            "n_obs": p.get("n_obs"), "weights": p.get("weights", {}),
            "scales": p.get("scales", {}), "corr": p.get("corr", {}),
            "current_regime": p.get("current_regime"), "tilts": p.get("tilts", {})}


@app.get("/api/health")
def health() -> dict:
    from ..health import system_health
    return system_health()


@app.get("/api/alerts")
def alerts(n: int = 20) -> dict:
    from ..alerts.gate_alerts import AlertFeed
    items = AlertFeed().recent(n)
    return {"alerts": items, "n_high": sum(a.get("severity") == "high" for a in items)}


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
    with open(os.path.join(HERE, "index.html")) as f:
        return f.read()
