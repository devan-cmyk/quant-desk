"""Simulated paper broker — realistic-enough fills: adverse slippage (bps per side) +
per-share commission. No network, no risk of a real order. This is the only executor the
spine wires; a live broker would implement the same fill() surface AND call
live_guard.assert_live_allowed() before sending."""
from __future__ import annotations

from dataclasses import dataclass

from ..config import settings


@dataclass
class Fill:
    side: str          # buy | sell
    qty: int
    ref_price: float
    fill_price: float
    commission: float


class PaperBroker:
    name = "paper"

    def __init__(self, slippage_bps: float | None = None, commission_per_share: float | None = None):
        self.slippage_bps = settings.risk.slippage_bps if slippage_bps is None else slippage_bps
        self.commission_per_share = (settings.risk.commission_per_share
                                     if commission_per_share is None else commission_per_share)

    def fill(self, side: str, qty: int, ref_price: float) -> Fill:
        sign = 1.0 if side == "buy" else -1.0          # buys slip up, sells slip down
        fill_price = ref_price * (1 + sign * self.slippage_bps / 1e4)
        commission = self.commission_per_share * qty
        return Fill(side, qty, ref_price, round(fill_price, 4), round(commission, 4))
