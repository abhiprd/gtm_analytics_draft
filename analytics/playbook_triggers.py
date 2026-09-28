"""Automated playbook triggers -- Wave 4 (build spec Section 8, item #10).
Grain: one row per trigger firing (rule_id, account_id, timestamp,
resulting_action, outcome); sources: fact_workflow_chain_events,
fact_opportunities, fact_committed_vs_utilized_monthly (main_marts only).

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
from datetime import date
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "playbook_triggers.csv")
_MODEL_NAME = "automated_playbook_triggers"

# Build spec Section 5 / line 118's exact operational-log grain.
_COLUMNS = ["rule_id", "account_id", "timestamp", "resulting_action", "outcome"]


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
    df = poc_df[poc_df["close_date"] <= pd.Timestamp(as_of_date)].copy()
    df = df.sort_values("close_date").reset_index(drop=True)
    window = pd.Timedelta(days=rule["trailing_window_days"])

    rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        if row["poc_outcome"] != "fail":
            continue
        if pd.isna(row["account_id"]):
            # A real trigger condition (a failed POC), but with no
            # traceable account the operational log's schema can name --
            # excluded from the LOGGED set, not from the cohort-rate
            # denominator computed above this loop.
            continue
        cohort = df[(df["close_date"] < row["close_date"]) &
                    (df["close_date"] >= row["close_date"] - window)]
        if len(cohort) < rule["min_cohort_size"]:
            continue
        cohort_pass_rate = (cohort["poc_outcome"] == "pass").mean()
        if cohort_pass_rate < rule["pass_rate_threshold"]:
            rows.append({
                "rule_id": "poc_pass_rate_below_threshold",
                "account_id": row["account_id"],
                "timestamp": row["close_date"],
                "resulting_action": rule["resulting_action"],
                "outcome": None,
            })
    return pd.DataFrame(rows, columns=_COLUMNS)


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
    merged = merged[merged["month"] <= pd.Timestamp(as_of_date)]

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
    df["month"] = pd.to_datetime(df["month"])
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
    df["close_date"] = pd.to_datetime(df["close_date"])
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
    df["close_date"] = pd.to_datetime(df["close_date"])
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
    df["month"] = pd.to_datetime(df["month"])
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

    outcome is always None for a freshly-evaluated trigger: this artifact
    fires triggers and records what fired, not whether any specific
    firing turned out to have been worth acting on. That judgement needs
    the trigger to have aged (an account's subsequent renewal/churn, a
    subsequent completion-rate recovery) which is exactly what the
    operational log exists to make possible to backtest later, per build
    spec line 118's own stated reason for the log's existence.
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
# Operational log -- append-only, upsert-safe. Exact pattern of
# analytics/model_performance.py's log_performance()/read_performance_
# history(), backed by a version-controlled CSV rather than a write
# straight into the gitignored, rebuilt-from-scratch data/acme_gtm.duckdb.
# =====================================================================

def _ts_key(v: Any) -> str:
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def log_triggers(triggers: pd.DataFrame) -> None:
    """Upserts fired-trigger rows into data/playbook_triggers.csv, keyed
    on (rule_id, account_id, timestamp) -- the operational log's own
    natural grain, one row per trigger firing. Re-running
    run_playbook_triggers() for a period that has already been logged
    replaces those rows rather than duplicating them, mirroring
    analytics/model_performance.py's log_performance() exactly (same
    read-filter-append-rewrite shape, same reason: a caller that forgets
    to dedupe produces a real duplicate-row defect in the operational
    log, not just a cosmetic one)."""
    existing = {
        (r["rule_id"], r["account_id"], r["timestamp"]): r
        for r in read_trigger_log()
    }
    for _, row in triggers.iterrows():
        key = (row["rule_id"], row["account_id"], _ts_key(row["timestamp"]))
        outcome = row["outcome"]
        existing[key] = {
            "rule_id": row["rule_id"],
            "account_id": row["account_id"],
            "timestamp": _ts_key(row["timestamp"]),
            "resulting_action": row["resulting_action"],
            # outcome starts null/pending for a freshly-fired trigger --
            # never fabricated. An existing logged row's own outcome
            # (once backtesting fills it in) is preserved by this same
            # upsert path if a caller re-logs a triggers frame that
            # carries a real outcome value for an already-logged key.
            "outcome": "" if outcome is None or (isinstance(outcome, float) and pd.isna(outcome)) else outcome,
        }

    with open(_CSV_PATH, "w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(_COLUMNS)
        for r in existing.values():
            writer.writerow([r[c] for c in _COLUMNS])


def read_trigger_log() -> List[Dict[str, str]]:
    """Full operational log as a list of dicts. Empty list if the CSV has
    not been written yet (no build-time run has happened)."""
    if not os.path.exists(_CSV_PATH):
        return []
    with open(_CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))


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

    return checks


def run_build_time_validation(as_of_date: date, write: bool = True,
                              log: bool = True) -> Dict[str, Any]:
    """Everything analytics-model-validator needs: the real-data trigger
    run at as_of_date, the synthetic-scenario correctness suite, and
    (optionally) the operational-log write and the model-performance-log
    persistence of build-time scalars."""
    triggers = run_playbook_triggers(as_of_date)
    scenarios = run_synthetic_scenarios()
    passed = sum(c["passed"] for c in scenarios)

    if write:
        log_triggers(triggers)

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
    # artifact, so 2025-11 is the last representative evaluation period.
    AS_OF = date(2025, 11, 30)
    out = run_build_time_validation(AS_OF)

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
