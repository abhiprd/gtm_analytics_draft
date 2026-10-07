# CRO / leadership interface (Phase 5, Wave 8)

A Streamlit app: the digest view, forecast view, segment-efficiency view, and one working
chat demo called for in the build spec's Section 6 scope guardrail. Nothing here is a mock
-- every page reads live from `data/acme_gtm.duckdb`'s `main_marts` schema, from
`analytics/outputs/`' already-generated readout JSON, or calls `analytics/forecast.py` and
`semantic/server.py` directly.

## Why Streamlit, not Next.js

Section 7 left the framework open. Streamlit was chosen because every other layer of this
project is already Python end-to-end -- the marts, the semantic layer, and all twenty-one Phase
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
| `pages/1_Digest.py` | `analytics/outputs/weekly_readout_*.json` | Nothing -- renders the artifact's own output verbatim, including its forecast section, each drill-down's repeat marker, and the segment-mix section (or a section's `unavailable` state and reason) |
| `pages/2_Forecast.py` | `analytics/forecast.py`'s `run_forecast()` | Trains the win-probability model live (`log=False` -- never writes to `fact_model_performance_history`), cached per forecast call date for the session. Opens on the newest readout's forecast call and reports whether its figures match that readout. Also calls `analytics/pipeline_coverage.py`'s `run_pipeline_coverage()` in-process at the same call date for the pipeline-coverage section (see below) |
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
registry's display names and keys and the semantic layer's alias table (`semantic/server.py`
`_ALIASES`, the one alias table; the dashboard's own `routing.SUPPLEMENTARY_ALIASES` is empty and a
test fails if an entry ever duplicates a server alias). The question is scanned left to right and the longest phrase at
each position wins, on whole tokens, with dashes, colons, arrows and the multiplication sign
treated as separators. A named dimension ("by channel") is always passed to the semantic layer,
and a segment-like word the registry does not know ("Tier 1", "Mid-Market") is passed through as
the filter so the guardrail answers with `invalid_segment_value`. A scope word outranks the broader
name beside it (`routing.SCOPE_OVERRIDES`: "win rate for renewals" is Renewal win rate). A "by" or
"per" split that is not a registry dimension (loss reason, rep, region, industry) is reported in
`unsupported_splits`: the page says "Split by X is not available for <metric>. The figures below are
not split." and offers the nearest real node (`answers.RELATED_SPLIT_NODES`) as a button, never a silent
reroute. A failure while answering or rendering shows a plain notice (`answers.safe_answer`), never a
traceback. It is never an LLM call and never
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

## The Forecast page's pipeline-coverage section

Below the lenses, the Forecast page shows a **coverage reading, not a forecast**: whether the open new-business
pipeline, at the recent realized win rate, covers the quota still to book this quarter. It calls
`analytics.pipeline_coverage.run_pipeline_coverage(as_of_date)` in-process at the page's forecast call date (the
artifact accepts any date, so there is no second date picker, and its open pipeline ties to the forecast's
new-business pipeline for the same call) and renders the output's `display` strings verbatim. `lib/coverage_view.py`
(Streamlit-free, `tests/test_dashboard_coverage_view.py`) holds the rules and `lib/coverage_render.py` draws them.
A failure to produce the reading (the call raises, for example on a date the underlying forecast data cannot serve)
shows a plain notice and leaves the lenses untouched; no exception text reaches the page.

- **Header.** A neutral "Coverage reading, not a forecast" chip, an info row (evaluation date, quarter, grain, artifact
  status) and one line saying open pipeline is new business only (ISR- and AE-owned, closing in the quarter) and so
  differs from the lenses above, which also price renewal and expansion. The artifact status ("In progress, not yet
  independently validated") reads from `project_status.json` and drops its suffix when the component is
  `built_and_validated`.
- **Per segment.** A heading, a neutral gray chip "Proposed band: Thin, 0.75x to below 1.00x of required" (bands from the
  artifact's `status_rule`; never green or red, because the bands are proposed and the evidence is a small set of
  mid-quarter readings), the artifact's one-sentence summary, then four equal-height cards: remaining quota, open
  new-business pipeline, coverage vs required ("0.50x of required"), conversion-implied gap ("$181.7K short" or
  "$1.27M ahead"). Each ends in a "Basis:" line. A segment whose quota is met has a null coverage ratio and reads
  "Quota met", never 0.00x. Enterprise adds a small card for the POC outcome view, labelled "Indicative, not a
  forecast", with its closed-deal and won counts.
- **Unavailable segment.** A plain-language info box per reason code (no quota, before the conversion window, too
  few closed deals, no wins in the window, after the data window) and no figures.
- **Next quarter.** At the data-window end the block is an honest blank ("coverage is blank: the data ends ..., before ...
  starts ... not zero coverage") with a "Why this is blank" expander. When present it is one line per segment with
  "no verdict"; Commercial with no open deal reads "none yet".
- **Compared with the forecast.** A table with the coverage reading's open pipeline and expected close beside the
  forecast manager lens's, the difference and the forecast's all-opportunity-type pipeline. Open pipeline ties
  exactly; the expected-close figures differ by design (one realized win rate per segment against per-deal category
  weights) and are never merged.
- **Notes & assumptions.** The artifact's caveats as written, the proposed-band assumption, and, when the newest
  committed `pipeline_coverage_*.json` carries a `backtest_summary`, the backtest accuracy and the Commercial
  understatement figures quoted from it (`data.load_pipeline_coverage_backtest`). The in-process call does not carry
  the backtest.

## The Digest's repeat marker

Each drill-down entry in the readout carries a `persistence` record from the variance engine
(`compute_persistence()`): whether the same Layer-2 driver was the largest adverse outlier in
consecutive months. `lib/persistence_view.py` (Streamlit-free, `tests/test_dashboard_persistence_view.py`)
holds the display rules and reads the record by key without recomputing any streak:

- **Flagged:** a neutral gray chip, "Repeat: N consecutive months", beside the drill-down breadcrumb.
  Gray, not a status color: it marks a repeated driver, not a good or bad result.
- **Not flagged:** no chip; the drill-down shows "Streak N of 2 months".
- **Not applicable:** no chip; the drill-down shows "Repeat marker: not applicable." with the engine's reason
  (single-candidate reads, no outlier, the truncated final month).
- Inside the drill-down: the engine's note, the month before the streak and what differed, a streak table
  (month, deviation from the driver's own trailing baseline, baseline months) and the method basis, which is its own
  sentence-case line. The streak line carries the threshold status ("marker threshold: 2 months, proposed") and the
  record's own caveat sits under it.

The marker is a repeat detector and the copy says so. The 2-month threshold is proposed, not confirmed, and an
independent profile found the flag fires about as often on shuffled, unrelated months as on real ones (about
17.7% against 17.1%): with two or three siblings a volatile sibling is the top outlier in most months. The chip
therefore never says "trend" or "persistent", no text implies a cause, the header carries no count of flagged
nodes, and the page's Notes & assumptions carries two scope lines: what the marker does not establish, and that in aggregate it
appears about as often on shuffled months as on real data.

## The Digest's segment-mix block

The readout's `segment_mix` section (from `analytics/segment_migration.py`) answers "are we moving upmarket".
`lib/segment_mix_view.py` holds the rules (`tests/test_dashboard_segment_mix_view.py`) and
`lib/segment_mix_render.py` draws them. The block sits below the decision tier, as context: the readout's
headline sentence verbatim, a 100%-stacked bar of segment share of ending MRR for the same month a year earlier
and the reporting month (segment palette), an upmarket-share card, and one card per migration pair showing the
trailing-12-month migration rate against the year before (in pp) with graduated MRR as a share of source-segment
MRR (worded as a share of average source-segment MRR over the window: a 12-month flow, not a share of current MRR). A
visible line per pair says why that share exceeds the account migration rate (migrating accounts carry about 6x the
MRR of the average account in their segment), bar labels use largest-remainder rounding so each bar sums to 100.0%,
and every readout caveat is kept in Notes & assumptions. Every card states its basis and is neutral gray: the tree defines no plan or favorable direction for mix or
migration. It is not a metric-tree node, so cards carry no Layer label. When the section is `unavailable` the block
shows the section's plain-language reason and no figures; its caveats go to Notes & assumptions (migration only
moves accounts up, so rates and mix lead rather than counts, and the data-window handling).

## Ask page: censored tail, query-interface gaps and default views

- **Censored workflow-chain tail** (`lib/censoring.py`, `tests/test_dashboard_censoring.py`). Partial chains exist only
  in the months before a churn, so the four workflow-chain nodes (Workflow chain under-utilization and its three
  Layer-3 legs) fall away across the last 5 months of the data window. The variance engine blanks that tail
  (`variance_diagnostic._drop_censored_chain_tail`); the query does not. `CENSORED_TAIL_MONTHS` is the one table of
  affected nodes, and a test ties the 5 to the engine's constant and checks the engine drops exactly the months the
  dashboard excludes. On Ask the headline is the last uncensored month, the excluded months are open markers labelled
  "Excluded: incomplete window", the data table flags them, and the card carries a visible tag and a data note.
  The Actions-weighted ingestion rate shows no visible tail in the data but the engine blanks it, so it is listed.
- **Not available here is not the same as not computable.** A node whose registry note says a validated artifact
  computes it (Pipeline generated) reads "Not available through this query interface; shown in the weekly readout",
  with the registry paragraph shown once and a short statement per child row. An overlay reads "Not queryable
  (non-additive overlay)".
- **Scalar views** carry their slice on the headline card, children table and chart axis (`labels.NODE_QUALIFIERS`),
  replacing a parenthetical the name already has instead of stacking on it.
- **Default view.** Win rate with no segment named opens on Commercial and Enterprise (`answers.DEFAULT_SEGMENT_VIEW`),
  because SMB win rate is 100% by construction and dominates the all-segment figure; the page says so.

## Digest drill-down tables

`lib/drilldown_view.py` (`tests/test_dashboard_drilldown_view.py`) reads each row's `comparison_basis`. The caption says
what the rank was computed on: deviation from the row's own trailing baseline, or absolute dollar (or percentage-point)
change for additive branches (NRR, GRR, the Magic number legs), which also get a change column. A row with no data
shows a dash in the rank column.

## Ask page: registry v5 nodes

`lib/answers.py` assigns a display unit to every queryable node (a test fails when a queryable registry node has
none), including per-account-month loads (`weighted_tickets_per_account_month`, `logins_per_account_month`) and a
score. A `segment_not_available` rejection (for example POC pass rate for Commercial, an Enterprise-only node)
reads "Segment not available" with a sentence naming the segment and the coverage, never the raw code. Layer-3
nodes that are one slice of a wider quantity carry the slice in their display label
(`labels.NODE_QUALIFIERS`: loss-reason mix is the competitive share; overage realization is overage MRR as a share of
total MRR).

## Copy voice and Notes & assumptions

Every page puts its assumptions, scope statements and data gaps in one `Notes & assumptions`
expander (`theme.notes_and_assumptions`), one line each, labelled `Assumption:`, `Scope:` or
`Data gap:`. Page copy elsewhere states facts and avoids hedging, editorializing and first
person (conventions Section 11). Text that originates in an analytics artifact (a readout's
plan-comparability notes, a registry `gap_note`) is shown as written.

## Tests

`tests/test_dashboard_routing.py`, `tests/test_dashboard_answers.py`, `tests/test_dashboard_registry_v5.py`,
`tests/test_dashboard_persistence_view.py`, `tests/test_dashboard_segment_mix_view.py`,
`tests/test_dashboard_censoring.py`, `tests/test_dashboard_drilldown_view.py`, `tests/test_dashboard_coverage_view.py` and
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
