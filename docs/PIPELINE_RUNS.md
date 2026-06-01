# Pipeline run log

A human-readable record of full end-to-end pipeline runs (research → paper-trade). The runs
themselves write ephemeral state (`registry.json`, `journal.db`, `paper_state.json`) outside the
repo; this file is the durable summary. Each entry is one run of:

`review → reconcile → monitor → allocate → alerts → paper-run`

over the basket `orb,meanrev,vwap,gapfade` on the universe `SPY,QQQ,IWM,AAPL,NVDA,MSFT`
(5m bars, 58-day window, `--regime`). Paper-only; live execution stays behind the triple-lock.

---

## 2026-06-01 — first run with the full gate stack

Layers active: cost-aware committee hard gate, edge-quality ceiling, promotion probation,
correlation + regime-tilt allocation, forward reconciliation, decay monitor, gate alerting.

**Funnel**

| Stage | Result |
|---|---|
| pairs evaluated | 24 (6 symbols × 4 strategies) |
| cost gate | **18 hard-rejected** (edge dies under 2× modeled costs) |
| committee approved | **6** (promote / paper_watch) |
| probation | all 6 — freshly promoted, forward edge unproven → **half size** |
| reconcile | 6 probation, 0 drift |
| allocate | regime = **TREND**; correlation + regime tilt → weights |
| alerts | 6 newly-approved in the feed |
| paper-run | traded the 6 at probation-halved size (1 forward session) |

**Tradeable set after the gate**

| pair | committee | forward | effective risk× |
|---|---|---|---|
| gapfade:MSFT | paper_watch | probation | 0.846 |
| meanrev:IWM | promote | probation | 0.621 |
| orb:SPY | promote | probation | 0.613 |
| vwap:NVDA | promote | probation | 0.344 |
| orb:MSFT | paper_watch | probation | 0.370 |
| orb:NVDA | promote | probation | 0.207 |

**Account:** $99,731.53 · 5 trades (1 forward session) · −0.27%.

**Honest notes**
- The single forward session (−0.27%) is noise; probation's value is structural (it caps
  day-one risk on unproven edges), not visible in one day.
- In-sample full-window backfill context (separate exercise): the cost gate cut the basket's
  in-sample loss from −5.4% to −1.68% by refusing cost-fragile edges.
- These 5m strategies remain marginal net-of-cost on free data — the gates make the system
  *honest about costs and forward survival*, they do not manufacture an edge.
