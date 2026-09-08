from __future__ import annotations

import json

import pytest

from quant_desk.execution.order_intent import (
    append_intent,
    build_order_intent,
    executed_externally,
    record_external_result,
    reject_intent,
)


def test_builds_auditable_human_confirmed_intent():
    intent = build_order_intent(
        symbol="spy",
        side="buy",
        quantity=2,
        order_type="limit",
        limit_price=500.25,
        strategy="manual-review-test",
        rationale="signal passed research and risk review",
        risk_snapshot={"max_loss_usd": 50.0},
    )
    assert intent.symbol == "SPY"
    assert intent.status == "staged"
    assert intent.human_confirmation_required is True
    assert intent.limit_price == 500.25
    assert intent.risk_snapshot["max_loss_usd"] == 50.0


def test_invalid_or_incomplete_intents_fail_closed():
    with pytest.raises(ValueError):
        build_order_intent(symbol="SPY", side="buy", quantity=0)
    with pytest.raises(ValueError):
        build_order_intent(symbol="SPY", side="buy", quantity=1, order_type="limit")
    with pytest.raises(ValueError):
        build_order_intent(symbol="SPY", side="buy", quantity=1, order_type="stop")


def test_intent_and_external_result_are_append_only_records(tmp_path):
    log = tmp_path / "order_intents.jsonl"
    intent = build_order_intent(symbol="QQQ", side="sell", quantity=1)
    append_intent(log, intent)

    result = executed_externally(
        intent.intent_id,
        broker="manual-broker-ui",
        external_order_id="example-123",
        filled_quantity=1,
        average_fill_price=450.0,
    )
    record_external_result(log, result)

    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows[0]["type"] == "order_intent"
    assert rows[0]["human_confirmation_required"] is True
    assert rows[1]["type"] == "external_execution"
    assert rows[1]["status"] == "executed_externally"


def test_rejection_is_recordable_without_execution(tmp_path):
    log = tmp_path / "order_intents.jsonl"
    intent = build_order_intent(symbol="IWM", side="buy", quantity=3)
    append_intent(log, intent)
    record_external_result(log, reject_intent(intent.intent_id, "human declined"))

    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows[-1]["status"] == "rejected"


def test_module_exposes_no_broker_submission_surface():
    import quant_desk.execution.order_intent as oi

    forbidden = {"submit_order", "place_order", "send_order", "execute_order", "broker_client"}
    assert forbidden.isdisjoint(set(dir(oi)))
