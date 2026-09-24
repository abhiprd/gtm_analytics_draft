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
  changed node keys).

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
   fuzzy `did_you_mean` suggestions (suggestions only; never silently
   substituted).
2. **Non-additive node treated as queryable/summable** -- the tree marks two
   nodes non-additive: Brand & Awareness (a leading indicator, "not summed
   into" the pipeline math) and Marketing-sales handoff quality (a
   diagnostic overlay, "not a fourth multiplicative factor"). Both carry
   `additive: false` in the registry, per CLAUDE.md's invariant ->
   `non_additive_metric`, with the tree's own non-additive language quoted
   back.
3. **Registered but not computable** -- most Layer-2/3 leaves have no
   `mart_*` table backing them (leads/campaigns, opportunity-stage detail,
   workflow-chain detail, AM comp data, etc. either don't exist in the raw
   sources or sit in a `fact_*` table with no `mart_*` rollup) ->
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

## What's actually queryable right now

20 of the tree's 69 parsed nodes (11 Layer-1 + 9 Layer-2/3) have a real
`mart_*` mapping today -- every Layer-1 node, plus `win_rate`,
`avg_initial_commitment`, `onboarding_completion_rate`,
`am_touchpoint_volume`, `automated_action_volume_delivered`,
`cac_by_channel` (blended only), `utilized_vs_committed_action_volume`,
`am_cost_by_segment` (NULL -- no comp data), `tenure_at_churn`. Everything
else is a genuine, cited data gap (see each node's `gap_note` via
`get_metric_definition`), not a stub -- consistent with how
`analytics/variance_diagnostic.py` already documents the same gaps against
the same marts.

`magic_number` and `am_efficiency` are marked computable (they have a real
`mart_efficiency` column) but that column is NULL in every row -- there is
no rep-cost/comp data anywhere in the raw sources. `query_metric()` will
return real, correctly-shaped `null` values for them, not an error; the
metric definition's `gap_note` explains why.

## Validation

Run the `semantic-layer-validator` subagent after any change here. It
checks numeric correctness against direct mart queries, exercises the
guardrails listed above, and maintains a golden-question NL-routing set at
`semantic/golden_questions.md`.
