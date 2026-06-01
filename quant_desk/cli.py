"""quant-desk CLI.  Examples:
  quant-desk mode                                  # show the safety posture
  quant-desk backtest --symbol SPY --strategy orb --interval 5m --days 30
"""
from __future__ import annotations

import argparse
import json
import os

from .backtest.engine import run_backtest
from .backtest.walkforward import walk_forward
from .backtest.multisymbol import multi_symbol_walkforward
from .selection.selector import select_symbols
from .live.portfolio import PaperPortfolio
from .live.paper_runner import run_forward
from .config import settings
from .data.yfinance_provider import YFinanceProvider
from .logging import configure, get
from .regime.filter import RegimeFilter
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
    rf = RegimeFilter() if a.regime else None
    res = run_backtest(df, strat_cls(), risk, regime_filter=rf)
    print(f"\n=== {a.strategy.upper()} on {a.symbol} ({a.interval}, {a.days}d, {len(df)} bars)"
          f"{' +regime' if rf else ''} ===")
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
    rf = RegimeFilter() if a.regime else None
    res = walk_forward(df, strat_cls, grid, is_sessions=a.is_sessions, oos_sessions=a.oos_sessions,
                       metric=a.metric, regime_filter=rf)
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


def cmd_multisymbol(a) -> int:
    strat_cls = REGISTRY.get(a.strategy)
    if not strat_cls:
        raise SystemExit(f"unknown strategy '{a.strategy}'. available: {list(REGISTRY)}")
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    prov = YFinanceProvider()
    data_fn = lambda sym: prov.bars(sym, interval=a.interval, lookback_days=a.days)
    rf = RegimeFilter() if a.regime else None
    res = multi_symbol_walkforward(symbols, strat_cls, PARAM_GRIDS.get(a.strategy, {}),
                                   data_fn=data_fn, regime_filter=rf,
                                   is_sessions=a.is_sessions, oos_sessions=a.oos_sessions)
    print(f"\n=== MULTI-SYMBOL WALK-FORWARD: {a.strategy.upper()}{' +regime' if rf else ''} "
          f"({len(symbols)} symbols, {a.interval}) ===")
    print(f"  {'symbol':8} {'OOS ret':>9} {'Sharpe':>8} {'PF':>6} {'win':>5} {'trades':>7}")
    for r in res["per_symbol"]:
        if "error" in r:
            print(f"  {r['symbol']:8} {'ERROR: ' + r['error'][:40]}"); continue
        sh = f"{r['sharpe']:+.2f}" if r["sharpe"] is not None else "  n/a"
        pf = f"{r['profit_factor']:.2f}" if r["profit_factor"] is not None else " n/a"
        print(f"  {r['symbol']:8} {r['oos_return']:+9.4f} {sh:>8} {pf:>6} {r['win_rate']:>5.2f} {r['trades']:>7}")
    s = res["summary"]
    print(f"\n  edge breadth: {s['symbols_positive_oos']}/{s['symbols_run']} symbols positive OOS · "
          f"{s['pooled_oos_trades']} pooled trades")
    print("\n--- POOLED Monte-Carlo (bootstrap, the robustness verdict) ---")
    print(json.dumps(res["pooled_monte_carlo"], indent=2, default=str))
    return 0


PAPER_STATE = os.path.expanduser("~/.quant-desk/paper_state.json")


def _data_fn(interval, days):
    prov = YFinanceProvider()
    return lambda sym: prov.bars(sym, interval=interval, lookback_days=days)


def cmd_select(a) -> int:
    strat_cls = REGISTRY[a.strategy]
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    rf = RegimeFilter() if a.regime else None
    res = select_symbols(symbols, strat_cls, PARAM_GRIDS.get(a.strategy, {}),
                         data_fn=_data_fn(a.interval, a.days), regime_filter=rf,
                         is_sessions=a.is_sessions, oos_sessions=a.oos_sessions)
    print(f"\n=== SYMBOL SELECTION: {a.strategy.upper()}{' +regime' if rf else ''} ===")
    print(f"  {'symbol':8} {'OOS ret':>9} {'PF':>6} {'trades':>7}  {'q':3} validated params")
    for r in res["ranking"]:
        if "error" in r:
            print(f"  {r['symbol']:8} ERROR"); continue
        pf = f"{r['profit_factor']:.2f}" if r["profit_factor"] is not None else " n/a"
        print(f"  {r['symbol']:8} {r['oos_return']:+9.4f} {pf:>6} {r['trades']:>7}  "
              f"{'✅ ' if r['qualified'] else '—  '} {r.get('best_params', {})}")
    print(f"\n  QUALIFIED UNIVERSE: {res['qualified'] or '(none cleared the bar)'}")
    print(f"  → each forward-traded with its own validated params: {res['selected_params']}")
    return 0


def cmd_monitor(a) -> int:
    from .monitor.decay import monitor_universe
    from .monitor.registry import Registry
    strat_cls = REGISTRY[a.strategy]
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    rf = RegimeFilter() if a.regime else None
    assessments = monitor_universe(symbols, strat_cls, PARAM_GRIDS.get(a.strategy, {}),
                                   data_fn=_data_fn(a.interval, a.days), regime_filter=rf,
                                   is_sessions=a.is_sessions, oos_sessions=a.oos_sessions)
    reg = Registry.load()
    changes = reg.update(a.strategy, assessments)
    reg.save()
    # journal the run + an immutable record for each retirement/recovery decision
    from .archive.journal import Journal
    jr = Journal()
    nh = sum(r["status"] == "healthy" for r in assessments)
    nr = sum(r["status"] == "retired" for r in assessments)
    jr.record("monitor", strategy=a.strategy, symbols=[r["symbol"] for r in assessments],
              summary=f"{nh} healthy, {nr} retired", payload={"assessments": assessments})
    for c in changes:
        kind = "retirement" if c["to"] == "retired" else "recovery"
        jr.record(kind, strategy=a.strategy, symbols=[c["symbol"]],
                  summary=f"{c['symbol']}: {c['from']} → {c['to']}",
                  decision=("edge decayed — retired" if c["to"] == "retired" else "edge recovered"))
    jr.close()
    icon = {"healthy": "✅", "watch": "⚠️", "retired": "💀", "insufficient_data": "·", "error": "✗"}
    num = lambda v, p: (format(v, p) if v is not None else "—")
    print(f"\n=== EDGE-DECAY MONITOR: {a.strategy.upper()}{' +regime' if rf else ''} ===")
    print(f"  {'symbol':8} {'status':16} {'recent OOS':>11} {'trend':>9} {'all-OOS':>9}")
    for r in assessments:
        label = f"{icon.get(r['status'], '')} {r['status']}"
        print(f"  {r['symbol']:8} {label:16} {num(r.get('recent_mean'), '+.4f'):>11} "
              f"{num(r.get('trend'), '+.5f'):>9} {num(r.get('oos_return'), '+.4f'):>9}")
    if changes:
        print("\n  ⚡ STATUS CHANGES since last run:")
        for c in changes:
            print(f"     {c['symbol']}: {c['from']} → {c['to']}")
    print(f"\n  ACTIVE (paper runner trades these): {reg.active(a.strategy) or '(none)'}")
    return 0


def cmd_stress(a) -> int:
    from .stress.lab import stress_test
    strat_cls = REGISTRY[a.strategy]
    df = YFinanceProvider().bars(a.symbol, interval=a.interval, lookback_days=a.days)
    rf = RegimeFilter() if a.regime else None
    res = stress_test(df, strat_cls, regime_filter=rf, ruin_drawdown=a.ruin)
    print(f"\n=== STRESS LAB: {a.strategy.upper()} on {a.symbol}{' +regime' if rf else ''} "
          f"(ruin at -{a.ruin:.0%} drawdown) ===")
    print(f"  {'scenario':18} {'return':>8} {'max DD':>8} {'worst trade':>12} {'trades':>7}  survived")
    for r in res["results"]:
        print(f"  {r['scenario']:18} {r['total_return']:+8.4f} {r['max_drawdown']:+8.4f} "
              f"{r['worst_trade']:>12.2f} {r['trades']:>7}  {'✅' if r['survived'] else '💀 RUIN'}")
    print(f"\n  worst drawdown across all crises: {res['worst_drawdown']:+.4f}  ·  "
          f"{'✅ SURVIVES ALL' if res['survived_all'] else '💀 DOES NOT SURVIVE'}")
    return 0


def cmd_paper_run(a) -> int:
    strat_cls = REGISTRY[a.strategy]
    data_fn = _data_fn(a.interval, a.days)
    rf = RegimeFilter() if a.regime else None
    params_by_symbol = None
    if a.select:
        sel = select_symbols([s.strip().upper() for s in a.symbols.split(",") if s.strip()],
                             strat_cls, PARAM_GRIDS.get(a.strategy, {}), data_fn=data_fn,
                             regime_filter=rf, is_sessions=a.is_sessions, oos_sessions=a.oos_sessions)
        symbols = sel["qualified"]
        params_by_symbol = sel["selected_params"]
        # honor the edge-decay registry: never trade a symbol the monitor has retired
        from .monitor.registry import Registry
        reg = Registry.load()
        retired = [s for s in symbols if reg.is_retired(a.strategy, s)]
        if retired:
            symbols = [s for s in symbols if s not in retired]
            params_by_symbol = {s: p for s, p in params_by_symbol.items() if s not in retired}
            print(f"excluded (edge decayed/retired): {retired}")
        print(f"selected universe + validated params: {params_by_symbol or '(none)'}")
    else:
        symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    if not symbols:
        raise SystemExit("no symbols to trade (selection returned empty)")
    pf = PaperPortfolio.load(PAPER_STATE)
    res = run_forward(symbols, strat_cls, data_fn=data_fn, portfolio=pf, regime_filter=rf,
                      params_by_symbol=params_by_symbol, max_bars=a.max_bars)
    pf.save(PAPER_STATE)
    from .archive.journal import Journal
    jr = Journal()
    jr.record("paper_run", strategy=a.strategy, symbols=symbols,
              summary=f"{res['bars_processed']} bars · equity {res['equity']} · {res['blotter_n']} total trades",
              payload={"bars": res["bars_processed"], "equity": res["equity"],
                       "open_positions": list(res["open_positions"])})
    jr.close()
    print(f"\n=== PAPER RUN (forward, paper-only) — {symbols} ===")
    print(json.dumps({k: v for k, v in res.items() if k != "actions"}, indent=2, default=str))
    print(f"\nrecent actions ({len(res['actions'])}):")
    for act in res["actions"][-10:]:
        print(f"  {act['ts']} {act['symbol']:6} {act['act']}" + (f"  pnl={act['pnl']:+.2f}" if "pnl" in act else f"  x{act.get('qty')}"))
    print(f"\nstate persisted → {PAPER_STATE}  (run again to continue the same paper account)")
    return 0


def cmd_journal(a) -> int:
    from .archive.journal import Journal
    jr = Journal()
    rows = jr.recent(a.n, kind=a.kind)
    print(f"\n=== RESEARCH & DECISION JOURNAL ({jr.count()} total records, append-only) ===")
    icon = {"monitor": "🔍", "retirement": "💀", "recovery": "🌱", "paper_run": "📈",
            "backtest": "🧪", "walkforward": "🚶", "stress": "🌪", "montecarlo": "🎲", "multisymbol": "🗂"}
    for r in rows:
        when = r["ts"][:16].replace("T", " ")
        print(f"  {when}  {icon.get(r['kind'], '·')} {r['kind']:11} {r['strategy']:5} "
              f"{r['summary']}" + (f"  → {r['decision']}" if r["decision"] else ""))
    if not rows:
        print("  (empty — runs are recorded as the monitor/paper-run/stress tools execute)")
    jr.close()
    return 0


def cmd_dashboard(a) -> int:
    try:
        import uvicorn
    except ImportError:
        raise SystemExit("dashboard needs extras: uv pip install -e '.[dashboard]'")
    print(f"quant-desk dashboard → http://{a.host}:{a.port}  (paper account, read-only)")
    uvicorn.run("quant_desk.dashboard.app:app", host=a.host, port=a.port, log_level="warning")
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
    b.add_argument("--regime", action="store_true", help="gate signals with the trend/chop filter")
    w = sub.add_parser("walkforward"); w.set_defaults(fn=cmd_walkforward)
    w.add_argument("--symbol", default="SPY")
    w.add_argument("--strategy", default="orb")
    w.add_argument("--interval", default="5m")
    w.add_argument("--days", type=int, default=58)
    w.add_argument("--is-sessions", type=int, default=15, dest="is_sessions")
    w.add_argument("--oos-sessions", type=int, default=5, dest="oos_sessions")
    w.add_argument("--metric", default="total_return")
    w.add_argument("--regime", action="store_true", help="gate signals with the trend/chop filter")
    ms = sub.add_parser("multisymbol"); ms.set_defaults(fn=cmd_multisymbol)
    ms.add_argument("--symbols", default="SPY,QQQ,IWM,AAPL,NVDA,MSFT")
    ms.add_argument("--strategy", default="orb")
    ms.add_argument("--interval", default="5m")
    ms.add_argument("--days", type=int, default=58)
    ms.add_argument("--is-sessions", type=int, default=15, dest="is_sessions")
    ms.add_argument("--oos-sessions", type=int, default=5, dest="oos_sessions")
    ms.add_argument("--regime", action="store_true", help="gate signals with the trend/chop filter")
    sl = sub.add_parser("select"); sl.set_defaults(fn=cmd_select)
    sl.add_argument("--symbols", default="SPY,QQQ,IWM,AAPL,NVDA,MSFT")
    sl.add_argument("--strategy", default="orb"); sl.add_argument("--interval", default="5m")
    sl.add_argument("--days", type=int, default=58)
    sl.add_argument("--is-sessions", type=int, default=15, dest="is_sessions")
    sl.add_argument("--oos-sessions", type=int, default=5, dest="oos_sessions")
    sl.add_argument("--regime", action="store_true")
    pr = sub.add_parser("paper-run"); pr.set_defaults(fn=cmd_paper_run)
    pr.add_argument("--symbols", default="SPY,QQQ,IWM,AAPL,NVDA,MSFT")
    pr.add_argument("--strategy", default="orb"); pr.add_argument("--interval", default="5m")
    pr.add_argument("--days", type=int, default=58)
    pr.add_argument("--is-sessions", type=int, default=15, dest="is_sessions")
    pr.add_argument("--oos-sessions", type=int, default=5, dest="oos_sessions")
    pr.add_argument("--select", action="store_true", help="trade only the qualified universe")
    pr.add_argument("--regime", action="store_true")
    pr.add_argument("--max-bars", type=int, default=78, dest="max_bars", help="forward bars to process")
    db = sub.add_parser("dashboard"); db.set_defaults(fn=cmd_dashboard)
    db.add_argument("--host", default="127.0.0.1"); db.add_argument("--port", type=int, default=8800)
    jo = sub.add_parser("journal"); jo.set_defaults(fn=cmd_journal)
    jo.add_argument("-n", type=int, default=40); jo.add_argument("--kind", default=None)
    mo = sub.add_parser("monitor"); mo.set_defaults(fn=cmd_monitor)
    mo.add_argument("--symbols", default="SPY,QQQ,IWM,AAPL,NVDA,MSFT")
    mo.add_argument("--strategy", default="orb"); mo.add_argument("--interval", default="5m")
    mo.add_argument("--days", type=int, default=58)
    mo.add_argument("--is-sessions", type=int, default=15, dest="is_sessions")
    mo.add_argument("--oos-sessions", type=int, default=5, dest="oos_sessions")
    mo.add_argument("--regime", action="store_true")
    ss = sub.add_parser("stress"); ss.set_defaults(fn=cmd_stress)
    ss.add_argument("--symbol", default="SPY"); ss.add_argument("--strategy", default="orb")
    ss.add_argument("--interval", default="5m"); ss.add_argument("--days", type=int, default=30)
    ss.add_argument("--ruin", type=float, default=0.25); ss.add_argument("--regime", action="store_true")
    a = ap.parse_args()
    configure(settings.log_level)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
