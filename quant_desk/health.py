"""System health / self-diagnostics — continuous validation of the autonomous platform's REAL
operational invariants. Not fantasy distributed/GPU/cloud telemetry; the actual failure modes of
this launchd + JSON-state + SQLite system:

  • are the scheduled agents loaded and not silently erroring?
  • has the committee gate gone STALE (review didn't run on cadence)?
  • is persisted state intact (registry JSON / journal DB / paper account all loadable)?
  • is the data layer reachable (cache present)?

Each check has a severity; the worst determines overall status (healthy / degraded / critical).
Surfaced via `quant-desk health`, /api/health, and a daily agent that alerts when degraded —
turning the platform's silent failure modes into observable, actionable signals.
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
import subprocess
import time

REPO_DIR = os.path.expanduser("~/quant-desk")
STATE_DIR = os.path.expanduser("~/.quant-desk")
STALE_GATE_DAYS = 9.0       # committee review runs weekly; older than this ⇒ stale gate


def _check(name, ok, severity, detail):
    return {"name": name, "ok": bool(ok), "severity": severity, "detail": detail}


def _age_days(path: str) -> float | None:
    return (time.time() - os.path.getmtime(path)) / 86400 if os.path.exists(path) else None


def _agents_loaded() -> dict:
    """launchctl-reported quant-desk agents (best-effort; darwin only)."""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10).stdout
        labels = [ln.split()[-1] for ln in out.splitlines() if "com.quantdesk." in ln]
        return _check("agents_loaded", len(labels) > 0, "high" if not labels else "info",
                      f"{len(labels)} quant-desk agents loaded" if labels else "NO agents loaded")
    except Exception as e:
        return _check("agents_loaded", True, "info", f"launchctl unavailable ({str(e)[:40]}) — skipped")


def _agent_errors(repo_dir: str) -> dict:
    """Any non-empty *.err.log means an agent wrote to stderr (a crash/traceback)."""
    errs = [os.path.basename(p) for p in glob.glob(os.path.join(repo_dir, "*.err.log"))
            if os.path.getsize(p) > 0]
    return _check("agent_errors", not errs, "high" if errs else "info",
                  f"stderr in: {errs}" if errs else "no agent stderr")


def _registry(state_dir: str) -> list[dict]:
    p = os.path.join(state_dir, "registry.json")
    if not os.path.exists(p):
        return [_check("registry", False, "warn", "no registry yet (run a review)")]
    try:
        with open(p) as f:
            data = json.load(f)
    except Exception as e:
        return [_check("registry", False, "critical", f"registry CORRUPT: {str(e)[:50]}")]
    age = _age_days(p)
    return [
        _check("registry", True, "info", f"{len(data)} pairs tracked"),
        _check("gate_fresh", age is not None and age <= STALE_GATE_DAYS, "warn",
               f"registry last updated {age:.1f}d ago" + (" — STALE" if age and age > STALE_GATE_DAYS else "")),
    ]


def _journal(state_dir: str) -> dict:
    p = os.path.join(state_dir, "journal.db")
    if not os.path.exists(p):
        return _check("journal", False, "warn", "no journal yet")
    try:
        db = sqlite3.connect(p)
        n = db.execute("SELECT COUNT(*) FROM research_log").fetchone()[0]
        db.close()
        return _check("journal", True, "info", f"{n} audit records")
    except Exception as e:
        return _check("journal", False, "critical", f"journal DB unreadable: {str(e)[:50]}")


def _paper_state(state_dir: str) -> dict:
    p = os.path.join(state_dir, "paper_state.json")
    if not os.path.exists(p):
        return _check("paper_state", False, "warn", "no paper account yet")
    try:
        with open(p) as f:
            d = json.load(f)
        missing = [k for k in ("cash", "positions", "blotter") if k not in d]
        if missing:
            return _check("paper_state", False, "critical", f"paper account missing keys: {missing}")
        return _check("paper_state", True, "info",
                      f"${d['cash']:,.0f} cash · {len(d['blotter'])} trades · {len(d['positions'])} open")
    except Exception as e:
        return _check("paper_state", False, "critical", f"paper account CORRUPT: {str(e)[:50]}")


def _data_cache() -> dict:
    cache = os.path.join(REPO_DIR, "data", "cache")
    n = len(glob.glob(os.path.join(cache, "*.parquet"))) if os.path.isdir(cache) else 0
    return _check("data_cache", n > 0, "warn", f"{n} cached datasets" if n else "no data cache")


def system_health(*, repo_dir: str = REPO_DIR, state_dir: str = STATE_DIR) -> dict:
    checks = [_agents_loaded(), _agent_errors(repo_dir), *_registry(state_dir),
              _journal(state_dir), _paper_state(state_dir), _data_cache()]
    crit = [c for c in checks if not c["ok"] and c["severity"] == "critical"]
    warn = [c for c in checks if not c["ok"] and c["severity"] in ("high", "warn")]
    status = "critical" if crit else ("degraded" if warn else "healthy")
    score = round(100 * sum(c["ok"] for c in checks) / len(checks))
    return {"status": status, "score": score, "checks": checks,
            "issues": [c for c in checks if not c["ok"]]}
