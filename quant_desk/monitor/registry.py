"""Strategy registry — persistent memory of each strategy/symbol's health over time. The
monitor updates it; it surfaces status CHANGES (a symbol just retired / recovered) and the
currently-active set the paper runner should trade. JSON-backed so it survives across runs."""
from __future__ import annotations

import datetime as dt
import json
import os

ACTIVE_STATUSES = {"healthy", "watch"}


class Registry:
    def __init__(self, data: dict | None = None, path: str | None = None):
        self.path = path or os.environ.get("QD_REGISTRY") or os.path.expanduser("~/.quant-desk/registry.json")
        self.data = data or {}      # "strategy:symbol" -> {status, recent_mean, trend, updated, history[]}

    @classmethod
    def load(cls, path: str | None = None) -> "Registry":
        p = path or os.environ.get("QD_REGISTRY") or os.path.expanduser("~/.quant-desk/registry.json")
        return cls(json.load(open(p)), p) if os.path.exists(p) else cls(path=p)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        json.dump(self.data, open(self.path, "w"), indent=2)

    def update(self, strategy: str, assessments: list[dict]) -> list[dict]:
        """Record the latest assessments; return the status-change events since last run."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        changes = []
        for a in assessments:
            if a["status"] in ("error", "insufficient_data"):
                continue
            key = f"{strategy}:{a['symbol']}"
            prev = self.data.get(key) or {}
            if prev.get("status") and prev["status"] != a["status"]:
                changes.append({"symbol": a["symbol"], "from": prev["status"], "to": a["status"]})
            hist = prev.get("history", [])
            hist.append({"ts": now, "status": a["status"], "recent_mean": a.get("recent_mean")})
            # merge, don't overwrite — preserve committee verdict + forward-recon fields that
            # other tools wrote to this pair (the decay monitor only owns the decay fields)
            prev.update({"status": a["status"], "recent_mean": a.get("recent_mean"),
                         "trend": a.get("trend"), "updated": now, "history": hist[-50:]})
            self.data[key] = prev
        return changes

    def active(self, strategy: str) -> list[str]:
        """Symbols currently healthy/watch (NOT retired) for this strategy."""
        return [k.split(":", 1)[1] for k, v in self.data.items()
                if k.startswith(f"{strategy}:") and v.get("status") in ACTIVE_STATUSES]

    def is_retired(self, strategy: str, symbol: str) -> bool:
        v = self.data.get(f"{strategy}:{symbol}")
        return bool(v and v.get("status") == "retired")

    # ── committee verdicts (the decision committee's promote/reject/retire) ───
    def set_verdict(self, strategy: str, symbol: str, verdict: str, rationale: str = "") -> None:
        import datetime as _dt
        key = f"{strategy}:{symbol}"
        e = self.data.get(key, {})
        e.update({"verdict": verdict, "verdict_rationale": rationale,
                  "verdict_ts": _dt.datetime.now(_dt.timezone.utc).isoformat()})
        self.data[key] = e

    def verdict(self, strategy: str, symbol: str) -> str | None:
        return (self.data.get(f"{strategy}:{symbol}") or {}).get("verdict")

    def set_params(self, strategy: str, symbol: str, params: dict) -> None:
        """The committee-validated params behind the verdict (walk-forward best params)."""
        key = f"{strategy}:{symbol}"
        e = self.data.get(key, {})
        e["params"] = dict(params or {})
        self.data[key] = e

    def params(self, strategy: str, symbol: str) -> dict:
        return (self.data.get(f"{strategy}:{symbol}") or {}).get("params") or {}

    # ── forward/backtest reconciliation (live truth vs the promoted backtest) ──
    def set_forward(self, strategy: str, symbol: str, status: str, detail: str = "") -> None:
        import datetime as _dt
        key = f"{strategy}:{symbol}"
        e = self.data.get(key, {})
        e.update({"forward": status, "forward_detail": detail,
                  "forward_ts": _dt.datetime.now(_dt.timezone.utc).isoformat()})
        self.data[key] = e

    def forward(self, strategy: str, symbol: str) -> str | None:
        return (self.data.get(f"{strategy}:{symbol}") or {}).get("forward")

    # ── portfolio allocation (diversification-aware per-pair risk weight) ──────
    def set_allocation(self, strategy: str, symbol: str, weight: float, scale: float) -> None:
        import datetime as _dt
        key = f"{strategy}:{symbol}"
        e = self.data.get(key, {})
        e.update({"weight": round(float(weight), 4), "risk_scale": round(float(scale), 3),
                  "alloc_ts": _dt.datetime.now(_dt.timezone.utc).isoformat()})
        self.data[key] = e

    def risk_scale(self, strategy: str, symbol: str) -> float:
        return (self.data.get(f"{strategy}:{symbol}") or {}).get("risk_scale", 1.0)

    def is_blocked(self, strategy: str, symbol: str) -> bool:
        """True if the runner must NOT trade this pair — the committee rejected/retired it, the
        decay monitor retired it, or forward reconciliation flagged drift (the promoted edge
        failed to show up live). The promotion gate for forward paper trading."""
        e = self.data.get(f"{strategy}:{symbol}") or {}
        return (e.get("verdict") in ("reject", "retire") or e.get("status") == "retired"
                or e.get("forward") == "drift")
