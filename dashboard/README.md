# CRO / leadership interface (Phase 5, Wave 8)

A Streamlit app: the digest view, forecast view, segment-efficiency view, and one working
chat demo called for in the build spec's Section 6 scope guardrail. Nothing here is a mock
-- every page reads live from `data/acme_gtm.duckdb`'s `main_marts` schema, from
`analytics/outputs/`' already-generated readout JSON, or calls `analytics/forecast.py` and
`semantic/server.py` directly.

## Why Streamlit, not Next.js

Section 7 left the framework open. Streamlit was chosen because every other layer of this
project is already Python end-to-end -- the marts, the semantic layer, and all twenty Phase
4 artifacts. A Next.js frontend would need a REST API layer in front of that Python to
expose it to a browser, which is exactly the kind of extra surface Section 6 says to avoid
("resist building a full BI platform"). Streamlit reads the DuckDB marts and imports
`analytics`/`semantic` modules directly, in-process -- no API layer, no second language,
no build step.

## Why its own virtualenv

`dashboard/` needs Python >=3.10 for the same reason `semantic/` does: the "Ask the metric
tree" page imports `semantic/server.py` in-process (see `lib/semantic_bridge.py`), and that
module requires the `mcp` package, which requires Python >=3.10. The repo's default
interpreter is system Python 3.9.6 (see `CLAUDE.md`), so `dashboard/` gets its own
virtualenv from Homebrew's Python 3.12, exactly like `semantic/.venv`:

```bash
/opt/homebrew/bin/python3.12 -m venv dashboard/.venv
dashboard/.venv/bin/pip install -r dashboard/requirements.txt
```

(Already done for this checkout -- `dashboard/.venv` exists and is gitignored, like every
other `.venv/` in this repo.)

## Running it

```bash
dashboard/.venv/bin/streamlit run dashboard/app.py
```

Requires `data/acme_gtm.duckdb` to exist (`cd dbt && dbt build`) and, for the digest view,
at least one `analytics/outputs/weekly_readout_*.json` (`python3 -c "from analytics.weekly_readout import ...` -- see that module's own `__main__`).

## Pages

| Page | Reads from | Computes |
|---|---|---|
| `app.py` (home) | `analytics/outputs/` latest readout | Nothing -- headline numbers only |
| `pages/1_Digest.py` | `analytics/outputs/weekly_readout_*.json` | Nothing -- renders the artifact's own output verbatim |
| `pages/2_Forecast.py` | `analytics/forecast.py`'s `run_forecast()` | Trains the win-probability model live (`log=False` -- never writes to `fact_model_performance_history`), cached per as-of-date for the session |
| `pages/3_Segment_Efficiency.py` | `mart_growth_bridge`, `mart_efficiency`, `mart_durability`, `mart_segment_migration` | Nothing -- these marts are already segment x month grain |
| `pages/4_Ask_the_Metric_Tree.py` | `semantic/server.py`'s `list_metrics`/`get_metric_definition`/`query_metric`, called in-process | Nothing new -- routes a question to the same guardrailed tool functions an MCP client calls |

## Visual design system

Every page follows `.claude/skills/dashboard-design-conventions/SKILL.md` -- color semantics
(a pillar palette, a status palette, and a segment palette that never share a hue), chart-type
selection, audience-adaptive layout (exec/analyst/ad-hoc/hybrid), grain constraints, and the
Section 7 honesty patterns (never render a live-looking value for a component that isn't
`built_and_validated`). The mechanical enforcement of that skill lives in two files every page
imports rather than repeating:

- **`theme.py`** -- the shared palette/font/component module (`scorecard()`, `status_color()`,
  `plotly_layout()`, the `render_pending()`/`component_status()` honesty helpers). See its own
  `inject_global_css()` docstring for a real, verified Streamlit limitation worth reading before
  adding a new bordered card: `st.container(border=True)`'s background fill only works reliably
  as one single `st.markdown()` call, not split across multiple calls or native widgets.
- **`project_status.json`** -- the concrete "is this component built_and_validated" source of
  truth the skill's Section 7 refers to as `project-status`. Update it whenever a component's
  real build state changes; it's a projection of `CLAUDE.md`'s "Current phase" section, not a
  second source of truth.

Two agents (`.claude/agents/dashboard-page-builder.md`, `.claude/agents/dashboard-visual-qa.md`)
build and independently audit pages against this system -- the builder renders and visually
inspects its own output before reporting done; the QA agent is diagnostic-only and checks
cross-page consistency plus the completeness-honesty pattern a single page's own builder is
least likely to catch in itself. Both rely on `dashboard/scripts/screenshot.py`
(Playwright-based) as their render/inspect harness -- `dashboard/.venv/bin/playwright install
chromium` once after installing `requirements.txt` if it hasn't been run yet.

## The chat demo's NL routing, and what it deliberately isn't

`lib/semantic_bridge.py`'s `parse_question()` is deterministic keyword and substring
matching against the registry's own whitelisted names, keys, and aliases -- never an LLM
call, and never a fuzzy substitution: `semantic/server.py`'s own `_resolve_metric()` is
documented as "never a fuzzy match," and this page's routing stays inside that guardrail by
only ever accepting an exact (substring) hit against a name the registry itself already
recognizes. When nothing matches, the page shows `_resolve_metric`'s own difflib-based
suggestions rather than guessing, and falls back to a plain metric browser.

Routing the question through the Claude API instead (build spec Section 3's "Claude API
... as the NL query interface via MCP") is the natural next step and is left as an open
seam, on purpose -- the same deliberate-deferral treatment this project already gives the
weekly readout's executive-summary narrative (see `docs/acme-corp-analytics-methods.md`
and `analytics/weekly_readout.py`'s own `executive_summary` placeholder). A portfolio repo
that only runs with someone's live API key configured is a worse demo than one that is
honest about where that seam is.
