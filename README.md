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

## Roadmap (what bolts onto this spine, in order)
1. More providers (Alpaca paper, Polygon) behind `DataProvider`; Redis hot cache.
2. More strategies (VWAP pullback, ORB short, mean-reversion, RVOL momentum) via `REGISTRY`.
3. Walk-forward + Monte Carlo + parameter sweeps in `backtest/`.
4. Options layer: chain/Greeks/IV provider + contract-selection scorer + spread strategies.
5. ML layer: regime classification, signal ranking (XGBoost/LightGBM) feeding the score.
6. Live broker adapter (Alpaca **paper** first) implementing `fill()` + calling `live_guard`.
7. Postgres persistence (signals/fills/backtests), Prometheus/Grafana, FastAPI dashboard.
8. The 5-agent LLM research council (research → peer review → chairman → backtest queue),
   which can propose/rank/queue but **cannot** trade live or relax risk limits.

Each is one tested increment — the spine never breaks.
