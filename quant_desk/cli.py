"""quant-desk CLI.  Examples:
  quant-desk mode                                  # show the safety posture
  quant-desk backtest --symbol SPY --strategy orb --interval 5m --days 30
"""
from __future__ import annotations

import argparse
import json

from .backtest.engine import run_backtest
from .config import settings
from .data.yfinance_provider import YFinanceProvider
from .logging import configure, get
from .risk.engine import RiskEngine
from .strategies import REGISTRY

log = get("cli")


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


def main() -> int:
    ap = argparse.ArgumentParser(prog="quant-desk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mode").set_defaults(fn=cmd_mode)
    b = sub.add_parser("backtest"); b.set_defaults(fn=cmd_backtest)
    b.add_argument("--symbol", default="SPY")
    b.add_argument("--strategy", default="orb")
    b.add_argument("--interval", default="5m")
    b.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    configure(settings.log_level)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
