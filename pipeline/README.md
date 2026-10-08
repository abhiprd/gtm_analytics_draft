# Orchestration layer and freshness contract

One task DAG replaces the repo's 19 independent `python3 -m analytics.<module>` entrypoints, the eleven generator commands and the test/dbt steps: `python3 -m pipeline`. It is deliberately a thin layer, standard library only, rather than an Airflow, Dagster or Prefect deployment. A node is a name, a command and the names of the nodes it needs first (`dag.py`), so the graph in `nodes.py` lifts into any of them unchanged; nothing here depends on the scheduler being ours.

```bash
python3 -m pipeline plan                        # the order `run` would use; no side effects
python3 -m pipeline run                         # verify the dataset on disk (default profile)
python3 -m pipeline run --with-generators       # cold rebuild: regenerate data/raw first
python3 -m pipeline run --only weekly_readout   # one node plus everything it needs first
python3 -m pipeline run --only forecast --no-deps
python3 -m pipeline run --from variance_diagnostic
python3 -m pipeline run --profile ci            # the fast subset CI runs
python3 -m pipeline gate                        # governance + registry enforcement
python3 -m pipeline check-freshness --as-of 2025-12-31
```

## The DAG

```
gen_* (opt-in) -> qa_pipeline -> qa_raw -> dbt_build -> qa_marts
                                              |-> governance_gate -> 22 analytics artifacts (21 + executive_summary)
registry_check                                                    -> proxy_metric_health (last)
   -> dbt_refresh_logs -> semantic_smoke, dashboard_smoke -> freshness_check
```

| Node(s) | Kind | Needs first | What it does |
|---|---|---|---|
| `gen_foundation`, `gen_batch2` ... `gen_batch12` (11) | generator, opt-in | per the README's generator table | Regenerate `data/raw`. Dependencies are the ones the code actually reads; `tests/test_pipeline_dag.py` parses each `run_*.py` and fails if a batch reads a CSV whose producer is not upstream. |
| `qa_pipeline` | pytest | nothing | Unit tests of this layer (DAG, selection, runner, freshness, gate). |
| `qa_raw` | pytest | `qa_pipeline` (and the generators, when selected) | `tests/test_phase1_*.py` against `data/raw`. |
| `dbt_build` | dbt | `qa_raw` | `dbt build` into `data/acme_gtm.duckdb`: models plus schema and singular tests. |
| `qa_marts` | pytest | `dbt_build` | Every other test file: mart-, log- and gate-level checks. |
| `governance_gate` | gate | `dbt_build` | `pipeline gate --check identity` (below). Read-only. |
| `registry_check` | gate | nothing | `pipeline gate --check registry` (below). |
| 21 other analytics nodes | analytics | `governance_gate`, plus real data dependencies | Each runs `python3 -m analytics.<module>` (`deal_diagnostics`, a library module, runs through `pipeline/entrypoints.py`). |
| Optional analytics node `executive_summary` | analytics | `weekly_readout` | Fills the readout's executive-summary slot through the Claude API and re-renders the Markdown (below). Ends `SKIPPED` without `ANTHROPIC_API_KEY`. |
| `dbt_refresh_logs` | dbt | `proxy_metric_health` | Re-materializes `fact_model_performance_history` and `fact_playbook_triggers` from the logs the analytics nodes just wrote. |
| `semantic_smoke` | smoke, `semantic/.venv` | `registry_check`, `dbt_refresh_logs` | The MCP server module imports and answers `list_metrics`, `get_metric_definition` and a real `query_metric`; an unknown metric is rejected. |
| `dashboard_smoke` | smoke, `dashboard/.venv` | `weekly_readout`, `dbt_refresh_logs` | Every Streamlit page renders headless (AppTest) without raising. |
| `freshness_check` | freshness | everything above | `pipeline check-freshness`. |

Analytics dependencies that are real data or log dependencies, not style: `marketing_attribution` before `variance_diagnostic` (it imports the pipeline-generated node) and before `mmm_incrementality` (it benchmarks against the holdout estimates); `variance_diagnostic` before `scenario_planning`; `capacity_planning` and `forecast` before `pipeline_coverage` (it imports capacity planning's quota loader and the forecast's open-pipeline scoping and reconciles to the forecast's manager lens); `playbook_triggers`, `variance_diagnostic`, `health_score` and `forecast` before `weekly_readout` (the readout reads `data/playbook_triggers.csv`, runs the variance engine and watchlist, and calls `run_forecast()` for its forecast section); `weekly_readout` before `executive_summary` (it summarizes the readout JSON that node just wrote); every other artifact, `executive_summary` included, before `proxy_metric_health`, which counts their logged checkpoints. `governance_gate` precedes all of them so a run never rewrites tracked outputs on top of marts whose metric-tree identities do not hold.

### Profiles and selection

* **`verify`** (default): everything above except the generators. `data/raw` is tracked, and regenerating it overwrites tracked files, so generators are opt-in: `--with-generators`, or naming one (`--only gen_batch3` also runs the generators it needs, `--from gen_batch7` runs batch 7 and everything downstream).
* **`ci`**: `qa_pipeline`, `qa_raw`, `dbt_build`, `qa_marts`, `governance_gate`, `registry_check`, `freshness_check`. No analytics refresh and no virtualenvs.
* **`rebuild`**: the generators alone.
* **`monitor`**: reserved for recurring drift checks. No node is registered to it, and selecting it is an error, not a silent pass. To schedule a check, add a `Node` with `profiles=frozenset({"monitor"})` and `deps=("proxy_metric_health",)` in `nodes.py`, then run `python3 -m pipeline run --profile monitor` on the cadence it needs.
* `--only NODE` (repeatable) runs the node and its required upstream; `--no-deps` runs exactly the named node. `--from NODE` runs the node and everything downstream. Edges to nodes that are not selected are treated as already satisfied on disk.

### Running

The first failing node stops the run. The output names the node, its exit code or reason and the tail of its log, then lists the nodes that did not run. Each node runs in its own subprocess with the interpreter it needs: the root interpreter for everything except `semantic_smoke` (`semantic/.venv`) and `dashboard_smoke` (`dashboard/.venv`). If a virtualenv is absent the node is reported as `SKIPPED: venv missing: ...`, never as passed; `--strict` turns a skip into exit code 3.

**Self-declared skips: `executive_summary`.** The executive-summary node needs `ANTHROPIC_API_KEY`. Without it the node still runs: it leaves the readout's `executive_summary` slot honestly `not_generated` (reason `no_api_key`), logs `narrative_generated = 0`, prints a `[SKIP]` line, and the runner records it as `SKIPPED` with that reason in the manifest, never as passed. The node declares the skip expected (`skip_is_expected`), so `--strict` lists it but does not fail on it: a missing key is a configuration state, not a broken environment, and `full-pipeline.yml` runs `--strict` without one. With a key, a summary that fails grounding validation after its one retry, or an API error, prints `[FAIL]` and stops the run. To generate: `ANTHROPIC_API_KEY=... python3 -m pipeline run --only executive_summary --no-deps`.

The analytics entrypoints report a failed validation check by printing `[FAIL]` and exiting 0, so the runner treats a `[FAIL]` line in a node's output as a failure. A node can declare `expected_fail` patterns for documented findings that are not defects: `mmm_incrementality` reports, by design, that community spend does not add explanatory value at this sample size (methods doc, "MMM / incrementality").

| Exit code | Meaning |
|---|---|
| 0 | Every selected node passed (skips allowed unless `--strict`) |
| 1 | A node failed, or `gate` / `check-freshness` found a violation |
| 2 | Invalid invocation: unknown node, empty profile, malformed date or contract |
| 3 | `--strict` and at least one node was skipped (except a skip the node declares expected: `executive_summary` without a key) |

**Run manifest.** Every `run` writes `pipeline/runs/<run_id>.json` (and `latest.json`) plus a log per node under `pipeline/runs/<run_id>/`: per-node status, exit code, seconds and argv, the selection flags, git commit and dirty flag, interpreter and platform. It is gitignored on purpose: wall-clock timestamps, durations and interpreter paths change on every run and would churn a tracked file. CI uploads the directory as a build artifact.

### Idempotence and what a run changes

The default path rewrites tracked files only through the artifacts' own writers: `data/model_performance_history.csv` (an upsert keyed on model, as-of date and metric that replaces a row in place, so a re-run never duplicates or reorders a row), `data/playbook_triggers.csv` (also an upsert), the four report families under `analytics/outputs/`, and the gitignored database.

Measured behavior of a repeated run:

* **Re-running the analytics over an unchanged database** (`python3 -m pipeline run --from governance_gate`): the trigger log and every report are byte-identical, and the performance log keeps its 712 rows in the same order. Two scalars differ in their last digits (`capacity_planning` `attainment_reconciliation_max_abs_diff_usd`, 7e-09 versus 0; `marketing_attribution` `campaign_vs_coarse_spend_pct_diff`, in the 13th significant digit) because DuckDB sums floats across threads in a run-dependent order.
* **Re-running the whole default path** (which rebuilds the database): the marts are not reproducible across two identical `dbt build`s. Nine of 35 marts differ byte-for-byte at the default thread count (`dim_reps`, `fact_opportunity_stage_history`, `fact_rep_monthly_cost`, `fact_subscriptions`, `mart_durability`, `mart_efficiency`, `mart_growth_bridge`, `mart_segment_migration`, `mart_tam_whitespace`), and three (`mart_durability`, `mart_efficiency`, `mart_growth_bridge`) still differ with DuckDB pinned to one thread. The content is the same; the row order and last-digit float sums are not, because the final selects carry no `ORDER BY`. Artifacts that fit models on the loaded frames (`forecast`'s ML lens, `deal_diagnostics`, `segment_migration`) see the rows in a different order and log slightly different values (an AUC moving in the third decimal, a confusion-matrix cell moving by one), and the readout, governance and proxy-health reports differ in float noise. Removing this needs an explicit `ORDER BY` in those marts' final selects and in the artifacts' loaders; until then a full re-run leaves small, meaningless diffs in tracked outputs, and the untouched-by-rebuild path above is the one that is exactly idempotent.

### Cold rebuild

`python3 -m pipeline run --with-generators` regenerates all 29 raw CSVs in dependency order, then runs the whole default path on top. The generators are seeded (`config.SEED` plus a per-batch offset) and their output is byte-identical across rebuilds: a cold run (database deleted, all 11 batches regenerated, then the full default path, 41 nodes at the time; the graph now has 42) took about five minutes, of which the generators are about 83 seconds, and reproduced all 29 files in `data/raw` bit for bit (SHA-256 compared before and after). `full-pipeline.yml` (manual dispatch, `rebuild_data: true`) asserts the same with `git diff --exit-code -- data/raw`.

## Governance gate

`python3 -m pipeline gate [--check identity|registry|all]`, exit 0 or 1.

* **identity** re-runs `analytics/data_quality_governance.py` read-only (`log=False, write_report=False`, so no tracked file changes) and fails on any failed metric-tree edge, marts data-quality check or CLAUDE.md invariant, or if that module's own synthetic self-check (does it still catch a known-broken case?) stops passing. The module computes these checks but its entrypoint always exits 0; this is the enforcement point. Each failure is listed by family and name.
* **registry** fails when `semantic/metric_registry.json` is stale against `docs/acme-corp-gtm-metric-tree.md`. The registry stamps the tree's SHA-256, but `build_registry.py` only rewrites the file when the *parsed content* changes, so a prose-only tree edit leaves the stamp behind without the registry being wrong. Staleness is therefore determined by content: if the stamp differs, the tree is re-parsed and the registry is stale only when the regenerated content hash differs (or the tree no longer parses). A lagging stamp over identical content is a warning, and fails under `--strict-stamp`. Remedy: `semantic/.venv/bin/python semantic/build_registry.py`.

## Freshness contract

`pipeline/freshness_contract.json` states, for every analytics artifact and for the raw data, the dbt marts, the model-performance log, the semantic registry and the dashboard's inputs: owner, cadence, SLA, basis, dependencies, the evidence that shows it is current, and what "fresh" means. `python3 -m pipeline check-freshness [--as-of DATE] [--artifact NAME] [--json]` evaluates it against the files on disk and exits 1 on any stale or missing artifact.

**Staleness** = basis date minus the newest evidence date, in days (evidence newer than the basis counts as zero). **Evidence** is read from: dated output files (`analytics/outputs/<name>_YYYY-MM-DD.json`), the newest `as_of_date` logged for the artifact's model in `data/model_performance_history.csv`, a column maximum in a CSV or a mart, a JSON field, or (for the registry) the gate's verdict. An artifact with several evidence sources takes its worst state.

**Reference date.** `--as-of` defaults to the dataset horizon, `analysis_as_of_date` in `dbt/dbt_project.yml`, not wall-clock today: the data is a fixed simulation, and measuring it against the real calendar would call everything stale. Pass a later date to see the contract fire (`--as-of 2026-03-31` marks the weekly readout stale).

**Basis.** `horizon` is the reference date itself. `last_complete_month` is the last day of the month before the reference date's month: artifacts that evaluate a whole month can only be run once it has closed, and the simulation's final month carries an end-of-window truncation artifact (`variance_diagnostic._data_window_check`), which is why their canonical checkpoint is 2025-11-30.

**`executive_summary` is fresh without prose.** Its evidence is the `executive_summary_narrative` checkpoint in the performance log, written on every run whether or not a summary was generated (`narrative_generated` is 1 or 0). Freshness therefore attests that the narrative step evaluated the current readout; it does not attest that prose exists, so a deployment with no key stays green here. The distinct state lives in the readout JSON (`executive_summary.status`: `generated`, `not_generated` with a reason, or `validation_failed`) and in `narrative_generated`; the dashboard renders from the JSON.

**SLA policy.** One cadence period plus a stated slip, using the native grains in the dashboard conventions' grain table and the wave structure in the build spec (Section 8): weekly = 7 + 3 days = 10; monthly = 31 + 4 = 35; quarterly = 92 + 7 = 99; per-build = 10; the registry = 0 (it must change in the same commit as the tree). The loader rejects an SLA tighter than its own cadence. Exceptions to the policy carry their reasoning in the entry's `sla_rationale`: `forecast` and `pipeline_coverage` are 21 days because their validated checkpoint (2025-11-14, the last mid-quarter point with a large enough open Commercial/Enterprise population to score) sits 16 days behind the last complete month.

| Artifact | Owner | Cadence | Basis | SLA (days) |
|---|---|---|---|---|
| `weekly_readout` | RevOps | weekly | last complete month | 10 |
| `executive_summary` | RevOps | weekly | last complete month | 10 |
| `playbook_triggers` | RevOps | weekly | horizon | 10 |
| `deal_diagnostics` | Sales Ops | weekly | last complete month | 10 |
| `forecast` | Sales Ops / Finance | weekly | last complete month | 21 |
| `pipeline_coverage` | Sales Ops / RevOps | weekly | last complete month | 21 |
| `data_quality_governance` | Analytics Engineering | weekly | horizon | 10 |
| `variance_diagnostic` | RevOps | monthly | last complete month | 35 |
| `scenario_planning` | Finance / RevOps | monthly | last complete month | 35 |
| `health_score` | CS / Account Management | monthly | horizon | 35 |
| `segment_migration` | RevOps | monthly | horizon | 35 |
| `marketing_attribution` | Marketing Ops | monthly | horizon | 35 |
| `proxy_metric_health` | Analytics Engineering | monthly | horizon | 35 |
| `capacity_planning` | Sales Ops | quarterly | horizon | 99 |
| `rep_productivity` | Sales Ops / Enablement | quarterly | horizon | 99 |
| `territory_coverage` | Sales Ops | quarterly | horizon | 99 |
| `tam_icp_sizing` | Strategy / Sales Ops | quarterly | horizon | 99 |
| `pricing_packaging` | Finance / Pricing | quarterly | last complete month | 99 |
| `retention_cohorts` | CS / Finance | quarterly | horizon | 99 |
| `lead_scoring_validation` | Marketing Ops | quarterly | horizon | 99 |
| `experimentation_platform` | Marketing Ops / Analytics Engineering | quarterly | horizon | 99 |
| `mmm_incrementality` | Marketing Ops / Finance | quarterly | horizon | 99 |
| `raw_data` | Analytics Engineering | monthly | horizon | 35 |
| `dbt_marts` | Analytics Engineering | monthly | horizon | 35 |
| `model_performance_log` | Analytics Engineering | per build | horizon | 10 |
| `semantic_registry` | Analytics Engineering | event driven | horizon | 0 |
| `dashboard_readout_input` | RevOps | weekly | last complete month | 10 |
| `dashboard_status_manifest` | Analytics Engineering | quarterly | horizon | 99 |

Owners are functional roles, not people. The per-entry `sla_rationale` in the JSON is the authority for why each number is what it is.

**Keeping the contract honest.** `tests/test_pipeline_dag.py` fails when an `analytics/*.py` module with a `__main__` has no DAG node or contract entry, when a new analytics module is neither contracted nor declared a library module, when an entry's checkpoint dates differ from the dates hard-coded in the module's `__main__`, when an entry's `model_name` differs from the module's `_MODEL_NAME`, when an entry's `depends_on` differs from the DAG, when a generator reads a CSV whose producer is not upstream, and when a file in `data/raw` has no producing node.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request: Python 3.9 from `requirements.txt`, then `python -m pipeline run --profile ci`, which is the DAG's own fast path (the pipeline unit tests, the Phase 1 QA suite, a from-scratch `dbt build` from the tracked raw CSVs, the mart and gate tests, the governance gate, the registry check and the freshness check on the committed outputs). Any failed metric-tree identity check or stale registry fails the job. The run manifest is uploaded as an artifact.

`.github/workflows/full-pipeline.yml` runs weekly and on demand: it adds both Python 3.12 virtualenvs, runs the whole DAG with `--strict` (so a missing virtualenv is a failure, not a skip), and, when dispatched with `rebuild_data`, regenerates `data/raw` and requires it to match the tracked files.
