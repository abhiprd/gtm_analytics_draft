"""Validation checks for batch 3 (support_tickets, am_activity,
marketing_spend_by_channel_month), scoped per the validate-gtm-data skill
and the QA plan's test cases (docs/acme-corp-phase1-data-qa-plan.md).

Rep-cost/S&M-cost checks (Magic Number, AM Efficiency) are out of scope
here -- no rep-cost source exists yet (see run_batch3.py's module
docstring and config.py's TARGET_CAC_BY_CHANNEL comment).

Run: python3 -m pytest tests/test_phase1_batch3.py -v
"""
import pandas as pd
import pytest

from generators import config

DATA_DIR = "data/raw"


@pytest.fixture(scope="module")
def accounts():
    return pd.read_csv(f"{DATA_DIR}/accounts.csv", parse_dates=["signup_date"])


@pytest.fixture(scope="module")
def users():
    return pd.read_csv(f"{DATA_DIR}/users.csv", parse_dates=["hire_date"])


@pytest.fixture(scope="module")
def rep_status_history():
    return pd.read_csv(f"{DATA_DIR}/rep_status_history.csv", parse_dates=["effective_date"])


@pytest.fixture(scope="module")
def subscriptions():
    df = pd.read_csv(f"{DATA_DIR}/subscriptions.csv", parse_dates=["start_date", "end_date"])
    return df


@pytest.fixture(scope="module")
def usage_monthly():
    return pd.read_csv(f"{DATA_DIR}/usage_monthly.csv", parse_dates=["month"])


@pytest.fixture(scope="module")
def tickets():
    return pd.read_csv(f"{DATA_DIR}/support_tickets.csv", parse_dates=["created_date", "resolved_date"])


@pytest.fixture(scope="module")
def am_activity():
    return pd.read_csv(f"{DATA_DIR}/am_activity.csv", parse_dates=["activity_date"])


@pytest.fixture(scope="module")
def marketing_spend():
    return pd.read_csv(f"{DATA_DIR}/marketing_spend_by_channel_month.csv", parse_dates=["month"])


@pytest.fixture(scope="module")
def churn_date_by_account(subscriptions):
    last_rows = subscriptions.sort_values("start_date").groupby("account_id").last()
    churned = last_rows[last_rows["status"] == "churned"]
    return dict(zip(churned.index, churned["end_date"]))


# =====================================================================
# A. Referential / structural integrity
# =====================================================================

class TestReferentialIntegrity:
    def test_ticket_account_id_resolves(self, tickets, accounts):
        assert tickets["account_id"].isin(accounts["account_id"]).all()

    def test_ticket_severity_is_valid(self, tickets):
        assert set(tickets["severity"].unique()) <= set(config.SEVERITY_MIX_BASELINE.keys())

    def test_resolved_tickets_have_resolution_time_open_tickets_dont(self, tickets):
        resolved = tickets[tickets["resolved_date"].notna()]
        open_ = tickets[tickets["resolved_date"].isna()]
        assert resolved["resolution_time_hours"].notna().all()
        assert open_["resolution_time_hours"].isna().all()

    def test_csat_only_on_resolved_tickets(self, tickets):
        with_csat = tickets[tickets["csat_score"].notna()]
        assert with_csat["resolved_date"].notna().all()
        assert with_csat["csat_score"].between(1, 5).all()

    def test_am_activity_account_id_resolves(self, am_activity, accounts):
        assert am_activity["account_id"].isin(accounts["account_id"]).all()

    def test_am_activity_only_commercial_and_enterprise(self, am_activity):
        assert set(am_activity["segment"].unique()) <= {"Commercial", "Enterprise"}

    def test_am_activity_type_matches_segment(self, am_activity):
        assert (am_activity.loc[am_activity["segment"] == "Enterprise", "activity_type"] == "QBR").all()
        assert (am_activity.loc[am_activity["segment"] == "Commercial", "activity_type"] == "check_in").all()

    def test_am_rep_id_resolves_to_users(self, am_activity, users):
        assert am_activity["am_rep_id"].isin(users["rep_id"]).all()

    def test_no_touchpoint_assigned_to_an_already_departed_am(self, am_activity, rep_status_history):
        """No orphaned ownership (build spec Section 5 / QA plan Test A,
        applied to AM ownership the same way opportunities.py already
        enforces it for deal ownership): no touchpoint's activity_date
        falls after its am_rep_id's own departure date."""
        departed = dict(zip(
            rep_status_history.loc[rep_status_history["status"] == "departed", "rep_id"],
            rep_status_history.loc[rep_status_history["status"] == "departed", "effective_date"],
        ))
        depart_date = am_activity["am_rep_id"].map(departed)
        violations = am_activity[depart_date.notna() & (am_activity["activity_date"] > depart_date)]
        assert violations.empty, f"{len(violations)} touchpoints assigned to an already-departed AM"

    def test_am_rep_is_correct_rep_type_for_segment(self, am_activity, users):
        merged = am_activity.merge(users[["rep_id", "rep_type"]], left_on="am_rep_id", right_on="rep_id")
        expected = merged["segment"].map({"Commercial": "AM-Commercial", "Enterprise": "AM-Enterprise"})
        assert (merged["rep_type"] == expected).all()

    def test_am_activity_no_touchpoint_before_signup(self, am_activity, accounts):
        merged = am_activity.merge(accounts[["account_id", "signup_date"]], on="account_id")
        assert (merged["activity_date"] >= merged["signup_date"]).all()

    def test_sentiment_score_in_range(self, am_activity):
        assert am_activity["sentiment_score"].between(1, 5).all()

    def test_no_negative_spend(self, marketing_spend):
        assert (marketing_spend["spend"] >= 0).all()

    def test_marketing_spend_channel_is_valid(self, marketing_spend):
        assert set(marketing_spend["channel"].unique()) == set(config.TARGET_CAC_BY_CHANNEL.keys())

    def test_marketing_spend_covers_every_channel_month(self, marketing_spend):
        n_months = 36
        n_channels = len(config.TARGET_CAC_BY_CHANNEL)
        assert len(marketing_spend) == n_months * n_channels


# =====================================================================
# B. Distributional realism
# =====================================================================

class TestDistributionalRealism:
    def test_severity_mix_near_baseline(self, tickets):
        mix = tickets["severity"].value_counts(normalize=True)
        for sev, target in config.SEVERITY_MIX_BASELINE.items():
            assert abs(mix.get(sev, 0) - target) < 0.12, f"{sev}: {mix.get(sev, 0):.2f} vs target {target:.2f}"

    def test_realized_cac_near_target_for_high_volume_channels(self, marketing_spend):
        """self_serve and inbound_marketing have enough monthly volume for
        realized CAC to track the target closely; outbound_sdr's low volume
        (see config.py's grounding comment) makes a tight check meaningless."""
        for channel in ["self_serve", "inbound_marketing"]:
            ch = marketing_spend[marketing_spend["channel"] == channel]
            realized = ch["spend"].sum() / max(ch["new_accounts"].sum(), 1)
            target = config.TARGET_CAC_BY_CHANNEL[channel]
            assert 0.5 * target <= realized <= 2.5 * target, f"{channel}: realized ${realized:.0f} vs target ${target}"

    def test_channels_show_genuinely_different_cac(self, marketing_spend):
        """QA plan Test C: 'channels show genuinely different CAC/conversion
        profiles from each other -- organic, paid, and community should not
        look statistically identical.' Applied here to this batch's coarser
        3-value channel taxonomy (see marketing.py's module docstring)."""
        by_channel = marketing_spend.groupby("channel").apply(
            lambda g: g["spend"].sum() / max(g["new_accounts"].sum(), 1), include_groups=False
        )
        assert by_channel.max() / by_channel.min() > 3, f"channel CAC values look too similar: {by_channel.to_dict()}"

    def test_am_touch_cadence_within_plausible_range(self, am_activity, accounts):
        covered = accounts[accounts["segment"].isin(["Commercial", "Enterprise"])]
        touches_per_account = am_activity.groupby("account_id").size()
        # loose sanity bound, not a tight benchmark-table check (no cited
        # source for AM cadence) -- catches a badly broken rate, not fine-tunes it
        assert touches_per_account.median() >= 1
        assert touches_per_account.reindex(covered["account_id"]).fillna(0).mean() > 0


# =====================================================================
# C. Correlational validity
# =====================================================================

class TestCorrelationalValidity:
    def test_prechurn_tickets_more_severe_than_baseline(self, tickets, churn_date_by_account):
        def bucket(row):
            cd = churn_date_by_account.get(row["account_id"])
            if cd is None:
                return "baseline"
            days_to_churn = (cd - row["created_date"]).days
            return "prechurn" if 0 <= days_to_churn <= 120 else "baseline"

        tickets = tickets.assign(bucket=tickets.apply(bucket, axis=1))
        high_sev = tickets["severity"].isin(["high", "critical"])
        rate_by_bucket = tickets.assign(high_sev=high_sev).groupby("bucket")["high_sev"].mean()
        assert rate_by_bucket["prechurn"] > rate_by_bucket["baseline"] + 0.05, (
            f"prechurn high/critical rate {rate_by_bucket['prechurn']:.2f} not clearly above "
            f"baseline {rate_by_bucket['baseline']:.2f}"
        )

    def test_prechurn_am_sentiment_lower_than_baseline(self, am_activity, churn_date_by_account):
        def bucket(row):
            cd = churn_date_by_account.get(row["account_id"])
            if cd is None:
                return "baseline"
            days_to_churn = (cd - row["activity_date"]).days
            return "prechurn" if 0 <= days_to_churn <= 120 else "baseline"

        am_activity = am_activity.assign(bucket=am_activity.apply(bucket, axis=1))
        mean_by_bucket = am_activity.groupby("bucket")["sentiment_score"].mean()
        assert mean_by_bucket["prechurn"] < mean_by_bucket["baseline"] - 0.5, (
            f"prechurn sentiment {mean_by_bucket['prechurn']:.2f} not clearly below "
            f"baseline {mean_by_bucket['baseline']:.2f}"
        )

    def test_injected_cac_creep_incident_detectable(self, marketing_spend):
        channel = config.CAC_CREEP_INCIDENT_CHANNEL
        win_start, win_end = config.CAC_CREEP_INCIDENT_WINDOW
        ch = marketing_spend[marketing_spend["channel"] == channel]
        in_window = ch[(ch["month"] >= pd.Timestamp(win_start)) & (ch["month"] <= pd.Timestamp(win_end))]
        rest = ch[~ch.index.isin(in_window.index)]

        cac_in = in_window["spend"].sum() / max(in_window["new_accounts"].sum(), 1)
        cac_rest = rest["spend"].sum() / max(rest["new_accounts"].sum(), 1)
        assert cac_in > cac_rest * 1.3, f"incident-window CAC ${cac_in:.0f} not clearly above baseline ${cac_rest:.0f}"


# =====================================================================
# D. Volume / sufficiency for modeling
# =====================================================================

class TestVolumeSufficiency:
    def test_enough_tickets_for_modeling(self, tickets):
        assert len(tickets) >= 1000

    def test_enough_am_touchpoints_for_modeling(self, am_activity):
        assert len(am_activity) >= 1000

    def test_every_am_rep_gets_at_least_one_touchpoint(self, am_activity, users):
        am_reps = users[users["rep_type"].isin(["AM-Commercial", "AM-Enterprise"])]["rep_id"]
        touched = set(am_activity["am_rep_id"].unique())
        untouched = set(am_reps) - touched
        # allow a small fraction of never-touched AMs (e.g. hired very late,
        # or only ever assigned to short-tenure accounts) -- not a hard zero
        assert len(untouched) / max(len(am_reps), 1) < 0.2


# =====================================================================
# E. Edge-case existence
# =====================================================================

class TestEdgeCaseExistence:
    def test_some_tickets_remain_unresolved_right_censored(self, tickets):
        assert (tickets["resolved_date"].isna()).sum() > 0

    def test_csat_response_rate_is_partial_not_universal_not_zero(self, tickets):
        resolved = tickets[tickets["resolved_date"].notna()]
        rate = resolved["csat_score"].notna().mean()
        assert 0.2 < rate < 0.8

    def test_at_least_one_am_reassignment_on_departure(self, am_activity, rep_status_history):
        """A weak existence check: some account's set of am_rep_id values
        over its tenure includes a departed rep followed by a different one
        -- confirms _assign_primary_am's reassignment path actually fired
        at least once, not just exists as dead code."""
        departed_reps = set(rep_status_history.loc[rep_status_history["status"] == "departed", "rep_id"])
        reassigned_accounts = 0
        for aid, grp in am_activity.groupby("account_id"):
            reps_used = grp.sort_values("activity_date")["am_rep_id"].unique()
            if len(reps_used) > 1 and reps_used[0] in departed_reps:
                reassigned_accounts += 1
        assert reassigned_accounts >= 1
