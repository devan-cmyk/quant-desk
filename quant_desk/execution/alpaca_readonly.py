"""Read-only Alpaca account connectivity for live-readiness checks.

This client can verify credentials and read account/position/order state from Alpaca,
including a live account when explicitly configured. It intentionally exposes GET-only
operations and has no order-submission method.
"""
from __future__ import annotations

import json
import os
import urllib.request

from .alpaca_broker import LIVE_URL, PAPER_URL, BrokerDisabled


class AlpacaReadOnlyClient:
    def __init__(self, *, paper: bool = True, key: str | None = None, secret: str | None = None, http=None):
        self.paper = paper
        self.key = key or os.environ.get("QD_ALPACA_KEY")
        self.secret = secret or os.environ.get("QD_ALPACA_SECRET")
        self.base = PAPER_URL if paper else LIVE_URL
        self._http = http or self._urllib_get
        if not (self.key and self.secret):
            raise BrokerDisabled("missing Alpaca credentials (QD_ALPACA_KEY / QD_ALPACA_SECRET)")

    def _urllib_get(self, path: str) -> dict | list:
        req = urllib.request.Request(
            self.base + path,
            method="GET",
            headers={
                "APCA-API-KEY-ID": self.key,
                "APCA-API-SECRET-KEY": self.secret,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read())

    def get_account(self) -> dict:
        return self._http("/v2/account")

    def get_positions(self) -> list[dict]:
        data = self._http("/v2/positions")
        return list(data)

    def get_orders(self, *, status: str = "open") -> list[dict]:
        if status not in {"open", "closed", "all"}:
            raise ValueError("status must be open, closed, or all")
        data = self._http(f"/v2/orders?status={status}")
        return list(data)
