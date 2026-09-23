# Changelog

All notable changes to this project are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
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
