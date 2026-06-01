"""PaperBroker fill model — the slippage + commission costs the entire cost-aware committee
and backtest realism depend on. Buys slip up, sells slip down; commission scales with qty."""
from quant_desk.execution.paper_broker import PaperBroker


def test_buy_slips_up_sell_slips_down():
    b = PaperBroker(slippage_bps=2.0, commission_per_share=0.005)
    buy = b.fill("buy", 100, 50.0)
    sell = b.fill("sell", 100, 50.0)
    assert buy.fill_price == round(50.0 * (1 + 2.0 / 1e4), 4)    # adverse: pays more
    assert sell.fill_price == round(50.0 * (1 - 2.0 / 1e4), 4)   # adverse: receives less
    assert buy.fill_price > 50.0 > sell.fill_price


def test_commission_scales_with_quantity():
    b = PaperBroker(slippage_bps=0.0, commission_per_share=0.005)
    assert b.fill("buy", 200, 10.0).commission == 1.0           # 0.005 × 200
    assert b.fill("sell", 1, 10.0).commission == 0.005


def test_zero_cost_config_is_frictionless():
    b = PaperBroker(slippage_bps=0.0, commission_per_share=0.0)
    f = b.fill("buy", 10, 123.45)
    assert f.fill_price == 123.45 and f.commission == 0.0


def test_round_trip_cost_is_positive_and_symmetric_in_qty():
    b = PaperBroker(slippage_bps=2.0, commission_per_share=0.005)
    # a buy-then-sell round trip on a flat price loses exactly the modeled friction
    qty, px = 100, 50.0
    buy, sell = b.fill("buy", qty, px), b.fill("sell", qty, px)
    pnl = (sell.fill_price - buy.fill_price) * qty - buy.commission - sell.commission
    assert pnl < 0                                              # friction always costs
    # slippage (2bps/side × $50 × 100 × 2) + commission ($0.005 × 100 × 2) = 2.00 + 1.00
    assert abs(pnl - (-3.0)) < 1e-6
