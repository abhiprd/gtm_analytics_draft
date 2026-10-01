"""The repo's task DAG: every runnable unit of work and what it needs first.

This file is the single declaration of build order. The README's "Running
it" section, the CI workflows and the freshness contract all defer to it
(tests/test_pipeline_dag.py keeps the contract and the generator
dependencies honest against the code they describe).

Reading the graph, left to right:

  generators (opt-in) -> qa_raw -> dbt_build -> qa_marts / governance_gate
      -> analytics artifacts (... -> weekly_readout -> executive_summary)
      -> proxy_metric_health -> dbt_refresh_logs -> smoke checks
      -> freshness_check

* Generators overwrite tracked data/raw, so they are opt-in
  (`--with-generators`); the default path verifies the dataset on disk.
* `governance_gate` precedes the analytics artifacts on purpose: it is
  read-only, and failing it first keeps artifacts from being regenerated
  (and their tracked outputs rewritten) on top of marts whose metric-tree
  identities do not hold.
* Dependencies among analytics artifacts are real data/log dependencies,
  not style: see the comment on each.

Adding an artifact: append a Node below, add its entry to
pipeline/freshness_contract.json. Any node added to ANALYTICS_NODES is
automatically upstream of `proxy_metric_health`, which counts every other
artifact's logged checkpoints. tests/test_pipeline_dag.py fails if an
analytics module with a `__main__` is missing from either place.

Monitoring hook (recurring model-drift checks): add Nodes with
`profiles=frozenset({"monitor"})` and `deps=("proxy_metric_health",)`, then
schedule `python3 -m pipeline run --profile monitor`. No node is registered
to it yet; selecting an empty profile is a reported error, not a silent pass.
"""
from __future__ import annotations

from typing import List, Tuple

from .dag import Node, validate

VERIFY = frozenset({"verify"})
VERIFY_CI = frozenset({"verify", "ci"})
REBUILD = frozenset({"rebuild"})

DB = "data/acme_gtm.duckdb"

# Analytics entrypoints print "[FAIL]" for a failed validation check and
# still exit 0; the runner treats that line as a node failure.
_FAIL = (r"^\s*\[FAIL\]",)

# A node that finds at run time it cannot do its optional work prints a
# "[SKIP]" line; the runner records the node as skipped, never as passed.
_SKIP = (r"^\s*\[SKIP\]",)

# dbt is invoked through the interpreter that runs the pipeline so it always
# uses the same installed dbt-core/dbt-duckdb as the rest of the root
# environment, whether or not a `dbt` executable is on PATH.
_DBT = ("{python}", "-c", "import sys; from dbt.cli.main import cli; sys.exit(cli())")


def _generator(name: str, module: str, deps: Tuple[str, ...], writes: Tuple[str, ...],
               description: str) -> Node:
    return Node(
        name=name, kind="generator", description=description,
        argv=("{python}", "-m", f"generators.{module}"), deps=deps,
        profiles=REBUILD, opt_in=True, mutates=tuple(f"data/raw/{w}.csv" for w in writes),
        timeout_s=1800,
    )


def _analytics(module: str, as_of: Tuple[str, ...], deps: Tuple[str, ...] = (),
               description: str = "", name: str = "",
               expected_fail: Tuple[str, ...] = (), requires: Tuple[str, ...] = (DB,),
               mutates: Tuple[str, ...] = (), skip_patterns: Tuple[str, ...] = (),
               skip_is_expected: bool = False) -> Node:
    return Node(
        name=name or module, kind="analytics", description=description,
        argv=("{python}", "-m", f"analytics.{module}"),
        deps=("governance_gate",) + deps,
        requires=requires, mutates=("data/model_performance_history.csv",) + mutates,
        as_of=as_of, fail_patterns=_FAIL, expected_fail=expected_fail,
        skip_patterns=skip_patterns, skip_is_expected=skip_is_expected, timeout_s=3600,
    )


GENERATOR_NODES: Tuple[Node, ...] = (
    _generator("gen_foundation", "run_foundation", (),
               ("users", "quota_history", "rep_status_history", "market_universe",
                "accounts", "account_segment_history"),
               "Reps, market universe, accounts, segment history"),
    _generator("gen_batch2", "run_batch2", ("gen_foundation",),
               ("opportunities", "opportunity_stage_history", "usage_monthly",
                "fact_workflow_chain_events", "subscriptions", "mrr_by_account_month",
                "committed_vs_utilized_monthly"),
               "CRM opportunities, product usage, billing"),
    _generator("gen_batch3", "run_batch3", ("gen_foundation", "gen_batch2"),
               ("support_tickets", "am_activity", "marketing_spend_by_channel_month"),
               "Support tickets, AM activity, marketing spend"),
    _generator("gen_batch4", "run_batch4", ("gen_foundation", "gen_batch2"),
               ("product_logins",), "Product login telemetry"),
    _generator("gen_batch5", "run_batch5", (), ("gtm_plan_targets",),
               "FP&A / RevOps plan targets (reads no other CSV, by design)"),
    _generator("gen_batch6", "run_batch6", ("gen_foundation", "gen_batch2"),
               ("fact_forecast_submissions", "cro_forecast_adjustments"),
               "Weekly forecast submissions and CRO overlay"),
    _generator("gen_batch7", "run_batch7", ("gen_foundation",),
               ("campaigns", "leads", "campaign_engagement_events"),
               "Marketing automation: campaigns, leads, engagement events"),
    _generator("gen_batch8", "run_batch8", ("gen_foundation", "gen_batch2"),
               ("fact_sales_activities",), "Sales engagement activities"),
    _generator("gen_batch9", "run_batch9", ("gen_foundation",),
               ("company_territory", "rep_territory"), "Territory dimension"),
    _generator("gen_batch11", "run_batch11", ("gen_foundation", "gen_batch7"),
               ("lead_scoring_history",), "Lead-scoring history"),
    _generator("gen_batch12", "run_batch12", ("gen_batch7",),
               ("experiments_registry", "experiment_assignment"),
               "Experiment registry and assignment"),
)

GATE_NODES: Tuple[Node, ...] = (
    Node(
        name="qa_pipeline", kind="qa",
        description="Unit tests of the orchestration layer itself (DAG, freshness, gate)",
        argv=("{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider",
              "{glob:tests/test_pipeline_*.py}"),
        profiles=VERIFY_CI,
    ),
    Node(
        name="qa_raw", kind="qa",
        description="Phase 1 QA suite against data/raw (referential integrity, distributions, edge cases)",
        argv=("{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider",
              "{glob:tests/test_phase1_*.py}"),
        deps=("qa_pipeline",) + tuple(n.name for n in GENERATOR_NODES),
        profiles=VERIFY_CI, timeout_s=1800,
    ),
    Node(
        name="dbt_build", kind="dbt",
        description="dbt build: staging -> intermediate -> marts, with schema and singular tests",
        argv=_DBT + ("build",), deps=("qa_raw",), cwd="dbt",
        profiles=VERIFY_CI, mutates=(DB,), timeout_s=3600,
    ),
    Node(
        name="qa_marts", kind="qa",
        description="Mart- and log-level tests (everything in tests/ that is not Phase 1 raw or pipeline)",
        argv=("{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests",
              "--ignore-glob=tests/test_phase1_*.py",
              "--ignore-glob=tests/test_pipeline_*.py"),
        deps=("dbt_build",), requires=(DB,), profiles=VERIFY_CI, timeout_s=1800,
    ),
    Node(
        name="governance_gate", kind="governance",
        description="Metric-tree identity checks, marts data quality, invariants (read-only; nonzero exit on any failure)",
        argv=("{python}", "-m", "pipeline", "gate", "--check", "identity"),
        deps=("dbt_build",), requires=(DB,), profiles=VERIFY_CI,
    ),
    Node(
        name="registry_check", kind="governance",
        description="Semantic metric registry is current against docs/acme-corp-gtm-metric-tree.md",
        argv=("{python}", "-m", "pipeline", "gate", "--check", "registry"),
        profiles=VERIFY_CI,
    ),
)

# Order matters only as a tie-break among nodes that are ready together;
# correctness comes from `deps`.
ANALYTICS_NODES: Tuple[Node, ...] = (
    _analytics("health_score", ("2025-12-31",),
               description="Account health / churn-risk score"),
    _analytics("segment_migration", ("2025-12-31",),
               description="Segment migration analysis"),
    _analytics("marketing_attribution", ("2025-12-31",),
               description="Marketing attribution and channel mix"),
    _analytics("capacity_planning", ("2025-12-31",),
               description="Sales capacity planning and quota achievability"),
    _analytics("forecast", ("2025-11-14",),
               description="Sales forecast: bottoms-up, ML and CRO-overlay lenses"),
    _analytics("data_quality_governance", ("2025-12-31",),
               description="Data quality and metric governance report"),
    Node(
        name="deal_diagnostics", kind="analytics",
        description="Deal-level risk diagnostics (library module; run through pipeline.entrypoints)",
        argv=("{python}", "-m", "pipeline.entrypoints", "deal_diagnostics", "2025-11-30"),
        deps=("governance_gate",), requires=(DB,),
        mutates=("data/model_performance_history.csv",), as_of=("2025-11-30",),
        fail_patterns=_FAIL, timeout_s=3600,
    ),
    _analytics("rep_productivity", ("2025-12-31",),
               description="Rep productivity and coaching diagnostics"),
    _analytics("territory_coverage", ("2025-12-31",),
               description="Territory and account coverage"),
    _analytics("tam_icp_sizing", ("2025-12-31",),
               description="TAM / ICP / opportunity sizing"),
    _analytics("pricing_packaging", ("2025-11-30",),
               description="Pricing and packaging analytics"),
    _analytics("retention_cohorts", ("2025-12-31",),
               description="Retention and expansion cohorts"),
    _analytics("lead_scoring_validation", ("2025-12-31",),
               description="Lead-scoring model validation and drift detection"),
    _analytics("experimentation_platform", ("2025-06-30", "2025-12-31"),
               description="Experimentation platform evaluation framework"),
    # Reuses marketing_attribution's holdout estimates as the benchmark the
    # media-mix regression is compared against.
    # The regression reports, by design, that community spend does not add
    # explanatory value at this sample size (methods doc, "MMM /
    # incrementality": 2 of 3 non-vacuousness checks pass at 2025-12-31).
    _analytics("mmm_incrementality", ("2025-12-31",), ("marketing_attribution",),
               description="Media-mix incrementality regression",
               expected_fail=(r"^\s*\[FAIL\] spend_adds_value_community:",)),
    # Imports marketing_attribution for the pipeline_generated node.
    _analytics("variance_diagnostic", ("2025-11-30",), ("marketing_attribution",),
               description="Variance-diagnostic engine over the metric tree"),
    # Propagates input changes through the variance engine's tree structure.
    _analytics("scenario_planning", ("2025-11-30",), ("variance_diagnostic",),
               description="Scenario planning and sensitivity"),
    # Upserts data/playbook_triggers.csv, which the weekly readout reads.
    _analytics("playbook_triggers", ("2025-11-30", "2025-12-31"),
               description="Automated playbook triggers"),
)

_ALL_BUT_LAST = tuple(n.name for n in ANALYTICS_NODES)

ANALYTICS_LAST: Tuple[Node, ...] = (
    # Reads the trigger log, the variance engine's scorecard and the
    # forecast artifact's lenses (its forecast section runs run_forecast()
    # at the latest weekly call on or before the reporting period's end).
    _analytics("weekly_readout", ("2025-11-30",),
               ("variance_diagnostic", "playbook_triggers", "health_score", "forecast"),
               description="Weekly executive readout (JSON + Markdown)"),
    # Fills the readout's executive_summary slot through the Claude API and
    # re-renders the readout Markdown. Without ANTHROPIC_API_KEY it writes
    # the honest not_generated slot, logs narrative_generated=0 and ends
    # SKIPPED (exit 0; --strict does not fail on it: a missing key is a
    # configuration state, not a broken environment). Validation failure or
    # an API error with a key present prints [FAIL] and stops the run.
    _analytics("executive_summary", ("2025-11-30",), ("weekly_readout",),
               description="Executive-summary narrative (Claude API, grounding-validated)",
               requires=("analytics/outputs/weekly_readout_2025-11-30.json",),
               mutates=("analytics/outputs/weekly_readout_2025-11-30.json",
                        "analytics/outputs/weekly_readout_2025-11-30.md"),
               skip_patterns=_SKIP, skip_is_expected=True),
    # Counts every other artifact's logged checkpoints: runs last.
    _analytics("proxy_metric_health", ("2025-12-31",),
               _ALL_BUT_LAST + ("weekly_readout", "executive_summary"),
               description="Proxy-metric health and analytics investment prioritization"),
)

TAIL_NODES: Tuple[Node, ...] = (
    Node(
        name="dbt_refresh_logs", kind="dbt",
        description="Re-materialize fact_model_performance_history and fact_playbook_triggers from the refreshed logs",
        argv=_DBT + ("build", "--select", "+fact_model_performance_history",
                     "+fact_playbook_triggers"),
        deps=("proxy_metric_health",), cwd="dbt", requires=(DB,),
        profiles=VERIFY, mutates=(DB,), timeout_s=1800,
    ),
    Node(
        name="semantic_smoke", kind="semantic",
        description="Semantic layer imports under semantic/.venv and answers list/get/query against the marts",
        argv=("{python}", "pipeline/smoke_semantic.py"), interpreter="semantic",
        deps=("registry_check", "dbt_refresh_logs"), requires=(DB,), profiles=VERIFY,
    ),
    Node(
        name="dashboard_smoke", kind="dashboard",
        description="Dashboard pages render headless under dashboard/.venv without raising",
        argv=("{python}", "pipeline/smoke_dashboard.py"), interpreter="dashboard",
        deps=("weekly_readout", "dbt_refresh_logs"), requires=(DB,), profiles=VERIFY,
        timeout_s=900,
    ),
    Node(
        name="freshness_check", kind="freshness",
        description="Every contracted artifact is within its freshness SLA",
        argv=("{python}", "-m", "pipeline", "check-freshness"),
        deps=("registry_check", "dbt_refresh_logs", "dashboard_smoke", "semantic_smoke"),
        profiles=VERIFY_CI,
    ),
)

NODES: Tuple[Node, ...] = (
    GENERATOR_NODES + GATE_NODES + ANALYTICS_NODES + ANALYTICS_LAST + TAIL_NODES
)

ANALYTICS_ALL: List[Node] = [n for n in NODES if n.kind == "analytics"]
BY_NAME = {n.name: n for n in NODES}

validate(NODES)
