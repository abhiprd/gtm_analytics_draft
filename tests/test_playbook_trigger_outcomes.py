"""Outcome capture, ownership and SLA for automated playbook triggers.

Two layers. The known-answer scenarios in
analytics/playbook_triggers.run_synthetic_scenarios() (resolved /
unresolved / pending / not_evaluable outcomes, owner resolution and its
unresolvable reasons, SLA breach / no breach / closure, manual-outcome
protection, log idempotence) are each run as their own test. The
real-data invariants read the committed operational log
(data/playbook_triggers.csv) and, where they need marts, the dbt-built
data/acme_gtm.duckdb (skipped when absent).

Run: python3 -m pytest tests/test_playbook_trigger_outcomes.py -v
"""
import os
import shutil
from datetime import date

import duckdb
import pandas as pd
import pytest

from analytics import playbook_triggers as pbt

DB_PATH = "data/acme_gtm.duckdb"
BACKFILL_AS_OF = date(2025, 12, 31)
SCENARIOS = pbt.run_synthetic_scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[c["name"] for c in SCENARIOS])
def test_known_answer_scenario(scenario):
    assert scenario["passed"], scenario["detail"]


def test_scenario_suite_covers_every_required_behavior():
    names = " ".join(c["name"] for c in SCENARIOS)
    for needle in ("outcome_resolved", "outcome_unresolved", "outcome_pending", "manual_outcome_is_never",
                   "owner_unresolved", "sla_breached", "sla_open_within_sla", "sla_closed_within_sla",
                   "sla_closed_late", "idempotent"):
        assert needle in names, needle


@pytest.fixture(scope="module")
def log():
    rows = pbt.read_trigger_log()
    if not rows or not rows[0]["sla_due_at"]:
        pytest.skip("operational log has not been backfilled")
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def con():
    if not os.path.exists(DB_PATH):
        pytest.skip("dbt-built database not present; run `cd dbt && dbt build`")
    c = duckdb.connect(DB_PATH, read_only=True)
    yield c
    c.close()


class TestLogInvariants:
    def test_schema_keeps_the_five_build_spec_columns_first(self):
        with open(pbt._CSV_PATH) as f:
            header = f.readline().strip().split(",")
        assert header[:5] == ["rule_id", "account_id", "timestamp", "resulting_action", "outcome"]
        assert header == pbt._LOG_COLUMNS

    def test_no_duplicate_keys(self, log):
        assert not log.duplicated(["rule_id", "account_id", "timestamp"]).any()

    def test_outcome_vocabulary_and_every_row_has_an_outcome(self, log):
        assert set(log["outcome"]) <= set(pbt.OUTCOME_VOCABULARY)

    def test_no_automated_outcome_decided_before_its_window_elapsed(self, log):
        a = log[log["outcome_source"] == pbt.AUTOMATED_SOURCE]
        decided = a[a["outcome"] != "pending"]
        assert (pd.to_datetime(decided["outcome_window_end"]) <= pd.to_datetime(decided["outcome_evaluated_as_of"])).all()
        pending = a[a["outcome"] == "pending"]
        assert (pd.to_datetime(pending["outcome_window_end"]) > pd.to_datetime(pending["outcome_evaluated_as_of"])).all()
        assert (pending["outcome_date"] == "").all() and (pending["outcome_metric_value"] == "").all()

    def test_window_end_matches_the_configured_window(self, log):
        for rule_id, crit in pbt.OUTCOME_CRITERIA.items():
            g = log[log["rule_id"] == rule_id]
            ts = pd.to_datetime(g["timestamp"])
            expected = (ts + pd.DateOffset(months=crit["window_months"]) if "window_months" in crit
                        else ts + pd.Timedelta(days=crit["window_days"]))
            assert (pd.to_datetime(g["outcome_window_end"]) == expected).all(), rule_id

    def test_owner_fields_are_consistent_and_never_fabricated(self, log):
        owned = log["owner_rep_id"] != ""
        assert (log.loc[owned, "owner_role"] != "").all()
        assert (log.loc[owned, "owner_unresolved_reason"] == "").all()
        assert (log.loc[~owned, "owner_role"] == "").all()
        assert (log.loc[~owned, "owner_unresolved_reason"] != "").all()

    def test_sla_due_follows_the_configured_clock(self, log):
        for rule_id in pbt.RULES:
            for r in log[log["rule_id"] == rule_id].head(50).itertuples():
                hours, due = pbt.compute_sla(rule_id, r.timestamp)
                assert int(r.sla_hours) == hours and pd.Timestamp(r.sla_due_at) == due

    def test_escalation_is_null_with_the_explicit_reason(self, log):
        assert (log["escalation_to"] == "").all()
        assert (log["escalation_reason"] == pbt.ESCALATION_NO_REPORTING_LINE).all()

    def test_owner_foreign_key_integrity(self, log, con):
        reps = set(con.execute("select distinct rep_id from main_marts.dim_reps").df()["rep_id"])
        assert set(log.loc[log["owner_rep_id"] != "", "owner_rep_id"]) <= reps
        accts = set(con.execute("select account_id from main_marts.dim_accounts").df()["account_id"])
        assert set(log["account_id"]) <= accts

    def test_owner_role_matches_the_rules_owner_basis(self, log):
        a = log[(log["owner_rep_id"] != "") & (log["rule_id"] != "poc_pass_rate_below_threshold")]
        assert set(a["owner_role"]) <= {"AM-Commercial", "AM-Enterprise"}
        b = log[(log["owner_rep_id"] != "") & (log["rule_id"] == "poc_pass_rate_below_threshold")]
        assert set(b["owner_role"]) <= {"AE"}

    def test_idempotent_rerun_leaves_the_log_byte_identical(self, tmp_path):
        if not os.path.exists(DB_PATH):
            pytest.skip("dbt-built database not present")
        copy = tmp_path / "playbook_triggers.csv"
        shutil.copy(pbt._CSV_PATH, copy)
        saved = pbt._CSV_PATH
        pbt._CSV_PATH = str(copy)
        try:
            before = copy.read_bytes()
            pbt.backfill_log(BACKFILL_AS_OF)
            assert copy.read_bytes() == before
        finally:
            pbt._CSV_PATH = saved

    def test_rerun_does_not_touch_a_manual_outcome_on_real_rows(self, tmp_path):
        if not os.path.exists(DB_PATH):
            pytest.skip("dbt-built database not present")
        copy = tmp_path / "playbook_triggers.csv"
        shutil.copy(pbt._CSV_PATH, copy)
        saved = pbt._CSV_PATH
        pbt._CSV_PATH = str(copy)
        try:
            first = pbt.read_trigger_log()[0]
            pbt.record_outcome(first["rule_id"], first["account_id"], first["timestamp"], outcome="resolved",
                               outcome_date="2025-01-01", outcome_reason="recorded_by_csm")
            pbt.backfill_log(BACKFILL_AS_OF)
            row = pbt.read_trigger_log()[0]
            assert row["outcome"] == "resolved" and row["outcome_source"] == "manual"
            assert row["outcome_reason"] == "recorded_by_csm"
        finally:
            pbt._CSV_PATH = saved

    def test_logged_trigger_set_matches_a_fresh_run(self, log):
        fresh = pbt.run_playbook_triggers(date(2025, 11, 30))
        assert len(fresh) == len(log)
        fresh_keys = set(zip(fresh["rule_id"], fresh["account_id"], fresh["timestamp"].dt.date.astype(str)))
        assert fresh_keys == set(zip(log["rule_id"], log["account_id"], log["timestamp"]))


class TestDbtFact:
    def test_fact_sla_status_equals_the_python_rule(self, log, con):
        f = con.execute("select rule_id, account_id, cast(timestamp as varchar) ts, sla_status "
                        "from main_marts.fact_playbook_triggers").df()
        if f.empty or f["sla_status"].isna().all():
            pytest.skip("fact_playbook_triggers not rebuilt from the enriched log")
        got = dict(zip(zip(f["rule_id"], f["account_id"], f["ts"]), f["sla_status"]))
        for r in log.itertuples():
            assert got[(r.rule_id, r.account_id, r.timestamp)] == pbt.compute_sla_status(
                r.sla_due_at, r.closed_at or None, BACKFILL_AS_OF)


class TestOpenTaskList:
    def test_ranked_by_sla_urgency_and_only_open_unsettled_tasks(self, log):
        t = pbt.open_trigger_tasks(BACKFILL_AS_OF)
        assert t["sla_due_at"].is_monotonic_increasing
        assert t["sla_status"].isin(["open_within_sla", "breached"]).all()
        assert (t["escalation_required"] == (t["sla_status"] == "breached")).all()
        assert (t["timestamp"] <= BACKFILL_AS_OF.isoformat()).all()

    def test_point_in_time_no_task_before_its_clock_starts(self, log):
        t = pbt.open_trigger_tasks(date(2024, 1, 15))
        assert (pd.to_datetime(t["timestamp"]) < pd.Timestamp("2024-01-15")).all()

    def test_outcomes_not_visible_before_their_window_closes(self, log):
        trig = pbt.run_playbook_triggers(date(2025, 6, 30))
        shown = pbt.with_known_outcomes(trig, date(2025, 6, 30))
        ends = {(r["rule_id"], r["account_id"], r["timestamp"]): r["outcome_window_end"] for r in pbt.read_trigger_log()}
        for r in shown.dropna(subset=["outcome"]).itertuples():
            assert pd.Timestamp(ends[(r.rule_id, r.account_id, r.timestamp.date().isoformat())]) <= pd.Timestamp("2025-06-30")
