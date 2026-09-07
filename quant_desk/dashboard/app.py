"""FastAPI dashboard for the forward paper account.

Reads the persistent paper_state.json and serves a single self-contained page.
The dashboard is read-only and paper-only; it cannot place trades. Hosted instances
can be protected with QD_DASH_USER / QD_DASH_PASS credentials.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import time
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..backtest.montecarlo import monte_carlo
from ..config import settings

HERE = os.path.dirname(__file__)
app = FastAPI(title="quant-desk dashboard")
_COOKIE = "qd_session"
_SESSION_SECONDS = 7 * 24 * 60 * 60


def _dashboard_credentials() -> tuple[str, str]:
    return os.environ.get("QD_DASH_USER", ""), os.environ.get("QD_DASH_PASS", "")


def _session_secret() -> str:
    return os.environ.get("QD_SESSION_SECRET") or os.environ.get("QD_DASH_PASS", "")


def _sign(user: str, expires: int) -> str:
    message = f"{user}|{expires}".encode()
    return hmac.new(_session_secret().encode(), message, hashlib.sha256).hexdigest()


def _make_token(user: str) -> str:
    expires = int(time.time()) + _SESSION_SECONDS
    raw = f"{user}|{expires}|{_sign(user, expires)}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _valid_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        padded = token + "=" * (-len(token) % 4)
        user, expires_s, signature = base64.urlsafe_b64decode(padded).decode().split("|", 2)
        expires = int(expires_s)
    except (ValueError, UnicodeDecodeError):
        return False
    expected_user, _ = _dashboard_credentials()
    return (
        expires >= int(time.time())
        and hmac.compare_digest(user, expected_user)
        and hmac.compare_digest(signature, _sign(user, expires))
    )


def _login_page(error: str = "") -> str:
    message = f'<div class="error">{html.escape(error)}</div>' if error else ""
    return f"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quant Desk — Sign in</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#07120f;color:#ecfff8;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
.card{{width:min(92vw,420px);padding:32px;border:1px solid #24453b;border-radius:20px;background:#0d1d18;box-shadow:0 24px 70px #0008}}
h1{{margin:0 0 8px;font-size:26px}}p{{margin:0 0 24px;color:#9cc6b8}}label{{display:block;margin:14px 0 6px;font-size:13px;color:#b9d5cc}}input{{width:100%;padding:13px 14px;border-radius:10px;border:1px solid #315f50;background:#071410;color:white;font-size:16px}}button{{width:100%;margin-top:20px;padding:13px;border:0;border-radius:10px;background:#d7fff1;color:#07120f;font-weight:800;font-size:15px}}.error{{margin:0 0 14px;padding:10px;border-radius:8px;background:#451b26;color:#ffd6df}}
</style></head><body><main class="card"><h1>Quant Desk</h1><p>Sign in to your private paper-trading research dashboard.</p>{message}
<form method="post" action="/login"><label>Username</label><input name="username" autocomplete="username" required autofocus><label>Password</label><input name="password" type="password" autocomplete="current-password" required><button type="submit">Sign in</button></form></main></body></html>"""


@app.middleware("http")
async def require_dashboard_auth(request: Request, call_next):
    if request.url.path in {"/healthz", "/login"}:
        return await call_next(request)
    username, password = _dashboard_credentials()
    if not username or not password:
        return await call_next(request)
    if _valid_token(request.cookies.get(_COOKIE)):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page() -> str:
    return _login_page()


@app.post("/login", response_class=HTMLResponse, include_in_schema=False)
async def login(request: Request):
    body = (await request.body()).decode("utf-8", errors="replace")
    form = parse_qs(body)
    supplied_user = (form.get("username") or [""])[0]
    supplied_pass = (form.get("password") or [""])[0]
    username, password = _dashboard_credentials()
    if not username or not password:
        return RedirectResponse("/", status_code=303)
    if not (hmac.compare_digest(supplied_user, username) and hmac.compare_digest(supplied_pass, password)):
        return HTMLResponse(_login_page("Incorrect username or password."), status_code=401)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        _COOKIE,
        _make_token(username),
        max_age=_SESSION_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return response


@app.get("/logout", include_in_schema=False)
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(_COOKIE, path="/")
    return response


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
