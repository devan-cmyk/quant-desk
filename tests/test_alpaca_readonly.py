from __future__ import annotations

from quant_desk.execution.alpaca_readonly import AlpacaReadOnlyClient


class _ReadOnlyHTTP:
    def __init__(self):
        self.paths = []

    def __call__(self, path):
        self.paths.append(path)
        if path == "/v2/account":
            return {"status": "ACTIVE"}
        if path == "/v2/positions":
            return [{"symbol": "SPY", "qty": "1"}]
        if path.startswith("/v2/orders"):
            return []
        raise AssertionError(path)


def test_live_account_reads_are_supported_without_order_submission_surface():
    mock = _ReadOnlyHTTP()
    client = AlpacaReadOnlyClient(paper=False, key="k", secret="s", http=mock)

    assert "api.alpaca.markets" in client.base
    assert client.get_account()["status"] == "ACTIVE"
    assert client.get_positions()[0]["symbol"] == "SPY"
    assert client.get_orders(status="open") == []

    forbidden = {"submit_order", "place_order", "send_order", "fill", "execute_order"}
    assert forbidden.isdisjoint(set(dir(client)))
    assert all(path.startswith("/v2/") for path in mock.paths)
