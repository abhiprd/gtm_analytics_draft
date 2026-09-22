# Acme Corp — Analytics methods

The Phase 4 equivalent of `acme-corp-gtm-metric-tree.md`: the source of truth for how each analytics artifact is built, what it's validated against, and when its performance has degraded enough to warrant review. Filled in as each artifact is actually built, per the build spec's priority order — not written speculatively ahead of the work.

An entry with no methodology yet is marked TBD, not omitted — the artifact's existence and its place in the priority order are already fixed by the build spec even before its method is chosen.

---

## Point-in-time discipline (applies to every entry below)

Every model in this doc must be computable as of any historical date using only data that existed up to that date — no leakage from the future. This is what makes backtesting and drift detection possible at all; see `analytics-engineering-conventions` for the coding rule this implies.

Historical performance is stored as a monthly time series, not sparse hand-picked checkpoints — `fact_model_performance_history` (model_name, as_of_date, metric_name, metric_value), an append-only log rather than a cross-cutting business mart. Any specific comparison ("today vs. a year ago") is a query against this series, not a separately-run one-off computation.

## Proxy-metric decoupling — general rule, applies to any Layer-3-to-Layer-2 relationship in the tree

A leaf is decoupling from its parent when the trailing 6-month correlation between them drops more than 30% relative to its trailing 12-month baseline, **while the leaf's own raw value has not declined**. That second condition is what distinguishes real decoupling (more meetings, not more wins) from a leaf simply falling off on its own (fewer meetings, naturally fewer wins) — the latter isn't decoupling, it's just decline, and the existing variance-diagnostic engine already handles it.

## Drift review trigger — general rule

Flag for review on **2 consecutive monthly checkpoints** below a stated threshold, never a single reading. One bad month is noise; two is a pattern. This applies uniformly — a specific entry below states its threshold, not a different consecutive-breach rule.

---

## Account health score / churn-risk model

- **Inputs**: usage trend (account-relative baseline), support ticket volume/severity, engagement/login frequency (reweighted per the QA plan — higher in an account's first ~90 days, lower after), AM sentiment notes
- **Target**: 0.65–0.80 AUC predicting eventual churn (QA plan grounding target)
- **Drift threshold**: AUC below 0.65 for 2 consecutive monthly checkpoints → flagged for review
- **Known limitation**: not yet validated against the QA plan's injected incidents specifically — first backtest run should confirm the model's AUC visibly dips at each injected-incident month, which both validates the drift detector and confirms the incidents are realistic

## Segment/lead scoring model

- **Inputs**: TBD — firmographic features at signup, per build spec Section 1's entry-scoring logic
- **Target**: TBD
- **Drift threshold**: TBD

## Forecast (sales bottoms-up / ML / CRO overlay reconciliation)

- **Inputs**: TBD
- **Target**: TBD
- **Drift threshold**: TBD

## Variance-diagnostic engine

- Not itself a predictive model — no AUC/accuracy target applies. Its correctness is structural (does it correctly identify the true outlier Layer-2 child), validated by `analytics-model-validator`, not by drift monitoring.

## Capacity planning

- **Inputs**: TBD
- **Target**: TBD
- **Drift threshold**: TBD
