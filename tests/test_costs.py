"""Asset-class-aware costs: crypto must be gated at realistic costs, never equity 2bps —
so a fragile edge that 'passes' on equity costs correctly fails on crypto costs."""
from quant_desk.costs import asset_class, cost_profile
from quant_desk.config import settings
from quant_desk.council.cost import cost_margin


def test_asset_class_detection():
    assert asset_class("BTC-USD") == "crypto"
    assert asset_class("ETH-USD") == "crypto"
    assert asset_class("SOLUSDT") == "crypto"
    assert asset_class("SPY") == "equity"
    assert asset_class("TLT") == "equity"
    assert asset_class("XLF") == "equity"


def test_cost_profile_crypto_is_more_expensive():
    eq = cost_profile("SPY")
    cr = cost_profile("BTC-USD")
    assert eq["asset_class"] == "equity" and cr["asset_class"] == "crypto"
    assert cr["slippage_bps"] == settings.risk.crypto_slippage_bps > eq["slippage_bps"]
    assert cr["commission_per_share"] == 0.0          # crypto fee is %-based, carried in slippage


def test_crypto_cost_strictly_lowers_the_margin():
    # the same trades cost more under crypto fills → smaller cost margin of safety
    tr = [{"entry": 100.0, "exit": 100.0 + p / 10, "qty": 10, "pnl": p}
          for p in [8, -5, 8, -5, 8, -5, 8, -5]]
    eq = cost_margin(tr, **{k: cost_profile("SPY")[k] for k in ("slippage_bps", "commission_per_share")})
    cr = cost_margin(tr, **{k: cost_profile("BTC-USD")[k] for k in ("slippage_bps", "commission_per_share")})
    assert cr["margin"] < eq["margin"]                # crypto's higher cost → lower margin
    assert cr["total_cost"] > eq["total_cost"]        # and a larger total modeled cost
