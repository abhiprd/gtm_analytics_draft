---
name: dbt-conventions
description: Reference this whenever writing, reviewing, or restructuring any dbt model for the Acme Corp GTM portfolio. Covers layering, naming, materialization, and testing conventions specific to this project's schema (build spec Sections 4–5). Load before writing any SQL model, not after.
---

# dbt conventions for Acme Corp

## Layering — strict, no skipping

- `stg_*` — one per raw source table. 1:1 with the source, light typing/renaming only. No joins, no business logic.
- `int_*` — joins and business logic that don't belong in a single staging model or a final mart (e.g., deriving time-in-segment from `account_segment_history`, resolving duplicate contacts).
- `dim_*` / `fct_*` — the dimensional model. Facts are append-only where possible; dimensions carry current state plus, where the build spec calls for it, historized attributes (e.g., `dim_reps` joined against `quota_history` and `rep_status_history` for point-in-time queries — don't collapse these into static current-value columns).
- `mart_*` — consumption-ready, aligned to the metric tree's own structure (`mart_growth_bridge`, `mart_efficiency`, `mart_durability`, `mart_segment_migration`, `mart_tam_whitespace`). A mart should map cleanly to a pillar or a cross-cutting analysis, not to whatever's convenient to join.

Never reference a `stg_` model from a `mart_`, and never reference a raw source from anything but its own `stg_` model. If a mart needs raw-source logic, that logic is missing from staging/intermediate — fix it there, don't shortcut.

## Naming

- `snake_case` throughout, matching the exact names in the build spec and QA plan — don't invent alternate names for something already specified there.
- Boolean columns: `is_*` or `has_*`.
- Every table name states its grain implicitly through the prefix; if grain isn't obvious from the name, add a one-line comment stating it explicitly.

## Materialization

- `stg_*`: view or ephemeral — cheap to recompute, no reason to persist.
- `int_*`: view unless a specific model is expensive and reused by multiple marts, in which case table.
- Large, append-only fact tables (`fact_workflow_chain_events`, `fact_sales_activities`, `fact_engagement`): incremental. Don't materialize as a full table rebuild every run once volume is non-trivial.
- `mart_*`: table — these get queried directly and repeatedly (semantic layer, dashboard).

## Testing — map directly to the QA plan, don't invent a parallel test taxonomy

- `not_null` / `unique` on every primary key
- `relationships` on every foreign key (this is the dbt-native version of the QA plan's referential-integrity category)
- `accepted_values` on every enum-like column: `segment`, `trigger_reason` (all 4 values), `opportunity_type`, `owner_role`, `loss_reason`
- Custom singular tests for anything the QA plan states as an invariant that generic tests can't express: downstream ≤ upstream Actions in `fact_workflow_chain_events`, no segment downgrades in `account_segment_history`, SMB accounts have 0 or 1 opportunity.
- Don't write a distributional-realism or correlational-validity test as a dbt test — those belong in the QA plan's pytest suite (`validate-gtm-data` skill), since they're statistical checks over the whole dataset, not per-row assertions. dbt tests are for structural correctness; the QA plan's suite is for realism.

## Style

- No `select *` in any model above `stg_`
- Every model has an explicit column list in its `select`, even if it's long
- Use `ref()` and `source()` exclusively — no hardcoded table names, ever
- CTEs over subqueries; name each CTE for what it does, not `cte1`/`cte2`
