---
name: analytics-engineering-conventions
description: Reference when building any Phase 4+ analytics artifact (forecast, capacity planning, variance-diagnostic engine, or any of the other artifacts in the build spec's Section 8 list) for the Acme Corp GTM portfolio. Lighter-touch than dbt-conventions since Phase 4 hasn't started — this is forward-looking scaffolding, not a fully worked style guide.
---

# Analytics engineering conventions for Acme Corp (Phase 4+)

This is intentionally light. Don't over-build conventions for artifacts that don't exist yet — extend this skill as each wave's artifacts actually get built, per the build spec's priority order, rather than speculatively covering all 22 now.

## Applies to every artifact regardless of type

- Read from `mart_*` tables only — never query `stg_`/`int_` models or raw sources directly from Phase 4 code. If a mart doesn't expose what's needed, that's a Phase 2 gap to fix, not a reason to reach around it.
- Seed every stochastic step (train/test splits, any simulation, any sampling) for reproducibility.
- State the artifact's target accuracy/error bound explicitly before building it, the same way the QA plan states target AUC ranges for the health-score model — an artifact with no stated success criterion can't be validated later.
- Every model or diagnostic function needs a one-line docstring stating its grain and its inputs' source mart(s).

## Specific to the first artifacts in the priority order (Wave 1)

- **Account health score / churn-risk model**: respect the QA plan's login-frequency reweighting (higher weight in an account's first ~90 days, lower after) — don't rebuild this from scratch as a naive equal-weighted composite.
- **Variance-diagnostic engine**: the drill-down logic must walk the actual tree structure from `acme-corp-gtm-metric-tree.md` — identify the outlier Layer-2 child among its true siblings, not just flag that the Layer-1 parent moved. Respect each branch's real depth; don't fabricate a Layer 3 under a node that only has two layers.

## Not yet decided, don't assume an answer

- Language/framework for Phase 4 beyond "Python" — no ML framework has been chosen
- Whether models get versioned/retrained on a schedule, or are one-off for the portfolio
- Where Phase 4 output lives (a `models/` output directory vs. writing back into DuckDB as new marts) — decide this when Wave 1's variance engine is actually being built, not now
