"""Asset-class-aware transaction costs.

Crypto spreads + taker fees run ~10-15× a liquid US ETF, so evaluating a crypto strategy at the
equity cost (2 bps) would let a fragile crypto edge falsely clear the cost gate — the exact
'unrealistic crypto costs' failure the system must refuse. This resolves a symbol to the right
cost profile so the backtest fills, walk-forward, and the 2× cost gate all use honest costs.

Detection is conservative: crypto pairs are priced in USD (`BTC-USD`, `ETH-USD`) or USDT.
Everything else is treated as an equity/ETF.
"""
from __future__ import annotations

from .config import settings


def asset_class(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith("-USD") or s.endswith("USDT") or s.endswith("USDC") or s.endswith("-USDT"):
        return "crypto"
    return "equity"


def cost_profile(symbol: str) -> dict:
    """Per-asset-class fill costs: {slippage_bps, commission_per_share, asset_class}. Crypto has no
    per-share commission (it's percentage-based) — its cost is carried entirely in slippage_bps."""
    if asset_class(symbol) == "crypto":
        return {"slippage_bps": settings.risk.crypto_slippage_bps, "commission_per_share": 0.0,
                "asset_class": "crypto"}
    return {"slippage_bps": settings.risk.slippage_bps,
            "commission_per_share": settings.risk.commission_per_share, "asset_class": "equity"}
