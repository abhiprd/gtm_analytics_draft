# CLAUDE.md

## Project

Acme Corp GTM Analytics Portfolio — a fictional company's simulated GTM analytics stack, built end-to-end: raw data generation → dbt models → semantic layer (MCP) → analytics artifacts → CRO dashboard. A portfolio project demonstrating GTM analytics, data engineering, and AI-context-layer design.

**Read `docs/acme-corp-gtm-portfolio-build-spec.md` first, every session.** It is the single source of truth for the company model, GTM motion, schema, build phases, and the full 22-artifact list with build priority order. Do not re-derive or contradict anything in it without flagging the conflict explicitly.

**Read `docs/acme-corp-gtm-metric-tree.md` before touching any metric definition.** Every metric's formula, owner, and layer depth is defined there. It is the only source of truth for metric definitions — never redefine a metric inline in code or in another doc.

**Read `docs/acme-corp-phase1-data-qa-plan.md` before writing or modifying any data generator.** It contains resolved design decisions, edge cases, grounding requirements, and the test suite the generated data must pass.

**Read `docs/acme-corp-analytics-methods.md` before building or evaluating any Phase 4 artifact.** It is the source of truth for each model's methodology, validation target, and drift threshold — the Phase 4 equivalent of the metric tree. Entries are filled in as each artifact is built, not written ahead of the work; an entry marked TBD is expected, not a gap to silently fill in yourself.

## Non-negotiable invariants

- Terminology is **segment**, not "tier" — SMB / Commercial / Enterprise. Never reintroduce "tier." "Segment" refers only to these three; industry and region are named as themselves, never called "segment."
- Every parent metric in the tree must be the actual mathematical result of its children (sum, product, or ratio) — never a "related metrics" grouping. The one deliberate exception is Brand & Awareness, explicitly marked as a non-additive leading indicator.
- No segment downgrade path. An account that fails to activate churns entirely; it never demotes to a lower segment.
- Currency is USD only. No FX modeling.
- Channel (how an account was acquired) and segment (what it is) are orthogonal. Never assume a channel implies a segment or vice versa.
- Migration `trigger_reason` has four values: `initial_firmographic`, `initial_default`, `usage_threshold`, `firmographic_rescore`. Both the usage-threshold and firmographic-rescore paths must actually fire in generated data, not just exist as unused schema values.
- All raw data is captured at event grain and aggregated in dbt — never pre-aggregate in the generator.
- Independently-random columns are a bug, not a feature. Win probability, churn probability, and usage growth must be generated as actual functions of their real drivers — every downstream diagnostic artifact needs real relationships in the data to find, not decoration.

## Current phase

Wave 1 of the 22-artifact priority order (build spec, Section 8) is built and validated end to end against real generated data: Metric tree → Account health score → Segment migration → Variance-diagnostic engine → Weekly executive readout. Phase 1 (raw data generation) and Phase 2 (dbt marts) are built and passing; Phase 4's first five artifacts are built, independently validated, and each has a `docs/asset-briefs/` entry. The weekly executive readout's executive-summary narrative (Claude API prose generation, per build spec Section 5) is a deliberately deferred, separate piece of work — not built here; the readout assembles everything else and leaves a documented seam for it. Next up is Wave 2 (Forecast, Capacity planning, Marketing attribution & channel mix — build spec Section 8).

## Repo structure

- `docs/` — the reference markdown files (do not edit one without checking cross-references in the others — see the `sync-portfolio-docs` skill). `docs/asset-briefs/` holds one plain-language, leadership-facing brief per built analytics asset (mart or Phase 4 model), maintained by `asset-brief-writer` — explicitly outside `sync-portfolio-docs`'s six-doc cross-reference set.
- `generators/` — Python Phase 1 raw data generators, one module per source system
- `data/raw/` — generator output (CSV/Parquet)
- `dbt/` — Phase 2 dbt-duckdb project
- `tests/` — the QA plan's test suite (pytest), run against generated and modeled data
- `semantic/` — Phase 3 MCP server + metric registry (generated from the tree file)
- `analytics/` — Phase 4 variance-diagnostic engine, forecast, capacity planning, etc.
- `dashboard/` — Phase 5 web app

## Stack

DuckDB · dbt-core (dbt-duckdb adapter) · Python · MCP Python SDK · Next.js or Streamlit (undecided — see build spec Section 7) · Claude API for the readout's narrative generation

## Available skills and agents

**Skills** (`.claude/skills/` — reference knowledge, loaded when relevant):
- `generate-gtm-data` — Phase 1 generator rules (edge cases, grounding, causal wiring)
- `validate-gtm-data` — the QA plan's test suite, execution order
- `sync-portfolio-docs` — checklist for propagating a change across all reference docs + deck
- `dbt-conventions` — layering, naming, materialization, testing for this project's dbt models
- `analytics-engineering-conventions` — light-touch conventions for Phase 4+ (extend as each artifact is built)
- `external-repo-conventions` — commit message and changelog rules; read before every commit
- `import-downloads` — routes a downloaded batch of project files into place; invoke explicitly via `/import-downloads`, never autonomously

**Agents** (`.claude/agents/` — isolated subagents for delegable tasks):
- `dbt-model-writer` — writes dbt models + schema.yml
- `dbt-test-runner` — writes/runs dbt tests, diagnoses failures against the QA plan
- `dbt-docs-writer` — maintains dbt's inline documentation, sourced from the metric tree
- `semantic-layer-builder` — generates/updates the MCP metric registry from the tree file
- `semantic-layer-validator` — checks registry correctness, guardrails, and NL-routing quality
- `analytics-model-builder` — builds any Phase 4 artifact (account health score, variance-diagnostic engine, forecast components, capacity planning, etc.) per the methods doc and analytics-engineering-conventions
- `analytics-model-validator` — one-time build-time check that a freshly built Phase 4 artifact meets its stated target; distinct from `drift-monitor`'s recurring production monitoring
- `repo-audit` — one-time/milestone scan of commit history and docs for process-revealing language before sharing the repo publicly; diagnostic only, run manually, not part of routine work
- `drift-monitor` — recurring production monitoring for model calibration drift and proxy-metric decoupling, checked against `docs/acme-corp-analytics-methods.md`'s stated thresholds; distinct from one-time build-time validation
- `asset-brief-writer` — writes/updates one plain-language leadership brief per built dbt mart or Phase 4 artifact under `docs/asset-briefs/`; distinct from `dbt-docs-writer` (schema.yml, technical audience) and `sync-portfolio-docs` (the six fixed reference docs)

## Repo hygiene

This repo is a shareable portfolio piece. Every commit follows `external-repo-conventions` — no reference to the design conversation, feedback, or back-and-forth that produced a change, in any commit message or diff. The one exception: the standard `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer stays on every commit Claude authors or co-authors — that's tooling attribution, not conversation narration. All revision history goes in `CHANGELOG.md`, not in commit messages and not as residue in the docs themselves. Run the `repo-audit` agent before the repo is ever made public or shared.

**On a fresh clone, run `git config core.hooksPath .githooks` once.** This activates the tracked commit-msg hook that mechanically rejects any commit violating Conventional Commits format or containing `external-repo-conventions`' red-flag terms. It doesn't self-activate — that config line is per-clone, not part of the repo's tracked state.

## Style

- Table and field names: `snake_case`, matching exactly what's named in the build spec and QA plan — don't invent an alternate name for something already specified
- Every new fact table needs a comment stating its grain
- Seed all randomness for reproducibility
