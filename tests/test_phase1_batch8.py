"""Validation checks for batch 8 (fact_sales_activities), scoped per the
validate-gtm-data skill and the QA plan's test cases
(docs/acme-corp-phase1-data-qa-plan.md).

This batch is the sales-engagement layer underneath opportunities.csv: every
individual rep-opportunity touch (call, email, meeting, demo) for
Commercial/Enterprise new-business deals. It reads opportunities.csv,
users.csv and rep_status_history.csv and writes none of them back, so every
correlational test here is checking whether the *new* activity data lines up
with outcomes that were already fixed by an earlier batch -- not whether
this batch quietly changed them.

Two things shape this batch's test profile specifically:

  * `fact_sales_activities` is the table this portfolio's two blocked Wave 4
    artifacts ("Deal-level diagnostics", "Rep productivity & coaching
    diagnostics") read directly, so the correlational tests below are not
    generic sanity checks -- they are the literal question those artifacts
    exist to answer ("are meetings correlated with wins?"), asserted here so
    a broken causal wiring is caught before either artifact gets built on
    top of it.
  * Two of the QA plan's required 3-5 injected incidents (grounding
    requirement 3) were structurally impossible before this batch existed
    and are implemented here for the first time: a meetings-rise-without-
    SQO-rise decoupling period, and an underperforming rep cohort.

Run: python3 -m pytest tests/test_phase1_batch8.py -v
"""
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from generators import config

DATA_DIR = "data/raw"

ACTIVITY_TYPES = set(config.SALES_ACTIVITY_TYPES)
ALL_OUTCOMES = {o for outcomes in config.SALES_ACTIVITY_OUTCOMES.values() for o in outcomes}


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture(scope="module")
def activities():
    return pd.read_csv(f"{DATA_DIR}/fact_sales_activities.csv", parse_dates=["activity_timestamp"])


@pytest.fixture(scope="module")
def opportunities():
    return pd.read_csv(f"{DATA_DIR}/opportunities.csv", parse_dates=["created_date", "close_date"])


@pytest.fixture(scope="module")
def users():
    return pd.read_csv(f"{DATA_DIR}/users.csv", parse_dates=["hire_date"])


@pytest.fixture(scope="module")
def rep_status_history():
    return pd.read_csv(f"{DATA_DIR}/rep_status_history.csv")


@pytest.fixture(scope="module")
def new_business(opportunities):
    return opportunities[
        (opportunities["opportunity_type"] == "new_business")
        & (opportunities["segment"].isin(["Commercial", "Enterprise"]))
    ]


@pytest.fixture(scope="module")
def joined(activities, new_business):
    """Every activity row joined back to its opportunity's segment,
    is_won, loss_reason, created/close dates and owning rep_id."""
    return activities.merge(
        new_business[["opportunity_id", "segment", "is_won", "loss_reason",
                      "created_date", "close_date", "rep_id"]],
        on="opportunity_id", how="left", suffixes=("", "_opp"),
    )


@pytest.fixture(scope="module")
def meeting_resolutions(joined):
    """One row per resolved meeting (excludes the antecedent 'booked' row)."""
    return joined[(joined["activity_type"] == "meeting") & (joined["outcome"] != "booked")]


@pytest.fixture(scope="module")
def opp_level(joined):
    """One row per opportunity: touch count, distinct contacts, is_won,
    segment, and the owning rep's ramp status at opportunity creation."""
    g = joined.groupby("opportunity_id").agg(
        segment=("segment", "first"),
        is_won=("is_won", "first"),
        loss_reason=("loss_reason", "first"),
        rep_id=("rep_id", "first"),
        created_date=("created_date", "first"),
        n_touches=("activity_id", "size"),
        n_contacts=("contact_ref", "nunique"),
    ).reset_index()
    return g


# =====================================================================
# A. Referential / structural integrity
# =====================================================================

class TestStructuralIntegrity:
    def test_columns_are_exactly_as_specified(self, activities):
        from generators.sales_activities import ACTIVITY_COLUMNS
        assert list(activities.columns) == ACTIVITY_COLUMNS

    def test_activity_id_is_unique(self, activities):
        assert activities["activity_id"].is_unique

    def test_every_rep_id_resolves_to_a_real_rep(self, activities, users):
        assert set(activities["rep_id"]) <= set(users["rep_id"])

    def test_every_opportunity_id_resolves_to_a_real_opportunity(self, activities, opportunities):
        assert set(activities["opportunity_id"]) <= set(opportunities["opportunity_id"])

    def test_no_smb_opportunity_is_present(self, activities, opportunities):
        smb_ids = set(opportunities.loc[opportunities["segment"] == "SMB", "opportunity_id"])
        assert not (set(activities["opportunity_id"]) & smb_ids)

    def test_no_expansion_or_renewal_opportunity_is_present(self, activities, opportunities):
        non_nb_ids = set(opportunities.loc[opportunities["opportunity_type"] != "new_business", "opportunity_id"])
        assert not (set(activities["opportunity_id"]) & non_nb_ids)

    def test_every_new_business_opportunity_has_at_least_one_touch(self, activities, new_business):
        assert set(new_business["opportunity_id"]) <= set(activities["opportunity_id"])

    def test_activity_type_is_one_of_the_declared_vocabulary(self, activities):
        assert set(activities["activity_type"]) <= ACTIVITY_TYPES

    def test_outcome_matches_its_own_activity_types_vocabulary(self, activities):
        for activity_type, outcomes in config.SALES_ACTIVITY_OUTCOMES.items():
            observed = set(activities.loc[activities["activity_type"] == activity_type, "outcome"])
            assert observed <= set(outcomes), f"{activity_type} carries outcome(s) outside its vocabulary: {observed - set(outcomes)}"

    def test_no_nulls_anywhere(self, activities):
        assert not activities.isna().any().any()

    def test_competitive_signal_and_is_outbound_touch_are_boolean(self, activities):
        assert activities["competitive_signal"].dtype == bool
        assert activities["is_outbound_touch"].dtype == bool

    def test_is_outbound_touch_only_ever_true_on_enterprise(self, joined):
        outbound = joined[joined["is_outbound_touch"]]
        assert (outbound["segment"] == "Enterprise").all()

    def test_is_outbound_touch_only_ever_on_call_or_email(self, activities):
        outbound = activities[activities["is_outbound_touch"]]
        assert set(outbound["activity_type"]) <= {"call", "email"}

    def test_meeting_booked_rows_have_a_later_resolution_row_on_the_same_opportunity(self, activities):
        """meetings_booked is represented as activity_type='meeting',
        outcome='booked' -- every such row must be followed by a
        resolution row (held/no_show/rescheduled/cancelled) for the same
        opportunity at a later timestamp, since a meeting lifecycle is two
        event-grain rows, not a single mutable status."""
        meetings = activities[activities["activity_type"] == "meeting"].sort_values(
            ["opportunity_id", "activity_timestamp"])
        booked = meetings[meetings["outcome"] == "booked"]
        resolved = meetings[meetings["outcome"] != "booked"]
        assert len(booked) == len(resolved), "booked/resolved meeting rows are not 1:1"
        booked_counts = booked.groupby("opportunity_id").size()
        resolved_counts = resolved.groupby("opportunity_id").size()
        pd.testing.assert_series_equal(booked_counts.sort_index(), resolved_counts.sort_index(),
                                        check_names=False)


# =====================================================================
# Point-in-time / window integrity
# =====================================================================

class TestWindowIntegrity:
    def test_every_touch_falls_inside_its_opportunitys_open_window(self, joined):
        after_created = joined["activity_timestamp"] >= joined["created_date"]
        before_closed = joined["activity_timestamp"] <= joined["close_date"]
        assert (after_created & before_closed).all()

    def test_meeting_resolution_never_precedes_its_booking(self, activities):
        meetings = activities[activities["activity_type"] == "meeting"].sort_values(
            ["opportunity_id", "activity_timestamp"])
        for opp_id, grp in meetings.groupby("opportunity_id"):
            booked_ts = grp.loc[grp["outcome"] == "booked", "activity_timestamp"].to_numpy()
            resolved_ts = grp.loc[grp["outcome"] != "booked", "activity_timestamp"].to_numpy()
            assert len(booked_ts) == len(resolved_ts)
            assert (np.sort(resolved_ts) >= np.sort(booked_ts)).all(), opp_id


# =====================================================================
# B. Distributional realism
# =====================================================================

class TestDistributionalRealism:
    def test_every_activity_type_actually_occurs(self, activities):
        assert set(activities["activity_type"]) == ACTIVITY_TYPES

    def test_every_declared_outcome_actually_occurs(self, activities):
        observed = set(activities["outcome"])
        missing = ALL_OUTCOMES - observed
        assert not missing, f"outcome value(s) exist only as unused schema values: {missing}"

    def test_enterprise_carries_more_touches_per_opportunity_than_commercial(self, opp_level):
        """Grounded in the coverage-model gradient (build spec Section 1):
        Enterprise's named-account, longer-cycle, AE+SE motion should show
        heavier per-deal engagement than Commercial's pooled-book ISR
        motion."""
        ent = opp_level.loc[opp_level["segment"] == "Enterprise", "n_touches"]
        comm = opp_level.loc[opp_level["segment"] == "Commercial", "n_touches"]
        assert ent.mean() > comm.mean() * 2

    def test_meeting_and_demo_share_is_higher_for_enterprise(self, joined):
        """Own resolved decision, config.SALES_ACTIVITY_TYPE_MIX: Enterprise
        leans meeting/demo-heavy (multi-stakeholder technical evaluation),
        Commercial leans call/email-heavy."""
        share = joined.groupby("segment")["activity_type"].apply(
            lambda s: s.isin(["meeting", "demo"]).mean())
        assert share["Enterprise"] > share["Commercial"]

    def test_meetings_booked_volume_is_a_meaningful_share_of_all_meeting_touches(self, activities):
        meetings = activities[activities["activity_type"] == "meeting"]
        booked_share = (meetings["outcome"] == "booked").mean()
        assert 0.40 <= booked_share <= 0.60, f"booked share {booked_share:.2%} of meeting rows"


# =====================================================================
# C. Correlational validity -- the "meaningful results" tests
# =====================================================================

class TestCorrelationalValidity:
    def test_meeting_held_rate_is_higher_on_won_deals(self, meeting_resolutions):
        by_outcome = meeting_resolutions.groupby("is_won")["outcome"].apply(lambda s: (s == "held").mean())
        assert by_outcome[True] > by_outcome[False], (
            f"won held-rate {by_outcome[True]:.2%} not clearly above lost {by_outcome[False]:.2%}")
        table = pd.crosstab(meeting_resolutions["is_won"], meeting_resolutions["outcome"] == "held")
        _, p, _, _ = stats.chi2_contingency(table)
        assert p < 0.001

    def test_multi_threading_is_higher_on_won_deals(self, opp_level):
        won = opp_level.loc[opp_level["is_won"], "n_contacts"]
        lost = opp_level.loc[~opp_level["is_won"], "n_contacts"]
        assert won.mean() > lost.mean(), (
            f"won distinct-contact mean {won.mean():.2f} not clearly above lost {lost.mean():.2f}")
        _, p = stats.mannwhitneyu(won, lost, alternative="greater")
        assert p < 0.01

    def test_touch_volume_is_higher_on_won_deals(self, opp_level):
        won = opp_level.loc[opp_level["is_won"], "n_touches"]
        lost = opp_level.loc[~opp_level["is_won"], "n_touches"]
        assert won.mean() > lost.mean()

    def test_neither_won_nor_lost_deals_are_a_perfect_separator_on_meeting_quality(self, meeting_resolutions):
        """QA plan's general framing for every causally-wired field in this
        project: correlated with the outcome, never a perfect predictor of
        it. Both won and lost deals must show meetings that go both ways."""
        by_outcome = meeting_resolutions.groupby("is_won")["outcome"].apply(lambda s: (s == "held").mean())
        assert 0.0 < by_outcome[True] < 1.0
        assert 0.0 < by_outcome[False] < 1.0

    def test_ramping_reps_show_lower_meeting_held_rate_than_ramped_reps(self, joined, users):
        hire_date_by_rep = dict(zip(users["rep_id"], users["hire_date"]))
        meetings = joined[(joined["activity_type"] == "meeting") & (joined["outcome"] != "booked")].copy()
        meetings["rep_is_ramped"] = (
            (meetings["created_date"] - meetings["rep_id"].map(hire_date_by_rep)).dt.days >= 180
        )
        by_ramp = meetings.groupby("rep_is_ramped")["outcome"].apply(lambda s: (s == "held").mean())
        assert by_ramp[True] > by_ramp[False], (
            f"ramped held-rate {by_ramp[True]:.2%} not clearly above ramping {by_ramp[False]:.2%}")

    def test_competitive_signal_is_elevated_on_competitive_losses(self, joined):
        """Correlates with opportunities.loss_reason == 'competitive'
        without being a perfect predictor of it -- present at a real,
        lower baseline on every other outcome too."""
        comp_loss = joined.loc[joined["loss_reason"] == "competitive", "competitive_signal"]
        other_loss = joined.loc[
            joined["loss_reason"].notna() & (joined["loss_reason"] != "competitive"), "competitive_signal"]
        won = joined.loc[joined["is_won"], "competitive_signal"]

        assert comp_loss.mean() > other_loss.mean() * 3
        assert comp_loss.mean() > won.mean() * 2
        assert 0.0 < comp_loss.mean() < 1.0, "competitive_signal must not be a perfect predictor of loss_reason"
        assert other_loss.mean() > 0.0, "non-competitive losses must still show some baseline signal"

        table = pd.crosstab(joined["loss_reason"].fillna("won") == "competitive", joined["competitive_signal"])
        _, p, _, _ = stats.chi2_contingency(table)
        assert p < 0.001


# =====================================================================
# D. Volume sufficiency
# =====================================================================

class TestVolumeSufficiency:
    def test_enough_total_activity_volume_to_model(self, activities):
        assert len(activities) >= 10_000

    def test_enough_distinct_reps_carry_enough_activity_each(self, activities, users):
        nb_reps = users[users["rep_type"].isin(["ISR", "AE"])]
        per_rep = activities[activities["rep_id"].isin(nb_reps["rep_id"])].groupby("rep_id").size()
        assert (per_rep >= 20).sum() >= 20, "too few reps carry enough deal-level activity for rep-productivity signal"

    def test_enough_opportunities_carry_a_meaningful_number_of_touches(self, opp_level):
        assert (opp_level["n_touches"] >= 5).mean() >= 0.5


# =====================================================================
# E. Edge-case-specific existence checks / injected incidents
# =====================================================================

class TestInjectedIncidents:
    def test_meetings_rise_without_sqo_rise_is_detectable(self, opp_level, new_business):
        """Injected incident #3: opportunities created inside the
        decoupling window show materially more activity than the rest of
        the population, while win rate for that same cohort stays within
        its normal range -- since opportunities.csv is read here and never
        rewritten, this batch cannot move the outcome even if it wanted to.
        Detectable by a straightforward variance check on touches/opp."""
        start, end = (pd.Timestamp(d) for d in config.SALES_ACTIVITY_DECOUPLING_INCIDENT_WINDOW)
        in_window = opp_level[opp_level["created_date"].between(start, end)]
        outside = opp_level[~opp_level["created_date"].between(start, end)]
        assert len(in_window) >= 100

        assert in_window["n_touches"].mean() > outside["n_touches"].mean() * 1.2, (
            f"in-window touches/opp {in_window['n_touches'].mean():.2f} not clearly above "
            f"baseline {outside['n_touches'].mean():.2f}")

        win_rate_window = new_business.loc[
            new_business["opportunity_id"].isin(in_window["opportunity_id"]), "is_won"].mean()
        win_rate_outside = new_business.loc[
            new_business["opportunity_id"].isin(outside["opportunity_id"]), "is_won"].mean()
        # "Decoupling" means win rate must NOT track the activity spike --
        # bounded to the same neighborhood as the rest of the simulation
        # window's natural quarter-to-quarter variance (config.
        # NEW_BUSINESS_WIN_RATE_TARGET +/- a wide band, not a tight one).
        assert abs(win_rate_window - win_rate_outside) < 0.15, (
            f"win rate moved with activity volume ({win_rate_window:.2%} vs {win_rate_outside:.2%}) "
            f"-- that is coupling, not decoupling")

    def test_underperforming_rep_cohort_is_visible_in_activity_patterns(self, meeting_resolutions):
        """Injected incident #4: a persistent subset of reps shows a
        materially worse meeting-held rate than the rest, independent of
        ramp status. Cannot be checked against opportunities.csv (this
        batch never rewrites it); it exists only in this activity data."""
        by_rep = meeting_resolutions.groupby("rep_id")["outcome"].apply(lambda s: (s == "held").mean())
        counts = meeting_resolutions.groupby("rep_id").size()
        eligible = by_rep[counts >= 8]
        assert len(eligible) >= 15, "too few reps with enough resolved meetings to detect a cohort"

        threshold = eligible.quantile(config.SALES_ACTIVITY_UNDERPERFORMER_SHARE)
        low_cohort = eligible[eligible <= threshold]
        rest = eligible[eligible > threshold]
        assert low_cohort.mean() < rest.mean() * 0.85, (
            f"bottom-cohort held-rate {low_cohort.mean():.2%} not clearly below "
            f"the rest {rest.mean():.2%}")

    def test_outbound_touches_exist_and_are_enterprise_only(self, activities, joined):
        assert activities["is_outbound_touch"].sum() >= 500
        outbound = joined[joined["is_outbound_touch"]]
        assert (outbound["segment"] == "Enterprise").all()
        assert not activities.loc[
            activities["opportunity_id"].isin(joined.loc[joined["segment"] == "Commercial", "opportunity_id"]),
            "is_outbound_touch",
        ].any()

    def test_both_multi_threaded_and_single_threaded_deals_exist(self, opp_level):
        """Both ends of the engagement-breadth distribution have to be
        present, or multi-threading has nothing real to distinguish."""
        assert (opp_level["n_contacts"] == 1).sum() >= 10
        assert (opp_level["n_contacts"] >= 3).sum() >= 50


# =====================================================================
# Reproducibility
# =====================================================================

class TestReproducibility:
    def test_output_is_reproducible_from_the_seed_alone(self, opportunities, users, rep_status_history):
        from generators import run_batch8
        from generators.sales_activities import ACTIVITY_COLUMNS, generate_sales_activities

        def build():
            rng = np.random.default_rng(run_batch8.BATCH8_SEED)
            df = generate_sales_activities(rng, opportunities, users, rep_status_history)
            return df[ACTIVITY_COLUMNS].reset_index(drop=True)

        pd.testing.assert_frame_equal(build(), build())


# =====================================================================
# NOT TESTED HERE -- deferred, deliberately
# =====================================================================
#
# Whether meeting-held rate or multi-threading actually *predicts* win
# probability well enough to power a deal-scoring model, and whether the
# rep-productivity cohort split identified here maps to a usable coaching
# intervention, are properties of the Wave 4 "Deal-level diagnostics" and
# "Rep productivity & coaching diagnostics" artifacts, not of this raw
# data. What this suite guarantees is that those artifacts have something
# real to work on: engagement quality, volume and multi-threading that
# genuinely move with win/loss and rep ramp status, a competitive_signal
# that tracks loss_reason without collapsing onto it, and both injected
# incidents detectable by a straightforward variance check.
