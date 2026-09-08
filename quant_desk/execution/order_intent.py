"""Human-confirmed live order staging.

This module deliberately stops before broker submission. It creates durable, auditable
order *intents* that a human can review and manually enter in an authorized broker UI.
It may also record the result after the human executes (or rejects) the trade externally.

There is intentionally no broker client, submit_order(), place_order(), or network write
path here. Real-money execution remains outside quant-desk automation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
import json
import re
import uuid

Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop", "stop_limit"]
IntentStatus = Literal["staged", "rejected", "executed_externally", "expired"]

_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    created_at: str
    symbol: str
    side: Side
    quantity: float
    order_type: OrderType
    limit_price: float | None = None
    stop_price: float | None = None
    strategy: str = ""
    rationale: str = ""
    risk_snapshot: dict[str, Any] = field(default_factory=dict)
    status: IntentStatus = "staged"
    human_confirmation_required: bool = True


@dataclass(frozen=True)
class ExternalExecutionRecord:
    intent_id: str
    recorded_at: str
    status: Literal["executed_externally", "rejected"]
    broker: str | None = None
    external_order_id: str | None = None
    filled_quantity: float | None = None
    average_fill_price: float | None = None
    notes: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_order_intent(
    *,
    symbol: str,
    side: Side,
    quantity: float,
    order_type: OrderType = "market",
    limit_price: float | None = None,
    stop_price: float | None = None,
    strategy: str = "",
    rationale: str = "",
    risk_snapshot: dict[str, Any] | None = None,
) -> OrderIntent:
    symbol = symbol.strip().upper()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError("invalid symbol")
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if order_type not in {"market", "limit", "stop", "stop_limit"}:
        raise ValueError("unsupported order_type")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if order_type in {"limit", "stop_limit"} and (limit_price is None or limit_price <= 0):
        raise ValueError("limit order types require positive limit_price")
    if order_type in {"stop", "stop_limit"} and (stop_price is None or stop_price <= 0):
        raise ValueError("stop order types require positive stop_price")

    return OrderIntent(
        intent_id=str(uuid.uuid4()),
        created_at=_now(),
        symbol=symbol,
        side=side,
        quantity=float(quantity),
        order_type=order_type,
        limit_price=float(limit_price) if limit_price is not None else None,
        stop_price=float(stop_price) if stop_price is not None else None,
        strategy=strategy.strip(),
        rationale=rationale.strip(),
        risk_snapshot=dict(risk_snapshot or {}),
    )


def append_intent(path: str | Path, intent: OrderIntent) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "order_intent", **asdict(intent)}, sort_keys=True) + "\n")


def record_external_result(path: str | Path, record: ExternalExecutionRecord) -> None:
    """Record what a human did in the broker after independent review.

    This function does not contact a broker and cannot execute an order.
    """
    if record.status == "executed_externally":
        if not record.broker:
            raise ValueError("executed_external records require broker")
        if record.filled_quantity is not None and record.filled_quantity <= 0:
            raise ValueError("filled_quantity must be positive")
        if record.average_fill_price is not None and record.average_fill_price <= 0:
            raise ValueError("average_fill_price must be positive")
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "external_execution", **asdict(record)}, sort_keys=True) + "\n")


def reject_intent(intent_id: str, notes: str = "") -> ExternalExecutionRecord:
    return ExternalExecutionRecord(
        intent_id=intent_id,
        recorded_at=_now(),
        status="rejected",
        notes=notes,
    )


def executed_externally(
    intent_id: str,
    *,
    broker: str,
    external_order_id: str | None = None,
    filled_quantity: float | None = None,
    average_fill_price: float | None = None,
    notes: str = "",
) -> ExternalExecutionRecord:
    return ExternalExecutionRecord(
        intent_id=intent_id,
        recorded_at=_now(),
        status="executed_externally",
        broker=broker.strip(),
        external_order_id=external_order_id,
        filled_quantity=filled_quantity,
        average_fill_price=average_fill_price,
        notes=notes,
    )
