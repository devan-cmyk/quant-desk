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
from .live.paper_runner import run_forward, run_forward_multi
from .config import settings
from .data.yfinance_provider import YFinanceProvider
from .logging import configure, get
from .regime.filter import RegimeFilter
from .risk.engine import RiskEngine
from .strategies import REGISTRY

log = get("cli")

# parameter search grids per strategy (used by walk-forward optimization)
PARAM_GRIDS = {
    # min_strength is the conviction filter — the committee picks it out-of-sample, so the system
    # itself decides whether trading fewer, higher-conviction setups beats taking everything.
    "orb": {"or_minutes": [15, 30], "target_r": [1.5, 2.0, 3.0]},
    "vwap": {"target_r": [1.0, 1.5, 2.0], "touch": [0.0005, 0.001], "min_strength": [0.0, 0.4]},
    "meanrev": {"lookback": [20, 30], "entry_z": [2.0, 2.5], "stop_k": [1.0, 1.5], "min_strength": [0.0, 0.5]},
    "gapfade": {"min_gap": [0.002, 0.004], "stop_k": [1.0, 1.5]},
    # daily swing mean-reversion (validated on 1d bars with long history + larger WF folds)
    # NB: max_vol_ratio (the volatility circuit-breaker) is intentionally NOT in this grid — it's a
    # mandatory tail-risk control (always on, default 1.8), not optimized, because a walk-forward
    # over a calm window would always disable it. See DailyMeanReversion.
    "dmr": {"lookback": [20, 30], "entry_z": [1.5, 2.0], "stop_k": [2.0, 3.0], "max_hold_bars": [5, 10]},
}


def _sens_str(sn: dict) -> str:
    """One-line parameter-robustness summary for review output: plateau vs overfit spike."""
    frac = sn.get("frac_profitable")
    if frac is None:
        return sn.get("detail", "n/a")
    tag = "PLATEAU" if sn.get("robust", True) else "FRAGILE SPIKE — overfit risk"
    return f"{frac:.0%} of grid profitable OOS ({sn.get('n_combos', '?')} combos) → {tag}"


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


PAPER_STATE = os.environ.get("QD_PAPER_STATE") or os.path.expanduser("~/.quant-desk/paper_state.json")


def _data_fn(interval, days):
    prov = YFinanceProvider()
    return lambda sym: prov.bars(sym, interval=interval, lookback_days=days)


def _strategies(a) -> list[str]:
    """--strategy accepts a comma list so the whole basket (e.g. orb,meanrev) runs at once."""
    return [s.strip() for s in a.strategy.split(",") if s.strip()]


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
    from .archive.journal import Journal
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    rf = RegimeFilter() if a.regime else None
    reg, jr = Registry.load(), Journal()
    icon = {"healthy": "✅", "watch": "⚠️", "retired": "💀", "insufficient_data": "·", "error": "✗"}
    num = lambda v, p: (format(v, p) if v is not None else "—")
    for strat in _strategies(a):
        assessments = monitor_universe(symbols, REGISTRY[strat], PARAM_GRIDS.get(strat, {}),
                                       data_fn=_data_fn(a.interval, a.days), regime_filter=rf,
                                       is_sessions=a.is_sessions, oos_sessions=a.oos_sessions)
        changes = reg.update(strat, assessments)
        nh = sum(r["status"] == "healthy" for r in assessments)
        nr = sum(r["status"] == "retired" for r in assessments)
        jr.record("monitor", strategy=strat, symbols=[r["symbol"] for r in assessments],
                  summary=f"{nh} healthy, {nr} retired", payload={"assessments": assessments})
        for c in changes:
            kind = "retirement" if c["to"] == "retired" else "recovery"
            jr.record(kind, strategy=strat, symbols=[c["symbol"]],
                      summary=f"{c['symbol']}: {c['from']} → {c['to']}",
                      decision=("edge decayed — retired" if c["to"] == "retired" else "edge recovered"))
        print(f"\n=== EDGE-DECAY MONITOR: {strat.upper()}{' +regime' if rf else ''} ===")
        print(f"  {'symbol':8} {'status':16} {'recent OOS':>11} {'trend':>9} {'all-OOS':>9}")
        for r in assessments:
            label = f"{icon.get(r['status'], '')} {r['status']}"
            print(f"  {r['symbol']:8} {label:16} {num(r.get('recent_mean'), '+.4f'):>11} "
                  f"{num(r.get('trend'), '+.5f'):>9} {num(r.get('oos_return'), '+.4f'):>9}")
        if changes:
            print("\n  ⚡ STATUS CHANGES since last run:")
            for c in changes:
                print(f"     {c['symbol']}: {c['from']} → {c['to']}")
        # decay-health is NOT the trade gate: the runner trades committee-approved, non-blocked
        # pairs (and sizes probationary ones down). Show both so the display can't mislead.
        tradeable = [s for s in symbols
                     if reg.verdict(strat, s) in ("promote", "paper_watch") and not reg.is_blocked(strat, s)]
        print(f"\n  DECAY-HEALTHY (not retired by this monitor): {reg.active(strat) or '(none)'}")
        print(f"  RUNNER TRADES (committee-approved + not blocked): {tradeable or '(none)'}"
              + (f"  · probation (half size): {[s for s in tradeable if not reg.is_confirmed(strat, s)]}"
                 if tradeable else ""))
    reg.save(); jr.close()
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
    from .monitor.registry import Registry
    data_fn = _data_fn(a.interval, a.days)
    rf = RegimeFilter() if a.regime else None
    base_syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    reg = Registry.load()
    # one mandate per strategy → all trade in ONE shared paper account (run_forward_multi)
    mandates = []
    for strat in _strategies(a):
        strat_cls = REGISTRY[strat]
        params_by_symbol = None
        if a.select:
            # the committee gate is the source of truth: trade exactly the approved, non-blocked
            # pairs, sized with the validated params the committee stored at review time — no
            # redundant selection walk-forward at trade time. (Run `review` first to populate it.)
            symbols = [s for s in base_syms
                       if reg.verdict(strat, s) in ("promote", "paper_watch") and not reg.is_blocked(strat, s)]
            params_by_symbol = {s: reg.params(strat, s) for s in symbols}
            print(f"[{strat}] committee-approved (registry params): {params_by_symbol or '(none)'}")
        else:
            symbols = base_syms
        if symbols:
            # allocator weight × probation factor: a promoted pair trades at half size until its
            # forward edge is CONFIRMED (survives live); full size only after it earns it
            scales = {s: reg.effective_scale(strat, s) for s in symbols}
            probation = [s for s in symbols if not reg.is_confirmed(strat, s)]
            if probation:
                print(f"[{strat}] on probation (half size until forward-confirmed): {probation}")
            mandates.append({"name": strat, "cls": strat_cls, "symbols": symbols,
                             "params": params_by_symbol or {}, "regime_filter": rf,
                             "risk_scales": scales})
    if not mandates:
        raise SystemExit("no symbols to trade (selection/gate returned empty)")
    pf = PaperPortfolio.load(PAPER_STATE)
    res = run_forward_multi(mandates, data_fn=data_fn, portfolio=pf, max_bars=a.max_bars)
    pf.save(PAPER_STATE)
    traded = {m["name"]: m["symbols"] for m in mandates}
    all_syms = sorted({s for ss in traded.values() for s in ss})
    from .archive.journal import Journal
    jr = Journal()
    jr.record("paper_run", strategy=",".join(traded), symbols=all_syms,
              summary=f"{res['bars_processed']} bars · equity {res['equity']} · {res['blotter_n']} total trades · {traded}",
              payload={"bars": res["bars_processed"], "equity": res["equity"],
                       "mandates": traded, "open_positions": list(res["open_positions"])})
    jr.close()
    print(f"\n=== PAPER RUN (forward, paper-only, shared account) — {traded} ===")
    print(json.dumps({k: v for k, v in res.items() if k != "actions"}, indent=2, default=str))
    print(f"\nrecent actions ({len(res['actions'])}):")
    for act in res["actions"][-10:]:
        tag = f"{act.get('strategy','') or '·'}/{act['symbol']}"
        print(f"  {act['ts']} {tag:14} {act['act']}" + (f"  pnl={act['pnl']:+.2f}" if "pnl" in act else f"  x{act.get('qty')}"))
    print(f"\nstate persisted → {PAPER_STATE}  (run again to continue the same paper account)")
    return 0


def cmd_evaluate(a) -> int:
    from .council.evaluate import evaluate
    from .archive.journal import Journal
    strat_cls = REGISTRY[a.strategy]
    df = YFinanceProvider().bars(a.symbol, interval=a.interval, lookback_days=a.days)
    rf = RegimeFilter() if a.regime else None
    res = evaluate(df, strat_cls, PARAM_GRIDS.get(a.strategy, {}), regime_filter=rf,
                   is_sessions=a.is_sessions, oos_sessions=a.oos_sessions, symbol=a.symbol)
    if res.get("error"):
        raise SystemExit(res["error"])
    ev, c = res["evidence"], res["council"]
    print(f"\n=== COMMITTEE REVIEW: {a.strategy.upper()} on {a.symbol}{' +regime' if rf else ''} ===")
    w, mc, st, sn = ev["walkforward"], ev["montecarlo"], ev["stress"], ev.get("sensitivity", {})
    print(f"  evidence: OOS {w['oos_return']:+.2%} ({w['num_trades']} trades, PF "
          f"{w['profit_factor']}) · MC ruin {mc['prob_ruin']} · stress survives_all={st['survived_all']} "
          f"· decay {ev['decay'].get('status')}")
    print(f"  param-robustness: {_sens_str(sn)}")
    print("  deliberation:")
    for v in c["votes"]:
        print(f"    {v['agent']:14} → {v['vote']:12} ({v['confidence']:.2f})  {'; '.join(v['reasons'])}")
    verdict = {"promote": "✅ PROMOTE", "paper_watch": "⚠️ PAPER-WATCH", "reject": "💀 REJECT",
               "retire": "🪦 RETIRE"}.get(c["decision"], c["decision"])
    print(f"\n  CHAIRMAN: {verdict}  (confidence {c['confidence']})  —  {c['rationale']}")
    if c["dissent"]:
        print(f"  dissent: {c['dissent']}")
    jr = Journal()
    jr.record("council_decision", strategy=a.strategy, symbols=[a.symbol],
              summary=f"{a.symbol}: {c['decision']} (conf {c['confidence']})",
              decision=c["rationale"], payload={"evidence": ev, "council": c})
    jr.close()
    from .monitor.registry import Registry
    reg = Registry.load(); reg.set_verdict(a.strategy, a.symbol, c["decision"], c["rationale"])
    reg.set_params(a.strategy, a.symbol, ev.get("params", {})); reg.save()
    print("\n  → verdict recorded to the registry + journal (the runner now honors it)")
    return 0


def cmd_review(a) -> int:
    """Committee meeting: evaluate the whole universe — across every strategy in the basket —
    and write the verdicts the runner honors. The committee diversifies across strategies."""
    from .council.evaluate import evaluate
    from .archive.journal import Journal
    from .monitor.registry import Registry
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    rf = RegimeFilter() if a.regime else None
    data_fn = _data_fn(a.interval, a.days)
    reg, jr = Registry.load(), Journal()
    icon = {"promote": "✅", "paper_watch": "⚠️", "reject": "💀", "retire": "🪦"}
    for strat in _strategies(a):
        strat_cls = REGISTRY[strat]
        print(f"\n=== COMMITTEE REVIEW: {strat.upper()}{' +regime' if rf else ''} ===")
        for sym in symbols:
            try:
                res = evaluate(data_fn(sym), strat_cls, PARAM_GRIDS.get(strat, {}), regime_filter=rf,
                               is_sessions=a.is_sessions, oos_sessions=a.oos_sessions, symbol=sym)
            except Exception as e:
                print(f"  {sym:6} error: {str(e)[:60]}"); continue
            if res.get("error"):
                print(f"  {sym:6} {res['error']}"); continue
            c = res["council"]
            reg.set_verdict(strat, sym, c["decision"], c["rationale"])
            reg.set_params(strat, sym, res["evidence"].get("params", {}))
            jr.record("council_decision", strategy=strat, symbols=[sym],
                      summary=f"{sym}: {c['decision']} (conf {c['confidence']})", decision=c["rationale"],
                      payload={"evidence": res["evidence"], "council": c})
            print(f"  {sym:6} {icon.get(c['decision'], '')} {c['decision']:12} (conf {c['confidence']}) — {c['rationale']}")
            sn = res["evidence"].get("sensitivity", {})
            if sn.get("frac_profitable") is not None:
                print(f"  {'':6} ↳ param-robustness: {_sens_str(sn)}")
        tradeable = [s for s in symbols if reg.verdict(strat, s) in ("promote", "paper_watch")]
        print(f"  TRADEABLE [{strat}]: {tradeable or '(none)'}")
    reg.save(); jr.close()
    return 0


def cmd_reconcile(a) -> int:
    """Forward/backtest reconciliation: does each promoted pair's REALIZED paper edge match
    what the committee promoted it on? Drift (edge absent live) blocks the pair via the gate."""
    from .archive.journal import Journal
    from .monitor.registry import Registry
    from .live.portfolio import PaperPortfolio
    from .recon.reconcile import reconcile_account
    reg, jr = Registry.load(), Journal()
    pf = PaperPortfolio.load(PAPER_STATE)
    icon = {"ok": "✅", "drift": "🚨", "probation": "🌱", "insufficient_data": "·"}
    flagged = []
    for strat in _strategies(a):
        # reconcile the pairs the committee currently approves (or an explicit --symbols list)
        if a.symbols:
            symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
        else:
            symbols = [k.split(":", 1)[1] for k in reg.data if k.startswith(f"{strat}:")
                       and reg.verdict(strat, k.split(":", 1)[1]) in ("promote", "paper_watch")]
        results = reconcile_account(pf, jr, strat, symbols,
                                    min_trades=a.min_trades, drift_fraction=a.drift_fraction)
        print(f"\n=== FORWARD RECONCILIATION: {strat.upper()} (realized paper vs promoted) ===")
        for r in results:
            # ok = forward-confirmed (graduates to full size); probation = not enough live
            # evidence yet (trades small); drift = forward edge absent (blocked by is_blocked)
            fwd = "probation" if r["status"] == "insufficient_data" else r["status"]
            reg.set_forward(strat, r["symbol"], fwd, r["detail"])
            if r["status"] == "drift":
                flagged.append(f"{strat}:{r['symbol']}")
                jr.record("reconciliation", strategy=strat, symbols=[r["symbol"]],
                          summary=f"{r['symbol']}: DRIFT — {r['detail']}", decision="blocked (forward drift)",
                          payload=r)
            label = "confirmed" if fwd == "ok" else fwd
            print(f"  {r['symbol']:6} {icon.get(fwd, '·')} {label:17} "
                  f"PF {str(r['realized_pf']):>6} vs promoted {str(r['expected_pf']):>6}  "
                  f"exp {r['realized_expectancy']:+8.2f} n={r['n']}  — {r['detail']}")
    reg.save(); jr.close()
    if flagged:
        print(f"\n  🚨 BLOCKED for forward drift (the runner will now skip these): {flagged}")
    else:
        print("\n  no drift — every promoted pair's live edge matches its backtest.")
    return 0


def cmd_allocate(a) -> int:
    """Portfolio allocation: across the committee-approved pairs, measure how correlated their
    edges are and set a diversification-aware per-pair risk weight the runner sizes against."""
    from .monitor.registry import Registry
    from .archive.journal import Journal
    from .portfolio.allocate import session_returns, allocate, regime_session_labels
    reg, jr = Registry.load(), Journal()
    data_fn = _data_fn(a.interval, a.days)
    rf = RegimeFilter() if a.regime else None
    # the tradeable basket: every approved, non-blocked pair across the strategies
    returns_by_pair: dict = {}
    for strat in _strategies(a):
        strat_cls = REGISTRY[strat]
        syms = [k.split(":", 1)[1] for k in reg.data if k.startswith(f"{strat}:")
                and reg.verdict(strat, k.split(":", 1)[1]) in ("promote", "paper_watch")
                and not reg.is_blocked(strat, k.split(":", 1)[1])]
        for sym in syms:
            try:
                # backtest each edge with its COMMITTEE-VALIDATED params (walk-forward best),
                # so the correlation reflects the edge as actually promoted (falls back to defaults)
                params = reg.params(strat, sym)
                res = run_backtest(data_fn(sym), strat_cls(**params), RiskEngine(), regime_filter=rf)
                returns_by_pair[f"{strat}:{sym}"] = session_returns(res["trades"])
                if params:
                    print(f"  {strat}:{sym:6} params {params}")
            except Exception as e:
                print(f"  {strat}:{sym} backtest error: {str(e)[:50]}")
    if not returns_by_pair:
        print("\n  no committee-approved pairs to allocate across — run review/reconcile first.")
        return 0
    # regime-conditional tilt: classify each session (and the current one) off a benchmark
    regime_labels = current_regime = None
    if rf:
        try:
            bench = data_fn(a.benchmark).sort_index()
            regime_labels = regime_session_labels(bench, rf)
            current_regime = regime_labels[max(regime_labels)]
        except Exception as e:
            print(f"  (regime benchmark {a.benchmark} unavailable: {str(e)[:40]} — unconditional)")
    alloc = allocate(returns_by_pair, regime_labels=regime_labels, current_regime=current_regime)
    for pair, w in alloc["weights"].items():
        strat, _, sym = pair.partition(":")
        reg.set_allocation(strat, sym, w, alloc["scales"][pair])
    reg.save()
    jr.record("allocation", strategy=",".join(_strategies(a)), symbols=list(returns_by_pair),
              summary=f"{len(returns_by_pair)} pairs · {alloc['method']} · {alloc['n_obs']} sessions",
              decision=alloc["method"], payload={"weights": alloc["weights"], "scales": alloc["scales"],
              "corr": alloc["corr"], "n_obs": alloc["n_obs"],
              "current_regime": alloc.get("current_regime"), "tilts": alloc.get("tilts", {})})
    jr.close()
    rtag = f" · regime: {alloc.get('current_regime').upper()}" if alloc.get("current_regime") else ""
    print(f"\n=== PORTFOLIO ALLOCATION ({alloc['method']}, {alloc['n_obs']} sessions{rtag}) ===")
    tilted = any(t != 1.0 for t in alloc.get("tilts", {}).values())
    print(f"  {'pair':18} {'weight':>8} {'risk×':>7} {'tilt':>6}  avg|corr|" if tilted
          else f"  {'pair':18} {'weight':>8} {'risk×':>7}  avg|corr|")
    pairs = list(alloc["weights"])
    corr = alloc["corr"]
    for p in pairs:
        others = [abs(corr[p][q]) for q in pairs if q != p] or [0.0]
        tcol = f" {alloc['tilts'].get(p, 1.0):>5.2f}" if tilted else ""
        print(f"  {p:18} {alloc['weights'][p]*100:7.1f}% {alloc['scales'][p]:>6.2f}x{tcol}   {sum(others)/len(others):.2f}")
    if len(pairs) > 1:
        print("\n  correlation matrix:")
        print("  " + " " * 18 + " ".join(f"{p.split(':')[1][:6]:>7}" for p in pairs))
        for p in pairs:
            print(f"  {p:18} " + " ".join(f"{corr[p][q]:>7.2f}" for q in pairs))
    print("\n  → weights written to the registry; the paper runner sizes against them.")
    return 0


def cmd_refresh(a) -> int:
    """Walk-forward param refresh: re-fit each promoted pair's params on the most recent window,
    adopting only refreshes that hold on a fresh holdout. Keeps deployed params current between
    committee reviews without re-litigating the promotion (review owns the verdict)."""
    from .monitor.registry import Registry
    from .archive.journal import Journal
    from .refresh.refresh import refresh_params
    reg, jr = Registry.load(), Journal()
    rf = RegimeFilter() if a.regime else None
    data_fn = _data_fn(a.interval, a.days)
    n_refreshed = 0
    for strat in _strategies(a):
        strat_cls = REGISTRY[strat]
        grid = PARAM_GRIDS.get(strat, {})
        pairs = [k.split(":", 1)[1] for k in reg.data if k.startswith(f"{strat}:")
                 and reg.verdict(strat, k.split(":", 1)[1]) in ("promote", "paper_watch")
                 and not reg.is_blocked(strat, k.split(":", 1)[1]) and reg.params(strat, k.split(":", 1)[1])]
        if not pairs:
            continue
        print(f"\n=== PARAM REFRESH: {strat.upper()}{' +regime' if rf else ''} ===")
        for sym in pairs:
            cur = reg.params(strat, sym)
            try:
                res = refresh_params(data_fn(sym), strat_cls, grid, cur, regime_filter=rf,
                                     fit_sessions=a.fit_sessions, holdout_sessions=a.holdout_sessions)
            except Exception as e:
                print(f"  {sym:6} error: {str(e)[:50]}"); continue
            if res["adopt"]:
                reg.set_params(strat, sym, res["new"]); n_refreshed += 1
                jr.record("param_refresh", strategy=strat, symbols=[sym],
                          summary=f"{sym}: {cur} → {res['new']} (holdout {res['cur_oos']}→{res['new_oos']})",
                          decision="adopted refreshed params", payload=res)
                print(f"  {sym:6} ↻ {cur} → {res['new']}  holdout {res['cur_oos']:+.4f}→{res['new_oos']:+.4f} (n={res['new_trades']})")
            else:
                print(f"  {sym:6} · kept {cur}  ({res['reason']})")
    reg.save(); jr.close()
    print(f"\n  {n_refreshed} pair(s) refreshed; the runner sizes against the updated params.")
    return 0


def cmd_cost_curve(a) -> int:
    """Cost margin-of-safety diagnostic: how much execution cost can each edge absorb before it
    dies? Answers 'WHY do edges fail after costs' with a number, not a guess."""
    from .council.cost import cost_curve
    strat_cls = REGISTRY[a.strategy]
    rf = RegimeFilter() if a.regime else None
    data_fn = _data_fn(a.interval, a.days)
    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    print(f"\n=== COST MARGIN OF SAFETY: {a.strategy.upper()}{' +regime' if rf else ''} "
          f"({a.interval}, {a.days}d) — how much cost each edge absorbs before breakeven ===")
    from .costs import cost_profile
    from .execution.paper_broker import PaperBroker
    print(f"  {'symbol':9} {'class':6} {'trades':>6} {'net%':>7} {'margin':>7} {'tolerates':>9}  verdict")
    for sym in symbols:
        prof = cost_profile(sym)   # crypto fills + gate at ~30bps; equities at 2bps
        try:
            broker = PaperBroker(slippage_bps=prof["slippage_bps"], commission_per_share=prof["commission_per_share"])
            res = run_backtest(data_fn(sym), strat_cls(), RiskEngine(), broker=broker, regime_filter=rf)
        except Exception as e:
            print(f"  {sym:9} error: {str(e)[:50]}"); continue
        cc = cost_curve(res["trades"], slippage_bps=prof["slippage_bps"], commission_per_share=prof["commission_per_share"])
        m = cc["margin"]
        verdict = ("no edge net of cost" if m is None or m <= 0 else
                   f"fragile — dies at {cc['cost_tolerance_x']}× cost" if m < 1 else
                   f"robust — survives to {cc['cost_tolerance_x']}× cost")
        tol = f"{cc['cost_tolerance_x']}×" if cc["cost_tolerance_x"] is not None else "—"
        print(f"  {sym:9} {prof['asset_class']:6} {cc['n']:>6} {cc['base_return']*100:>6.2f}% {str(m):>7} {tol:>9}  {verdict}")
    print("\n  margin = extra cost-multiples absorbed before breakeven; ≥1.0 clears the 2× gate."
          "  (crypto gated at the realistic ~30bps cost, not equity 2bps.)")
    return 0


def cmd_live_tick(a) -> int:
    """One REAL-TIME decision cycle on the latest bar (not a replay): manage open positions,
    evaluate new entries on the current bar, route through the chosen broker. Idempotent per bar.
    Run this on a cadence (after the close for daily) — the correct forward-execution path."""
    from .monitor.registry import Registry
    from .live.realtime import live_tick
    data_fn = _data_fn(a.interval, a.days)
    rf = RegimeFilter() if a.regime else None
    reg = Registry.load()
    base_syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    mandates = []
    for strat in _strategies(a):
        approved = [s for s in base_syms
                    if reg.verdict(strat, s) in ("promote", "paper_watch") and not reg.is_blocked(strat, s)]
        if approved:
            mandates.append({"name": strat, "cls": REGISTRY[strat],
                             "symbols": approved, "params": {s: reg.params(strat, s) for s in approved},
                             "regime_filter": rf, "risk_scales": {s: reg.effective_scale(strat, s) for s in approved}})
    if not mandates:
        print("no committee-approved pairs to trade (run review first)"); return 0
    broker = None
    if a.broker == "alpaca":
        from .execution.alpaca_broker import AlpacaBroker
        broker = AlpacaBroker(paper=not a.live, unlock_token=a.unlock_token)   # fail-secure: needs QD_ALPACA_ENABLE etc.
    pf = PaperPortfolio.load(PAPER_STATE)
    res = live_tick(mandates, data_fn=data_fn, portfolio=pf, broker=broker)
    pf.save(PAPER_STATE)
    print(f"\n=== LIVE TICK ({a.broker}{'/LIVE' if a.live else '/paper'}) — equity {res['equity']} ===")
    for act in res["actions"]:
        print(f"  {act['ts']} {act.get('strategy','')}/{act['symbol']} {act['act']}"
              + (f" pnl={act['pnl']:+.2f}" if 'pnl' in act else f" x{act.get('qty')}"))
    print(f"  open: {list(res['open_positions'])}  ·  actions: {len(res['actions'])}")
    print(f"  state → {PAPER_STATE}")
    return 0


def cmd_backup(a) -> int:
    """Integrity-verified state backup / verify / restore for ~/.quant-desk."""
    from .backup import create_backup, verify_backup, restore_backup, list_backups, verify_state
    if a.list:
        bks = list_backups()
        print(f"\n=== STATE BACKUPS ({len(bks)}) ===")
        for b in bks: print(f"  {os.path.basename(b)}  ({os.path.getsize(b)//1024} KB)")
        return 0
    if a.verify:
        v = verify_backup(a.verify)
        print(f"\n=== VERIFY {os.path.basename(a.verify)} → {'✅ RESTORABLE' if v['restorable'] else '🔴 CORRUPT'} ===")
        for f, r in v["files"].items(): print(f"  {'✓' if r['ok'] else '✗'} {f:20} {r['detail']}")
        return 0 if v["restorable"] else 1
    if a.restore:
        target = a.restore if a.restore != "latest" else (list_backups()[-1] if list_backups() else None)
        if not target: raise SystemExit("no backups to restore")
        r = restore_backup(target)
        print(f"\n  ✅ restored {r['restored']} from {os.path.basename(target)}")
        print(f"  previous state stashed → {r['previous_state_saved_to']}")
        return 0
    # default: create a verified backup
    live = verify_state()
    res = create_backup()
    print(f"\n=== STATE BACKUP {'✅' if res['all_ok'] else '⚠️ SOURCE NOT CLEAN'} ===")
    print(f"  archive: {os.path.basename(res['archive'])}  ({res['n_files']} files)")
    for f, v in res["manifest"]["files"].items():
        print(f"    {'✓' if v['ok'] else '✗'} {f:20} {v['detail']}")
    if not res["all_ok"]:
        print("  ⚠ live state has integrity issues — backed up anyway, rotation skipped to preserve good backups")
    if res["rotated_out"]:
        print(f"  rotated out {len(res['rotated_out'])} old backup(s)")
    return 0 if res["all_ok"] else 1


def cmd_health(a) -> int:
    """System self-diagnostics: are the agents alive, the gate fresh, state intact? Continuous
    validation of the platform's real operational invariants; --alert pages on a degraded state."""
    from .health import system_health
    h = system_health()
    icon = {"critical": "🔴", "degraded": "🟡", "healthy": "🟢"}
    sev = {"critical": "🔴", "high": "🟠", "warn": "🟡", "info": "·"}
    print(f"\n=== SYSTEM HEALTH: {icon.get(h['status'])} {h['status'].upper()} ({h['score']}/100) ===")
    for c in h["checks"]:
        mark = "✓" if c["ok"] else sev.get(c["severity"], "✗")
        print(f"  {mark} {c['name']:16} {c['detail']}")
    if a.alert and h["status"] != "healthy":
        from .alerts.gate_alerts import AlertFeed, _notify_macos, _notify_webhook
        import datetime as _dt
        ev = [{"ts": _dt.datetime.now(_dt.timezone.utc).isoformat(), "pair": "SYSTEM",
               "kind": "health", "severity": "high",
               "message": f"system {h['status']} ({h['score']}/100): "
                          + "; ".join(f"{c['name']}: {c['detail']}" for c in h["issues"])}]
        f = AlertFeed(); f.append(ev); f.save()
        if not a.quiet:
            _notify_macos(ev); _notify_webhook(ev)
        print(f"\n  ⚠ alerted: system is {h['status']}")
    return 0 if h["status"] != "critical" else 1


def cmd_alerts(a) -> int:
    """Gate alerting: notify when a pair flips TRADING↔BLOCKED or is newly approved. Diffs the
    current gate against the last-alerted snapshot; appends to the feed + raises notifications."""
    from .monitor.registry import Registry
    from .alerts.gate_alerts import run_alerts, AlertFeed
    if a.list:
        for e in AlertFeed().recent(a.n):
            mark = "🚨" if e["severity"] == "high" else "·"
            print(f"  {e['ts'][:16].replace('T',' ')} {mark} {e['message']}")
        return 0
    if a.test:
        ev = [{"ts": __import__("datetime").datetime.now().isoformat(), "pair": "test:PAIR",
               "kind": "blocked", "severity": "high", "message": "test alert — channel check"}]
        from .alerts.gate_alerts import _notify_macos, _notify_webhook
        _notify_macos(ev); _notify_webhook(ev)
        print("  → fired a test alert through the configured channels (macOS/webhook).")
        return 0
    events = run_alerts(Registry.load(), notify=not a.quiet)
    if not events:
        print("\n  gate unchanged since last check — no alerts.")
        return 0
    print(f"\n=== GATE ALERTS ({len(events)} change{'s' if len(events) != 1 else ''}) ===")
    for e in events:
        mark = "🚨" if e["severity"] == "high" else "·"
        print(f"  {mark} {e['message']}")
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
    from . import __version__
    ap = argparse.ArgumentParser(prog="quant-desk", description="paper-only quant research toolkit")
    ap.add_argument("--version", action="version", version=f"quant-desk {__version__}")
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
    ev = sub.add_parser("evaluate"); ev.set_defaults(fn=cmd_evaluate)
    ev.add_argument("--symbol", default="SPY"); ev.add_argument("--strategy", default="orb")
    ev.add_argument("--interval", default="5m"); ev.add_argument("--days", type=int, default=58)
    ev.add_argument("--is-sessions", type=int, default=15, dest="is_sessions")
    ev.add_argument("--oos-sessions", type=int, default=5, dest="oos_sessions")
    ev.add_argument("--regime", action="store_true")
    rc = sub.add_parser("reconcile"); rc.set_defaults(fn=cmd_reconcile)
    rc.add_argument("--strategy", default="orb")
    rc.add_argument("--symbols", default=None, help="default: every committee-approved pair")
    rc.add_argument("--min-trades", type=int, default=8, dest="min_trades")
    rc.add_argument("--drift-fraction", type=float, default=0.6, dest="drift_fraction")
    al = sub.add_parser("allocate"); al.set_defaults(fn=cmd_allocate)
    al.add_argument("--strategy", default="orb,meanrev,vwap,gapfade")
    al.add_argument("--interval", default="5m"); al.add_argument("--days", type=int, default=58)
    al.add_argument("--regime", action="store_true")
    al.add_argument("--benchmark", default="SPY", help="symbol used to classify the market regime")
    rf2 = sub.add_parser("refresh"); rf2.set_defaults(fn=cmd_refresh)
    rf2.add_argument("--strategy", default="orb,meanrev,vwap")
    rf2.add_argument("--interval", default="5m"); rf2.add_argument("--days", type=int, default=58)
    rf2.add_argument("--fit-sessions", type=int, default=20, dest="fit_sessions")
    rf2.add_argument("--holdout-sessions", type=int, default=5, dest="holdout_sessions")
    rf2.add_argument("--regime", action="store_true")
    cc = sub.add_parser("cost-curve"); cc.set_defaults(fn=cmd_cost_curve)
    cc.add_argument("--strategy", default="orb"); cc.add_argument("--symbols", default="SPY,QQQ,IWM")
    cc.add_argument("--interval", default="5m"); cc.add_argument("--days", type=int, default=58)
    cc.add_argument("--regime", action="store_true")
    lt = sub.add_parser("live-tick"); lt.set_defaults(fn=cmd_live_tick)
    lt.add_argument("--strategy", default="dmr"); lt.add_argument("--symbols", default="SPY,QQQ,IWM,XLF,XLK,XLP,TLT")
    lt.add_argument("--interval", default="1d"); lt.add_argument("--days", type=int, default=730)
    lt.add_argument("--regime", action="store_true")
    lt.add_argument("--broker", choices=["sim", "alpaca"], default="sim")
    lt.add_argument("--live", action="store_true", help="alpaca: route REAL money (needs the triple-lock)")
    lt.add_argument("--unlock-token", default=None, dest="unlock_token")
    bk = sub.add_parser("backup"); bk.set_defaults(fn=cmd_backup)
    bk.add_argument("--list", action="store_true", help="list existing backups")
    bk.add_argument("--verify", metavar="ARCHIVE", help="verify an archive is restorable")
    bk.add_argument("--restore", metavar="ARCHIVE|latest", help="restore state from an archive")
    he = sub.add_parser("health"); he.set_defaults(fn=cmd_health)
    he.add_argument("--alert", action="store_true", help="page (feed + notify) if not healthy")
    he.add_argument("--quiet", action="store_true", help="with --alert: record but don't notify")
    al2 = sub.add_parser("alerts"); al2.set_defaults(fn=cmd_alerts)
    al2.add_argument("--list", action="store_true", help="show the recent alert feed")
    al2.add_argument("--test", action="store_true", help="fire a test alert through the channels")
    al2.add_argument("--quiet", action="store_true", help="record to the feed but don't notify")
    al2.add_argument("-n", type=int, default=30)
    rv = sub.add_parser("review"); rv.set_defaults(fn=cmd_review)
    rv.add_argument("--symbols", default="SPY,QQQ,IWM,AAPL,NVDA,MSFT")
    rv.add_argument("--strategy", default="orb"); rv.add_argument("--interval", default="5m")
    rv.add_argument("--days", type=int, default=58)
    rv.add_argument("--is-sessions", type=int, default=15, dest="is_sessions")
    rv.add_argument("--oos-sessions", type=int, default=5, dest="oos_sessions")
    rv.add_argument("--regime", action="store_true")
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
    rc = a.fn(a)
    # record a success heartbeat for scheduled commands → health can detect a stopped agent
    if rc in (0, None):
        from .health import record_heartbeat, CADENCE_DAYS
        cmd = a.fn.__name__[4:] if a.fn.__name__.startswith("cmd_") else a.fn.__name__
        if cmd in CADENCE_DAYS:
            record_heartbeat(cmd, interval=getattr(a, "interval", None))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
