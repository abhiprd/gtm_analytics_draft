---
name: analytics-engineering-conventions
description: Reference when building any Phase 4+ analytics artifact (forecast, capacity planning, variance-diagnostic engine, or any of the other artifacts in the build spec's Section 8 list) for the Acme Corp GTM portfolio. Lighter-touch than dbt-conventions since Phase 4 hasn't started — this is forward-looking scaffolding, not a fully worked style guide.
---

# Analytics engineering conventions for Acme Corp (Phase 4+)

This is intentionally light. Don't over-build conventions for artifacts that don't exist yet — extend this skill as each wave's artifacts actually get built, per the build spec's priority order, rather than speculatively covering all 22 now.

## Applies to every artifact regardless of type

- Read business-input data from `mart_*` tables only — never query `stg_`/`int_` models or raw sources directly from Phase 4 code. If a mart doesn't expose what's needed, that's a Phase 2 gap to fix, not a reason to reach around it. The one named exception is `fact_model_performance_history` (below) — Phase 4 code both writes and reads it directly, since it's the model layer's own bookkeeping log, not business input a mart derives.
- Seed every stochastic step (train/test splits, any simulation, any sampling) for reproducibility.
- State the artifact's target accuracy/error bound explicitly before building it, the same way the QA plan states target AUC ranges for the health-score model — an artifact with no stated success criterion can't be validated later. Record this in `docs/acme-corp-analytics-methods.md`, not just in code comments.
- Every model or diagnostic function needs a one-line docstring stating its grain and its inputs' source mart(s).
- **Every model accepts an `as_of_date` parameter and uses only data available as of that date — no leakage from the future.** This isn't optional per-artifact; it's what makes backtesting and drift detection possible at all. A model that only knows how to compute "as of now" can't be checked against its own history later.

## Specific to the first artifacts in the priority order (Wave 1)

- **Account health score / churn-risk model**: respect the QA plan's login-frequency reweighting (higher weight in an account's first ~90 days, lower after) — don't rebuild this from scratch as a naive equal-weighted composite.
- **Variance-diagnostic engine**: the drill-down logic must walk the actual tree structure from `acme-corp-gtm-metric-tree.md` — identify the outlier Layer-2 child among its true siblings, not just flag that the Layer-1 parent moved. Respect each branch's real depth; don't fabricate a Layer 3 under a node that only has two layers.

## Where model-performance history lives

`fact_model_performance_history` (model_name, as_of_date, metric_name, metric_value) is the destination for every build-time validation and drift-monitor backtest checkpoint. It's backed by `data/model_performance_history.csv` — version-controlled like Phase 1 raw data, not written straight into `data/acme_gtm.duckdb`, which is gitignored and gets rebuilt from scratch (a table populated only via direct DuckDB inserts would lose its whole history on the next clean `dbt build`). Append to it via `analytics/model_performance.py`'s `log_performance()` — never write the CSV by hand and never insert into the DuckDB table directly.

## Not yet decided, don't assume an answer

- Language/framework for Phase 4 beyond "Python" — no ML framework has been chosen
- Whether models get versioned/retrained on a schedule, or are one-off for the portfolio
