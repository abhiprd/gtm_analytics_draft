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

Open the app at its root URL. Streamlit serves a deep link to a page (for example `/Digest`) from the
legacy `pages/` listing for the first request after the server starts, which shows the file name "app" in the
sidebar until the root page has loaded once; every later request uses the router.

Requires `data/acme_gtm.duckdb` to exist (`cd dbt && dbt build`) and, for the digest view,
at least one `analytics/outputs/weekly_readout_*.json` (`python3 -c "from analytics.weekly_readout import ...` -- see that module's own `__main__`).

## Pages

| Page | Reads from | Computes |
|---|---|---|
| `app.py` (router) + `home.py` | `analytics/outputs/` latest readout | Nothing -- `app.py` registers the pages with `st.navigation` (so the sidebar entry reads "Home", not "app"); `home.py` shows headline counts only |
| `pages/1_Digest.py` | `analytics/outputs/weekly_readout_*.json` | Nothing -- renders the artifact's own output verbatim, including its forecast section (or that section's `unavailable` state and reason) |
| `pages/2_Forecast.py` | `analytics/forecast.py`'s `run_forecast()` | Trains the win-probability model live (`log=False` -- never writes to `fact_model_performance_history`), cached per forecast call date for the session. Opens on the newest readout's forecast call and reports whether its figures match that readout |
| `pages/3_Segment_Efficiency.py` | `mart_growth_bridge`, `mart_efficiency`, `mart_durability`, `mart_segment_migration` | Nothing -- these marts are already segment x month grain |
| `pages/4_Ask_the_Metric_Tree.py` | `semantic/server.py`'s registry and `query_metric`, called in-process | Nothing new -- routes a question to the same guardrailed tool an MCP client calls; a standing sidebar tree built from the registry is the on-ramp |

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

## The chat demo, its tree panel, and what its routing deliberately isn't

**Tree panel.** The sidebar lists all 11 Layer-1 nodes under Growth, Efficiency and Durability,
expandable to Layers 2 and 3. It is built at render time from the semantic layer's own registry
(`semantic/metric_registry.json`, generated from `docs/acme-corp-gtm-metric-tree.md`), never from a
copy. Each node shows its real status from its registry flags: queryable, queryable (partial), not
computable, non-additive overlay, or cross-reference. Selecting a node submits a ready question
("What is Win rate and what is driving it?") to the chat.

**Answers include children.** An answer about a metric with children carries the metric's own
value and one row per immediate child (`lib/answers.py`), each queried through the same
`query_metric()` call. A child that cannot be queried is listed with its registry reason and no
value. A malformed request (an invalid segment, an unsupported dimension) is answered by the
guardrail's message alone.

**Routing.** `lib/routing.py` holds the deterministic keyword rules as a pure function
(`tests/test_dashboard_routing.py`); `lib/semantic_bridge.py` builds its vocabulary from the
registry's display names and keys, the semantic layer's alias table, and a short list of
dashboard-side supplementary aliases (`routing.SUPPLEMENTARY_ALIASES`: LTV, lifetime value,
LTV:CAC, payback, CAC payback). The question is scanned left to right and the longest phrase at
each position wins, on whole tokens, with dashes, colons, arrows and the multiplication sign
treated as separators. A named dimension ("by channel") is always passed to the semantic layer,
and a segment-like word the registry does not know ("Tier 1", "Mid-Market") is passed through as
the filter so the guardrail answers with `invalid_segment_value`. It is never an LLM call and never
a fuzzy substitution: `semantic/server.py`'s `_resolve_metric()` stays the whitelist.

Routing the question through the Claude API instead (build spec Section 3's "Claude API
... as the NL query interface via MCP") is the natural next step and is left as an open
seam, on purpose. A portfolio repo that only runs with someone's live API key configured is
a worse demo than one that is honest about where that seam is.

## The Digest's executive summary, and what it deliberately does not do

The weekly readout's executive-summary narrative is no longer a placeholder: the Digest reads
the readout JSON's `executive_summary` slot, which `analytics/executive_summary.py` fills. The
dashboard only reads that slot -- it never calls the API, never imports the `anthropic` SDK
(not installed in `dashboard/.venv`), and computes nothing.

`lib/exec_summary_view.py` (Streamlit-free, unit-tested in
`tests/test_dashboard_exec_summary_view.py`) holds the single rule for what the page may show.
Prose renders only when the slot is `generated`, `validation.passed` is true, every statement
is well formed, and the slot's `input_hash` equals the hash of the readout it sits in. Every
other state -- `not_generated` (no key, not yet run, stale, API error, SDK missing),
`validation_failed`, a malformed or out-of-date slot -- renders no prose at all: a plain-language
reason plus a "Why this is blank" expander (conventions Section 7). The committed readouts carry
`not_generated` / `no_api_key` because no key exists in this repository, so that is the state a
fresh checkout shows; the narrative component stays `in_progress` in `project_status.json`
(no independent validator pass, no live run yet) and a generated block says so on its face
until that changes.

To see the generated state without a key or a model, point the readout reader at a scratch copy
of `analytics/outputs` whose slot was filled from a test fixture:
`ACME_DASHBOARD_OUTPUTS_DIR=/path/to/copy streamlit run dashboard/app.py`. The Digest, run this way,
shows a visible "Test/QA mode" warning. Unset, the dashboard reads `analytics/outputs` as always.

## The Digest's forecast section

The weekly readout JSON carries a `forecast` section written by `analytics/weekly_readout.py`
from `analytics/forecast.py`: the forecast call current at the reporting month's end (a Friday
snapshot), the quarter that call sits in, and four lenses per segment (Commercial and Enterprise).
The Digest renders it verbatim -- the call date, quarter, days to quarter end, a reconciled
CRO-adjusted headline with a divergence badge, and the four lenses as a sorted bar chart -- and
recomputes nothing. When `status` is `unavailable` it shows the section's own plain-language
detail and reason and no figures. `lib/forecast_view.py` is shared with the Forecast page so both
show the same figures in the same form; the Forecast page opens on the newest readout's forecast
call and states whether its figures match that readout.

## Copy voice and Notes & assumptions

Every page puts its assumptions, scope statements and data gaps in one `Notes & assumptions`
expander (`theme.notes_and_assumptions`), one line each, labelled `Assumption:`, `Scope:` or
`Data gap:`. Page copy elsewhere states facts and avoids hedging, editorializing and first
person (conventions Section 11). Text that originates in an analytics artifact (a readout's
plan-comparability notes, a registry `gap_note`) is shown as written.

## Tests

`tests/test_dashboard_routing.py`, `tests/test_dashboard_answers.py` and
`tests/test_dashboard_exec_summary_view.py` cover the Streamlit-free modules under the repo's
default interpreter. `python3 -m pipeline run --only dashboard_smoke` renders every page headless
under `dashboard/.venv`.

## Generating the Digest's executive summary

The Digest shows the summary only when the readout carries a validated one. To produce it, set
`ANTHROPIC_API_KEY` and run `python3 -m analytics.executive_summary`. The page itself never names this
command: its "Why this is blank" panel gives the reader the reason, what is needed (for example an API key)
and the component's status label, and nothing else.

## Presentation decisions recorded from the visual-QA pass

These are implemented in `theme.py`, `lib/verdict.py`, `lib/labels.py`, `lib/forecast_logic.py` and
`lib/answers.py`, each unit-tested (`tests/test_dashboard_verdict.py`, `..._labels.py`, `..._forecast_logic.py`,
`..._answers.py`). They are proposed additions to the conventions skill, listed in the build report.

- **Caveated comparison.** A readout row with `plan_comparability == "caveated"` renders the gap to plan in
  neutral gray with no arrow and a small "Caveated comparison" tag inside the card, so Ahead/Behind never reads
  as a finding when the levels are not on the same footing. Rows the readout does not flag are not tagged; the
  readout carries no note linking Expansion or Contraction + churn to the NRR/GRR gross-bucket caveat, so they
  stay untagged. A period-over-period move on a metric whose level is caveated (Consumption payback on Segment
  Efficiency) keeps its status color and carries the tag.
- **Constant series.** A Not-computable row whose actual, prior value and baseline are the same number, and an
  Ask answer whose registry note says the series is constant and whose data is constant, show "Not computable"
  and the reason in place of a number or a flat chart. The tree panel labels such a node "No variation in data".
- **Basis on every figure.** Digest cards say "Month of YYYY-MM" or "Trailing 12 months to YYYY-MM"; Segment
  Efficiency says "Monthly"; Ask says "last complete month". The truncated final month of the data window
  (read from the readout's `data_window.last_month_in_marts`, the value `variance_diagnostic._data_window_check`
  produces) is excluded from Ask headlines and the Segment Efficiency default, drawn as an open marker and
  labeled partial.
- **Zero and rate deltas.** A delta that rounds to zero at its displayed precision has no status color or arrow.
  Changes in a rate are labeled pp.
- **Registry notes in answers.** A `gap_note` on a live metric is shown above the chart, not only under Query
  details. Table and file identifiers and markdown are removed from registry and guardrail text before display.
- **Cards.** One card anatomy (`theme.scorecard_row`, a CSS grid in one markdown call) is used on every page;
  `st.container(border=True)` plus a bleed hack is no longer used. Narrow viewports collapse the grid to two
  columns.
- **Notes & assumptions.** Each item is one short line; longer text keeps its first sentence(s) and puts the
  remainder behind a "Details" toggle.
- **Upstream text at display time.** Registry and readout strings the dashboard cannot edit pass through an
  explicit phrase map (`lib/labels.py`, `PHRASE_MAP`, unit-tested): it keeps each fact and changes only the wording
  (document paths, build-spec references, snake_case names, hedging phrases). `PHRASE_MAP_UPSTREAM` lists the
  source strings to fix where they originate. Every `st.warning`/`st.info`/`st.error`/`st.success` that
  interpolates data wraps it in `theme.escape_md` (a test enforces this), so two dollar amounts in one string never
  render as a LaTeX span.
- **No scientific notation.** Display formatters (`lib/verdict.py`, `lib/answers.py`) never emit an exponent;
  touches per Action are shown per 1M Actions, matching Segment Efficiency.
