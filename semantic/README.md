# Semantic layer / AI context layer (Phase 3, Wave 3)

MCP server + metric registry for the Acme Corp GTM metric tree
(`docs/acme-corp-gtm-metric-tree.md`). This is the artifact named in the
build spec's Phase 3 section and Section 8, item #8 ("Semantic layer / AI
context layer").

## Why this directory runs on a different Python than the rest of the repo

The MCP Python SDK requires Python >=3.10. This project's default
interpreter is system Python 3.9.6 (see CLAUDE.md / project memory). To
avoid touching that interpreter, `semantic/` has its own virtualenv built
from Homebrew's Python 3.12:

```bash
/opt/homebrew/bin/python3.12 -m venv semantic/.venv
semantic/.venv/bin/pip install -r semantic/requirements.txt
```

(Already done for this checkout -- `semantic/.venv` exists and is
gitignored like every other `.venv/` in this repo, per `.gitignore`.)

**Always invoke Python under `semantic/` as `semantic/.venv/bin/python`,
never the bare `python3`/`pip3` used elsewhere in this project.**

## Files

| File | What it is |
|---|---|
| `build_registry.py` | Deterministic parser: `docs/acme-corp-gtm-metric-tree.md` -> `metric_registry.json`. Re-run this whenever the tree file changes. |
| `metric_registry.json` | The generated registry -- versioned (`registry_version`), stamped with a sha256 of the tree file it was parsed from (`source_tree_sha256`) so a consumer of `query_metric()` results can know which tree shape they queried against. |
| `CHANGELOG.md` | One line per registry regeneration that actually changed the structure. |
| `server.py` | The MCP server: `list_metrics()`, `get_metric_definition(name)`, `query_metric(...)`. |
| `golden_questions.md` | The natural-language routing regression set, re-run against the live server after each regeneration. |
| `requirements.txt` | `mcp`, `duckdb` -- Python >=3.10 only. |

## Regenerating the registry after a tree-file edit

```bash
semantic/.venv/bin/python semantic/build_registry.py
```

This re-parses the markdown from scratch, diffs the result against the
previous `metric_registry.json`, and:
- if nothing structurally changed: leaves the file untouched, prints "no
  structural change detected", no changelog line;
- if it changed: writes the new registry, bumps `registry_version`, and
  appends a line to `CHANGELOG.md` describing what changed (added/removed/
  changed node keys). Pass `--summary "what changed and why"` to replace the
  generated node list with a written entry.

The build also checks every entry of `server.py`'s `_ALIASES` table against
the new registry and fails if an alias targets a metric that is not in it.

The parser is a line-by-line state machine over the tree markdown's own
grammar (H2 = pillar, H3 = Layer 1, `**bold**` = Layer 2, `- bullet` =
Layer 3, backtick text = formula, `-- owner`/`, by segment` = the tree's
own scope annotations). It never hand-types a metric's formula --
`source_mart` (which `mart_*` table computes each metric) is the one
annotation layer that genuinely can't come from the tree file, since the
tree never names a database table; that mapping lives in
`build_registry.py`'s `_SOURCE_MART_MAP`/`_GAP_NOTE_OVERRIDES`, built by
reading the actual dbt mart SQL under `dbt/models/marts/marts/` and
`_mart_schema.yml`, cited inline.

## Running the MCP server

```bash
semantic/.venv/bin/python semantic/server.py
```

Runs over stdio (the MCP SDK's default transport) -- point an MCP client
(Claude Desktop, Claude Code's own MCP config, `mcp dev`, etc.) at that
command. Example Claude Code / Claude Desktop MCP config entry:

```json
{
  "mcpServers": {
    "acme-gtm-semantic-layer": {
      "command": "/absolute/path/to/semantic/.venv/bin/python",
      "args": ["/absolute/path/to/semantic/server.py"]
    }
  }
}
```

The server reads `data/acme_gtm.duckdb` **read-only**, opening a fresh
connection per `query_metric()` call and closing it immediately after --
it never holds a lock that would block a concurrent `dbt build`. It reads
only the `main_marts` schema's `dim_*`/`fact_*`/`mart_*` tables, never
`stg_`/`int_`/raw, matching `analytics-engineering-conventions` and the
same connection pattern `analytics/variance_diagnostic.py` uses.

## The three tools

- **`list_metrics(pillar=None, layer=None, computable_only=False)`** --
  browse the whitelist. This *is* the whitelist: nothing outside this list
  is a valid `metric` argument to the other two tools.
- **`get_metric_definition(name)`** -- full tree definition for one metric
  (formula, owner, `allowed_dimensions`, `source_mart`, parent/children,
  `additive`, and, if not directly queryable, `gap_note` explaining why).
  Works for every registered node, including ones `query_metric()` can't
  execute (most Layer-2/3 leaves) -- the tree definition is still useful
  even where the data doesn't exist yet.
- **`query_metric(metric, dimensions=[], filters={}, grain="month", date_range=None)`**
  -- executes against the dbt marts and returns real rows. Every response
  (success or rejection) echoes the metric's own registry definition
  alongside the result.

## Guardrails (what gets rejected, and why)

1. **Unknown metric** -- not in the registry -> `unknown_metric`, with
   `did_you_mean` suggestions (suggestions only; never silently
   substituted). Suggestions come from the `_ALIASES` table in `server.py`
   first (acronyms and short names such as `ltv`, `payback`, `overage`,
   `tickets`, `renewals`, `discount`, matched ignoring case and punctuation),
   then from character-level fuzzy matching against keys and names.
2. **Non-additive node treated as queryable/summable** -- the tree marks three
   nodes non-additive: Brand & Awareness (a leading indicator, "not summed
   into" the pipeline math), Marketing-sales handoff quality (a
   diagnostic overlay, "not a fourth multiplicative factor"), and LTV by
   segment x acquisition channel (a diagnostic overlay on Consumption
   payback, "not a mathematical child"). All three carry
   `additive: false` in the registry, per CLAUDE.md's invariant ->
   `non_additive_metric`, with the tree's own non-additive language quoted
   back.
3. **Registered but not computable** -- most Layer-2/3 leaves have no
   `mart_*` table backing them: the marketing-sales handoff nodes need an
   MQL/SAL lifecycle that no source carries, stage-to-stage conversion is
   100% at every hop, wallet share has no denominator, and Pipeline generated with its channel legs is
   computed by `analytics/marketing_attribution.py` (point-in-time lead
   resolution) rather than served from a mart rollup ->
   `metric_not_queryable`, with the specific gap and, where meaningful, a
   `suggested_alternative` (usually the nearest computable ancestor).
4. **Dimension not allowed by the tree** -- e.g. `opportunity_type` on NRR
   -> `invalid_dimension`.
5. **Dimension allowed by the tree but not backed by current mart data** --
   e.g. `channel` on CAC by channel (`mart_efficiency` only exposes
   `blended_cac`, not a per-channel cut) -> `dimension_not_queryable`, a
   distinct rejection from #4 so a caller can tell "the tree disallows
   this" from "the tree allows it, the data doesn't support it yet".
6. **Invalid segment value** -- must be `SMB` / `Commercial` / `Enterprise`
   (never `tier`) -> `invalid_segment_value`.
7. **Valid segment the metric's source table has no rows for** -- e.g.
   `poc_pass_rate` for Commercial (POC exists only in the Enterprise
   motion), or `overage_realization` for SMB (no commitment) ->
   `segment_not_available`, naming the segments the node does carry
   (`queryable_segments` in its definition). A restricted node is also
   scoped to those segments in its SQL, so a segment cut or an
   all-segments total never mixes in rows the metric does not define.
   `am_efficiency` is restricted to Commercial and Enterprise (SMB has no
   AM). Where the mart does carry rows for the segment but not the metric's
   data (`poc_pass_rate` for Commercial: the POC columns are empty), the node
   carries a `segment_unavailable_reason` and the message says "has no POC
   data for segment ..." rather than claiming the mart has no rows.
8. **Bad date_range** -- both ends must be real calendar dates in
   `YYYY-MM-DD` form (`2025-02-30` and month 13 are rejected), `start` may
   not be after `end`, and keys other than `start`/`end` are rejected ->
   `invalid_request`, never a database error.

## Notes that travel with the data

A node's `gap_note` is returned in `warnings` on every successful
`query_metric` call, not only in the metric echo: prefixed "Partially
computable:" when the node is `partial`, verbatim when it is `full` but the
note changes how the number is read (win rate for SMB is always 1.0,
ingestion without completion is actions-weighted, renewal win rate starts in
2021-02 for Commercial and 2022-07 for Enterprise). `onboarding_completion_rate`
is `partial`, matching the variance-diagnostic engine: it is identically 1.0,
so it carries no variance signal.

## What's actually queryable right now

37 of the tree's 70 parsed nodes (11 Layer-1 + 26 Layer-2/3) have a real
`mart_*` mapping today -- every Layer-1 node, plus `win_rate`,
`avg_initial_commitment`, `onboarding_completion_rate`,
`am_touchpoint_volume`, `automated_action_volume_delivered`,
`cac_by_channel` (blended only), `utilized_vs_committed_action_volume`,
`s_m_cost`, `rep_fully_loaded_cost_incl_ramp`,
`marketing_spend_allocation_by_channel` (summed over channels, attributed to
segment), `am_cost_by_segment`, `tenure_at_churn`, and the deal-level,
workflow-chain, overage and account-health-input nodes: `poc_pass_rate`
(Enterprise only), `rep_capacity_ramp_mix`, `loss_reason_mix`,
`discount_rate_vs_list`, `deal_size_trend_within_segment_band`,
`renewal_win_rate`, `workflow_chain_under_utilization`,
`ingestion_without_completion_rate`, `mid_chain_workflow_abandonment`,
`declining_share_of_full_chain_vs_partial_chain_runs`,
`overage_realization` (overage MRR over total MRR; the realization rate is
100% by billing construction), `support_ticket_volume_severity`,
`engagement_login_frequency` and `am_sentiment_notes`. Everything else is a
genuine, cited data gap (see each node's `gap_note` via
`get_metric_definition`), not a stub -- consistent with how
`analytics/variance_diagnostic.py` already documents the same gaps against
the same marts.

`magic_number` and `am_efficiency` are ratio-of-sums metrics over
`mart_efficiency`'s cost columns: Magic number is summed net new ARR over
summed prior-period S&M cost, AM efficiency is summed monthly expansion MRR
over summed AM cost. At month grain a single month is seasonal and can be
negative; `grain="year"` gives a stable read. SMB has no reps and no AM, so
Magic number for SMB reflects program spend only and AM efficiency for SMB
is not queryable (no AM to divide by): a request for SMB is rejected as
`segment_not_available`, not returned as a null series.

## Tests

`tests/test_semantic_server.py` runs under the root interpreter (it injects a
stand-in for the MCP server class when the SDK is not importable) and covers
every queryable node at every grain (month, quarter, year, all) with no
filter, a segment dimension and each segment filter, date_range validation,
segment scoping, the notes-as-warnings rule, the alias table and its build-time
check. Its `TestMcpCallPath` class goes through the real `call_tool` path
when run where the SDK is installed.

## Validation

Run the `semantic-layer-validator` subagent after any change here. It
checks numeric correctness against direct mart queries, exercises the
guardrails listed above, and maintains a golden-question NL-routing set at
`semantic/golden_questions.md`.
