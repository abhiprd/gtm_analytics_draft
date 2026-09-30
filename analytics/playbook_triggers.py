"""Automated playbook triggers -- Wave 4 (build spec Section 8, item #10).
Grain: one row per trigger firing (rule_id, account_id, timestamp,
resulting_action, outcome, plus owner / SLA / outcome-capture columns);
sources: fact_workflow_chain_events, fact_opportunities,
fact_committed_vs_utilized_monthly, fact_am_activity, fact_subscriptions,
dim_reps, dim_accounts, fact_account_segment_history (main_marts only).

WHAT THIS IS
------------
Build spec Section 5's "Playbook triggers: binary threshold rules... with
a log of which triggers fired and what action resulted." Section 8's
build-priority order places this artifact in Wave 4 with the stated
dependency "needs Wave 1's thresholds validated against real data first"
-- satisfied: the variance-diagnostic engine and the weekly executive
readout (Wave 1's fourth and fifth artifacts) are both built and
validated. `analytics/variance_diagnostic.py` and
`analytics/weekly_readout.py` both record the resolved scope decision
that playbook triggers are NOT built there; this module is where that
deferred work lands.

SHAPE -- STRUCTURAL/LOGIC, NOT PREDICTIVE
------------------------------------------
Every rule below is a deterministic threshold comparison against
already-materialized mart values -- no coefficient, no AUC, no confusion
matrix, no R^2/RMSE applies, and their absence is deliberate, not
pending, per `.claude/skills/analytics-engineering-conventions`'
"Structural/logic artifacts" category (the same category the
variance-diagnostic engine, segment migration analysis, capacity
planning, marketing attribution and data-quality-governance entries all
use). The correctness claim this artifact makes is narrower: does each
rule fire on a hand-constructed case it should fire on, and not fire on
one it shouldn't. That is `run_synthetic_scenarios()` below.

WHY THESE THREE RULES, AND WHY THEIR THRESHOLDS DIFFER FROM THE BUILD
SPEC'S OWN ILLUSTRATIVE NUMBERS
------------------------------------------------------------------------
Build spec Section 5 offers three rules as examples ("e.g."), not a fixed
spec: "14+ days of ingestion-without-completion," "POC pass rate below
60%," "30 days post-close under 50% committed-Action utilization." All
three are kept as the starting set -- they map cleanly onto three real
marts (fact_workflow_chain_events, fact_opportunities.poc_outcome,
fact_committed_vs_utilized_monthly) and the build spec itself frames them
as the working examples for this artifact. Their NUMBERS are not kept
unchanged: build-time grounding against this data's real distribution
(see each rule's threshold constant below, and the "Automated playbook
triggers" entry in docs/acme-corp-analytics-methods.md) showed the
literal 60% and 50% examples sit so close to this population's median
that they would fire on the large majority of accounts almost always --
a threshold that fires constantly is not a trigger, it is a constant. The
day-grain "14+ days" / "30 days" language is also translated to this
data's real grain: every one of these three source marts is
account-per-MONTH, not per-day (no day-level ingestion or utilization
event exists anywhere in Phase 1), so "N+ days" becomes "N+ consecutive
months" throughout, the same translation build spec Section 5's own
Activation trailing-baseline precedent and the account-health score's
"N consecutive months" churn language already establish elsewhere in
this project.

POINT-IN-TIME DESIGN
---------------------
Every loader filters its source mart to `month <= as_of_date` /
`close_date <= as_of_date`. Every rule's own trailing-window logic (the
ingestion-stall streak count, the POC cohort pass rate) only ever looks
backward from the row being evaluated -- never at a value dated after
that row -- so no rule can leak a future month's data into a trigger
timestamped earlier.

OUTCOME CAPTURE, OWNERSHIP AND SLA (Wave 9)
--------------------------------------------
`run_playbook_triggers()` still returns only what fired (outcome None).
`enrich_triggers()` adds, per trigger: (a) an outcome resolved from data
observed strictly AFTER the trigger, against a rule-specific documented
criterion (OUTCOME_CRITERIA), `pending` until that rule's window has
elapsed as of the evaluation date; (b) the owning rep resolved from real
assignment data (OWNER_RULES), null + an explicit reason when none is
resolvable; (c) an SLA clock (SLA_CONFIG) and an escalation field.
Manually/externally recorded outcomes (`record_outcome()`, the seam for a
future CRM round-trip) are never overwritten by the automated resolver.
`open_trigger_tasks()` is the task-list read over the log. Every value in
OUTCOME_CRITERIA / OWNER_RULES / SLA_CONFIG is PROPOSED, not confirmed.

DETERMINISM
-----------
No stochastic step exists anywhere in this module -- no sampling, no
simulation, no train/test split. Every rule is a deterministic threshold
comparison over already-materialized mart values, so no random seed
applies, matching analytics/segment_migration.py's and
analytics/variance_diagnostic.py's precedent.
"""
import csv
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import pandas as pd

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "playbook_triggers.csv")
_MODEL_NAME = "automated_playbook_triggers"

# Build spec Section 5 / line 118's exact operational-log grain.
_COLUMNS = ["rule_id", "account_id", "timestamp", "resulting_action", "outcome"]

# Operational-log CSV schema: the five build-spec columns first, everything
# added by outcome capture / ownership / SLA appended after them, so a
# reader of the original five-column layout still finds them in place.
_OUTCOME_FIELDS = ["outcome", "outcome_date", "outcome_metric_value", "outcome_reason",
                   "outcome_window_end", "outcome_evaluated_as_of", "outcome_source"]
_ENRICH_FIELDS = ["owner_rep_id", "owner_role", "owner_unresolved_reason", "account_territory",
                  "sla_hours", "sla_due_at", "escalation_to", "escalation_reason"]
_LOG_COLUMNS = (_COLUMNS
                + ["outcome_date", "outcome_metric_value", "outcome_reason", "outcome_window_end",
                   "outcome_evaluated_as_of", "outcome_source"]
                + _ENRICH_FIELDS + ["closed_at"])
_KEY = ("rule_id", "account_id", "timestamp")

# Outcome vocabulary. `pending` = the rule's observation window has not
# elapsed as of the evaluation date (never guessed); `not_evaluable` = the
# window elapsed but the data cannot decide it (e.g. too few forward POCs).
OUTCOME_VOCABULARY = ("resolved", "unresolved", "pending", "not_evaluable")
AUTOMATED_SOURCE = "automated"
MANUAL_SOURCES = ("manual", "crm")


# =====================================================================
# Rule configuration -- stored, configurable thresholds, not hardcoded
# inline per-call. Every threshold is PROPOSED, not yet confirmed by
# analytics-model-validator -- see docs/acme-corp-analytics-methods.md's
# "Automated playbook triggers" entry for the real-distribution grounding
# behind each number.
# =====================================================================

RULES: Dict[str, Dict[str, Any]] = {
    "ingestion_without_completion": {
        "description": (
            "Workflow-chain ingestion-without-completion sustained "
            "2+ consecutive months (full_chain_completion_rate < 70%)."
        ),
        "completion_rate_threshold": 0.70,
        "min_consecutive_months": 2,
        "resulting_action": "Escalate to CS for workflow-chain diagnostic outreach",
        "source_mart": "fact_workflow_chain_events",
    },
    "poc_pass_rate_below_threshold": {
        "description": (
            "An Enterprise POC resolves as a fail while the trailing 90-day "
            "cohort POC pass rate (as of that resolution, backward-looking "
            "only) sits below 30%."
        ),
        "pass_rate_threshold": 0.30,
        "trailing_window_days": 90,
        "min_cohort_size": 5,
        "resulting_action": "Escalate to Sales Engineering leadership for POC process review",
        "source_mart": "fact_opportunities",
    },
    "post_close_underutilization": {
        "description": (
            "Commercial/Enterprise new-business account's first full "
            "calendar month post-close runs under 30% committed-Action "
            "utilization."
        ),
        "utilization_threshold": 0.30,
        "eligible_segments": ("Commercial", "Enterprise"),
        "resulting_action": "Trigger AM proactive onboarding check-in",
        "source_mart": "fact_committed_vs_utilized_monthly + fact_opportunities",
    },
}


# =====================================================================
# Outcome-capture, ownership and SLA configuration -- PROPOSED, not yet
# confirmed. Each value is a first-build judgement grounded in this
# data's own structure (see docs/acme-corp-analytics-methods.md's
# "Automated playbook triggers" entry), not a fitted or validated number.
# =====================================================================

# Success criterion per rule, tied to the rule's own purpose. All windows
# open strictly AFTER the trigger timestamp and evidence is used only up
# to as_of_date; a trigger is `pending` until its window has fully elapsed.
OUTCOME_CRITERIA: Dict[str, Dict[str, Any]] = {
    "ingestion_without_completion": {
        "kind": "sustained_recovery",
        "description": (
            "Resolved if the account's full_chain_completion_rate returns to "
            ">= 0.70 for 2 consecutive months within 6 months after the "
            "trigger; unresolved if it does not (including if the account "
            "churns first)."),
        "recovery_threshold": 0.70,
        "recovery_consecutive_months": 2,
        "window_months": 6,
        # Horizon of the adverse event (churn) used ONLY by
        # evaluate_rule_informativeness()'s flagged-vs-unflagged comparison.
        "adverse_horizon_months": 6,
    },
    "poc_pass_rate_below_threshold": {
        "kind": "forward_cohort_pass_rate",
        "description": (
            "Resolved if the Enterprise POC pass rate over the 90 days after "
            "the trigger (>= 5 resolved POCs) is >= 30%, i.e. the systemic "
            "low-pass-rate condition the rule fired on has cleared; "
            "unresolved if it is still below 30%; not_evaluable if fewer than "
            "5 POCs resolved in that window."),
        "pass_rate_threshold": 0.30,
        "window_days": 90,
        "min_cohort_size": 5,
    },
    "post_close_underutilization": {
        "kind": "sustained_recovery",
        "description": (
            "Resolved if committed-Action utilization reaches >= 0.50 for 2 "
            "consecutive months within 3 months after the (first full "
            "post-close month) trigger; unresolved if it does not (including "
            "if the account churns first)."),
        "recovery_threshold": 0.50,
        "recovery_consecutive_months": 2,
        "window_months": 3,
        "adverse_horizon_months": 12,
    },
}

# Owner per rule, resolved from real assignment data only. There is no
# account-to-AM assignment table in the source data: the AM of record is
# the AM who most recently logged an activity on the account on or before
# the SLA clock start (fact_am_activity is the only place an account is
# tied to an AM). SMB is no-touch by design and carries no AM.
OWNER_RULES: Dict[str, Dict[str, Any]] = {
    "ingestion_without_completion": {
        "basis": "am_of_record",
        "description": "Account's AM of record (most recent fact_am_activity rep as of the SLA clock start), "
                       "active in dim_reps at that date.",
    },
    "poc_pass_rate_below_threshold": {
        "basis": "deal_owner_ae",
        "description": "The AE who owns the failed-POC Enterprise opportunity (fact_opportunities.rep_id "
                       "on the account's failed-POC opportunity closing on the trigger date). The action's "
                       "addressee, SE leadership, has no rep-level representation in the source data.",
    },
    "post_close_underutilization": {
        "basis": "am_of_record",
        "description": "Account's AM of record (most recent fact_am_activity rep as of the SLA clock start), "
                       "active in dim_reps at that date.",
    },
}

# SLA per rule. timestamp_grain "month": the trigger is stamped at the
# first of the month its underlying monthly figure describes, but that
# figure is not knowable until the month has ended -- the SLA clock starts
# at the first of the FOLLOWING month. "day": the clock starts at the
# trigger date itself.
SLA_CONFIG: Dict[str, Dict[str, Any]] = {
    "ingestion_without_completion": {"sla_hours": 120, "timestamp_grain": "month"},
    "poc_pass_rate_below_threshold": {"sla_hours": 168, "timestamp_grain": "day"},
    "post_close_underutilization": {"sla_hours": 72, "timestamp_grain": "month"},
}

# The source data carries no manager / reporting-line field for any rep
# (users.csv: rep_id, rep_type, segment, hire_date, book_size, comp only),
# so escalation_to cannot be resolved from real data. It is left null with
# this reason rather than inferred from seniority or role; resolve_
# escalation() accepts a rep_id -> manager_id mapping as the seam for the
# raw-data addition that would close this.
ESCALATION_NO_REPORTING_LINE = "no_reporting_line_in_source"


# =====================================================================
# Pure compute functions -- no DB connection. Every rule's actual logic
# lives here, taking already-loaded DataFrames, so the exact same code
# path real-data triggers run through is what the synthetic scenarios
# below exercise.
# =====================================================================

def compute_ingestion_stall_triggers(chain_df: pd.DataFrame, as_of_date: date,
                                     rule: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Grain in: account_id, month, full_chain_completion_rate (one row
    per account per month). Grain out: one row per contiguous below-
    threshold streak that first reaches min_consecutive_months length, at
    the month it crosses that bar -- fires once per episode, not once per
    month the episode continues."""
    rule = rule or RULES["ingestion_without_completion"]
    df = chain_df[chain_df["month"] <= pd.Timestamp(as_of_date)].copy()
    df = df.sort_values(["account_id", "month"]).reset_index(drop=True)
    df["below"] = df["full_chain_completion_rate"] < rule["completion_rate_threshold"]

    rows: List[Dict[str, Any]] = []
    for account_id, g in df.groupby("account_id"):
        streak = 0
        for _, row in g.iterrows():
            streak = streak + 1 if bool(row["below"]) else 0
            if streak == rule["min_consecutive_months"]:
                rows.append({
                    "rule_id": "ingestion_without_completion",
                    "account_id": account_id,
                    "timestamp": row["month"],
                    "resulting_action": rule["resulting_action"],
                    "outcome": None,
                })
    return pd.DataFrame(rows, columns=_COLUMNS)


def _failed_poc_cohort_rates(poc_df: pd.DataFrame, as_of_date: date,
                             rule: Dict[str, Any]) -> pd.DataFrame:
    """Grain: one row per failed Enterprise POC (traceable account or not)
    closing <= as_of_date, with cohort_n / cohort_pass_rate over every
    other resolved POC in the trailing window strictly before it, so its
    own outcome never enters its own cohort rate. Shared by the trigger
    rule and by its flagged-vs-unflagged comparison."""
    df = poc_df[poc_df["close_date"] <= pd.Timestamp(as_of_date)].copy()
    df = df.sort_values("close_date").reset_index(drop=True)
    window = pd.Timedelta(days=rule["trailing_window_days"])
    rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        if row["poc_outcome"] != "fail":
            continue
        cohort = df[(df["close_date"] < row["close_date"]) &
                    (df["close_date"] >= row["close_date"] - window)]
        rows.append({
            "account_id": row["account_id"], "close_date": row["close_date"],
            "cohort_n": len(cohort),
            "cohort_pass_rate": (cohort["poc_outcome"] == "pass").mean() if len(cohort) else float("nan"),
        })
    return pd.DataFrame(rows, columns=["account_id", "close_date", "cohort_n", "cohort_pass_rate"])


def compute_poc_pass_rate_triggers(poc_df: pd.DataFrame, as_of_date: date,
                                   rule: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Grain in: account_id, opportunity_id, close_date, poc_outcome (one
    row per Enterprise opportunity with a resolved POC -- account_id may
    be null on a lost opportunity; see load_enterprise_poc_opportunities).
    Grain out: one row per opportunity whose own POC failed, whose own
    account_id is traceable, and whose trailing cohort (every other POC
    that closed in the window, strictly before this one, so today's own
    outcome never enters its own cohort rate, REGARDLESS of whether that
    other POC's own account_id happens to be null) sat below the
    pass-rate floor. The cohort-rate computation intentionally uses every
    resolved POC in the window, nameable account or not -- only the row
    actually emitted requires one, per the loader's own docstring."""
    rule = rule or RULES["poc_pass_rate_below_threshold"]
    rates = _failed_poc_cohort_rates(poc_df, as_of_date, rule)

    rows: List[Dict[str, Any]] = []
    for _, row in rates.iterrows():
        if pd.isna(row["account_id"]):
            # A real trigger condition (a failed POC), but with no
            # traceable account the operational log's schema can name --
            # excluded from the LOGGED set, not from the cohort-rate
            # denominator computed above.
            continue
        if row["cohort_n"] < rule["min_cohort_size"]:
            continue
        if row["cohort_pass_rate"] < rule["pass_rate_threshold"]:
            rows.append({
                "rule_id": "poc_pass_rate_below_threshold",
                "account_id": row["account_id"],
                "timestamp": row["close_date"],
                "resulting_action": rule["resulting_action"],
                "outcome": None,
            })
    return pd.DataFrame(rows, columns=_COLUMNS)


def _post_close_population(opps_df: pd.DataFrame, util_df: pd.DataFrame, as_of_date: date,
                           rule: Dict[str, Any]) -> pd.DataFrame:
    """Grain: one row per eligible won new-business Commercial/Enterprise
    account whose first full post-close month already exists in util_df as
    of as_of_date (account_id, month, utilization_rate). Shared by the
    rule's trigger logic and by its flagged-vs-unflagged comparison so both
    are drawn from exactly the same eligible population."""
    opps = opps_df[
        (opps_df["close_date"] <= pd.Timestamp(as_of_date)) &
        (opps_df["segment"].isin(rule["eligible_segments"]))
    ].copy()
    opps["post_close_month"] = (
        (opps["close_date"] + pd.offsets.MonthBegin(1)).dt.to_period("M").dt.to_timestamp()
    )
    merged = opps.merge(util_df, left_on=["account_id", "post_close_month"],
                        right_on=["account_id", "month"], how="inner")
    # Point-in-time: the post-close month itself must already have
    # happened as of as_of_date, or its utilization figure doesn't exist
    # yet to evaluate.
    return merged[merged["month"] <= pd.Timestamp(as_of_date)]


def compute_post_close_utilization_triggers(opps_df: pd.DataFrame, util_df: pd.DataFrame,
                                            as_of_date: date,
                                            rule: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Grain in: opps_df is one row per won new-business opportunity
    (account_id, close_date, segment); util_df is one row per account per
    month (account_id, month, utilization_rate) from the committed-vs-
    utilized mart. Grain out: one row per account whose first full
    calendar month after close -- the monthly-grain translation of "30
    days post-close" -- carries a committed-Action utilization rate below
    the floor. A row that has no committed-vs-utilized entry for that
    month at all (no commitment on file yet) is silently excluded rather
    than treated as zero utilization, since a missing commitment and a
    genuinely-unused commitment are different facts."""
    rule = rule or RULES["post_close_underutilization"]
    merged = _post_close_population(opps_df, util_df, as_of_date, rule)

    rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        if pd.notna(row["utilization_rate"]) and row["utilization_rate"] < rule["utilization_threshold"]:
            rows.append({
                "rule_id": "post_close_underutilization",
                "account_id": row["account_id"],
                "timestamp": row["month"],
                "resulting_action": rule["resulting_action"],
                "outcome": None,
            })
    return pd.DataFrame(rows, columns=_COLUMNS)


# =====================================================================
# Loaders -- main_marts only, per analytics-engineering-conventions.
# =====================================================================

def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


def load_workflow_chain_events(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per account_id per month, month <= as_of_date.
    Source mart: fact_workflow_chain_events."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select account_id, month, full_chain_completion_rate "
            "from main_marts.fact_workflow_chain_events where month <= ?", [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["month"] = pd.to_datetime(df["month"]).astype("datetime64[ns]")
    return df


def load_enterprise_poc_opportunities(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per Enterprise opportunity with a resolved POC
    outcome, close_date <= as_of_date, account_id included whether or not
    it is populated. Source mart: fact_opportunities.

    account_id is deliberately NOT filtered to non-null here, even though
    the operational log this rule feeds needs a real account per row (see
    compute_poc_pass_rate_triggers). fact_opportunities.account_id is
    NULL on every LOST opportunity (the same structural gap
    analytics/marketing_attribution.py's "Measure caveat" documents for
    lost new-business deals -- it holds for lost Enterprise/POC-stage
    opportunities too: of 452 Enterprise POCs at 2025-12-31, only the 113
    that closed Won carry a traceable account_id). Dropping the
    account_id-null rows HERE, before the trailing cohort pass rate is
    computed, would compute that rate over a Won-only, survivorship-
    biased subset (91 of 113 Won POCs passed -- 80.5% -- against the true
    population rate of 42.5% across all 452), which would make the rule
    almost never fire. The cohort rate must be computed over every
    resolved POC regardless of whether its account is nameable; only the
    row that would actually BE LOGGED needs a real account_id, and that
    filter is applied downstream, after the cohort rate, not before it.
    """
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select account_id, opportunity_id, close_date, poc_outcome "
            "from main_marts.fact_opportunities "
            "where segment = 'Enterprise' and poc_outcome is not null "
            "and close_date is not null and close_date <= ?", [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["close_date"] = pd.to_datetime(df["close_date"]).astype("datetime64[ns]")
    return df


def load_new_business_won_opportunities(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per won new-business opportunity with a traceable
    account, close_date <= as_of_date. Source mart: fact_opportunities."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select account_id, close_date, segment from main_marts.fact_opportunities "
            "where opportunity_type = 'new_business' and is_won = true "
            "and account_id is not null and close_date <= ?", [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["close_date"] = pd.to_datetime(df["close_date"]).astype("datetime64[ns]")
    return df


def load_committed_vs_utilized(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per account_id per month, month <= as_of_date.
    Source mart: fact_committed_vs_utilized_monthly."""
    owns = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select account_id, month, utilization_rate "
            "from main_marts.fact_committed_vs_utilized_monthly where month <= ?",
            [as_of_date]).df()
    finally:
        if owns:
            con.close()
    df["month"] = pd.to_datetime(df["month"]).astype("datetime64[ns]")
    return df


# =====================================================================
# Top-level: evaluate all three rules
# =====================================================================

def run_playbook_triggers(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per trigger firing (rule_id, account_id, timestamp,
    resulting_action, outcome). Evaluates all three configured threshold
    rules as of as_of_date against main_marts fact tables only, and
    returns the combined, UNRANKED trigger set -- build spec Section 5's
    weekly-readout section is explicit that this list is "unranked
    (binary, not prioritized)"; ranking or prioritizing it here would
    contradict that.

    outcome is always None on the frame this returns: it says what fired
    at as_of_date, not whether a firing turned out to be worth acting on.
    enrich_triggers() resolves that from data observed after each trigger
    (OUTCOME_CRITERIA), and the operational log stores it, per build spec
    line 118's stated reason for the log's existence.
    """
    owns = con is None
    con = con or _connect()
    try:
        chain = load_workflow_chain_events(as_of_date, con=con)
        poc = load_enterprise_poc_opportunities(as_of_date, con=con)
        new_biz = load_new_business_won_opportunities(as_of_date, con=con)
        util = load_committed_vs_utilized(as_of_date, con=con)
    finally:
        if owns:
            con.close()

    t1 = compute_ingestion_stall_triggers(chain, as_of_date)
    t2 = compute_poc_pass_rate_triggers(poc, as_of_date)
    t3 = compute_post_close_utilization_triggers(new_biz, util, as_of_date)
    return pd.concat([t1, t2, t3], ignore_index=True)[_COLUMNS]


# =====================================================================
# Outcome resolution -- pure functions over already-loaded data. Evidence
# is only ever read from AFTER the trigger and only up to as_of_date; a
# trigger whose observation window has not fully elapsed by as_of_date is
# `pending`, never resolved on partial evidence.
# =====================================================================

def _months_apart(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _iso(ts: Any) -> Optional[str]:
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).date().isoformat()


def _outcome_result(outcome: str, reason: str, as_of_date: date, window_end: pd.Timestamp,
                    outcome_date: Any = None, metric: Optional[float] = None) -> Dict[str, Any]:
    return {
        "outcome": outcome,
        "outcome_date": _iso(outcome_date),
        "outcome_metric_value": None if metric is None or pd.isna(metric) else float(metric),
        "outcome_reason": reason,
        "outcome_window_end": _iso(window_end),
        "outcome_evaluated_as_of": as_of_date.isoformat(),
        "outcome_source": AUTOMATED_SOURCE,
    }


def resolve_sustained_recovery_outcome(series: pd.Series, start: Any, criterion: Dict[str, Any],
                                       as_of_date: date, churn_date: Any = None) -> Dict[str, Any]:
    """Grain: one trigger. series is one account's monthly metric (index =
    month-start Timestamps, values = the metric, e.g. from
    fact_workflow_chain_events or fact_committed_vs_utilized_monthly).
    Resolved if the metric holds >= recovery_threshold for
    recovery_consecutive_months calendar-consecutive months inside
    (start, start + window_months]; unresolved if it never does (reason
    distinguishes churn from no recovery); not_evaluable if the window
    elapsed with no observation at all; pending if the window has not
    elapsed as of as_of_date."""
    start = pd.Timestamp(start)
    window_end = start + pd.DateOffset(months=criterion["window_months"])
    if window_end > pd.Timestamp(as_of_date):
        return _outcome_result("pending", "window_open", as_of_date, window_end)

    obs = (series if series.empty
           else series[(series.index > start) & (series.index <= window_end)]).dropna().sort_index()
    run, last = 0, None
    for month, val in obs.items():
        if val >= criterion["recovery_threshold"]:
            run = run + 1 if (last is not None and _months_apart(last, month) == 1) else 1
            last = month
            if run >= criterion["recovery_consecutive_months"]:
                return _outcome_result("resolved", "sustained_recovery_within_window", as_of_date,
                                       window_end, outcome_date=month, metric=val)
        else:
            run, last = 0, None

    if churn_date is not None and not pd.isna(churn_date) and start < pd.Timestamp(churn_date) <= window_end:
        return _outcome_result("unresolved", "churned_before_recovery", as_of_date, window_end,
                               outcome_date=churn_date)
    if obs.empty:
        return _outcome_result("not_evaluable", "no_observations_in_window", as_of_date, window_end)
    return _outcome_result("unresolved", "no_sustained_recovery_in_window", as_of_date, window_end,
                           outcome_date=window_end, metric=obs.iloc[-1])


def resolve_forward_pass_rate_outcome(poc_df: pd.DataFrame, start: Any, criterion: Dict[str, Any],
                                      as_of_date: date) -> Dict[str, Any]:
    """Grain: one trigger. poc_df is every resolved Enterprise POC
    (close_date, poc_outcome), traceable account or not -- the same
    population the rule's own cohort rate is computed over. Resolved if
    the pass rate over (start, start + window_days] is >= the rule's
    pass_rate_threshold (the systemic condition cleared); unresolved if
    still below it; not_evaluable if fewer than min_cohort_size POCs
    resolved in the window; pending if the window has not elapsed."""
    start = pd.Timestamp(start)
    window_end = start + pd.Timedelta(days=criterion["window_days"])
    if window_end > pd.Timestamp(as_of_date):
        return _outcome_result("pending", "window_open", as_of_date, window_end)
    fwd = poc_df[(poc_df["close_date"] > start) & (poc_df["close_date"] <= window_end)]
    if len(fwd) < criterion["min_cohort_size"]:
        return _outcome_result("not_evaluable", "forward_cohort_below_min_size", as_of_date, window_end)
    rate = float((fwd["poc_outcome"] == "pass").mean())
    if rate >= criterion["pass_rate_threshold"]:
        return _outcome_result("resolved", "forward_pass_rate_recovered", as_of_date, window_end,
                               outcome_date=window_end, metric=rate)
    return _outcome_result("unresolved", "forward_pass_rate_still_below_threshold", as_of_date,
                           window_end, outcome_date=window_end, metric=rate)


# =====================================================================
# Ownership, SLA and escalation -- pure functions.
# =====================================================================

@dataclass
class OwnerContext:
    """Already-loaded assignment data owner resolution reads from.
    am_activity: account_id, rep_id, activity_date (fact_am_activity).
    reps: rep_id, rep_type, period_start_date, period_end_date, rep_status
    (dim_reps). segment_history: account_id, segment, effective_date
    (fact_account_segment_history). poc_owners: account_id, close_date,
    rep_id, one row per Enterprise opportunity with a failed POC and a
    traceable account (fact_opportunities)."""
    am_activity: pd.DataFrame
    reps: pd.DataFrame
    segment_history: pd.DataFrame
    poc_owners: pd.DataFrame


def sla_clock_start(timestamp: Any, timestamp_grain: str) -> pd.Timestamp:
    """A month-grain trigger is stamped at the first of the month its
    figure describes, which is not knowable until that month ends: its
    clock starts the first of the following month. A day-grain trigger's
    clock starts at its own date."""
    ts = pd.Timestamp(timestamp)
    return ts + pd.offsets.MonthBegin(1) if timestamp_grain == "month" else ts


def compute_sla(rule_id: str, timestamp: Any) -> Tuple[int, pd.Timestamp]:
    """(sla_hours, sla_due_at) for one trigger, from SLA_CONFIG."""
    cfg = SLA_CONFIG[rule_id]
    return cfg["sla_hours"], sla_clock_start(timestamp, cfg["timestamp_grain"]) + pd.Timedelta(hours=cfg["sla_hours"])


def _eval_instant(as_of_date: date) -> pd.Timestamp:
    """Evaluation instant = the end of as_of_date (start of the next day)."""
    return pd.Timestamp(as_of_date) + pd.Timedelta(days=1)


def compute_sla_status(sla_due_at: Any, closed_at: Any, as_of_date: date) -> str:
    """One of open_within_sla / breached / closed_within_sla / closed_late,
    as of as_of_date. A closure dated after as_of_date does not exist yet
    as of that date and leaves the task open. closed_at is set only by a
    recorded closure (record_outcome), never inferred."""
    due = pd.Timestamp(sla_due_at)
    now = _eval_instant(as_of_date)
    if closed_at is not None and not pd.isna(closed_at) and str(closed_at) != "":
        closed = pd.Timestamp(closed_at)
        if closed < now:
            return "closed_within_sla" if closed <= due else "closed_late"
    return "open_within_sla" if now <= due else "breached"


def resolve_escalation(owner_rep_id: Optional[str],
                       reporting_lines: Optional[Dict[str, str]] = None) -> Tuple[Optional[str], Optional[str]]:
    """(escalation_to, escalation_reason). The source data has no
    reporting-line field, so with no mapping supplied this is always
    (None, 'no_reporting_line_in_source'); reporting_lines (rep_id ->
    manager rep_id) is the seam for the raw-data addition that would
    populate it."""
    if owner_rep_id and reporting_lines and owner_rep_id in reporting_lines:
        return reporting_lines[owner_rep_id], None
    return None, ESCALATION_NO_REPORTING_LINE


def _segment_as_of(seg_hist: pd.DataFrame, account_id: str, at: pd.Timestamp) -> Optional[str]:
    h = seg_hist[(seg_hist["account_id"] == account_id) & (seg_hist["effective_date"] <= at)]
    return None if h.empty else h.sort_values("effective_date").iloc[-1]["segment"]


def _rep_as_of(reps: pd.DataFrame, rep_id: str, at: pd.Timestamp) -> Tuple[Optional[str], Optional[str]]:
    """(rep_type, status as of `at`). status None if no dim_reps period
    covers `at`; rep_type None only if the rep is absent from dim_reps."""
    r = reps[reps["rep_id"] == rep_id]
    if r.empty:
        return None, None
    covering = r[(r["period_start_date"] <= at) &
                 (r["period_end_date"].isna() | (r["period_end_date"] >= at))]
    status = None if covering.empty else covering.sort_values("period_start_date").iloc[-1]["rep_status"]
    return r.iloc[0]["rep_type"], (None if status is None or pd.isna(status) else status)


def resolve_owner(rule_id: str, account_id: str, timestamp: Any, ctx: OwnerContext) -> Dict[str, Any]:
    """Grain: one trigger. Returns owner_rep_id, owner_role (dim_reps
    rep_type) and owner_unresolved_reason; when no owner is resolvable
    from real assignment data, owner_rep_id/owner_role are None and the
    reason names why -- an owner is never fabricated."""
    def unresolved(reason: str) -> Dict[str, Any]:
        return {"owner_rep_id": None, "owner_role": None, "owner_unresolved_reason": reason}

    ts = pd.Timestamp(timestamp)
    clock = sla_clock_start(ts, SLA_CONFIG[rule_id]["timestamp_grain"])
    basis = OWNER_RULES[rule_id]["basis"]

    if basis == "am_of_record":
        a = ctx.am_activity[(ctx.am_activity["account_id"] == account_id) &
                            (ctx.am_activity["activity_date"] <= clock)]
        if a.empty:
            seg = _segment_as_of(ctx.segment_history, account_id, ts)
            return unresolved("smb_no_touch_no_human_owner" if seg == "SMB"
                              else "no_am_activity_as_of_trigger")
        rep_id = a.sort_values(["activity_date", "rep_id"]).iloc[-1]["rep_id"]
    elif basis == "deal_owner_ae":
        p = ctx.poc_owners[(ctx.poc_owners["account_id"] == account_id) &
                           (ctx.poc_owners["close_date"] == ts) & ctx.poc_owners["rep_id"].notna()]
        if p.empty:
            return unresolved("no_matching_opportunity")
        rep_id = p.sort_values("rep_id").iloc[0]["rep_id"]
    else:  # pragma: no cover -- configuration error
        raise ValueError(f"unknown owner basis {basis!r} for {rule_id}")

    rep_type, status = _rep_as_of(ctx.reps, rep_id, clock)
    if rep_type is None:
        return unresolved("owner_not_in_dim_reps")
    if status == "departed":
        return unresolved("owner_departed_as_of_trigger")
    return {"owner_rep_id": rep_id, "owner_role": rep_type, "owner_unresolved_reason": None}


# =====================================================================
# Enrichment loaders -- main_marts only.
# =====================================================================

def load_enrichment_context(as_of_date: date, con=None) -> Dict[str, Any]:
    """Everything enrich_triggers() reads beyond the three rule loaders:
    AM activity, rep periods, segment history, failed-POC deal owners,
    churn dates and account territory. Source marts: fact_am_activity,
    dim_reps, fact_account_segment_history, fact_opportunities,
    fact_subscriptions, dim_accounts. Everything is filtered to
    <= as_of_date."""
    owns = con is None
    con = con or _connect()
    try:
        am = con.execute(
            "select account_id, rep_id, activity_date from main_marts.fact_am_activity "
            "where activity_date <= ?", [as_of_date]).df()
        reps = con.execute(
            "select rep_id, rep_type, period_start_date, period_end_date, rep_status "
            "from main_marts.dim_reps").df()
        seg = con.execute(
            "select account_id, segment, effective_date from main_marts.fact_account_segment_history "
            "where effective_date <= ?", [as_of_date]).df()
        poc_owners = con.execute(
            "select account_id, close_date, rep_id from main_marts.fact_opportunities "
            "where segment = 'Enterprise' and poc_outcome = 'fail' and account_id is not null "
            "and close_date <= ?", [as_of_date]).df()
        churn = con.execute(
            "select account_id, max(end_date) as churn_date from main_marts.fact_subscriptions "
            "where status = 'churned' and end_date <= ? group by 1", [as_of_date]).df()
        terr = con.execute("select account_id, territory from main_marts.dim_accounts").df()
    finally:
        if owns:
            con.close()
    am["activity_date"] = pd.to_datetime(am["activity_date"]).astype("datetime64[ns]")
    reps["period_start_date"] = pd.to_datetime(reps["period_start_date"]).astype("datetime64[ns]")
    reps["period_end_date"] = pd.to_datetime(reps["period_end_date"]).astype("datetime64[ns]")
    seg["effective_date"] = pd.to_datetime(seg["effective_date"]).astype("datetime64[ns]")
    poc_owners["close_date"] = pd.to_datetime(poc_owners["close_date"]).astype("datetime64[ns]")
    churn["churn_date"] = pd.to_datetime(churn["churn_date"]).astype("datetime64[ns]")
    return {
        "owner_ctx": OwnerContext(am, reps, seg, poc_owners),
        "churn_dates": dict(zip(churn["account_id"], churn["churn_date"])),
        "territory": dict(zip(terr["account_id"], terr["territory"])),
    }


def _series_by_account(df: pd.DataFrame, value_col: str) -> Dict[str, pd.Series]:
    return {k: g.set_index("month")[value_col] for k, g in df.groupby("account_id")}


def enrich_triggers(triggers: pd.DataFrame, as_of_date: date, con=None,
                    reporting_lines: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """Grain: one row per trigger firing (rule_id, account_id, timestamp,
    resulting_action, outcome + the outcome / owner / SLA / escalation
    columns of the operational log). Resolves each trigger's outcome from
    data observed after it, as of as_of_date, its owner from real
    assignment data, its SLA due time and its escalation target. Source
    marts: those of the three rules plus load_enrichment_context()'s.
    Deterministic; no stochastic step."""
    owns = con is None
    con = con or _connect()
    try:
        chain = load_workflow_chain_events(as_of_date, con=con)
        util = load_committed_vs_utilized(as_of_date, con=con)
        poc = load_enterprise_poc_opportunities(as_of_date, con=con)
        ctx = load_enrichment_context(as_of_date, con=con)
    finally:
        if owns:
            con.close()

    series = {
        "ingestion_without_completion": _series_by_account(chain, "full_chain_completion_rate"),
        "post_close_underutilization": _series_by_account(util.dropna(subset=["utilization_rate"]),
                                                          "utilization_rate"),
    }
    empty = pd.Series(dtype=float)

    rows: List[Dict[str, Any]] = []
    for rec in triggers.to_dict(orient="records"):
        rule_id, acct, ts = rec["rule_id"], rec["account_id"], pd.Timestamp(rec["timestamp"])
        crit = OUTCOME_CRITERIA[rule_id]
        if crit["kind"] == "sustained_recovery":
            out = resolve_sustained_recovery_outcome(
                series[rule_id].get(acct, empty), ts, crit, as_of_date, ctx["churn_dates"].get(acct))
        else:
            out = resolve_forward_pass_rate_outcome(poc, ts, crit, as_of_date)
        own = resolve_owner(rule_id, acct, ts, ctx["owner_ctx"])
        sla_hours, due = compute_sla(rule_id, ts)
        esc_to, esc_reason = resolve_escalation(own["owner_rep_id"], reporting_lines)
        rows.append({
            "rule_id": rule_id, "account_id": acct, "timestamp": ts,
            "resulting_action": rec["resulting_action"],
            **out, **own,
            "account_territory": ctx["territory"].get(acct),
            "sla_hours": sla_hours,
            "sla_due_at": due.strftime("%Y-%m-%d %H:%M:%S"),
            "escalation_to": esc_to, "escalation_reason": esc_reason,
        })
    cols = [c for c in _LOG_COLUMNS if c != "closed_at"]
    return pd.DataFrame(rows, columns=cols)


# =====================================================================
# Operational log -- append-only, upsert-safe. Exact pattern of
# analytics/model_performance.py's log_performance()/read_performance_
# history(), backed by a version-controlled CSV rather than a write
# straight into the gitignored, rebuilt-from-scratch data/acme_gtm.duckdb.
# Columns: the five build-spec columns first, then outcome / owner / SLA
# columns appended (_LOG_COLUMNS) so the original layout is preserved.
# =====================================================================

def _ts_key(v: Any) -> str:
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _cell(v: Any) -> str:
    """CSV cell text: None / NaN / NaT -> empty."""
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    if v is pd.NaT:
        return ""
    return str(v)


def _is_protected(row: Dict[str, str]) -> bool:
    """A logged outcome that did not come from the automated resolver
    (manual / CRM, or any outcome with no automated source) is protected
    from being overwritten by it."""
    return bool(row.get("outcome")) and row.get("outcome_source") != AUTOMATED_SOURCE


def _merge_log_row(existing: Optional[Dict[str, str]], incoming: Dict[str, str]) -> Dict[str, str]:
    """Upsert semantics for one (rule_id, account_id, timestamp) key.
    - key + resulting_action: refreshed from incoming.
    - owner / SLA / escalation group: replaced as a unit when the incoming
      row carries it (sla_due_at present); otherwise kept.
    - outcome group: replaced as a unit only when the incoming row carries
      an outcome AND the existing outcome is not protected (manual/CRM) AND
      the incoming automated evaluation is not older than the existing
      automated one. A row that carries no outcome never wipes one.
    - closed_at: an existing recorded closure is kept; otherwise incoming.
    """
    row = dict(existing) if existing else {c: "" for c in _LOG_COLUMNS}
    for c in _KEY:
        row[c] = incoming[c]
    row["resulting_action"] = incoming["resulting_action"]

    if incoming.get("sla_due_at"):
        for c in _ENRICH_FIELDS:
            row[c] = incoming.get(c, "")

    if incoming.get("outcome"):
        inc_source = incoming.get("outcome_source") or "manual"
        if inc_source == AUTOMATED_SOURCE and _is_protected(row):
            pass  # the automated resolver never overwrites a manual/CRM outcome
        elif (inc_source == AUTOMATED_SOURCE and row.get("outcome_source") == AUTOMATED_SOURCE
              and row.get("outcome_evaluated_as_of")
              and incoming.get("outcome_evaluated_as_of", "") < row["outcome_evaluated_as_of"]):
            pass  # never replace a later automated evaluation with an earlier one
        else:
            for c in _OUTCOME_FIELDS:
                row[c] = incoming.get(c, "")
            row["outcome_source"] = inc_source

    if not row.get("closed_at") and incoming.get("closed_at"):
        row["closed_at"] = incoming["closed_at"]
    return row


def _write_log(rows: List[Dict[str, str]]) -> None:
    with open(_CSV_PATH, "w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(_LOG_COLUMNS)
        for r in rows:
            writer.writerow([r.get(c, "") for c in _LOG_COLUMNS])


def log_triggers(triggers: pd.DataFrame) -> None:
    """Upserts fired-trigger rows into data/playbook_triggers.csv, keyed
    on (rule_id, account_id, timestamp) -- the operational log's own
    natural grain, one row per trigger firing. Re-running a period that
    has already been logged updates those rows in place rather than
    duplicating them (mirroring analytics/model_performance.py's
    log_performance()). `triggers` may be the five-column frame
    run_playbook_triggers() returns or the full enrich_triggers() frame;
    columns it lacks leave the logged row's existing values untouched, and
    a manually / CRM-recorded outcome or closure is never overwritten
    (see _merge_log_row)."""
    existing = {(r["rule_id"], r["account_id"], r["timestamp"]): r for r in read_trigger_log()}
    for rec in triggers.to_dict(orient="records"):
        incoming = {c: _cell(rec.get(c)) for c in _LOG_COLUMNS}
        incoming["timestamp"] = _ts_key(rec["timestamp"])
        key = (incoming["rule_id"], incoming["account_id"], incoming["timestamp"])
        existing[key] = _merge_log_row(existing.get(key), incoming)
    _write_log(list(existing.values()))


def read_trigger_log() -> List[Dict[str, str]]:
    """Full operational log as a list of dicts, every _LOG_COLUMNS key
    present (empty string where a legacy file lacks a column). Empty list
    if the CSV has not been written yet."""
    if not os.path.exists(_CSV_PATH):
        return []
    with open(_CSV_PATH, newline="") as f:
        return [{c: r.get(c) or "" for c in _LOG_COLUMNS} for r in csv.DictReader(f)]


def record_outcome(rule_id: str, account_id: str, timestamp: Any, outcome: Optional[str] = None,
                   outcome_date: Any = None, outcome_metric_value: Optional[float] = None,
                   outcome_reason: Optional[str] = None, closed_at: Any = None,
                   source: str = "manual") -> None:
    """Write path for an outcome and/or task closure recorded outside the
    automated resolver -- the seam a future CRM round-trip calls. The
    trigger must already be in the log. An outcome recorded here carries
    outcome_source manual/crm and is never overwritten by
    enrich_triggers()/log_triggers(). A non-pending outcome requires an
    outcome_date; closed_at (when the owner actioned the task) drives the
    SLA's closed_within_sla / closed_late statuses."""
    if outcome is None and closed_at is None:
        raise ValueError("record_outcome needs an outcome and/or a closed_at")
    if outcome is not None and outcome not in OUTCOME_VOCABULARY:
        raise ValueError(f"outcome {outcome!r} not in {OUTCOME_VOCABULARY}")
    if source not in MANUAL_SOURCES:
        raise ValueError(f"source must be one of {MANUAL_SOURCES}; the automated resolver "
                         f"writes through enrich_triggers()")
    if outcome not in (None, "pending") and outcome_date is None:
        raise ValueError("a non-pending outcome requires outcome_date")

    key = (rule_id, account_id, _ts_key(pd.Timestamp(timestamp)))
    rows = read_trigger_log()
    hit = [r for r in rows if (r["rule_id"], r["account_id"], r["timestamp"]) == key]
    if not hit:
        raise ValueError(f"no logged trigger for {key}; record_outcome updates, never creates")
    row = hit[0]
    if outcome is not None:
        row.update({
            "outcome": outcome,
            "outcome_date": _cell(_iso(outcome_date)),
            "outcome_metric_value": _cell(outcome_metric_value),
            "outcome_reason": _cell(outcome_reason),
            "outcome_window_end": "",
            "outcome_evaluated_as_of": "",
            "outcome_source": source,
        })
    if closed_at is not None:
        row["closed_at"] = pd.Timestamp(closed_at).strftime("%Y-%m-%d %H:%M:%S")
    _write_log(rows)


def _known_outcome(row: Dict[str, str], as_of_date: date) -> Optional[str]:
    """The outcome of a logged row as it would have been knowable on
    as_of_date, else None. Automated: knowable once its window has
    elapsed. Manual/CRM: knowable once its outcome_date has."""
    if not row["outcome"] or row["outcome"] == "pending":
        return None
    cutoff = pd.Timestamp(as_of_date)
    if row["outcome_source"] == AUTOMATED_SOURCE:
        known = bool(row["outcome_window_end"]) and pd.Timestamp(row["outcome_window_end"]) <= cutoff
    else:
        known = bool(row["outcome_date"]) and pd.Timestamp(row["outcome_date"]) <= cutoff
    return row["outcome"] if known else None


def with_known_outcomes(triggers: pd.DataFrame, as_of_date: date) -> pd.DataFrame:
    """Grain: as `triggers`. Fills `outcome` from the operational log where
    that outcome was already knowable on as_of_date (a historical readout
    never shows an outcome that only resolved later); otherwise None.
    Reads the log only -- no computation."""
    known = {(r["rule_id"], r["account_id"], r["timestamp"]): _known_outcome(r, as_of_date)
             for r in read_trigger_log()}
    out = triggers.copy()
    out["outcome"] = [known.get((r["rule_id"], r["account_id"], _ts_key(r["timestamp"])))
                      for r in out.to_dict(orient="records")]
    return out


def open_trigger_tasks(as_of_date: date, lookback_days: Optional[int] = None,
                       include_settled: bool = False) -> pd.DataFrame:
    """Grain: one row per still-open trigger task as of as_of_date, read
    from the operational log. Open = the SLA clock has started, no
    closure is recorded by as_of_date and (unless include_settled) its
    outcome, as knowable on as_of_date, is not already settled: `resolved`
    (the condition cleared) or churned before recovery (nothing left to
    work). Reads the log only: a trigger still `pending` is listed even if
    its account has since churned, because that fact only enters the log
    once the window elapses.
    Ranked by SLA urgency: earliest sla_due_at first, so the most overdue
    breached tasks lead and within-SLA tasks follow soonest-due first.
    hours_overdue > 0 means past due. Ownerless tasks are kept, with their
    owner_unresolved_reason, since an unroutable task is itself the thing
    to triage. Ranks by SLA clock only, not business value -- the readout's
    trigger list stays unranked per build spec Section 5."""
    now = _eval_instant(as_of_date)
    rows = []
    for r in read_trigger_log():
        clock = sla_clock_start(r["timestamp"], SLA_CONFIG[r["rule_id"]]["timestamp_grain"])
        if clock >= now or not r["sla_due_at"]:
            continue
        if lookback_days is not None and clock < now - pd.Timedelta(days=lookback_days):
            continue
        status = compute_sla_status(r["sla_due_at"], r["closed_at"], as_of_date)
        if status.startswith("closed"):
            continue
        known = _known_outcome(r, as_of_date)
        settled = known == "resolved" or (known == "unresolved" and r["outcome_reason"] == "churned_before_recovery")
        if settled and not include_settled:
            continue
        due = pd.Timestamp(r["sla_due_at"])
        rows.append({
            "rule_id": r["rule_id"], "account_id": r["account_id"], "timestamp": r["timestamp"],
            "resulting_action": r["resulting_action"],
            "owner_rep_id": r["owner_rep_id"] or None, "owner_role": r["owner_role"] or None,
            "owner_unresolved_reason": r["owner_unresolved_reason"] or None,
            "account_territory": r["account_territory"] or None,
            "sla_due_at": due, "sla_status": status,
            "hours_overdue": (now - due).total_seconds() / 3600.0,
            "escalation_required": status == "breached",
            "escalation_to": r["escalation_to"] or None,
            "escalation_reason": r["escalation_reason"] or None,
        })
    cols = ["rule_id", "account_id", "timestamp", "resulting_action", "owner_rep_id", "owner_role",
            "owner_unresolved_reason", "account_territory", "sla_due_at", "sla_status",
            "hours_overdue", "escalation_required", "escalation_to", "escalation_reason"]
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values(["sla_due_at", "rule_id", "account_id"]).reset_index(drop=True)


def summarize_log() -> Dict[str, Dict[str, Any]]:
    """Per-rule count of logged triggers by outcome, by outcome_reason,
    owner-resolved share and owner_unresolved_reason counts -- descriptive
    read of the log as stored."""
    out: Dict[str, Dict[str, Any]] = {}
    for rule_id in RULES:
        rs = [r for r in read_trigger_log() if r["rule_id"] == rule_id]
        n = len(rs)
        owned = sum(1 for r in rs if r["owner_rep_id"])
        out[rule_id] = {
            "n": n,
            "outcomes": pd.Series([r["outcome"] or "unset" for r in rs], dtype=object).value_counts().to_dict(),
            "outcome_reasons": pd.Series([r["outcome_reason"] or "unset" for r in rs], dtype=object).value_counts().to_dict(),
            "owner_resolved": owned,
            "owner_resolved_share": (owned / n) if n else None,
            "owner_unresolved_reasons": pd.Series(
                [r["owner_unresolved_reason"] for r in rs if not r["owner_rep_id"]], dtype=object
            ).value_counts().to_dict(),
        }
    return out


def backfill_log(as_of_date: date, con=None, reporting_lines: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """Resolves outcome, owner, SLA and escalation for every trigger
    already in the operational log (timestamp <= as_of_date) as of
    as_of_date and upserts them back. Idempotent; manual/CRM outcomes are
    left untouched. Returns the enriched frame."""
    logged = pd.DataFrame(
        [{"rule_id": r["rule_id"], "account_id": r["account_id"], "timestamp": pd.Timestamp(r["timestamp"]),
          "resulting_action": r["resulting_action"], "outcome": None}
         for r in read_trigger_log() if pd.Timestamp(r["timestamp"]) <= pd.Timestamp(as_of_date)],
        columns=_COLUMNS)
    enriched = enrich_triggers(logged, as_of_date, con=con, reporting_lines=reporting_lines)
    log_triggers(enriched)
    return enriched


# =====================================================================
# Is the alert informative? Flagged vs comparable NON-flagged accounts.
# =====================================================================

def _rate(flags: List[bool]) -> Optional[float]:
    return float(sum(flags) / len(flags)) if flags else None


def _rule1_informativeness(chain: pd.DataFrame, seg_hist: pd.DataFrame, churn_dates: Dict[str, Any],
                           flagged: pd.DataFrame, as_of_date: date) -> Dict[str, Any]:
    """Churn within the rule's horizon: flagged accounts vs accounts of the
    same segment (as of the trigger month) that were healthy (completion
    >= threshold this month and last month) in the same trigger months,
    weighted to the flagged mix. Horizon-elapsed triggers only."""
    crit = OUTCOME_CRITERIA["ingestion_without_completion"]
    thr = RULES["ingestion_without_completion"]["completion_rate_threshold"]
    h = crit["adverse_horizon_months"]
    c = chain.sort_values(["account_id", "month"]).copy()
    prev = c.groupby("account_id")["full_chain_completion_rate"].shift(1)
    prev_month = c.groupby("account_id")["month"].shift(1)
    contiguous = (c["month"] - prev_month).dt.days.between(28, 31)
    c["healthy"] = (c["full_chain_completion_rate"] >= thr) & (prev >= thr) & contiguous
    c = pd.merge_asof(c.sort_values("month"), seg_hist.sort_values("effective_date"),
                      left_on="month", right_on="effective_date", by="account_id", direction="backward")
    churn = c["account_id"].map(churn_dates)
    c["churned_in_window"] = (churn > c["month"]) & (churn <= c["month"] + pd.DateOffset(months=h))

    f = flagged[flagged["timestamp"] + pd.DateOffset(months=h) <= pd.Timestamp(as_of_date)].copy()
    f = pd.merge_asof(f.sort_values("timestamp"), seg_hist.sort_values("effective_date"),
                      left_on="timestamp", right_on="effective_date", by="account_id", direction="backward")
    f_churn = f["account_id"].map(churn_dates)
    f["churned"] = (f_churn > f["timestamp"]) & (f_churn <= f["timestamp"] + pd.DateOffset(months=h))

    base = c[c["healthy"]].groupby(["segment", "month"])["churned_in_window"].agg(["mean", "size"]).reset_index()
    cells = f.groupby(["segment", "timestamp"]).size().rename("n_flagged").reset_index().merge(
        base, left_on=["segment", "timestamp"], right_on=["segment", "month"], how="left")
    cells = cells.dropna(subset=["mean"])
    expected = float((cells["mean"] * cells["n_flagged"]).sum() / cells["n_flagged"].sum())
    return {
        "adverse_event": f"churn within {h} months of the trigger month",
        "flagged_n": int(len(f)),
        "flagged_rate": float(f["churned"].mean()),
        "unflagged_comparable_n": int(cells["size"].sum()),
        "unflagged_comparable_rate": expected,
        "matching": "same segment as of the trigger month, healthy (completion >= threshold this and "
                    "last month) in the same trigger month, weighted to the flagged mix",
        "median_months_trigger_to_churn": float(
            (((f_churn - f["timestamp"]).dt.days) / 30.4375).median()),
    }


def _rule3_informativeness(opps: pd.DataFrame, util: pd.DataFrame, churn_dates: Dict[str, Any],
                           as_of_date: date) -> Dict[str, Any]:
    """Same eligible population (won new-business Commercial/Enterprise
    accounts' first full post-close month), split by the rule's own
    threshold. Compares the rule's recovery criterion (applied identically
    to both groups) and churn within the adverse horizon."""
    rule = RULES["post_close_underutilization"]
    crit = OUTCOME_CRITERIA["post_close_underutilization"]
    pop = _post_close_population(opps, util, as_of_date, rule)
    pop = pop.dropna(subset=["utilization_rate"]).copy()
    pop["flagged"] = pop["utilization_rate"] < rule["utilization_threshold"]
    series = _series_by_account(util.dropna(subset=["utilization_rate"]), "utilization_rate")
    empty = pd.Series(dtype=float)
    h = crit["adverse_horizon_months"]

    out: Dict[str, Any] = {"adverse_event": f"churn within {h} months of the post-close month"}
    for name, grp in (("flagged", pop[pop["flagged"]]), ("unflagged", pop[~pop["flagged"]])):
        res = [resolve_sustained_recovery_outcome(series.get(r.account_id, empty), r.month, crit,
                                                   as_of_date, churn_dates.get(r.account_id))
               for r in grp.itertuples()]
        decided = [x for x in res if x["outcome"] in ("resolved", "unresolved")]
        elapsed = grp[grp["month"] + pd.DateOffset(months=h) <= pd.Timestamp(as_of_date)]
        ch = elapsed["account_id"].map(churn_dates)
        churned = ((ch > elapsed["month"]) & (ch <= elapsed["month"] + pd.DateOffset(months=h))).tolist()
        out[name] = {
            "n": int(len(grp)),
            "recovery_decided_n": len(decided),
            "recovery_resolved_rate": _rate([x["outcome"] == "resolved" for x in decided]),
            "churn_horizon_elapsed_n": len(churned),
            "churned_n": int(sum(churned)),
            "churn_rate": _rate(churned),
        }
    return out


def _rule2_informativeness(poc: pd.DataFrame, as_of_date: date) -> Dict[str, Any]:
    """Every failed Enterprise POC with a full cohort, traceable account or
    not (the log holds only the traceable ones): forward 90-day pass rate
    after failures in a LOW trailing-cohort window (the rule's condition)
    vs after failures in a healthy window. Window-elapsed failures only."""
    rule = RULES["poc_pass_rate_below_threshold"]
    crit = OUTCOME_CRITERIA["poc_pass_rate_below_threshold"]
    r = _failed_poc_cohort_rates(poc, as_of_date, rule)
    r = r[r["cohort_n"] >= rule["min_cohort_size"]].copy()
    r["systemic"] = r["cohort_pass_rate"] < rule["pass_rate_threshold"]
    out: Dict[str, Any] = {"note": "all failed POCs, traceable account or not; the log holds only the "
                                   "traceable subset"}
    for name, grp in (("systemic_condition", r[r["systemic"]]), ("healthy_window", r[~r["systemic"]])):
        res = [resolve_forward_pass_rate_outcome(poc, x.close_date, crit, as_of_date)
               for x in grp.itertuples()]
        decided = [x for x in res if x["outcome"] in ("resolved", "unresolved")]
        out[name] = {
            "n": int(len(grp)),
            "decided_n": len(decided),
            "resolved_rate": _rate([x["outcome"] == "resolved" for x in decided]),
            "mean_forward_pass_rate": (float(pd.Series([x["outcome_metric_value"] for x in decided]).mean())
                                       if decided else None),
        }
    return out


def evaluate_rule_informativeness(as_of_date: date, con=None) -> Dict[str, Any]:
    """Grain: one entry per rule. Whether each rule's alerts carry
    information beyond the population they were drawn from: flagged vs
    comparable NON-flagged accounts on the rule's outcome / adverse event,
    all evidence dated <= as_of_date. Source marts: those of the three
    rules plus load_enrichment_context()'s. Descriptive, no inference --
    the comparison groups are stated with each result."""
    owns = con is None
    con = con or _connect()
    try:
        chain = load_workflow_chain_events(as_of_date, con=con)
        util = load_committed_vs_utilized(as_of_date, con=con)
        poc = load_enterprise_poc_opportunities(as_of_date, con=con)
        opps = load_new_business_won_opportunities(as_of_date, con=con)
        ctx = load_enrichment_context(as_of_date, con=con)
    finally:
        if owns:
            con.close()
    t1 = compute_ingestion_stall_triggers(chain, as_of_date)
    return {
        "ingestion_without_completion": _rule1_informativeness(
            chain, ctx["owner_ctx"].segment_history, ctx["churn_dates"], t1, as_of_date),
        "poc_pass_rate_below_threshold": _rule2_informativeness(poc, as_of_date),
        "post_close_underutilization": _rule3_informativeness(opps, util, ctx["churn_dates"], as_of_date),
    }


# =====================================================================
# Validation -- synthetic test cases with known-correct answers, per
# .claude/skills/analytics-engineering-conventions' "Structural/logic
# artifacts" category: one account that should trigger and one that
# clearly shouldn't, per rule. Run through the exact same compute_*
# functions real-data triggers use.
# =====================================================================

def run_synthetic_scenarios() -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    as_of = date(2025, 12, 31)

    # ---- Rule 1: ingestion-without-completion -------------------------
    chain_rows = [
        # SYN-CHAIN-TRIGGER: two consecutive months below 0.70 -> fires
        # once, at the second (2025-03-01).
        {"account_id": "SYN-CHAIN-TRIGGER", "month": "2025-01-01", "full_chain_completion_rate": 0.95},
        {"account_id": "SYN-CHAIN-TRIGGER", "month": "2025-02-01", "full_chain_completion_rate": 0.60},
        {"account_id": "SYN-CHAIN-TRIGGER", "month": "2025-03-01", "full_chain_completion_rate": 0.55},
        {"account_id": "SYN-CHAIN-TRIGGER", "month": "2025-04-01", "full_chain_completion_rate": 0.95},
        # SYN-CHAIN-NOTRIGGER: only a single isolated bad month -> never
        # reaches a 2-month streak, never fires.
        {"account_id": "SYN-CHAIN-NOTRIGGER", "month": "2025-01-01", "full_chain_completion_rate": 0.95},
        {"account_id": "SYN-CHAIN-NOTRIGGER", "month": "2025-02-01", "full_chain_completion_rate": 0.60},
        {"account_id": "SYN-CHAIN-NOTRIGGER", "month": "2025-03-01", "full_chain_completion_rate": 0.95},
        {"account_id": "SYN-CHAIN-NOTRIGGER", "month": "2025-04-01", "full_chain_completion_rate": 0.95},
    ]
    chain_df = pd.DataFrame(chain_rows)
    chain_df["month"] = pd.to_datetime(chain_df["month"])
    t1 = compute_ingestion_stall_triggers(chain_df, as_of)

    trig = t1[t1["account_id"] == "SYN-CHAIN-TRIGGER"]
    check("ingestion_stall_fires_on_sustained_two_month_dip",
          len(trig) == 1 and trig.iloc[0]["timestamp"] == pd.Timestamp("2025-03-01"),
          f"expected exactly 1 trigger at 2025-03-01, got {trig.to_dict(orient='records')}")
    check("ingestion_stall_does_not_fire_on_isolated_single_month",
          (t1["account_id"] == "SYN-CHAIN-NOTRIGGER").sum() == 0,
          f"expected 0 triggers, got {(t1['account_id'] == 'SYN-CHAIN-NOTRIGGER').sum()}")

    # ---- Rule 2: POC pass rate below threshold -------------------------
    def _poc_cohort(prefix: str, n_pass: int, n_fail: int, target_outcome: str,
                    origin: pd.Timestamp) -> List[Dict[str, Any]]:
        rows = []
        d = origin
        for i in range(n_pass):
            rows.append({"account_id": f"{prefix}-COHORT-PASS-{i}", "opportunity_id": f"{prefix}-P{i}",
                        "close_date": d + pd.Timedelta(days=i), "poc_outcome": "pass"})
        for i in range(n_fail):
            rows.append({"account_id": f"{prefix}-COHORT-FAIL-{i}", "opportunity_id": f"{prefix}-F{i}",
                        "close_date": d + pd.Timedelta(days=n_pass + i), "poc_outcome": "fail"})
        rows.append({"account_id": f"{prefix}-TARGET", "opportunity_id": f"{prefix}-TARGET-OPP",
                    "close_date": d + pd.Timedelta(days=n_pass + n_fail + 5), "poc_outcome": target_outcome})
        return rows

    # SYN-POC-TRIGGER: 1 pass / 5 fail cohort (pass rate ~16.7%, below the
    # 30% floor), target account's own POC fails -> should fire. Each
    # scenario's dates are placed 200+ days apart (well outside the
    # 90-day trailing window) so the two synthetic cohorts never bleed
    # into each other's trailing-window computation.
    poc_trigger_rows = _poc_cohort("SYN-POC-TRIGGER", n_pass=1, n_fail=5, target_outcome="fail",
                                   origin=pd.Timestamp("2025-01-01"))
    # SYN-POC-NOTRIGGER: 4 pass / 2 fail cohort (pass rate ~66.7%, well
    # above the floor), target account's own POC also fails -> should NOT
    # fire, since the systemic cohort condition isn't met.
    poc_notrigger_rows = _poc_cohort("SYN-POC-NOTRIGGER", n_pass=4, n_fail=2, target_outcome="fail",
                                     origin=pd.Timestamp("2025-08-01"))

    poc_df = pd.DataFrame(poc_trigger_rows + poc_notrigger_rows)
    poc_df["close_date"] = pd.to_datetime(poc_df["close_date"])
    t2 = compute_poc_pass_rate_triggers(poc_df, as_of)

    check("poc_pass_rate_fires_when_own_poc_fails_during_a_low_cohort_rate",
          (t2["account_id"] == "SYN-POC-TRIGGER-TARGET").sum() == 1,
          f"expected exactly 1 trigger for SYN-POC-TRIGGER-TARGET, "
          f"got {(t2['account_id'] == 'SYN-POC-TRIGGER-TARGET').sum()}")
    check("poc_pass_rate_does_not_fire_when_cohort_rate_is_healthy",
          (t2["account_id"] == "SYN-POC-NOTRIGGER-TARGET").sum() == 0,
          f"expected 0 triggers for SYN-POC-NOTRIGGER-TARGET despite its own POC failing, "
          f"got {(t2['account_id'] == 'SYN-POC-NOTRIGGER-TARGET').sum()}")

    # ---- Rule 3: post-close committed-Action utilization ---------------
    opps_rows = [
        {"account_id": "SYN-UTIL-TRIGGER", "close_date": pd.Timestamp("2025-01-15"), "segment": "Commercial"},
        {"account_id": "SYN-UTIL-NOTRIGGER", "close_date": pd.Timestamp("2025-01-15"), "segment": "Commercial"},
        # SMB new business is out of scope for this rule (no commitment
        # concept -- metered, no contract) and must never fire regardless
        # of any utilization_rate a caller might (incorrectly) supply.
        {"account_id": "SYN-UTIL-SMB-OUT-OF-SCOPE", "close_date": pd.Timestamp("2025-01-15"), "segment": "SMB"},
    ]
    util_rows = [
        {"account_id": "SYN-UTIL-TRIGGER", "month": pd.Timestamp("2025-02-01"), "utilization_rate": 0.12},
        {"account_id": "SYN-UTIL-NOTRIGGER", "month": pd.Timestamp("2025-02-01"), "utilization_rate": 0.55},
        {"account_id": "SYN-UTIL-SMB-OUT-OF-SCOPE", "month": pd.Timestamp("2025-02-01"), "utilization_rate": 0.05},
    ]
    opps_df = pd.DataFrame(opps_rows)
    util_df = pd.DataFrame(util_rows)
    t3 = compute_post_close_utilization_triggers(opps_df, util_df, as_of)

    check("post_close_utilization_fires_below_threshold",
          (t3["account_id"] == "SYN-UTIL-TRIGGER").sum() == 1,
          f"expected exactly 1 trigger for SYN-UTIL-TRIGGER, "
          f"got {(t3['account_id'] == 'SYN-UTIL-TRIGGER').sum()}")
    check("post_close_utilization_does_not_fire_above_threshold",
          (t3["account_id"] == "SYN-UTIL-NOTRIGGER").sum() == 0,
          f"expected 0 triggers for SYN-UTIL-NOTRIGGER, "
          f"got {(t3['account_id'] == 'SYN-UTIL-NOTRIGGER').sum()}")
    check("post_close_utilization_excludes_smb_even_when_below_threshold",
          (t3["account_id"] == "SYN-UTIL-SMB-OUT-OF-SCOPE").sum() == 0,
          "SMB has no committed-Action concept (metered, no contract) and must never fire "
          "this rule regardless of any utilization_rate value present")

    return checks + run_outcome_owner_sla_scenarios()


def run_outcome_owner_sla_scenarios() -> List[Dict[str, Any]]:
    """Known-answer scenarios for outcome resolution, owner resolution,
    SLA / escalation and the log's manual-outcome protection, run through
    the same pure functions real-data enrichment uses. The log scenarios
    write to a throwaway CSV, never to data/playbook_triggers.csv."""
    import tempfile

    checks: List[Dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    def monthly(start: str, values: List[Optional[float]]) -> pd.Series:
        idx = pd.date_range(start, periods=len(values), freq="MS")
        return pd.Series(values, index=idx, dtype=float)

    c1 = OUTCOME_CRITERIA["ingestion_without_completion"]
    c3 = OUTCOME_CRITERIA["post_close_underutilization"]
    c2 = OUTCOME_CRITERIA["poc_pass_rate_below_threshold"]
    late = date(2026, 12, 31)

    # ---- Outcome resolution: sustained-recovery rules ------------------
    # trigger 2025-01-01; evidence months 2025-02..2025-07
    rec = monthly("2025-01-01", [0.5, 0.55, 0.6, 0.9, 0.92, 0.95, 0.95])
    r = resolve_sustained_recovery_outcome(rec, "2025-01-01", c1, late)
    check("outcome_resolved_on_sustained_recovery_within_window",
          r["outcome"] == "resolved" and r["outcome_date"] == "2025-05-01"
          and abs(r["outcome_metric_value"] - 0.92) < 1e-9, str(r))

    flat = monthly("2025-01-01", [0.5, 0.55, 0.6, 0.6, 0.65, 0.6, 0.62])
    r = resolve_sustained_recovery_outcome(flat, "2025-01-01", c1, late)
    check("outcome_unresolved_when_no_recovery_in_window",
          r["outcome"] == "unresolved" and r["outcome_reason"] == "no_sustained_recovery_in_window", str(r))

    dip = monthly("2025-01-01", [0.5, 0.55, 0.9, 0.5, 0.9, 0.5, 0.9])
    r = resolve_sustained_recovery_outcome(dip, "2025-01-01", c1, late)
    check("outcome_requires_consecutive_months_not_scattered_good_months",
          r["outcome"] == "unresolved", str(r))

    gap = monthly("2025-01-01", [0.5, 0.55, 0.9, None, 0.9, None, None])
    r = resolve_sustained_recovery_outcome(gap.dropna(), "2025-01-01", c1, late)
    check("outcome_missing_month_between_good_months_breaks_the_run",
          r["outcome"] == "unresolved", str(r))

    r = resolve_sustained_recovery_outcome(monthly("2025-01-01", [0.5, 0.55]), "2025-01-01", c1, late,
                                           churn_date=pd.Timestamp("2025-04-10"))
    check("outcome_unresolved_churned_before_recovery",
          r["outcome"] == "unresolved" and r["outcome_reason"] == "churned_before_recovery"
          and r["outcome_date"] == "2025-04-10", str(r))

    r = resolve_sustained_recovery_outcome(pd.Series(dtype=float), "2025-01-01", c1, late)
    check("outcome_not_evaluable_with_no_observations",
          r["outcome"] == "not_evaluable", str(r))

    # window ends 2025-07-01; as_of 2025-06-30 -> pending even though the
    # recovery is already visible in the data (never resolved on a partial
    # window), and evidence dated after as_of is not read.
    r = resolve_sustained_recovery_outcome(rec, "2025-01-01", c1, date(2025, 6, 30))
    check("outcome_pending_until_window_elapsed_even_if_recovery_already_visible",
          r["outcome"] == "pending" and r["outcome_metric_value"] is None and r["outcome_date"] is None, str(r))
    r = resolve_sustained_recovery_outcome(rec, "2025-01-01", c1, date(2025, 7, 1))
    check("outcome_decided_on_the_day_the_window_closes",
          r["outcome"] == "resolved", str(r))

    ramp = monthly("2025-01-01", [0.2, 0.35, 0.6, 0.9])
    r = resolve_sustained_recovery_outcome(ramp, "2025-01-01", c3, late)
    check("post_close_outcome_resolved_when_utilization_ramps_to_floor",
          r["outcome"] == "resolved" and r["outcome_date"] == "2025-04-01", str(r))
    r = resolve_sustained_recovery_outcome(monthly("2025-01-01", [0.2, 0.25, 0.3, 0.35]), "2025-01-01", c3, late)
    check("post_close_outcome_unresolved_when_utilization_stays_low",
          r["outcome"] == "unresolved", str(r))

    # ---- Outcome resolution: forward cohort rule -----------------------
    def poc_frame(outcomes: List[str], start: str = "2025-03-01") -> pd.DataFrame:
        return pd.DataFrame({
            "close_date": [pd.Timestamp(start) + pd.Timedelta(days=5 * i) for i in range(len(outcomes))],
            "poc_outcome": outcomes})
    trig = pd.Timestamp("2025-02-15")
    r = resolve_forward_pass_rate_outcome(poc_frame(["pass", "pass", "fail", "fail", "pass", "fail"]),
                                          trig, c2, date(2026, 12, 31))
    check("poc_outcome_resolved_when_forward_pass_rate_recovers",
          r["outcome"] == "resolved" and abs(r["outcome_metric_value"] - 0.5) < 1e-9, str(r))
    r = resolve_forward_pass_rate_outcome(poc_frame(["fail"] * 5 + ["pass"]), trig, c2, date(2026, 12, 31))
    check("poc_outcome_unresolved_when_forward_pass_rate_stays_low",
          r["outcome"] == "unresolved", str(r))
    r = resolve_forward_pass_rate_outcome(poc_frame(["pass", "fail"]), trig, c2, date(2026, 12, 31))
    check("poc_outcome_not_evaluable_below_min_forward_cohort",
          r["outcome"] == "not_evaluable", str(r))
    r = resolve_forward_pass_rate_outcome(poc_frame(["pass"] * 6), trig, c2, date(2025, 4, 1))
    check("poc_outcome_pending_until_90_day_window_elapsed",
          r["outcome"] == "pending", str(r))
    r = resolve_forward_pass_rate_outcome(
        pd.DataFrame({"close_date": [trig] * 3 + [trig + pd.Timedelta(days=91)] * 3,
                      "poc_outcome": ["pass"] * 6}), trig, c2, date(2026, 12, 31))
    check("poc_outcome_forward_window_excludes_trigger_day_and_beyond_window",
          r["outcome"] == "not_evaluable", str(r))

    # ---- Owner resolution ----------------------------------------------
    reps = pd.DataFrame([
        {"rep_id": "R-AM1", "rep_type": "AM-Enterprise", "period_start_date": pd.Timestamp("2020-01-01"),
         "period_end_date": pd.NaT, "rep_status": "active"},
        {"rep_id": "R-AM2", "rep_type": "AM-Commercial", "period_start_date": pd.Timestamp("2020-01-01"),
         "period_end_date": pd.Timestamp("2025-01-31"), "rep_status": "active"},
        {"rep_id": "R-AM2", "rep_type": "AM-Commercial", "period_start_date": pd.Timestamp("2025-02-01"),
         "period_end_date": pd.NaT, "rep_status": "departed"},
        {"rep_id": "R-AE1", "rep_type": "AE", "period_start_date": pd.Timestamp("2020-01-01"),
         "period_end_date": pd.NaT, "rep_status": "active"},
    ])
    am = pd.DataFrame([
        {"account_id": "A-OWNED", "rep_id": "R-AM1", "activity_date": pd.Timestamp("2025-01-10")},
        {"account_id": "A-OWNED", "rep_id": "R-AM1", "activity_date": pd.Timestamp("2025-03-20")},
        {"account_id": "A-LATE-AM", "rep_id": "R-AM1", "activity_date": pd.Timestamp("2025-06-01")},
        {"account_id": "A-DEPARTED", "rep_id": "R-AM2", "activity_date": pd.Timestamp("2024-12-01")},
        {"account_id": "A-REASSIGNED", "rep_id": "R-AM2", "activity_date": pd.Timestamp("2024-12-01")},
        {"account_id": "A-REASSIGNED", "rep_id": "R-AM1", "activity_date": pd.Timestamp("2025-03-01")},
    ])
    seg = pd.DataFrame([
        {"account_id": "A-SMB", "segment": "SMB", "effective_date": pd.Timestamp("2024-01-01")},
        {"account_id": "A-LATE-AM", "segment": "Commercial", "effective_date": pd.Timestamp("2024-01-01")},
    ])
    poc_owners = pd.DataFrame([
        {"account_id": "A-POC", "close_date": pd.Timestamp("2025-04-10"), "rep_id": "R-AE1"},
        {"account_id": "A-POC-NOREP", "close_date": pd.Timestamp("2025-04-10"), "rep_id": None},
    ])
    ctx = OwnerContext(am, reps, seg, poc_owners)
    rid1, rid3, rid2 = ("ingestion_without_completion", "post_close_underutilization",
                        "poc_pass_rate_below_threshold")

    o = resolve_owner(rid1, "A-OWNED", "2025-03-01", ctx)   # clock 2025-04-01: sees the 03-20 activity
    check("owner_am_of_record_resolved_from_activity_as_of_clock_start",
          o["owner_rep_id"] == "R-AM1" and o["owner_role"] == "AM-Enterprise"
          and o["owner_unresolved_reason"] is None, str(o))
    o = resolve_owner(rid1, "A-OWNED", "2025-01-01", ctx)   # clock 2025-02-01: only the 01-10 activity
    check("owner_uses_only_activity_dated_on_or_before_clock_start",
          o["owner_rep_id"] == "R-AM1", str(o))
    o = resolve_owner(rid1, "A-LATE-AM", "2025-03-01", ctx)  # first AM activity is after the clock
    check("owner_unresolved_when_no_am_activity_yet_as_of_trigger_non_smb",
          o["owner_rep_id"] is None and o["owner_unresolved_reason"] == "no_am_activity_as_of_trigger", str(o))
    o = resolve_owner(rid1, "A-SMB", "2025-03-01", ctx)
    check("owner_unresolved_smb_has_no_human_owner",
          o["owner_rep_id"] is None and o["owner_role"] is None
          and o["owner_unresolved_reason"] == "smb_no_touch_no_human_owner", str(o))
    o = resolve_owner(rid3, "A-DEPARTED", "2025-03-01", ctx)
    check("owner_unresolved_when_am_of_record_departed",
          o["owner_rep_id"] is None and o["owner_unresolved_reason"] == "owner_departed_as_of_trigger", str(o))
    o = resolve_owner(rid3, "A-REASSIGNED", "2025-03-01", ctx)
    check("owner_follows_the_most_recent_am_when_an_account_is_reassigned",
          o["owner_rep_id"] == "R-AM1", str(o))
    o = resolve_owner(rid2, "A-POC", "2025-04-10", ctx)
    check("owner_poc_rule_is_the_deal_owner_ae",
          o["owner_rep_id"] == "R-AE1" and o["owner_role"] == "AE", str(o))
    o = resolve_owner(rid2, "A-POC-NOREP", "2025-04-10", ctx)
    check("owner_poc_rule_unresolved_without_a_rep_on_the_opportunity",
          o["owner_rep_id"] is None and o["owner_unresolved_reason"] == "no_matching_opportunity", str(o))
    o = resolve_owner(rid2, "A-POC", "2025-05-10", ctx)
    check("owner_poc_rule_unresolved_when_no_failed_poc_on_the_trigger_date",
          o["owner_rep_id"] is None and o["owner_unresolved_reason"] == "no_matching_opportunity", str(o))

    # ---- SLA and escalation --------------------------------------------
    h1, due1 = compute_sla(rid1, "2025-03-01")
    check("sla_month_grain_clock_starts_the_first_of_the_next_month",
          h1 == 120 and due1 == pd.Timestamp("2025-04-06"), f"{h1}, {due1}")
    h2, due2 = compute_sla(rid2, "2025-04-10")
    check("sla_day_grain_clock_starts_on_the_trigger_date",
          h2 == 168 and due2 == pd.Timestamp("2025-04-17"), f"{h2}, {due2}")
    check("sla_open_within_sla_before_due",
          compute_sla_status(due1, None, date(2025, 4, 5)) == "open_within_sla")
    check("sla_breached_after_due_when_no_closure_recorded",
          compute_sla_status(due1, None, date(2025, 4, 6)) == "breached")
    check("sla_closed_within_sla",
          compute_sla_status(due1, "2025-04-04 09:00:00", date(2025, 6, 30)) == "closed_within_sla")
    check("sla_closed_late",
          compute_sla_status(due1, "2025-04-09 09:00:00", date(2025, 6, 30)) == "closed_late")
    check("sla_closure_dated_after_as_of_leaves_the_task_open",
          compute_sla_status(due1, "2025-04-09 09:00:00", date(2025, 4, 8)) == "breached")
    check("escalation_null_with_explicit_reason_when_no_reporting_line",
          resolve_escalation("R-AM1") == (None, ESCALATION_NO_REPORTING_LINE))
    check("escalation_uses_a_supplied_reporting_line_mapping",
          resolve_escalation("R-AM1", {"R-AM1": "R-MGR"}) == ("R-MGR", None))

    # ---- Log: manual-outcome protection, idempotence, task list --------
    global _CSV_PATH
    saved = _CSV_PATH
    with tempfile.TemporaryDirectory() as d:
        _CSV_PATH = os.path.join(d, "playbook_triggers.csv")
        try:
            base = pd.DataFrame([
                {"rule_id": rid3, "account_id": "A-OWNED", "timestamp": pd.Timestamp("2025-03-01"),
                 "resulting_action": RULES[rid3]["resulting_action"], "outcome": None},
                {"rule_id": rid1, "account_id": "A-SMB", "timestamp": pd.Timestamp("2025-03-01"),
                 "resulting_action": RULES[rid1]["resulting_action"], "outcome": None},
            ])
            auto = base.copy()
            for col in _LOG_COLUMNS:
                if col not in auto.columns and col != "closed_at":
                    auto[col] = None
            auto["outcome"] = "unresolved"
            auto["outcome_source"] = AUTOMATED_SOURCE
            auto["outcome_evaluated_as_of"] = "2025-12-31"
            auto["outcome_window_end"] = "2025-09-01"
            auto["outcome_reason"] = "no_sustained_recovery_in_window"
            auto["owner_rep_id"] = ["R-AM1", None]
            auto["owner_unresolved_reason"] = [None, "smb_no_touch_no_human_owner"]
            auto["sla_due_at"] = ["2025-04-04 00:00:00", "2025-04-06 00:00:00"]

            log_triggers(base)
            log_triggers(auto)
            n_after_two = len(read_trigger_log())
            log_triggers(auto)
            check("log_upsert_is_idempotent_no_duplicate_rows",
                  n_after_two == 2 and len(read_trigger_log()) == 2 and read_trigger_log()[0]["outcome"] == "unresolved",
                  f"rows {n_after_two} -> {len(read_trigger_log())}")

            log_triggers(base)
            check("log_relogging_a_five_column_frame_does_not_wipe_a_logged_outcome_or_owner",
                  read_trigger_log()[0]["outcome"] == "unresolved" and read_trigger_log()[0]["owner_rep_id"] == "R-AM1")

            record_outcome(rid3, "A-OWNED", "2025-03-01", outcome="resolved", outcome_date="2025-05-02",
                           outcome_reason="csm_confirmed_onboarded", closed_at="2025-04-02 10:00:00")
            log_triggers(auto)
            row = read_trigger_log()[0]
            check("manual_outcome_is_never_overwritten_by_the_automated_resolver",
                  row["outcome"] == "resolved" and row["outcome_source"] == "manual"
                  and row["outcome_reason"] == "csm_confirmed_onboarded" and row["closed_at"] == "2025-04-02 10:00:00",
                  str(row))

            auto2 = auto.copy()
            auto2["outcome"] = "pending"
            auto2["outcome_evaluated_as_of"] = "2025-06-30"
            log_triggers(auto2)
            check("automated_evaluation_never_replaced_by_an_earlier_evaluation",
                  read_trigger_log()[1]["outcome"] == "unresolved", str(read_trigger_log()[1]))

            try:
                record_outcome(rid3, "A-NOT-LOGGED", "2025-03-01", outcome="resolved", outcome_date="2025-05-01")
                unlogged_rejected = False
            except ValueError:
                unlogged_rejected = True
            try:
                record_outcome(rid3, "A-OWNED", "2025-03-01", outcome="great", outcome_date="2025-05-01")
                bad_vocab_rejected = False
            except ValueError:
                bad_vocab_rejected = True
            try:
                record_outcome(rid3, "A-OWNED", "2025-03-01", outcome="resolved")
                no_date_rejected = False
            except ValueError:
                no_date_rejected = True
            check("record_outcome_rejects_unlogged_trigger_bad_vocabulary_and_missing_date",
                  unlogged_rejected and bad_vocab_rejected and no_date_rejected)

            tasks = open_trigger_tasks(date(2025, 12, 31))
            check("open_tasks_exclude_closed_and_rank_earliest_due_first_keeping_ownerless_tasks",
                  list(tasks["account_id"]) == ["A-SMB"] and bool(tasks.iloc[0]["escalation_required"])
                  and tasks.iloc[0]["owner_unresolved_reason"] == "smb_no_touch_no_human_owner",
                  tasks.to_dict(orient="records").__repr__())
            def known_on(d: date, acct: str) -> Any:
                return with_known_outcomes(base, d).set_index("account_id").loc[acct, "outcome"]

            check("automated_outcome_known_only_from_the_day_its_window_closed",
                  known_on(date(2025, 8, 31), "A-SMB") is None and known_on(date(2025, 9, 1), "A-SMB") == "unresolved",
                  "A-SMB automated row, outcome_window_end 2025-09-01")
            check("manual_outcome_known_only_from_its_outcome_date",
                  known_on(date(2025, 5, 1), "A-OWNED") is None and known_on(date(2025, 5, 2), "A-OWNED") == "resolved",
                  "A-OWNED manual row, outcome_date 2025-05-02")
        finally:
            _CSV_PATH = saved

    return checks


def log_outcome_checkpoint(as_of_date: date) -> None:
    """Persists the per-rule outcome mix and owner-resolved share of the
    operational log as scalars to fact_model_performance_history (one row
    per metric), for as_of_date -- call after backfill_log(as_of_date)."""
    for rule_id, sm in summarize_log().items():
        for outcome in ("resolved", "unresolved", "pending", "not_evaluable"):
            log_performance(_MODEL_NAME, as_of_date, f"outcome_{outcome}_{rule_id}",
                            float(sm["outcomes"].get(outcome, 0)))
        if sm["owner_resolved_share"] is not None:
            log_performance(_MODEL_NAME, as_of_date, f"owner_resolved_share_{rule_id}",
                            float(sm["owner_resolved_share"]))


def run_build_time_validation(as_of_date: date, write: bool = True,
                              log: bool = True) -> Dict[str, Any]:
    """Everything analytics-model-validator needs: the real-data trigger
    run at as_of_date, the synthetic-scenario correctness suite, and
    (optionally) the enriched operational-log write (outcome, owner, SLA,
    escalation as of as_of_date) and the model-performance-log persistence
    of build-time scalars."""
    triggers = run_playbook_triggers(as_of_date)
    scenarios = run_synthetic_scenarios()
    passed = sum(c["passed"] for c in scenarios)

    if write:
        log_triggers(enrich_triggers(triggers, as_of_date))

    if log:
        log_performance(_MODEL_NAME, as_of_date, "triggers_fired_total", float(len(triggers)))
        for rule_id in RULES:
            log_performance(_MODEL_NAME, as_of_date, f"triggers_fired_{rule_id}",
                            float((triggers["rule_id"] == rule_id).sum()))
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_passed", float(passed))
        log_performance(_MODEL_NAME, as_of_date, "synthetic_scenarios_total", float(len(scenarios)))

    return {
        "triggers": triggers,
        "scenarios": scenarios,
        "checks_passed": passed,
        "checks_total": len(scenarios),
    }


if __name__ == "__main__":
    # 2025-11-30, matching analytics/variance_diagnostic.py's and
    # analytics/weekly_readout.py's own canonical build-time checkpoint --
    # 2025-12 carries that engine's documented end-of-window truncation
    # artifact, so 2025-11 is the last representative evaluation period
    # for firing triggers. Outcomes are then resolved for everything
    # logged as of BACKFILL_AS_OF, the latest as_of_date the repo uses, so
    # the most triggers possible have an elapsed observation window.
    AS_OF = date(2025, 11, 30)
    BACKFILL_AS_OF = date(2025, 12, 31)
    out = run_build_time_validation(AS_OF)
    backfill_log(BACKFILL_AS_OF)
    log_outcome_checkpoint(BACKFILL_AS_OF)

    print(f"=== Automated playbook triggers -- as of {AS_OF} ===")
    print(f"Triggers fired total: {len(out['triggers'])}")
    for rule_id in RULES:
        n = int((out["triggers"]["rule_id"] == rule_id).sum())
        print(f"  {rule_id}: {n}")
    print()
    for c in out["scenarios"]:
        print(f"[{'PASS' if c['passed'] else 'FAIL'}] {c['name']}"
              f"{'' if c['passed'] else '  -- ' + c['detail']}")
    print(f"\n{out['checks_passed']}/{out['checks_total']} synthetic scenarios passed")

    print(f"\n=== Outcomes, owners as of {BACKFILL_AS_OF} ===")
    for rule_id, sm in summarize_log().items():
        print(f"{rule_id}: n={sm['n']} outcomes={sm['outcomes']} "
              f"owner_resolved={sm['owner_resolved']} ({sm['owner_resolved_share']:.1%}) "
              f"unresolved_reasons={sm['owner_unresolved_reasons']}")
