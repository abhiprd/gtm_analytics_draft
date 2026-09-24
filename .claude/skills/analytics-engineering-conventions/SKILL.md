---
name: analytics-engineering-conventions
description: Reference when building any Phase 4+ analytics artifact (forecast, capacity planning, variance-diagnostic engine, or any of the other artifacts in the build spec's Section 8 list) for the Acme Corp GTM portfolio. Lighter-touch than dbt-conventions since Phase 4 hasn't started — this is forward-looking scaffolding, not a fully worked style guide.
---

# Analytics engineering conventions for Acme Corp (Phase 4+)

This is intentionally light. Don't over-build conventions for artifacts that don't exist yet — extend this skill as each wave's artifacts actually get built, per the build spec's priority order, rather than speculatively covering all 22 now.

## Applies to every artifact regardless of type

- Read business-input data from the finished marts layer only — never query `stg_`/`int_` models or raw sources directly from Phase 4 code. That layer is `dim_*` and `fact_*` models under `dbt/models/marts/` (dimensions and facts alike, not only `mart_*`-prefixed rollups) — all three subdirectories (`marts/dimensions`, `marts/facts`, `marts/marts`) are configured identically in `dbt_project.yml` (materialized as tables in the `main_marts` schema) and carry the same grain-comment/schema-test discipline. `mart_*` is a naming convention for cross-cutting rollups, not a different trust tier from `dim_*`/`fact_*` — a prefix-literal reading of "mart_* only" is stricter than the boundary this rule actually protects (reaching around the modeling layer into `stg_`/`int_`/raw), and has already produced a real defect: `analytics/variance_diagnostic.py`'s watchlist reads a segment-average ARR proxy from `mart_durability` instead of account-grain ARR from `fact_revenue_monthly`, solely because the latter is `fact_*`-prefixed — degenerating the watchlist to one segment. If a `dim_*`/`fact_*`/`mart_*` model doesn't expose what's needed, that's a Phase 2 gap to fix, not a reason to reach into `stg_`/`int_`/raw. The one named exception to the whole rule is `fact_model_performance_history` (below) — Phase 4 code both writes and reads it directly, since it's the model layer's own bookkeeping log, not business input a mart derives.
- Seed every stochastic step (train/test splits, any simulation, any sampling) for reproducibility.
- State the artifact's target accuracy/error bound explicitly before building it, the same way the QA plan states target AUC ranges for the health-score model — an artifact with no stated success criterion can't be validated later. Record this in `docs/acme-corp-analytics-methods.md`, not just in code comments.
- Every model or diagnostic function needs a one-line docstring stating its grain and its inputs' source mart(s).
- **Every model accepts an `as_of_date` parameter and uses only data available as of that date — no leakage from the future.** This isn't optional per-artifact; it's what makes backtesting and drift detection possible at all. A model that only knows how to compute "as of now" can't be checked against its own history later.

## Specific to the first artifacts in the priority order (Wave 1)

- **Account health score / churn-risk model**: respect the QA plan's login-frequency reweighting (higher weight in an account's first ~90 days, lower after) — don't rebuild this from scratch as a naive equal-weighted composite.
- **Variance-diagnostic engine**: the drill-down logic must walk the actual tree structure from `acme-corp-gtm-metric-tree.md` — identify the outlier Layer-2 child among its true siblings, not just flag that the Layer-1 parent moved. Respect each branch's real depth; don't fabricate a Layer 3 under a node that only has two layers.

## Where model-performance history lives

`fact_model_performance_history` (model_name, as_of_date, metric_name, metric_value) is the destination for every build-time validation and drift-monitor backtest checkpoint. It's backed by `data/model_performance_history.csv` — version-controlled like Phase 1 raw data, not written straight into `data/acme_gtm.duckdb`, which is gitignored and gets rebuilt from scratch (a table populated only via direct DuckDB inserts would lose its whole history on the next clean `dbt build`). Append to it via `analytics/model_performance.py`'s `log_performance()` — never write the CSV by hand and never insert into the DuckDB table directly.

## Statistical validation package — every predictive model, by artifact type

Every Phase 4 model captures a validation package appropriate to its type at build time, not just a single headline metric. `analytics-model-builder` produces it; `analytics-model-validator` independently recomputes the parts that are correctness claims (not merely descriptive) and confirms they match. Which elements apply depends on the artifact's shape:

**Classification models** (account health score today; lead/segmentation scoring later):
- Full fitted-coefficient (or feature-importance) table — every model input, not a grouped/aggregated subset. State explicitly whether coefficients are in raw-unit or standardized/encoded scale (a `StandardScaler` step means they are not directly "one unit of X" interpretable without unscaling).
- AUC on held-out data (already required).
- Confusion matrix — precision/recall/F1 — computed at the model's actual production operating threshold(s), never an arbitrary 0.5 cutoff. If the model uses quantile-based tiers (as the health score does), derive the confusion-matrix threshold the same way production does: a quantile cut over the scored population's probabilities, not a fixed probability.
- A calibration note: whether raw predicted probabilities reflect true frequencies, demonstrated with the lightest honest check available (e.g. mean predicted probability vs. actual base rate on held-out data) — no new library required. State plainly when `class_weight='balanced'` (or any other reweighting) breaks calibration, since a ranking-only score must never be read by a consumer as a calibrated probability.
- Sample sizes and class balance for both train and held-out splits.
- Confirmation that evaluation happened on held-out data, not in-sample.

**Regression models** (forecast — not yet built; capacity planning turned out not to be one, see below): R², RMSE/MAE on held-out data, full coefficient table, and residual diagnostics (at minimum: residuals-vs-fitted for non-random pattern, and a note on whether errors are roughly homoscedastic). Nothing exists yet to apply this to — that's expected, not a gap, per this doc's TBD convention; the checklist exists so the first regression model has a bar to build to instead of improvising one. Don't assume every artifact this list names in passing turns out to be this shape once actually built — verify against what the artifact's own inputs support, the way capacity planning did.

**Structural/logic artifacts** (the variance-diagnostic engine and capacity planning, both confirmed at build time): none of the above applies. There is no coefficient, no R², no confusion matrix — forcing one onto an artifact with no accuracy concept produces theater, not rigor. Each has its own correctness check appropriate to what it actually computes (the variance-diagnostic engine: synthetic test cases with known-correct answers — does it identify the true outlier Layer-2 child, respecting real tree depth; capacity planning: exact structural reconciliation — attainment tying to its source fact table, and the productivity/coverage/ramp-mix gap decomposition summing to the stated-quota-minus-expected-capacity identity to floating-point precision). Say so explicitly in the methods doc entry rather than leaving statistics fields blank/TBD, which would misleadingly imply they're still pending.

**Persistence**: single scalar metrics that make sense to track over time against a stated threshold (AUC, precision/recall/F1 at the operating threshold, calibration gap, confusion-matrix cell counts) go into `fact_model_performance_history` via `log_performance()`, one row per metric — same mechanism as `auc_holdout` today. Artifacts with no natural single-number/time-series shape (the full coefficient table; residual diagnostics) are recorded as a structured entry in `docs/acme-corp-analytics-methods.md` instead — this table's flat `(model_name, as_of_date, metric_name, metric_value)` grain fits a scalar time series, not a variable-width table like N coefficients.

**Model type selection and rationale**: every predictive model states, in the methods doc, why its model class was chosen over credible alternatives — tied to this artifact's actual constraints (need for direct interpretability, dataset size/dimensionality, what the score is actually used for downstream), not a default or arbitrary pick. Resolves the "which ML framework" question below for the concrete case each model actually faces, without pre-committing every future model to the same choice.

## Not yet decided, don't assume an answer

- Language/framework for Phase 4 beyond "Python" — no ML framework has been chosen
- Whether models get versioned/retrained on a schedule, or are one-off for the portfolio
