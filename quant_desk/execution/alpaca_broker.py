"""Alpaca PAPER broker adapter.

Implements the same fill() surface as PaperBroker, but routes orders to Alpaca's paper REST API.
Real-money execution is intentionally not available from this automated adapter.

Safety:
  • OFF by default — raises unless QD_ALPACA_ENABLE=1.
  • requires API credentials (QD_ALPACA_KEY / QD_ALPACA_SECRET).
  • PAPER endpoint only (paper-api.alpaca.markets).
  • live-account inspection belongs in AlpacaReadOnlyClient.
  • proposed real-money trades belong in execution.order_intent for human review/manual entry.

Dependency-free (stdlib urllib); HTTP is injectable for offline tests.
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
    """Alpaca routing not enabled / not configured / unsafe mode requested."""


class BrokerError(RuntimeError):
    """An order was rejected, canceled, or did not fill."""


class AlpacaBroker:
    name = "alpaca-paper"

    def __init__(self, *, paper: bool = True, key: str | None = None, secret: str | None = None,
                 unlock_token: str | None = None, poll_timeout: float = 10.0, http=None):
        del unlock_token  # retained for backward-compatible call sites; live execution is disabled.
        if not paper:
            raise BrokerDisabled(
                "real-money order submission is intentionally disabled; "
                "use AlpacaReadOnlyClient for live account reads and order_intent for manual execution"
            )
        self.paper = True
        self.key = key or os.environ.get("QD_ALPACA_KEY")
        self.secret = secret or os.environ.get("QD_ALPACA_SECRET")
        self.base = PAPER_URL
        self.poll_timeout = poll_timeout
        self._http = http or self._urllib

        if os.environ.get("QD_ALPACA_ENABLE") != "1":
            raise BrokerDisabled("Alpaca paper routing disabled — set QD_ALPACA_ENABLE=1 to opt in")
        if not (self.key and self.secret):
            raise BrokerDisabled("missing Alpaca credentials (QD_ALPACA_KEY / QD_ALPACA_SECRET)")
        log.warning("alpaca_paper_broker_armed", base=self.base)

    def _urllib(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            self.base + path,
            method=method,
            data=(json.dumps(body).encode() if body is not None else None),
            headers={
                "APCA-API-KEY-ID": self.key,
                "APCA-API-SECRET-KEY": self.secret,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read())

    def get_account(self) -> dict:
        return self._http("GET", "/v2/account")

    def fill(self, side: str, qty: int, ref_price: float, symbol: str | None = None) -> Fill:
        """Submit a market order to Alpaca PAPER and poll until it fills."""
        if not symbol:
            raise ValueError("AlpacaBroker.fill requires a symbol")
        if qty <= 0:
            raise ValueError("qty must be positive")
        order = self._http(
            "POST",
            "/v2/orders",
            {"symbol": symbol, "qty": qty, "side": side, "type": "market", "time_in_force": "day"},
        )
        oid = order["id"]
        deadline = time.time() + self.poll_timeout
        while time.time() <= deadline:
            current = self._http("GET", f"/v2/orders/{oid}")
            status = current.get("status")
            if status == "filled":
                return Fill(
                    side,
                    qty,
                    ref_price,
                    fill_price=float(current["filled_avg_price"]),
                    commission=0.0,
                )
            if status in ("rejected", "canceled", "expired"):
                raise BrokerError(f"order {oid} {status}")
            time.sleep(0.5)
        raise BrokerError(f"order {oid} did not fill within {self.poll_timeout}s")
