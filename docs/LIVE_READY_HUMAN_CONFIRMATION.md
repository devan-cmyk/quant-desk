# Live-ready trading with mandatory human execution

## Objective
Make Quant Desk useful against live market/account state without allowing the software, an AI agent, scheduler, or hosted service to submit a real-money order.

## What is enabled
- Alpaca **paper** order routing through `AlpacaBroker` when explicitly enabled.
- Read-only Alpaca account connectivity through `AlpacaReadOnlyClient`, including an explicitly configured live account.
- Durable order-intent staging through `execution.order_intent`.
- Durable recording of a human's external execution or rejection after independent review.
- Existing risk engine, committee gate, decay controls, reconciliation, and paper validation remain upstream of any staged intent.

## What remains locked
`AlpacaBroker(paper=False)` fails closed. Automated code cannot POST an order to a live Alpaca endpoint.

A real-money trade must be entered by the authorized account holder in the broker's own interface after reviewing the staged intent, current market conditions, account state, and broker disclosures.

## Intended flow
1. Strategy/research produces a candidate.
2. Existing committee/risk controls decide whether it is eligible to be staged.
3. Quant Desk creates an immutable `OrderIntent` containing symbol, side, quantity, order type, optional prices, strategy, rationale, and risk snapshot.
4. Human reviews the intent and current live account/market state.
5. Human either rejects it or manually enters an order in the broker interface.
6. Quant Desk records the external broker result for later reconciliation and track-record analysis.

## Evidence rules
- A staged intent is **not** a trade.
- A broker acknowledgement is not a fill.
- An external execution is recorded only from retained broker evidence supplied/read after the human action.
- Performance reporting must distinguish paper fills, staged intents, rejected intents, and externally executed live fills.

## Security rules
- Broker credentials never belong in source control.
- Read-only connectivity should use the least-privilege credentials available from the broker.
- Real-money order submission must not be reintroduced into scheduled agents or AI-driven paths.
- Any future live-execution design requires a separate security/legal/risk review and explicit owner-controlled broker action outside autonomous agent execution.
