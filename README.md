# quant-desk

A modular, **paper-only-by-default** quantitative trading research platform. This repo is
the **spine** — the foundation a full multi-strategy desk grows on, built correctly first:
data abstraction → pluggable strategies → realistic backtest → **risk engine** → simulated
paper broker, with live execution locked behind a hard triple-lock.

> Survivability over aggressiveness. Nothing here can place a live order by default.

## Safety posture (read first)
Live trading is impossible unless **all four** hold (see `execution/live_guard.py`):
1. `settings.trading_mode == "live"`
2. env `QD_ALLOW_LIVE_ENV=1`
3. `settings.allow_live == True`
4. a runtime unlock token matching `settings.live_unlock_token`

Default is **paper**. The backtest and the paper broker never touch a live account.

## Architecture (clean, provider-abstracted)
```
quant_desk/
  config.py            pydantic settings — paper default + risk limits + live locks
  logging.py           structlog
  data/                DataProvider ABC + YFinanceProvider (parquet cache)   ← swap vendors freely
  strategies/          Strategy ABC + OpeningRangeBreakout   (REGISTRY for plug-in)
  risk/engine.py       sizing, daily-loss halt, exposure cap, cooldown, kill switch  ← core
  execution/           PaperBroker (slippage+commission) + live_guard (triple-lock)
  backtest/            event-loop engine (intrabar stop/target, EOD flatten) + metrics
  cli.py               `quant-desk mode` / `quant-desk backtest ...`
tests/                 strategy · risk · backtest · live-guard (synthetic data, no network)
```
Design: separation of concerns, provider abstraction, config-driven, the **risk engine
vetoes every entry** (strategies never size or place orders themselves).

## Quickstart
```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/pytest -q                                  # all tests, offline
.venv/bin/quant-desk mode                             # show the safety posture
.venv/bin/quant-desk backtest --symbol SPY --strategy orb --interval 5m --days 30
```

## Metrics
total return, CAGR, Sharpe, Sortino, Calmar, max drawdown, win rate, expectancy, profit
factor. (Ulcer/VaR/CVaR/recovery-factor bolt onto `backtest/metrics.py` the same way.)

## Autonomous operation (scheduled launchd agents)
The desk runs itself on a weekly research → daily paper-trade cadence over a **basket of
strategies** (`orb,meanrev,vwap,gapfade`): the committee reviews each independently and the runner trades
them together in one shared paper account (positions keyed `strategy:symbol`, P&L attributed
per strategy). The **decision committee** is the promotion gate (basket: `orb,meanrev,vwap,gapfade`): nothing reaches the paper
account it hasn't cleared, and approval is revoked the moment an edge decays. Install each with
`cp scripts/<agent>.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/<agent>.plist`.

| Agent | When | Does |
|---|---|---|
| `com.quantdesk.review`    | Sat 09:00 | Convenes the committee over the universe (walk-forward + Monte-Carlo + stress lab + decay), writes each **promote/paper_watch/reject/retire** verdict to the registry + append-only journal. |
| `com.quantdesk.reconcile` | Sat 09:30 | Compares each approved pair's **realized forward paper edge** against the profit factor it was promoted on; flags **drift** (edge absent live) — the feedback loop that catches overfit validation missed. |
| `com.quantdesk.monitor`   | Sat 10:00 | Re-assesses rolling out-of-sample health, **auto-retires** decayed symbols in the registry. |
| `com.quantdesk.allocate`  | Sat 10:30 | Measures the **correlation** of the approved edges' return streams and sets a diversification-aware per-pair **risk weight** the runner sizes against (risk-parity + correlation penalty), then **tilts toward edges that earn in the current regime** (trend vs chop, classified off a benchmark; bounded, falls back where data is thin). Not a return optimizer. |
| `com.quantdesk.alerts`    | Sat 11:00 | Diffs the gate vs the last snapshot and **alerts** on every pair that flipped TRADING↔BLOCKED or was newly approved — to a feed (dashboard reads it) + a macOS notification. External webhook off unless `QD_ALERT_WEBHOOK` is set. |
| `com.quantdesk.refresh`   | Wed 12:00 | **Walk-forward param refresh**: re-fits each promoted pair's params on the most recent window, adopting only refreshes that hold on a fresh holdout AND beat the deployed params. Keeps params current between reviews; never overfits (a refit that fails OOS is discarded) and never changes a verdict. |
| `com.quantdesk.paperrun`  | Weekdays 17:00 | `paper-run --select` — paper-trades only committee-approved pairs (`is_blocked` excludes anything rejected/retired). |
| `com.quantdesk.dashboard` | always-on (:8800) | FastAPI dashboard: account, per-strategy P&L, equity curve, **strategy gate** (kill-paths + allocation), **correlation heatmap**, gate alerts, research journal. |

The gate (`monitor/registry.py: is_blocked`) blocks a pair if the committee said
`reject`/`retire`, the decay monitor retired it, **or** forward reconciliation flagged
`drift`. Three independent kill-paths, one gate. Run them by hand anytime:
`quant-desk review --strategy orb --symbols SPY,QQQ,IWM,AAPL,NVDA,MSFT --regime` then
`quant-desk reconcile --strategy orb`. State is env-overridable for isolated runs
(`QD_REGISTRY`, `QD_JOURNAL`, `QD_PAPER_STATE`).

## Roadmap (what bolts onto this spine, in order)
1. More providers (Alpaca paper, Polygon) behind `DataProvider`; Redis hot cache.
2. More strategies (ORB short, RVOL momentum) via `REGISTRY` — orb + mean-reversion + VWAP-pullback + gap-fade already run as a basket.
3. Walk-forward + Monte Carlo + parameter sweeps in `backtest/`.
4. Options layer: chain/Greeks/IV provider + contract-selection scorer + spread strategies.
5. ML layer: regime classification, signal ranking (XGBoost/LightGBM) feeding the score.
6. Live broker adapter (Alpaca **paper** first) implementing `fill()` + calling `live_guard`.
7. Postgres persistence (signals/fills/backtests), Prometheus/Grafana, FastAPI dashboard.
8. The 5-agent LLM research council (research → peer review → chairman → backtest queue),
   which can propose/rank/queue but **cannot** trade live or relax risk limits.

Each is one tested increment — the spine never breaks.
