"""quant-desk CLI.  Examples:
  quant-desk mode                                  # show the safety posture
  quant-desk backtest --symbol SPY --strategy orb --interval 5m --days 30
"""
from __future__ import annotations

import argparse
import json

from .backtest.engine import run_backtest
from .backtest.walkforward import walk_forward
from .config import settings
from .data.yfinance_provider import YFinanceProvider
from .logging import configure, get
from .risk.engine import RiskEngine
from .strategies import REGISTRY

log = get("cli")

# parameter search grids per strategy (used by walk-forward optimization)
PARAM_GRIDS = {
    "orb": {"or_minutes": [15, 30], "target_r": [1.5, 2.0, 3.0]},
    "vwap": {"target_r": [1.0, 1.5, 2.0], "touch": [0.0005, 0.001]},
}


def cmd_mode(_a) -> int:
    print(json.dumps({
        "trading_mode": settings.trading_mode,
        "allow_live": settings.allow_live,
        "live_unlock_token_set": bool(settings.live_unlock_token),
        "note": "LIVE is locked until trading_mode=live AND QD_ALLOW_LIVE_ENV=1 AND "
                "allow_live=True AND a matching runtime unlock token. Default: PAPER ONLY.",
    }, indent=2))
    return 0


def cmd_backtest(a) -> int:
    strat_cls = REGISTRY.get(a.strategy)
    if not strat_cls:
        raise SystemExit(f"unknown strategy '{a.strategy}'. available: {list(REGISTRY)}")
    df = YFinanceProvider().bars(a.symbol, interval=a.interval, lookback_days=a.days)
    risk = RiskEngine()
    res = run_backtest(df, strat_cls(), risk)
    print(f"\n=== {a.strategy.upper()} on {a.symbol} ({a.interval}, {a.days}d, {len(df)} bars) ===")
    print(json.dumps(res["metrics"], indent=2, default=str))
    print(f"\ntrades: {len(res['trades'])}  (paper-only simulation)")
    for t in res["trades"][-8:]:
        print(f"  {t['entry_ts']:%m-%d %H:%M} {t['side']:5} x{t['qty']:>4} "
              f"{t['entry']:.2f}->{t['exit']:.2f} [{t['reason']}] pnl={t['pnl']:+.2f}")
    return 0


def cmd_walkforward(a) -> int:
    strat_cls = REGISTRY.get(a.strategy)
    if not strat_cls:
        raise SystemExit(f"unknown strategy '{a.strategy}'. available: {list(REGISTRY)}")
    df = YFinanceProvider().bars(a.symbol, interval=a.interval, lookback_days=a.days)
    grid = PARAM_GRIDS.get(a.strategy, {})
    res = walk_forward(df, strat_cls, grid, is_sessions=a.is_sessions, oos_sessions=a.oos_sessions,
                       metric=a.metric)
    if res.get("error"):
        raise SystemExit(res["error"] + f" (have {len(set(df.index.tz_convert('America/New_York').date))} sessions)")
    print(f"\n=== WALK-FORWARD {a.strategy.upper()} on {a.symbol} "
          f"(IS={a.is_sessions} / OOS={a.oos_sessions} sessions, optimize {a.metric}) ===")
    for f in res["folds"]:
        print(f"  IS {f['is'][0]}→{f['is'][1]}  best={f['best_params']} (is {a.metric}={f['is_score']})"
              f"  →  OOS {f['oos'][0]}→{f['oos'][1]}  ret={f['oos_return']:+.4f} ({f['oos_trades']} trades)")
    print("\n--- aggregate OUT-OF-SAMPLE (the honest number) ---")
    print(json.dumps(res["oos_metrics"], indent=2, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="quant-desk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mode").set_defaults(fn=cmd_mode)
    b = sub.add_parser("backtest"); b.set_defaults(fn=cmd_backtest)
    b.add_argument("--symbol", default="SPY")
    b.add_argument("--strategy", default="orb")
    b.add_argument("--interval", default="5m")
    b.add_argument("--days", type=int, default=30)
    w = sub.add_parser("walkforward"); w.set_defaults(fn=cmd_walkforward)
    w.add_argument("--symbol", default="SPY")
    w.add_argument("--strategy", default="orb")
    w.add_argument("--interval", default="5m")
    w.add_argument("--days", type=int, default=58)
    w.add_argument("--is-sessions", type=int, default=15, dest="is_sessions")
    w.add_argument("--oos-sessions", type=int, default=5, dest="oos_sessions")
    w.add_argument("--metric", default="total_return")
    a = ap.parse_args()
    configure(settings.log_level)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
