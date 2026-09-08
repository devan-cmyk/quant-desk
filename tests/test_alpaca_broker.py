"""Alpaca PAPER adapter — safety gates + order lifecycle, all offline via a mock HTTP client.
No network, no credentials. Real-money execution is intentionally absent from this adapter."""
import pytest

from quant_desk.execution.alpaca_broker import AlpacaBroker, BrokerDisabled, BrokerError
from quant_desk.execution.paper_broker import Fill


class _MockHTTP:
    """Canned Alpaca REST responses; records calls."""
    def __init__(self, fill_status="filled", avg=101.0):
        self.calls = []; self.fill_status = fill_status; self.avg = avg
    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "POST" and path == "/v2/orders":
            return {"id": "ord-1", "status": "new"}
        if path.startswith("/v2/orders/"):
            return {"id": "ord-1", "status": self.fill_status, "filled_avg_price": str(self.avg)}
        if path == "/v2/account":
            return {"status": "ACTIVE", "cash": "100000"}
        return {}


def _enable(monkeypatch):
    monkeypatch.setenv("QD_ALPACA_ENABLE", "1")
    monkeypatch.setenv("QD_ALPACA_KEY", "k"); monkeypatch.setenv("QD_ALPACA_SECRET", "s")


# ── safety gates (fail-secure) ─────────────────────────────────────────────────
def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("QD_ALPACA_ENABLE", raising=False)
    with pytest.raises(BrokerDisabled, match="disabled"):
        AlpacaBroker(http=_MockHTTP())


def test_requires_credentials(monkeypatch):
    monkeypatch.setenv("QD_ALPACA_ENABLE", "1")
    monkeypatch.delenv("QD_ALPACA_KEY", raising=False); monkeypatch.delenv("QD_ALPACA_SECRET", raising=False)
    with pytest.raises(BrokerDisabled, match="credentials"):
        AlpacaBroker(http=_MockHTTP())


def test_live_routing_is_hard_disabled_even_if_other_locks_exist(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("QD_ALLOW_LIVE_ENV", "1")
    with pytest.raises(BrokerDisabled, match="real-money order submission is intentionally disabled"):
        AlpacaBroker(paper=False, unlock_token="anything", http=_MockHTTP())


def test_paper_routing_arms_with_enable_and_creds(monkeypatch):
    _enable(monkeypatch)
    b = AlpacaBroker(http=_MockHTTP())
    assert b.paper and "paper-api" in b.base


# ── order lifecycle ────────────────────────────────────────────────────────────
def test_market_order_fills(monkeypatch):
    _enable(monkeypatch)
    m = _MockHTTP(fill_status="filled", avg=101.25)
    b = AlpacaBroker(http=m)
    f = b.fill("buy", 10, ref_price=101.0, symbol="SPY")
    assert isinstance(f, Fill) and f.fill_price == 101.25 and f.commission == 0.0
    assert ("POST", "/v2/orders", {"symbol": "SPY", "qty": 10, "side": "buy",
                                   "type": "market", "time_in_force": "day"}) in m.calls


def test_fill_requires_symbol(monkeypatch):
    _enable(monkeypatch)
    with pytest.raises(ValueError, match="symbol"):
        AlpacaBroker(http=_MockHTTP()).fill("buy", 10, 101.0)


def test_rejected_order_raises(monkeypatch):
    _enable(monkeypatch)
    b = AlpacaBroker(http=_MockHTTP(fill_status="rejected"))
    with pytest.raises(BrokerError, match="rejected"):
        b.fill("sell", 5, 100.0, symbol="QQQ")


def test_get_account_connectivity(monkeypatch):
    _enable(monkeypatch)
    assert AlpacaBroker(http=_MockHTTP()).get_account()["status"] == "ACTIVE"
