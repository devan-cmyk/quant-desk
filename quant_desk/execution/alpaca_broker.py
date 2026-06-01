"""Alpaca broker adapter — the execution foundation toward real fills.

Implements the same fill() surface as PaperBroker, but routes orders to Alpaca's REST API
instead of simulating them locally. SAFETY, layered:
  • OFF by default — raises unless QD_ALPACA_ENABLE=1 (you never touch Alpaca by accident).
  • requires API credentials (QD_ALPACA_KEY / QD_ALPACA_SECRET).
  • PAPER endpoint by default (paper-api.alpaca.markets) — no real money.
  • LIVE (real-money) routing additionally inherits the full live_guard triple-lock.

Dependency-free (stdlib urllib); the HTTP call is injectable so the logic is fully testable
offline with a mock — no keys, no network.

INTEGRATION NOTE (honest): this is the order-routing foundation, NOT a live-trading switch. The
current run_forward_multi is a historical-bar REPLAY that advances last_ts; pointing it at a
real broker would submit orders for stale signals. Going live needs a real-time event loop
(a separate build). This adapter is intentionally not wired into the scheduled agents.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

from ..logging import get
from .paper_broker import Fill

log = get("alpaca")

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"


class BrokerDisabled(RuntimeError):
    """Alpaca routing not enabled / not configured."""


class BrokerError(RuntimeError):
    """An order was rejected, canceled, or did not fill."""


class AlpacaBroker:
    name = "alpaca"

    def __init__(self, *, paper: bool = True, key: str | None = None, secret: str | None = None,
                 unlock_token: str | None = None, poll_timeout: float = 10.0, http=None):
        self.paper = paper
        self.key = key or os.environ.get("QD_ALPACA_KEY")
        self.secret = secret or os.environ.get("QD_ALPACA_SECRET")
        self.base = PAPER_URL if paper else LIVE_URL
        self.poll_timeout = poll_timeout
        self._http = http or self._urllib                 # injectable for tests (no network)

        # ── safety gates (fail-secure, in order) ──────────────────────────────
        if os.environ.get("QD_ALPACA_ENABLE") != "1":
            raise BrokerDisabled("Alpaca routing disabled — set QD_ALPACA_ENABLE=1 to opt in")
        if not (self.key and self.secret):
            raise BrokerDisabled("missing Alpaca credentials (QD_ALPACA_KEY / QD_ALPACA_SECRET)")
        if not paper:
            from .live_guard import assert_live_allowed
            assert_live_allowed(unlock_token)              # real money inherits the triple-lock
        log.warning("alpaca_broker_armed", paper=paper, base=self.base)

    # ── HTTP (stdlib; injectable) ─────────────────────────────────────────────
    def _urllib(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            self.base + path, method=method,
            data=(json.dumps(body).encode() if body is not None else None),
            headers={"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    # ── surface ───────────────────────────────────────────────────────────────
    def get_account(self) -> dict:
        """Account snapshot — also the cheapest connectivity/credential check."""
        return self._http("GET", "/v2/account")

    def fill(self, side: str, qty: int, ref_price: float, symbol: str | None = None) -> Fill:
        """Submit a market order and poll until it fills; return the real fill (Alpaca is
        commission-free, so commission=0 and the cost is the actual market slippage)."""
        if not symbol:
            raise ValueError("AlpacaBroker.fill requires a symbol (real orders need one)")
        if qty <= 0:
            raise ValueError("qty must be positive")
        order = self._http("POST", "/v2/orders", {"symbol": symbol, "qty": qty, "side": side,
                                                   "type": "market", "time_in_force": "day"})
        oid = order["id"]
        deadline = time.time() + self.poll_timeout
        while time.time() <= deadline:
            o = self._http("GET", f"/v2/orders/{oid}")
            status = o.get("status")
            if status == "filled":
                return Fill(side, qty, ref_price, fill_price=float(o["filled_avg_price"]), commission=0.0)
            if status in ("rejected", "canceled", "expired"):
                raise BrokerError(f"order {oid} {status}")
            time.sleep(0.5)
        raise BrokerError(f"order {oid} did not fill within {self.poll_timeout}s")
