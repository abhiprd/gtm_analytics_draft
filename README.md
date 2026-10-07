# Acme Corp GTM Analytics Portfolio

An end-to-end GTM analytics stack for Acme Corp, a fictional consumption-based B2B SaaS company: simulated raw data → dbt data model → semantic layer → diagnostic analytics → a CRO-facing weekly readout. Built to demonstrate GTM analytics, data engineering, and AI-context-layer design as a single coherent system rather than a collection of disconnected notebooks.

Every number in this repo is generated, not sampled from a real company — but it's generated with real causal structure (win probability, churn probability, and usage growth are functions of their actual drivers, not independently random columns), so every diagnostic artifact built on top of it has something real to find.

## The company

Acme Corp sells workflow orchestration software, priced on metered usage ("Actions" executed). Three segments — SMB, Commercial, Enterprise — differentiated by touch model, deal size, and coverage, with accounts migrating upward as usage or firmographics cross defined thresholds (never downward: an account that fails to activate churns entirely rather than demoting). Channel (how an account was acquired) and segment (what it is) are orthogonal.

## Workflow: data → analytics → feedback

The system is a loop, not a pipeline. Diagnostic output doesn't just get read — it drives account-level action (AM outreach, playbook triggers), and the outcome of that action shows up in next period's raw data, closing the loop back into the same metric tree that flagged it.

```
┌─────────────────┐     ┌──────────────┐     ┌───────────────┐     ┌────────────────────┐     ┌──────────────┐
│  1. Raw source   │────▶│  2. dbt data │────▶│  3. Semantic   │────▶│  4. Diagnostic       │────▶│ 5. CRO       │
│     simulation   │     │     model    │     │     layer      │     │     analytics        │     │    readout   │
│                  │     │              │     │     (MCP)      │     │                      │     │              │
│  Event-grain     │     │ staging →    │     │ Metric tree,   │     │ Account health score,│     │ Weekly       │
│  CRM, billing,   │     │ intermediate │     │ registry-      │     │ segment migration,   │     │ scorecard +  │
│  usage, CS-ops,  │     │ → dims/facts │     │ backed query   │     │ variance-diagnostic  │     │ narrative    │
│  marketing spend │     │ → marts      │     │ tool           │     │ engine, forecast      │     │ drill-downs  │
└─────────────────┘     └──────────────┘     └───────────────┘     └──────────┬───────────┘     └──────┬───────┘
        ▲                                                                      │                        │
        │                                                                      ▼                        ▼
        │                                                          ┌────────────────────┐    ┌──────────────────┐
        └──────────────────────────────────────────────────────────┤ Playbook triggers /  │◀───┤ AM outreach,      │
                                   next period's                    │ churn-risk flags     │    │ renewal/expansion │
                                   raw data reflects                │ (threshold rules,    │    │ opportunity       │
                                   whether the                      │ logged fire + result)│    │ opened            │
                                   intervention worked               └──────────────────────┘    └──────────────────┘
```

Concretely, the loop that actually runs through the data model:

1. **Account health declines** — usage trend, support ticket volume/severity, and AM sentiment all move together in the months before a real churn (this is generated causally, not decorative noise; a naive classifier on these inputs lands at ~0.65–0.80 AUC, not ~0.5 or ~0.98).
2. **The variance-diagnostic engine** flags the account (or the segment-level metric it rolls up into) once its health score crosses a threshold, and drills from the Layer-1 metric that missed plan down to the actual Layer-2/3 driver — not just "revenue is down."
3. **A playbook trigger fires** off that same threshold (binary rule, e.g. "30 days post-close under 50% committed-Action utilization"), logged with what action resulted — not just fired silently.
4. **AM outreach happens** (`am_activity`), and a renewal or expansion opportunity opens ahead of term end.
5. **The opportunity closes** — Won (retained/expanded, possibly with a segment migration) or Lost (churned, `loss_reason` populated) — and that outcome lands back in the raw event data.
6. **Next week's readout** recomputes the same metric tree against the new data, so the drill-down either disappears (intervention worked) or persists/worsens (it didn't) — the same diagnostic loop runs again, informed by what actually happened.

## The metric tree

Every parent metric is the literal mathematical result of its children (sum, product, or ratio) — never a "related metrics" grouping. Three deliberate exceptions, all explicitly marked non-additive in the tree's own text: Brand & Awareness (a leading indicator, not summed into the pipeline math), Marketing–sales handoff quality (a diagnostic overlay on New Logo's three multiplicative factors, not a fourth factor), and LTV by segment × acquisition channel (a diagnostic overlay on Consumption payback, not a mathematical child).

- **Growth** — `Starting + New Logo − Contraction − Churn + Expansion` (± segment migration, nets to zero). New Logo decomposes into Pipeline Generated × Win Rate × Avg Initial Commitment; Expansion into Wallet Share Progression × Overage Realization; Contraction/Churn into workflow under-utilization, account health score, and renewal win rate.
- **Efficiency** — is the touch model paying for itself. Magic Number, Consumption Payback (CAC ÷ utilized-Action margin), Onboarding/CS Efficiency, AM Efficiency.
- **Durability** — is what we sold sticking. NRR, GRR, Logo Retention.

Full formulas, owners, and layer depth: [`docs/acme-corp-gtm-metric-tree.md`](docs/acme-corp-gtm-metric-tree.md).

## Repo structure

| Path | Contents |
|---|---|
| `docs/` | Company model, GTM motion, schema, and metric-tree reference docs — the single source of truth for anything defined here |
| `generators/` | Phase 1 Python generators — one module per simulated source system (CRM, billing, usage, CS-ops, marketing) |
| `data/raw/` | Generator output (CSV), seeded for reproducibility |
| `dbt/` | Phase 2 dbt-duckdb project — staging → intermediate → dimensions/facts → marts |
| `tests/` | QA plan's pytest suite — referential integrity, distributional realism, correlational validity, volume sufficiency, edge-case existence |
| `semantic/` | Phase 3 MCP server + metric registry, generated from the tree file |
| `analytics/` | All twenty-one Phase 4 artifacts — variance-diagnostic engine, health score, forecast, capacity planning, marketing attribution, data quality governance, deal-level diagnostics, rep productivity, automated playbook triggers, territory coverage, TAM/ICP sizing, pricing/packaging analytics, MMM/incrementality, scenario planning, retention/expansion cohorts, lead-scoring model validation, testing/experimentation platform, proxy-metric health, pipeline coverage |
| `dashboard/` | Phase 5 CRO-facing web app (Streamlit) — digest, forecast, segment-efficiency, and "ask the metric tree" chat views |
| `pipeline/` | Orchestration layer: one task DAG over the generators, QA gates, dbt build, every analytics artifact and the smoke checks; the governance gate; the freshness contract ([`pipeline/README.md`](pipeline/README.md)) |
| `.github/workflows/` | CI: a fast verification workflow on every push and pull request, and a weekly full-DAG workflow |

## Build status

Built phase by phase, each validated against real generated data before the next begins.

- [x] **Phase 1 — Raw source simulation**: raw tables across CRM, billing, usage, CS-ops, and marketing spend (including `campaigns`/`leads`/`campaign_engagement_events` and `fact_forecast_submissions`/`cro_forecast_adjustments`, added in Wave 2; `fact_sales_activities`, event-grain rep-opportunity engagement data added in Wave 4; and `company_territory`/`rep_territory`, the territory dimension `mart_tam_whitespace` slices by, added as a Wave 5 prerequisite), causally wired and incident-injected.
- [x] **Phase 2 — dbt data model**: staging through the core marts (`mart_growth_bridge`, `mart_efficiency`, `mart_durability`, `mart_segment_migration`) plus TAM whitespace.
- [x] **Phase 3 — Semantic layer (MCP)**: metric registry generated from the tree file + MCP server (`list_metrics`, `get_metric_definition`, `query_metric`) under `semantic/`.
- [x] **Phase 4 — Analytics artifacts**: all seven waves (twenty artifacts — see `analytics/` above and `docs/asset-briefs/` for the full list) are built and validated, closing the build spec's full 22-artifact priority order (three items were absorbed into other artifacts by the spec's own design, not built standalone). Pipeline coverage is a twenty-first artifact added after that order closed (Wave 10, built; independent validation pending): a by-segment coverage reading of open new-business pipeline against realized conversion and the quota still to book, reconciled to the forecast and never merged with it. See `CLAUDE.md`'s "Current phase" section or `CHANGELOG.md` for per-wave detail.
- [x] **Phase 5 — CRO / leadership interface**: a Streamlit app (`dashboard/`) reading live from the finished marts, the weekly readout's own generated output, and `analytics/forecast.py`/`semantic/server.py` called in-process — the digest, forecast, segment-efficiency, and chat views called for in the build spec's Section 6 scope guardrail, not a full BI platform.

The weekly readout's executive-summary narrative is built but not generated in the committed outputs (it needs an API key; see "Executive summary narrative" under step 4).

Known, deliberate gaps rather than silent placeholders: Consumption Payback's CAC is marketing-spend-only (rep fully-loaded cost is carried in Magic Number and AM Efficiency, not folded into payback), so its level is caveated against the benchmark band, and Magic Number's S&M cost excludes marketing-team headcount, which the raw data does not carry.

## Stack

DuckDB · dbt-core (dbt-duckdb adapter) · Python · MCP Python SDK · Streamlit · Claude API for the readout's narrative generation

## Running it

Every command below runs from the repo root unless it says otherwise. The generators and the test suite read and write `data/raw/` by relative path, and `python3 -m pytest` (rather than bare `pytest`) is what puts the repo root on the import path.

### Prerequisites

- **Root environment (generators, tests, dbt, `analytics/`)**: Python 3.9 or later. Built and validated on 3.9.6; `requirements.txt` pins the exact versions (`numpy 2.0.2`, `pandas 2.3.3`, `duckdb 1.4.3`, `scikit-learn 1.6.1`, `scipy 1.13.1`, `pytest 8.4.2`, `dbt-core 1.10.23`, `dbt-duckdb 1.10.0`):

  ```bash
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  ```

  `python3 -m pipeline` invokes dbt through the same interpreter, so no `dbt` executable needs to be on your `PATH`; running `dbt` by hand in step 3 does need one (with a user-level `pip3 install` on macOS it lands in `~/Library/Python/3.9/bin`). The root environment pins `duckdb 1.4.3` while `semantic/` and `dashboard/` use `1.5.5`: the database is always written by dbt in the root environment, and the two virtualenvs only read it.
- **`semantic/.venv` and `dashboard/.venv` (Python 3.12)**: the MCP SDK needs Python 3.10 or later, so the semantic layer and the dashboard (which imports `semantic/server.py` in-process) each get their own virtualenv. Setup commands are in [`semantic/README.md`](semantic/README.md) and [`dashboard/README.md`](dashboard/README.md). Neither venv is needed for anything before the final step below.
- **dbt profile**: `dbt/profiles.yml` lives inside the project directory, so running dbt from `dbt/` needs no `~/.dbt` setup. It writes `data/acme_gtm.duckdb` (gitignored, rebuilt from scratch on every clean build).

### One command: the orchestration layer

The numbered steps below are the same sequence `python3 -m pipeline` runs as a dependency graph (details in [`pipeline/README.md`](pipeline/README.md)):

```bash
python3 -m pipeline plan                    # show the execution order; no side effects
python3 -m pipeline run                     # verify the dataset on disk: QA suites -> dbt build -> governance gate
                                            #   -> all 21 analytics artifacts + the optional executive summary -> log refresh -> smoke checks -> freshness
python3 -m pipeline run --with-generators   # cold rebuild: regenerate data/raw first (overwrites tracked CSVs)
python3 -m pipeline run --only weekly_readout    # one node plus what it needs; add --no-deps for the node alone
python3 -m pipeline gate                    # governance checks + registry staleness, nonzero exit on failure
python3 -m pipeline check-freshness         # every artifact against its SLA in pipeline/freshness_contract.json
```

The default run never regenerates `data/raw`. The first failing node stops the run and is named in the output; run manifests land in the gitignored `pipeline/runs/`. The semantic-layer and dashboard smoke nodes need `semantic/.venv` and `dashboard/.venv` and are reported as `SKIPPED` (never as passed) when those are absent. GitHub Actions runs `python3 -m pipeline run --profile ci` on every push and pull request (`.github/workflows/ci.yml`) and the full DAG weekly (`.github/workflows/full-pipeline.yml`).

### 1. Generate the raw data (Phase 1)

Eleven generator batches write 29 CSVs into `data/raw/`. Later batches read earlier batches' output CSVs, not their in-memory state, so each is a separate command and the order matters. Numeric order is a valid order; there is no batch 10 (numbering runs 9 → 11), and nothing needs to run out of numeric sequence.

| # | Command | Source system | Writes to `data/raw/` | Needs first |
|---|---|---|---|---|
| 1 | `python3 -m generators.run_foundation` | Reps, market universe, accounts | `users`, `quota_history`, `rep_status_history`, `market_universe`, `accounts`, `account_segment_history` | nothing |
| 2 | `python3 -m generators.run_batch2` | CRM, product usage, billing | `opportunities`, `opportunity_stage_history`, `usage_monthly`, `fact_workflow_chain_events`, `subscriptions`, `mrr_by_account_month`, `committed_vs_utilized_monthly` | foundation |
| 3 | `python3 -m generators.run_batch3` | CS-ops, marketing spend | `support_tickets`, `am_activity`, `marketing_spend_by_channel_month` | foundation, batch 2 |
| 4 | `python3 -m generators.run_batch4` | Product telemetry (logins) | `product_logins` | foundation, batch 2 |
| 5 | `python3 -m generators.run_batch5` | FP&A / RevOps plan | `gtm_plan_targets` | nothing (reads no CSV, by design: a plan cannot depend on the period it plans) |
| 6 | `python3 -m generators.run_batch6` | Forecasting | `fact_forecast_submissions`, `cro_forecast_adjustments` | foundation, batch 2 |
| 7 | `python3 -m generators.run_batch7` | Marketing automation | `campaigns`, `leads`, `campaign_engagement_events` | foundation |
| 8 | `python3 -m generators.run_batch8` | Sales engagement | `fact_sales_activities` | foundation, batch 2 |
| 9 | `python3 -m generators.run_batch9` | Territory dimension | `company_territory`, `rep_territory` | foundation |
| 11 | `python3 -m generators.run_batch11` | Lead scoring | `lead_scoring_history` | foundation, batch 7 |
| 12 | `python3 -m generators.run_batch12` | Experimentation | `experiments_registry`, `experiment_assignment` | batch 7 |

Dependencies form a tree, not a chain: foundation feeds batches 2, 7 and 9; batch 2 feeds 3, 4, 6 and 8; batch 7 feeds 11 and 12; batch 5 stands alone. Re-running a batch changes every downstream batch's inputs, so after regenerating foundation or batch 2, re-run everything after it. Each batch is seeded (`config.SEED` plus a per-batch offset; batch 12 draws no randomness), and prints a summary of what it generated (most also print build-time sanity checks) when it finishes.

### 2. Validate the raw data

```bash
python3 -m pytest tests/ -v
```

`tests/` holds the QA plan's suite, one file per batch (`test_phase1_foundation.py`, then `test_phase1_batch2.py` through `test_phase1_batch9.py`, `test_phase1_batch11.py`, `test_phase1_batch12.py`; there is no batch 10 file). The suite reads `data/raw/` only, so it needs all eleven batches to have run but not dbt. To check one batch, run its file directly, for example `python3 -m pytest tests/test_phase1_batch7.py -v`; `test_phase1_batch7.py` also reads batch 3's `marketing_spend_by_channel_month.csv`.

### 3. Build the dbt project (Phase 2)

```bash
cd dbt && dbt build
```

dbt reads each `data/raw/*.csv` in place as a DuckDB external table (path set by the `raw_data_path` var in `dbt/dbt_project.yml`; no seeds, no copy into the warehouse), builds staging → intermediate → dimensions/facts → marts, and runs the schema tests plus the singular tests in `dbt/tests/`. Two more version-controlled CSVs are also sources: `data/model_performance_history.csv` and `data/playbook_triggers.csv`, the append-only logs the Phase 4 artifacts write. Both ship with the repo, so a first build needs nothing beyond step 1.

### 4. Run the analytics artifacts (Phase 4)

Every `analytics/` module reads the finished marts in `data/acme_gtm.duckdb` read-only, so step 3 must have completed and no `dbt` process may be holding the file. Each module's `__main__` runs its build-time validation at its own fixed as-of date, prints the result, and by default upserts scalar checkpoints into `data/model_performance_history.csv`; a few also write `analytics/outputs/` reports or `data/playbook_triggers.csv`.

```bash
python3 -m analytics.<module>     # e.g. weekly_readout, forecast, health_score, variance_diagnostic
```

This step is a refresh, not a prerequisite: the logs and `analytics/outputs/` files that the dashboard reads are committed. Ordering constraints between artifacts (`proxy_metric_health` counts every other artifact's logged checkpoints and runs last; `weekly_readout` reads the trigger log `playbook_triggers` writes and calls `forecast` for its forecast section) are encoded in the orchestration layer's DAG. `analytics.model_performance` is a library module, and `analytics.deal_diagnostics` has no command-line entry point of its own (the pipeline runs it through `python3 -m pipeline.entrypoints deal_diagnostics 2025-11-30`). Re-run `dbt build` afterwards if you want the refreshed logs reflected in `fact_model_performance_history` and `fact_playbook_triggers` (the pipeline's `dbt_refresh_logs` node does this).

#### Executive summary narrative (optional; needs an Anthropic API key)

The weekly readout's executive summary is written by the Claude API, in a separate pipeline step, and stored in the readout JSON (`analytics/outputs/weekly_readout_<date>.json`, key `executive_summary`); the dashboard only reads it. Every statement is checked by a deterministic validator before it is published: each figure must appear, within its displayed rounding and in its written unit, in an object the statement cites, with segment, forecast-lens and metric labels bound to their own figures where checkable; the engine's top-ranked driver must be named; caveats and banned wording are enforced. The checks do not verify that the prose is the right story or a causal explanation. Text that fails twice is discarded. With no key the section says `not_generated` and why, and everything else runs as usual. There is no template fallback.

```bash
pip install -r requirements.txt                              # includes the pinned anthropic SDK
export ANTHROPIC_API_KEY=...                                 # never stored or logged by this repo
export ACME_SUMMARY_MODEL=claude-sonnet-5-5                  # optional; this is the default
python3 -m pipeline run --only executive_summary --no-deps   # or: python3 -m analytics.executive_summary
```

Each drill-down in the readout carries a persistence record from the variance engine (whether the same Layer-2 driver has been the largest adverse outlier on consecutive months, flagged at 2), and the readout includes a segment-mix section (each segment's share of MRR and migration rates). The summary may cite the persistence records and does not read the segment mix. A summary is reused, with no API call, while the readout it was generated from is unchanged (`input_hash`); `python3 -m analytics.executive_summary --force` regenerates it. The committed readouts carry `not_generated` because no live run has been made from this repository. See `docs/acme-corp-analytics-methods.md`, "Executive summary narrative".

### 5. Semantic layer and dashboard (Phases 3 and 5)

```bash
# MCP server (stdio); see semantic/README.md for client configuration
semantic/.venv/bin/python semantic/server.py

# CRO dashboard; needs data/acme_gtm.duckdb and at least one analytics/outputs/weekly_readout_*.json
dashboard/.venv/bin/streamlit run dashboard/app.py
```
