"""Decision committee — the AQROS council, RULE-BASED and deterministic (no LLM that could
hallucinate a 'promote' on a strategy that blows up). Three specialist agents reason over the
real evidence packet (walk-forward, Monte-Carlo, stress, decay); the Chairman synthesizes
under HARD risk gates that cannot be voted away. Output is a reasoned, auditable verdict:

  promote      — validated; eligible to forward paper-trade
  paper_watch  — marginal; paper-trade but watch closely
  reject       — failed validation
  retire       — edge has decayed
"""
from __future__ import annotations

MAX_RUIN = 0.05            # >5% bootstrap risk-of-ruin → hard reject
MIN_TRADES = 20            # below this the sample is too thin to trust
MIN_PROFIT_FACTOR = 1.3


def _risk_officer(ev: dict) -> dict:
    st, mc = ev.get("stress", {}), ev.get("montecarlo", {})
    reasons, vote, conf = [], "promote", 0.7
    if not st.get("survived_all", True):
        vote, conf = "reject", 0.95
        reasons.append(f"fails a synthetic crisis (worst DD {st.get('worst_drawdown')})")
    ruin = mc.get("prob_ruin")
    if ruin is not None and ruin > MAX_RUIN:
        vote, conf = "reject", 0.95
        reasons.append(f"risk-of-ruin {ruin:.0%} exceeds {MAX_RUIN:.0%} cap")
    if vote == "promote":
        wdd = mc.get("maxdd_p95_worst")
        if wdd is not None and wdd < -0.15:
            vote, conf = "paper_watch", 0.6
            reasons.append(f"bad-case drawdown {wdd:.1%} — paper only")
        else:
            reasons.append(f"survives all crises; ruin {ruin if ruin is None else f'{ruin:.0%}'}")
    return {"agent": "RiskOfficer", "vote": vote, "confidence": conf, "reasons": reasons}


def _quant(ev: dict) -> dict:
    wf = ev.get("walkforward", {})
    oos, n, pf = wf.get("oos_return", 0.0), wf.get("num_trades", 0), wf.get("profit_factor")
    reasons = [f"OOS {oos:+.2%} on {n} trades, PF {pf if pf is None else round(pf,2)}"]
    if oos <= 0:
        return {"agent": "QuantResearch", "vote": "reject", "confidence": 0.8,
                "reasons": reasons + ["out-of-sample is not positive"]}
    if n < MIN_TRADES:
        return {"agent": "QuantResearch", "vote": "paper_watch", "confidence": 0.5,
                "reasons": reasons + [f"thin sample (<{MIN_TRADES} trades)"]}
    if (pf or 0) >= MIN_PROFIT_FACTOR:
        return {"agent": "QuantResearch", "vote": "promote", "confidence": 0.75,
                "reasons": reasons + ["positive OOS with adequate profit factor"]}
    return {"agent": "QuantResearch", "vote": "paper_watch", "confidence": 0.55,
            "reasons": reasons + ["edge present but weak"]}


def _contrarian(ev: dict) -> dict:
    wf, decay = ev.get("walkforward", {}), ev.get("decay", {})
    n = wf.get("num_trades", 0)
    status = decay.get("status")
    reasons = []
    if status == "retired":
        return {"agent": "Contrarian", "vote": "reject", "confidence": 0.85,
                "reasons": ["edge has already decayed (recent OOS negative)"]}
    if status == "watch":
        reasons.append("edge trending down — overfit risk")
        return {"agent": "Contrarian", "vote": "paper_watch", "confidence": 0.6, "reasons": reasons}
    if n < 15:
        return {"agent": "Contrarian", "vote": "paper_watch", "confidence": 0.5,
                "reasons": [f"too few trades ({n}) — could be luck"]}
    sharpe = wf.get("sharpe")
    if sharpe is not None and sharpe > 3 and n < 40:
        reasons.append(f"Sharpe {sharpe:.1f} on {n} trades looks too good — suspect overfit")
        return {"agent": "Contrarian", "vote": "paper_watch", "confidence": 0.55, "reasons": reasons}
    return {"agent": "Contrarian", "vote": "promote", "confidence": 0.55,
            "reasons": reasons + ["no obvious overfit tells"]}


def decide(evidence: dict) -> dict:
    votes = [_risk_officer(evidence), _quant(evidence), _contrarian(evidence)]
    st, mc, decay = evidence.get("stress", {}), evidence.get("montecarlo", {}), evidence.get("decay", {})

    # ── HARD GATES (cannot be voted away) ────────────────────────────────────
    if not st.get("survived_all", True) or (mc.get("prob_ruin") or 0) > MAX_RUIN:
        decision, why = "reject", "HARD RISK GATE: fails a crisis or ruin risk too high"
    elif decay.get("status") == "retired":
        decision, why = "retire", "edge decayed (recent OOS negative)"
    else:
        rejects = sum(v["vote"] == "reject" for v in votes)
        promotes = sum(v["vote"] == "promote" for v in votes)
        if rejects >= 2:
            decision, why = "reject", "majority reject"
        elif promotes >= 2 and rejects == 0:
            decision, why = "promote", "validated by the committee — eligible to paper-trade"
        else:
            decision, why = "paper_watch", "mixed verdict — paper-trade and monitor"

    conf = round(sum(v["confidence"] for v in votes) / len(votes), 2)
    dissent = [v["agent"] for v in votes if (v["vote"] == "reject") != (decision in ("reject", "retire"))]
    return {"decision": decision, "rationale": why, "confidence": conf,
            "votes": votes, "dissent": dissent}
