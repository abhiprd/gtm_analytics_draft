# Changelog

All notable changes to this project are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- `gtm_plan_targets`: `expansion_consumption_revenue` and `contraction_churned_revenue` are now derived from the benchmark-blended `nrr`/`grr` anchors (`1 − grr**(1/12)`, and `nrr**(1/12) − 1 + that`, re-derived per plan year) instead of being set from standalone monthly shares of the revenue base. The standalone shares compounded to an annual GRR of ≈0.51 and NRR of ≈1.55 against plan rows stating ≈0.91 and ≈1.15, so the plan table stated the same identity two contradicting ways; the two halves now reconcile to machine precision. Adds a table-level regression check in `tests/test_phase1_batch5.py`, and restates the `nrr`/`grr` level-comparability caveat in `analytics/variance_diagnostic.py` and `docs/acme-corp-analytics-methods.md` to locate the remaining gap on the actuals side (gross contraction bucket scope) rather than in the plan generator

### Added
- Weekly executive readout (`analytics/weekly_readout.py`): assembles the variance-diagnostic engine's output into the build spec's readout structure — header, all 11 Layer-1 nodes grouped by pillar, variable-length drill-downs, and the health-score watchlist — and renders it as a Markdown deliverable under `analytics/outputs/`. Performs no business computation; every figure traces field-by-field to the artifact that owns it, verified by a 20-check structural/trace/rendered-document suite. Executive-summary narrative generation, automated playbook triggers, and forecast are carried as explicitly-statused sections rather than omitted or fabricated, with `assemble_readout()` as the structured seam a narrative step consumes
- Variance-diagnostic engine (`analytics/variance_diagnostic.py`): for any Layer-1 metric, computes variance from plan (or, for Activation, from a trailing baseline) and identifies the true outlier Layer-2 child among its tree siblings, with Layer-3 evidence surfaced where the branch and available marts support it. Enforces the metric tree's real layer structure programmatically — a node's layer is read from a single frozen tree definition, never assigned at emit time — and validated against a synthetic test suite with known-correct answers rather than a statistical accuracy target, per its structural/logic-artifact shape
- `gtm_plan_targets`: FP&A/RevOps plan values for ten of the metric tree's eleven Layer-1 nodes, generated on an annual planning cycle grounded in the QA plan's benchmark reference table and independently of any other generator's realized output (`generators/gtm_plan.py`), exposed through `stg_gtm_plan_targets` and `mart_gtm_plan`. Activation carries no plan row by design — the readout reports it against a trailing baseline instead
- Segment/segmentation migration analysis (`analytics/segment_migration.py`): migration velocity and trigger-reason mix by segment pair, time-in-prior-segment distribution, and graduated revenue, reconciled against `mart_growth_bridge`'s independently-computed migration MRR to floating-point precision
- Statistical validation package for Phase 4 predictive models (coefficients, confusion matrix at the production operating threshold, calibration check, relative input-importance breakdown, model-choice rationale), applied to the account health score and captured as a standing requirement in `analytics-engineering-conventions` and `analytics-model-builder`/`analytics-model-validator`
- `asset-brief-writer`'s "Technical validation" appendix section, reproducing a model's statistical validation package for a stats-literate reader alongside the plain-language brief
- Commit-msg githook enforcing Conventional Commits format and the repo's process-language restrictions, activated via `git config core.hooksPath .githooks`
- `fact_model_performance_history`: append-only log of Phase 4 model-eval checkpoints, backed by a version-controlled CSV and a Python logging helper (`analytics/model_performance.py`)
- `docs/acme-corp-analytics-methods.md`: methodology, validation target, and drift threshold reference for every Phase 4 artifact
- `analytics-model-builder`, `analytics-model-validator`, and `drift-monitor` agents for building, validating, and monitoring Phase 4 artifacts
- Initial repository scaffold: company model, GTM motion mechanics, metric tree, and Phase 1 data QA plan
- Three-segment GTM model (SMB, Commercial, Enterprise) with firmographic entry scoring and usage-based migration
- Consumption-based revenue model with a three-pillar diagnostic metric tree (Growth, Efficiency, Durability)
- Sample weekly executive readout demonstrating the tree's variance-diagnostic drill-down capability
- 22-artifact analytics portfolio plan with dependency-ordered build sequencing
- Phase 1 data generation QA plan: edge cases, grounding benchmarks, and test suite
- Claude Code project configuration (`CLAUDE.md`) and skill/agent set for dbt modeling, semantic layer construction, and repo hygiene
