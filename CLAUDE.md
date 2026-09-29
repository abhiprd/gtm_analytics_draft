# CLAUDE.md

## Project

Acme Corp GTM Analytics Portfolio — a fictional company's simulated GTM analytics stack, built end-to-end: raw data generation → dbt models → semantic layer (MCP) → analytics artifacts → CRO dashboard. A portfolio project demonstrating GTM analytics, data engineering, and AI-context-layer design.

**Read `docs/acme-corp-gtm-portfolio-build-spec.md` first, every session.** It is the single source of truth for the company model, GTM motion, schema, build phases, and the full 22-artifact list with build priority order. Do not re-derive or contradict anything in it without flagging the conflict explicitly.

**Read `docs/acme-corp-gtm-metric-tree.md` before touching any metric definition.** Every metric's formula, owner, and layer depth is defined there. It is the only source of truth for metric definitions — never redefine a metric inline in code or in another doc.

**Read `docs/acme-corp-phase1-data-qa-plan.md` before writing or modifying any data generator.** It contains resolved design decisions, edge cases, grounding requirements, and the test suite the generated data must pass.

**Read `docs/acme-corp-analytics-methods.md` before building or evaluating any Phase 4 artifact.** It is the source of truth for each model's methodology, validation target, and drift threshold — the Phase 4 equivalent of the metric tree. Entries are filled in as each artifact is built, not written ahead of the work; an entry marked TBD is expected, not a gap to silently fill in yourself.

## Non-negotiable invariants

- Terminology is **segment**, not "tier" — SMB / Commercial / Enterprise. Never reintroduce "tier." "Segment" refers only to these three; industry and region are named as themselves, never called "segment."
- Every parent metric in the tree must be the actual mathematical result of its children (sum, product, or ratio) — never a "related metrics" grouping. Two deliberate exceptions, both explicitly marked non-additive in the tree's own text: Brand & Awareness (a leading indicator, not summed into the pipeline math) and Marketing–sales handoff quality (a diagnostic overlay on New Logo's three multiplicative factors, not a fourth factor).
- No segment downgrade path. An account that fails to activate churns entirely; it never demotes to a lower segment.
- Currency is USD only. No FX modeling.
- Channel (how an account was acquired) and segment (what it is) are orthogonal. Never assume a channel implies a segment or vice versa.
- Migration `trigger_reason` has four values: `initial_firmographic`, `initial_default`, `usage_threshold`, `firmographic_rescore`. Both the usage-threshold and firmographic-rescore paths must actually fire in generated data, not just exist as unused schema values.
- All raw data is captured at event grain and aggregated in dbt — never pre-aggregate in the generator.
- Independently-random columns are a bug, not a feature. Win probability, churn probability, and usage growth must be generated as actual functions of their real drivers — every downstream diagnostic artifact needs real relationships in the data to find, not decoration.

## Current phase

All seven waves of the 22-artifact priority order (build spec, Section 8) are built and validated end to end against real generated data. Phase 1 and Phase 2 are built and passing. Full per-wave detail lives in `CHANGELOG.md`; this section stays a current-state pointer, not a running history:

- **Wave 1**: Metric tree → Account health score → Segment migration → Variance-diagnostic engine → Weekly executive readout.
- **Wave 2**: Capacity planning, Forecast, Marketing attribution & channel mix — extended Phase 1 with `fact_forecast_submissions`/`cro_forecast_adjustments` and `campaigns`/`leads`/`campaign_engagement_events`, plus a `quota_history` fix (attainment moved from a structurally unreachable 12.9% to a realistic 84–95%).
- **Wave 3**: Data quality / metric governance (`analytics/data_quality_governance.py`) and the Semantic layer / AI context layer (`semantic/` — MCP server + metric registry; needs a dedicated Python 3.12 venv at `semantic/.venv`, see `semantic/README.md`).
- **Wave 4**: Deal-level diagnostics, Rep productivity & coaching diagnostics, Automated playbook triggers — extended Phase 1/2 with `fact_sales_activities` (`generators/sales_activities.py`), event-grain rep-opportunity engagement data.
- **Wave 5**: Territory / account coverage & routing, TAM / ICP / opportunity-sizing model, Pricing / packaging analytics — territory coverage extended Phase 1/2 with a territory dimension (`generators/territories.py`); TAM/ICP and Pricing/packaging needed no new raw data.
- **Wave 6**: MMM / incrementality-based measurement (`analytics/mmm_incrementality.py` — a media-mix regression extending incrementality estimation past `marketing_attribution.py`'s holdout-only channels; the build spec's own pre-flagged concern about a thin 36-month time series is borne out honestly — no channel's effect clears significance, and the model's point estimate for paid/community disagrees with the holdout method, which is the one to trust where both exist), Scenario planning / sensitivity analysis (`analytics/scenario_planning.py` — propagates a hypothetical input change through the metric tree's real equations by reusing `variance_diagnostic.py`'s tree structure, never a competing copy), and Retention / expansion cohort analytics (`analytics/retention_cohorts.py` — quarterly acquisition-vintage cohorts; the headline finding is contract-structure showing up directly in the retention curves, SMB eroding smoothly from month 1 while Commercial/Enterprise stay flat near 100% until a sharp cliff at their contract renewal month). None of the three needed new raw data.
- **Wave 7** (last by build-spec necessity, since none of the three is computable meaningfully until real history accumulates): Lead/segmentation scoring model validation & drift detection (`analytics/lead_scoring_validation.py` — validates the existing fixed firmographic score against real lead-conversion outcomes rather than fitting a new one; a real, dateable model-version change partway through the company's history produces a small, causally-isolated discrimination improvement, separated carefully from calendar-time confounding), Testing/experimentation methodology & platform (`analytics/experimentation_platform.py` — a reusable evaluation framework proven by independently re-deriving the one real randomized experiment this project has, matching its already-published result almost exactly), and Proxy-metric health / analytics investment prioritization (`analytics/proxy_metric_health.py` — a governance catalog, not a fabricated trend tool; its own headline finding is that this project's analytics-monitoring history is still too thin, 1–3 checkpoints per model, for any genuine drift claim, stated plainly rather than manufactured around; it also found a real, immediately actionable win, a data gap marked unbuilt that a different already-shipped artifact had already closed). Lead-scoring validation and the experimentation platform each needed a new Phase 1/2 extension (`lead_scoring_history` via `generators/lead_scoring.py`, reusing `compute_fit_score()`'s real logic rather than a new formula; `experiments_registry`/`experiment_assignment` via `generators/experiments.py`, cataloging the real marketing holdout program already built in Wave 2 rather than inventing a second experiment). Proxy-metric health needed no new data.

All twenty `analytics/*.py` Phase 4 artifacts across Waves 1–7 are built and independently validated, each with a `docs/asset-briefs/` entry. The metric tree itself (build spec item #1, Wave 1) and the semantic layer (Phase 3 infrastructure) are also built and validated but sit outside this count — neither is an `analytics/*.py` module, and neither takes a `docs/asset-briefs/` entry (the semantic layer's equivalent is `semantic/README.md`). The weekly executive readout's executive-summary narrative (Claude API prose generation, per build spec Section 5) remains a deliberately deferred, separate piece of work — not built here; the readout assembles everything else and leaves a documented seam for it. This closes the build spec's full 22-artifact priority order (Section 8) — three items (quota setting, LTV:CAC/marginal-CAC economics, customer journey/time-to-value) were, per the spec's own design, absorbed into other artifacts rather than built standalone.

- **Wave 8 (Phase 5 — CRO / leadership interface):** the digest view, forecast view, segment-efficiency view, and chat demo called for in Section 6's scope guardrail (`dashboard/`, Streamlit — see `dashboard/README.md` for the framework rationale and Section 7). Reads only from finished marts, `analytics/outputs/` readout JSON, and `analytics/forecast.py`/`semantic/server.py` called in-process; introduces no new computation of its own. The chat page's natural-language routing is deterministic keyword/substring matching against the semantic layer's own whitelisted registry, not an LLM call — routing it through the Claude API instead is left as an open seam, the same deliberate-deferral treatment already given the weekly readout's executive-summary narrative.

Every phase in the build spec's system diagram (Section 1) is now built. The two deliberately deferred seams — the executive-summary narrative and the chat page's live NL routing, both Claude-API integrations — are the only remaining unbuilt pieces, and both are documented seams, not gaps.

## Repo structure

- `docs/` — the reference markdown files (do not edit one without checking cross-references in the others — see the `sync-portfolio-docs` skill). `docs/asset-briefs/` holds one plain-language, leadership-facing brief per built analytics asset (mart or Phase 4 model), maintained by `asset-brief-writer` — explicitly outside `sync-portfolio-docs`'s six-doc cross-reference set.
- `generators/` — Python Phase 1 raw data generators, one module per source system
- `data/raw/` — generator output (CSV/Parquet)
- `dbt/` — Phase 2 dbt-duckdb project
- `tests/` — the QA plan's test suite (pytest), run against generated and modeled data
- `semantic/` — Phase 3 MCP server + metric registry (generated from the tree file)
- `analytics/` — Phase 4 variance-diagnostic engine, forecast, capacity planning, etc.
- `dashboard/` — Phase 5 web app (Streamlit; needs its own Python 3.12 venv at `dashboard/.venv`, see `dashboard/README.md`, same reason as `semantic/`)

## Stack

DuckDB · dbt-core (dbt-duckdb adapter) · Python · MCP Python SDK · Streamlit · Claude API for the readout's narrative generation

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
