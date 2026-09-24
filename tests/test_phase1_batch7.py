"""Validation checks for batch 7 (campaigns, leads,
campaign_engagement_events), scoped per the validate-gtm-data skill and the
QA plan's test cases (docs/acme-corp-phase1-data-qa-plan.md).

This batch is the marketing-automation funnel underneath the account
population: the campaign calendar, the leads those campaigns produced, and
every individual touch on the way. Three things shape its test profile:

  * Referential integrity runs in two directions, not one. Every converting
    lead must resolve to a real inbound-sourced account, AND every
    inbound-sourced account must be explained by exactly one converting
    lead. A batch that only checked the first direction could silently drop
    half the account population's funnel and still pass.
  * Point-in-time safety is a first-class category here. A touch attributed
    as pre-conversion evidence must actually precede the conversion, or
    every downstream attribution model is reading the future.
  * This is where QA plan Test C's "channels show genuinely different
    CAC/conversion profiles from each other -- organic, paid, and community
    should not look statistically identical" becomes checkable at the grain
    the requirement is actually written at. Until this batch the only
    channel field in the raw layer was the coarse 3-value acquisition
    taxonomy on accounts.channel, which does not contain organic, paid or
    community at all.

Tolerances below are written out independently rather than imported from
generators.config wherever a failure should mean the data drifted -- not
that a constant moved and the test moved with it. Where a test asserts an
ordering or a relationship rather than a level, it reads config directly,
since the ordering is the claim being tested.

Run: python3 -m pytest tests/test_phase1_batch7.py -v
"""
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from generators import config

DATA_DIR = "data/raw"

SUB_CHANNELS = ["organic", "paid", "community"]

# Lead -> customer conversion rate per sub-channel. Bands are the generator's
# documented targets with room for the holdout cells and the
# minimum-lead-pool floor to pull the realised rate down.
CONVERSION_RATE_BAND = {
    "organic": (0.040, 0.070),
    "paid": (0.022, 0.045),
    "community": (0.060, 0.100),
}

# Median days from lead creation to signup, per sub-channel. Bands bracket
# the generator's medians once the segment factor (build spec Section 1's
# sales-cycle gradient) is mixed across the real segment distribution.
LEAD_TO_SIGNUP_MEDIAN_BAND = {
    "organic": (8, 28),
    "paid": (16, 46),
    "community": (32, 95),
}

# Cost per acquisition per sub-channel, campaign budget over conversions.
# The parent channel's blended target is $1,400 (config.TARGET_CAC_BY_CHANNEL
# ["inbound_marketing"]); these are that scaled by each sub-channel's cost
# multiplier, widened for the injected CAC-creep incident on paid.
CAC_BAND = {
    "organic": (500, 1_100),
    "paid": (1_700, 3_200),
    "community": (950, 1_900),
}

# Mean touches per lead per sub-channel.
TOUCHES_PER_LEAD_BAND = {
    "organic": (3.0, 5.0),
    "paid": (1.6, 2.8),
    "community": (2.3, 4.0),
}

OBSERVATION_END = pd.Timestamp(config.SIM_END) + pd.offsets.MonthEnd(0)


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture(scope="module")
def campaigns():
    return pd.read_csv(f"{DATA_DIR}/campaigns.csv", parse_dates=["start_date", "end_date"])


@pytest.fixture(scope="module")
def leads():
    return pd.read_csv(f"{DATA_DIR}/leads.csv", parse_dates=["created_date", "converted_date"])


@pytest.fixture(scope="module")
def events():
    return pd.read_csv(f"{DATA_DIR}/campaign_engagement_events.csv", parse_dates=["event_timestamp"])


@pytest.fixture(scope="module")
def accounts():
    return pd.read_csv(f"{DATA_DIR}/accounts.csv", parse_dates=["signup_date"])


@pytest.fixture(scope="module")
def market_universe():
    return pd.read_csv(f"{DATA_DIR}/market_universe.csv")


@pytest.fixture(scope="module")
def inbound_accounts(accounts):
    return accounts[accounts["channel"] == config.MARKETING_SUB_CHANNEL_PARENT]


@pytest.fixture(scope="module")
def touch_counts(events):
    return events.groupby("lead_id").size().rename("touches")


@pytest.fixture(scope="module")
def leads_with_touches(leads, events, touch_counts):
    """Leads enriched with the two engagement features every correlational
    test in this module reads: how many times the lead was touched, and how
    long its engagement ran past lead creation before it went quiet."""
    last_touch = events.groupby("lead_id")["event_timestamp"].max().rename("last_touch")
    df = leads.merge(touch_counts, left_on="lead_id", right_index=True, how="left")
    df = df.merge(last_touch, left_on="lead_id", right_index=True, how="left")
    df["touches"] = df["touches"].fillna(0).astype(int)
    df["days_to_last_touch"] = (df["last_touch"] - df["created_date"]).dt.days
    return df


@pytest.fixture(scope="module")
def holdout_membership(events, campaigns):
    """A lead sits in the holdout cell when the campaign that sourced it --
    its first touch -- is a holdout campaign."""
    holdout_ids = set(campaigns.loc[campaigns["is_holdout"], "campaign_id"])
    first = (events.sort_values("event_timestamp", kind="mergesort")
                   .groupby("lead_id", as_index=False).first()[["lead_id", "campaign_id", "event_type"]])
    first["in_holdout"] = first["campaign_id"].isin(holdout_ids)
    return first


# =====================================================================
# A. Referential / structural integrity
# =====================================================================

class TestStructuralIntegrity:
    def test_campaign_columns_are_exactly_as_specified(self, campaigns):
        assert list(campaigns.columns) == [
            "campaign_id", "name", "channel", "start_date", "end_date", "budget", "is_holdout"]

    def test_lead_columns_are_exactly_as_specified(self, leads):
        assert list(leads.columns) == [
            "lead_id", "account_id", "company_id", "channel", "created_date",
            "lead_score", "converted_date", "is_converted"]

    def test_event_columns_are_exactly_as_specified(self, events):
        assert list(events.columns) == [
            "event_id", "lead_id", "campaign_id", "channel", "event_type", "event_timestamp"]

    def test_primary_keys_are_unique(self, campaigns, leads, events):
        assert campaigns["campaign_id"].is_unique
        assert leads["lead_id"].is_unique
        assert events["event_id"].is_unique

    def test_channels_are_the_metric_trees_three_sub_channels(self, campaigns, leads, events):
        for frame in (campaigns, leads, events):
            assert set(frame["channel"]) == set(config.MARKETING_SUB_CHANNELS)

    def test_every_converting_lead_resolves_to_a_real_inbound_account(self, leads, inbound_accounts):
        converted = leads[leads["is_converted"]]
        assert set(converted["account_id"]) <= set(inbound_accounts["account_id"])

    def test_every_inbound_account_has_exactly_one_converting_lead(self, leads, inbound_accounts):
        """Both directions. A converting lead pointing at a real account is
        not enough -- the funnel has to explain the whole inbound-sourced
        population, not a subset of it."""
        converted = leads[leads["is_converted"]]
        assert converted["account_id"].is_unique
        assert set(converted["account_id"]) == set(inbound_accounts["account_id"])
        assert len(converted) == len(inbound_accounts)

    def test_no_converting_lead_points_at_a_non_inbound_account(self, leads, accounts):
        converted = leads[leads["is_converted"]]
        channel_by_account = accounts.set_index("account_id")["channel"]
        resolved = converted["account_id"].map(channel_by_account)
        assert (resolved == config.MARKETING_SUB_CHANNEL_PARENT).all()

    def test_non_converting_leads_carry_no_account_or_conversion_date(self, leads):
        unconverted = leads[~leads["is_converted"]]
        assert unconverted["account_id"].isna().all()
        assert unconverted["converted_date"].isna().all()

    def test_converting_leads_carry_both_an_account_and_a_conversion_date(self, leads):
        converted = leads[leads["is_converted"]]
        assert converted["account_id"].notna().all()
        assert converted["converted_date"].notna().all()

    def test_non_nullable_lead_columns_have_no_nulls(self, leads):
        required = ["lead_id", "company_id", "channel", "created_date", "lead_score", "is_converted"]
        assert not leads[required].isna().any().any()

    def test_no_nulls_in_campaigns_or_events(self, campaigns, events):
        assert not campaigns.isna().any().any()
        assert not events.isna().any().any()

    def test_every_lead_company_resolves_to_the_market_universe(self, leads, market_universe):
        assert set(leads["company_id"]) <= set(market_universe["company_id"])

    def test_non_converting_leads_are_non_customer_companies(self, leads, market_universe):
        """A company that is or was a customer already has its converting
        lead; drawing it again as a never-converted lead would double-count
        the same prospect on both sides of the funnel."""
        ever = market_universe[
            market_universe["is_customer"].astype(bool)
            | market_universe["was_ever_customer"].astype(bool)]
        unconverted = leads[~leads["is_converted"]]
        assert set(unconverted["company_id"]).isdisjoint(set(ever["company_id"]))

    def test_converting_lead_company_matches_its_accounts_company(self, leads, accounts):
        converted = leads[leads["is_converted"]]
        company_by_account = accounts.set_index("account_id")["company_id"]
        assert (converted["account_id"].map(company_by_account).to_numpy()
                == converted["company_id"].to_numpy()).all()

    def test_no_orphaned_event_references(self, events, leads, campaigns):
        assert set(events["lead_id"]) <= set(leads["lead_id"])
        assert set(events["campaign_id"]) <= set(campaigns["campaign_id"])

    def test_every_lead_has_at_least_one_touch(self, leads, touch_counts):
        """A lead record exists because someone was touched. A lead with no
        touch would be a row multi-touch attribution can never reach."""
        assert set(leads["lead_id"]) <= set(touch_counts.index)
        assert touch_counts.min() >= 1

    def test_event_channel_always_matches_its_campaigns_channel(self, events, campaigns):
        channel_by_campaign = campaigns.set_index("campaign_id")["channel"]
        assert (events["campaign_id"].map(channel_by_campaign).to_numpy()
                == events["channel"].to_numpy()).all()

    def test_event_types_come_from_their_channels_closed_vocabulary(self, events):
        for channel, vocabulary in config.CAMPAIGN_EVENT_TYPES.items():
            observed = set(events.loc[events["channel"] == channel, "event_type"])
            assert observed <= set(vocabulary), f"{channel} has out-of-vocabulary event types"

    def test_campaign_windows_are_well_formed(self, campaigns):
        assert (campaigns["start_date"] <= campaigns["end_date"]).all()
        assert (campaigns["end_date"] <= OBSERVATION_END).all()

    def test_holdout_flag_only_appears_where_the_program_defines_it(self, campaigns):
        holdout = campaigns[campaigns["is_holdout"]]
        assert set(holdout["channel"]) <= set(config.HOLDOUT_CHANNELS)
        quarters = holdout["start_date"].dt.year.astype(str) + "Q" + holdout["start_date"].dt.quarter.astype(str)
        assert set(quarters) <= set(config.HOLDOUT_QUARTERS)


# =====================================================================
# A2. Point-in-time safety
# =====================================================================

class TestPointInTimeSafety:
    """A touch attributed as pre-conversion evidence must actually precede
    the conversion. Without this every downstream attribution or lead-
    scoring model is reading the outcome it is supposed to predict.
    """

    def test_every_lead_is_created_strictly_before_it_converts(self, leads):
        converted = leads[leads["is_converted"]]
        gap = (converted["converted_date"] - converted["created_date"]).dt.days
        assert (gap >= 1).all(), "a lead converted the same day it was created"

    def test_no_touch_lands_on_or_after_its_leads_conversion_date(self, events, leads):
        joined = events.merge(leads[["lead_id", "converted_date"]], on="lead_id", how="left")
        converted = joined[joined["converted_date"].notna()]
        assert (converted["event_timestamp"] < converted["converted_date"]).all()

    def test_no_touch_precedes_its_leads_creation_date(self, events, leads):
        joined = events.merge(leads[["lead_id", "created_date"]], on="lead_id", how="left")
        assert (joined["event_timestamp"].dt.normalize() >= joined["created_date"]).all()

    def test_no_touch_falls_outside_the_observation_window(self, events):
        assert events["event_timestamp"].max() <= OBSERVATION_END + pd.Timedelta(days=1)

    def test_no_lead_is_created_after_the_observation_window(self, leads):
        assert leads["created_date"].max() <= OBSERVATION_END

    def test_every_touch_falls_inside_its_campaigns_own_window(self, events, campaigns):
        """A touch attributed to a campaign that had not started, or had
        already ended, would make campaign-level CPL and ROAS meaningless."""
        windows = campaigns.set_index("campaign_id")[["start_date", "end_date"]]
        joined = events.join(windows, on="campaign_id")
        day = joined["event_timestamp"].dt.normalize()
        assert (day >= joined["start_date"]).all()
        assert (day <= joined["end_date"]).all()

    def test_touches_are_strictly_ordered_within_each_lead(self, events):
        ordered = events.sort_values(["lead_id", "event_timestamp"], kind="mergesort")
        duplicated = ordered.duplicated(["lead_id", "event_timestamp"])
        assert not duplicated.any(), "two touches on one lead share a timestamp"

    def test_the_first_touch_is_always_the_sourcing_channels_entry_event(self, leads, holdout_membership):
        """leads.channel records where the lead came from, so the earliest
        touch has to be that channel's entry event. This is also the one
        intra-lead ordering constraint in the event vocabulary: it makes an
        `event_attendance` on a community-sourced lead impossible before its
        `event_registration`."""
        first = leads.merge(holdout_membership, on="lead_id", how="left")
        expected = first["channel"].map(config.CAMPAIGN_FIRST_TOUCH_TYPE)
        assert (first["event_type"].to_numpy() == expected.to_numpy()).all()


# =====================================================================
# B. Distributional realism
# =====================================================================

class TestDistributionalRealism:
    def test_conversion_rate_per_channel_lands_in_its_band(self, leads):
        for channel, (low, high) in CONVERSION_RATE_BAND.items():
            rate = leads.loc[leads["channel"] == channel, "is_converted"].mean()
            assert low <= rate <= high, f"{channel} converts at {rate:.3%}"

    def test_blended_conversion_rate_is_plausible_for_a_marketing_qualified_lead(self, leads):
        rate = leads["is_converted"].mean()
        assert 0.02 <= rate <= 0.09, f"blended lead->customer rate {rate:.3%}"

    def test_lead_to_signup_gap_per_channel_lands_in_its_band(self, leads):
        converted = leads[leads["is_converted"]]
        gap = (converted["converted_date"] - converted["created_date"]).dt.days
        for channel, (low, high) in LEAD_TO_SIGNUP_MEDIAN_BAND.items():
            median = gap[converted["channel"] == channel].median()
            assert low <= median <= high, f"{channel} median gap {median}d"

    def test_lead_to_signup_gap_widens_with_segment(self, leads, accounts):
        """Build spec Section 1's sales-cycle gradient: an Enterprise
        decision takes longer than an SMB one, at every sub-channel."""
        converted = leads[leads["is_converted"]].copy()
        segment_by_account = accounts.set_index("account_id")["segment"]
        converted["segment"] = converted["account_id"].map(segment_by_account)
        converted["gap"] = (converted["converted_date"] - converted["created_date"]).dt.days
        medians = converted.groupby("segment")["gap"].median()
        assert medians["SMB"] < medians["Commercial"] < medians["Enterprise"]

    def test_touches_per_lead_per_channel_lands_in_its_band(self, leads_with_touches):
        for channel, (low, high) in TOUCHES_PER_LEAD_BAND.items():
            mean = leads_with_touches.loc[leads_with_touches["channel"] == channel, "touches"].mean()
            assert low <= mean <= high, f"{channel} averages {mean:.2f} touches/lead"

    def test_cost_per_acquisition_per_channel_lands_in_its_band(self, campaigns, leads):
        converted = leads[leads["is_converted"]]
        for channel, (low, high) in CAC_BAND.items():
            budget = campaigns.loc[campaigns["channel"] == channel, "budget"].sum()
            n = (converted["channel"] == channel).sum()
            cac = budget / n
            assert low <= cac <= high, f"{channel} CAC ${cac:,.0f}"

    def test_campaign_budget_reconciles_with_the_coarse_spend_table(self, campaigns, leads):
        """campaigns.budget and marketing_spend_by_channel_month are two
        views of the same money at different grains -- this table splits the
        parent inbound_marketing channel into its three sub-channels. They
        are built independently (that table works from monthly new-account
        counts, this one from planned per-campaign conversions), so exact
        agreement is not expected, but a large divergence would mean the
        finer split had drifted away from the coarse figure several
        Efficiency-pillar metrics already read."""
        spend = pd.read_csv(f"{DATA_DIR}/marketing_spend_by_channel_month.csv", parse_dates=["month"])
        coarse = spend.loc[spend["channel"] == config.MARKETING_SUB_CHANNEL_PARENT, "spend"].sum()
        in_window = campaigns.loc[campaigns["start_date"] >= pd.Timestamp(config.SIM_START), "budget"].sum()
        assert abs(in_window / coarse - 1) < 0.20, (
            f"campaign budget ${in_window:,.0f} vs coarse inbound spend ${coarse:,.0f}")

    def test_all_budgets_are_positive(self, campaigns):
        assert (campaigns["budget"] > 0).all()

    def test_lead_scores_stay_on_their_scale(self, leads):
        assert leads["lead_score"].between(0, 100).all()

    def test_every_event_type_in_every_vocabulary_actually_occurs(self, events):
        """An event type that exists only as a schema value and never fires
        is the same defect the QA plan flags for migration trigger_reason."""
        for channel, vocabulary in config.CAMPAIGN_EVENT_TYPES.items():
            observed = set(events.loc[events["channel"] == channel, "event_type"])
            assert observed == set(vocabulary), f"{channel} never emits {set(vocabulary) - observed}"

    def test_campaign_calendar_covers_every_lead_creation_date(self, campaigns, leads):
        """Every lead was created while at least one campaign in its own
        sub-channel was running -- otherwise its sourcing campaign is a
        back-dated fiction."""
        for channel in SUB_CHANNELS:
            windows = campaigns[campaigns["channel"] == channel]
            created = leads.loc[leads["channel"] == channel, "created_date"]
            assert created.min() >= windows["start_date"].min()
            assert created.max() <= windows["end_date"].max()


# =====================================================================
# C. Correlational validity -- the "meaningful results" tests
# =====================================================================

class TestCorrelationalValidity:
    """The two relationships this batch exists to put into the data:
    engagement predicts conversion, and the three sub-channels are genuinely
    different from one another. Both are asserted statistically, not by
    eyeballing a level.
    """

    def test_touch_volume_predicts_conversion_monotonically(self, leads_with_touches):
        buckets = pd.cut(leads_with_touches["touches"], [0, 1, 3, 6, 10, 10_000],
                         labels=["1", "2-3", "4-6", "7-10", "11+"])
        rates = leads_with_touches.groupby(buckets, observed=False)["is_converted"].mean()
        assert (np.diff(rates.to_numpy()) > 0).all(), f"non-monotonic: {rates.to_dict()}"
        assert rates.iloc[-1] > 10 * rates.iloc[0], (
            "the most-touched bucket must convert far better than the least-touched one, "
            f"got {rates.iloc[-1]:.3%} vs {rates.iloc[0]:.3%}")

    def test_converting_leads_are_touched_significantly_more(self, leads_with_touches):
        converted = leads_with_touches.loc[leads_with_touches["is_converted"], "touches"]
        other = leads_with_touches.loc[~leads_with_touches["is_converted"], "touches"]
        statistic, p = stats.mannwhitneyu(converted, other, alternative="greater")
        assert p < 1e-10, f"touch-count difference not significant (p={p:.3g})"
        assert converted.mean() > 2 * other.mean()

    def test_touch_recency_predicts_conversion(self, leads_with_touches):
        """Measured at a common horizon after lead creation: a lead still
        being touched weeks in converts far better than one whose last touch
        was days after it appeared. This is the recency half of the causal
        wiring, distinct from raw volume."""
        df = leads_with_touches
        buckets = pd.cut(df["days_to_last_touch"], [-1, 7, 21, 45, 10_000],
                         labels=["0-7d", "8-21d", "22-45d", "46d+"])
        rates = df.groupby(buckets, observed=False)["is_converted"].mean()
        assert (np.diff(rates.to_numpy()) > 0).all(), f"non-monotonic: {rates.to_dict()}"
        stale = df.loc[df["days_to_last_touch"] <= 7, "is_converted"].mean()
        recent = df.loc[df["days_to_last_touch"] > 21, "is_converted"].mean()
        assert recent > 5 * stale

    def test_lead_score_is_not_independent_noise(self, leads):
        """The QA plan's causal-wiring rule applied to this table's one
        composite column: it has to be a function of real drivers, so it
        must carry real signal about the outcome -- but a score that nearly
        determined the outcome would mean the composite had collapsed onto
        it."""
        r, p = stats.pointbiserialr(leads["is_converted"].astype(int), leads["lead_score"])
        assert p < 1e-10
        assert 0.15 <= r <= 0.70, f"lead_score/conversion correlation {r:.3f}"

    def test_lead_score_rises_with_both_of_its_drivers(self, leads_with_touches, market_universe):
        df = leads_with_touches.copy()
        icp = market_universe.set_index("company_id")["icp_fit_score"]
        df["icp_fit_score"] = df["company_id"].map(icp)
        assert stats.spearmanr(df["lead_score"], df["touches"]).statistic > 0.3
        assert stats.spearmanr(df["lead_score"], df["icp_fit_score"]).statistic > 0.3

    def test_the_three_sub_channels_convert_at_significantly_different_rates(self, leads):
        """QA plan Test C, at the grain the requirement is written at. The
        coarse accounts.channel taxonomy contains no organic/paid/community
        value at all, so this could not be checked before this batch."""
        table = pd.crosstab(leads["channel"], leads["is_converted"])
        _, p, _, _ = stats.chi2_contingency(table)
        assert p < 1e-10, f"channel conversion rates are not distinguishable (p={p:.3g})"
        for a, b in [("organic", "paid"), ("organic", "community"), ("paid", "community")]:
            pair = table.loc[[a, b]]
            _, pair_p, _, _ = stats.chi2_contingency(pair)
            assert pair_p < 0.001, f"{a} vs {b} conversion rates not distinguishable (p={pair_p:.3g})"

    def test_the_three_sub_channels_carry_different_touch_distributions(self, leads_with_touches):
        groups = [leads_with_touches.loc[leads_with_touches["channel"] == c, "touches"] for c in SUB_CHANNELS]
        _, p = stats.kruskal(*groups)
        assert p < 1e-10
        for i, j in [(0, 1), (0, 2), (1, 2)]:
            _, pair_p = stats.mannwhitneyu(groups[i], groups[j])
            assert pair_p < 0.001, f"{SUB_CHANNELS[i]} vs {SUB_CHANNELS[j]} touch counts not distinguishable"

    def test_the_three_sub_channels_carry_different_lead_to_signup_gaps(self, leads):
        converted = leads[leads["is_converted"]].copy()
        converted["gap"] = (converted["converted_date"] - converted["created_date"]).dt.days
        groups = [converted.loc[converted["channel"] == c, "gap"] for c in SUB_CHANNELS]
        _, p = stats.kruskal(*groups)
        assert p < 1e-10
        # Ordering, not just difference: organic self-serves fastest,
        # community/event leads sit in the longest nurture cycle.
        assert groups[0].median() < groups[1].median() < groups[2].median()

    def test_the_three_sub_channels_carry_different_cac(self, campaigns, leads):
        converted = leads[leads["is_converted"]]
        cac = {
            c: campaigns.loc[campaigns["channel"] == c, "budget"].sum() / (converted["channel"] == c).sum()
            for c in SUB_CHANNELS
        }
        assert cac["organic"] < cac["community"] < cac["paid"]
        assert cac["paid"] > 2 * cac["organic"], f"CAC profiles too close: {cac}"

    def test_paid_leads_score_materially_lower_than_the_other_two(self, leads):
        """The lead-score axis of Test C. Organic and community land closer
        to each other than either does to paid, and that is a real property
        of a composite rather than a defect: community's higher channel
        quality is partly offset by organic's deeper touch volume. The
        assertion is written to that shape rather than forcing three
        separated means."""
        by_channel = leads.groupby("channel")["lead_score"]
        means = by_channel.mean()
        assert means["paid"] < means["organic"] - 5
        assert means["paid"] < means["community"] - 5
        for other in ("organic", "community"):
            _, p = stats.mannwhitneyu(leads.loc[leads["channel"] == "paid", "lead_score"],
                                      leads.loc[leads["channel"] == other, "lead_score"],
                                      alternative="less")
            assert p < 1e-10

    def test_channels_are_not_statistically_identical_on_any_axis(self, campaigns, leads, leads_with_touches):
        """The QA plan's requirement stated directly: across conversion
        rate, touch volume, lead-to-signup gap, CAC and lead score, no two
        sub-channels look alike on all five at once. Asserted as a summary
        so a future change that flattened the split fails here with a
        readable message rather than in five separate places."""
        converted = leads[leads["is_converted"]]
        profile = {}
        for c in SUB_CHANNELS:
            sub = leads_with_touches[leads_with_touches["channel"] == c]
            sub_conv = converted[converted["channel"] == c]
            gap = (sub_conv["converted_date"] - sub_conv["created_date"]).dt.days
            profile[c] = np.array([
                sub["is_converted"].mean(),
                sub["touches"].mean(),
                gap.median(),
                campaigns.loc[campaigns["channel"] == c, "budget"].sum() / len(sub_conv),
                sub["lead_score"].mean(),
            ])
        for a, b in [("organic", "paid"), ("organic", "community"), ("paid", "community")]:
            relative = np.abs(profile[a] - profile[b]) / np.abs(profile[a] + profile[b]) * 2
            assert (relative > 0.05).sum() >= 4, (
                f"{a} and {b} differ on fewer than four of the five profile axes: {relative}")


# =====================================================================
# D. Volume / sufficiency for modeling
# =====================================================================

class TestVolumeSufficiency:
    def test_every_sub_channel_has_enough_leads_to_model(self, leads):
        counts = leads["channel"].value_counts()
        for channel in SUB_CHANNELS:
            assert counts[channel] >= 1_000, f"{channel} has only {counts[channel]} leads"

    def test_every_sub_channel_has_enough_conversions_for_class_balance(self, leads):
        converted = leads[leads["is_converted"]]["channel"].value_counts()
        for channel in SUB_CHANNELS:
            assert converted[channel] >= 150, f"{channel} has only {converted[channel]} conversions"

    def test_every_sub_channel_has_enough_campaigns_for_campaign_level_analysis(self, campaigns):
        counts = campaigns["channel"].value_counts()
        for channel in SUB_CHANNELS:
            assert counts[channel] >= 20, f"{channel} has only {counts[channel]} campaigns"

    def test_touch_volume_is_sufficient_for_multi_touch_attribution(self, events):
        assert len(events) >= 50_000

    def test_the_holdout_cell_is_large_enough_to_read(self, leads, holdout_membership):
        """An incrementality test on a handful of leads is not a test. The
        control cell needs enough volume that its suppressed conversion rate
        is separable from noise."""
        merged = leads.merge(holdout_membership[["lead_id", "in_holdout"]], on="lead_id", how="left")
        assert merged["in_holdout"].sum() >= 300

    def test_conversions_are_spread_across_the_whole_window(self, leads):
        converted = leads[leads["is_converted"]]
        by_year = converted["converted_date"].dt.year.value_counts()
        for year in range(pd.Timestamp(config.SIM_START).year, pd.Timestamp(config.SIM_END).year + 1):
            assert by_year.get(year, 0) >= 100, f"{year} has too few inbound conversions"


# =====================================================================
# E. Edge-case-specific existence checks
# =====================================================================

class TestEdgeCaseExistence:
    def test_holdout_campaigns_exist(self, campaigns):
        """Build spec Section 4 requires a deliberately-excluded control
        group somewhere in the data."""
        assert campaigns["is_holdout"].any()
        assert campaigns["is_holdout"].sum() >= len(config.HOLDOUT_QUARTERS)

    def test_the_holdout_group_is_genuinely_suppressed_not_merely_flagged(
            self, leads_with_touches, holdout_membership):
        """The whole point of a holdout: it converts materially worse than
        its treated peers in the same sub-channels and the same quarters.
        Compared like-for-like, so the gap cannot be a channel-mix or
        seasonality artefact.
        """
        df = leads_with_touches.merge(holdout_membership[["lead_id", "in_holdout"]],
                                      on="lead_id", how="left")
        quarter = (df["created_date"].dt.year.astype(str) + "Q"
                   + df["created_date"].dt.quarter.astype(str))
        comparable = df[df["channel"].isin(config.HOLDOUT_CHANNELS)
                        & quarter.isin(config.HOLDOUT_QUARTERS)]
        treated = comparable[~comparable["in_holdout"]]
        control = comparable[comparable["in_holdout"]]

        assert len(control) >= 300
        assert control["is_converted"].mean() < 0.6 * treated["is_converted"].mean(), (
            f"holdout converts at {control['is_converted'].mean():.3%} vs treated "
            f"{treated['is_converted'].mean():.3%} -- not a suppressed control group")

        table = pd.crosstab(comparable["in_holdout"], comparable["is_converted"])
        _, p, _, _ = stats.chi2_contingency(table)
        assert p < 0.001, f"holdout suppression is not statistically detectable (p={p:.3g})"

    def test_the_holdout_group_receives_the_treatment_withheld(
            self, leads_with_touches, holdout_membership, campaigns):
        """Suppression has to run through a mechanism, not a standalone
        conversion knob: the control cell is touched less, and its budget is
        withheld rather than re-labelled."""
        df = leads_with_touches.merge(holdout_membership[["lead_id", "in_holdout"]],
                                      on="lead_id", how="left")
        comparable = df[df["channel"].isin(config.HOLDOUT_CHANNELS)]
        treated = comparable.loc[~comparable["in_holdout"], "touches"]
        control = comparable.loc[comparable["in_holdout"], "touches"]
        assert control.mean() < 0.7 * treated.mean()
        _, p = stats.mannwhitneyu(control, treated, alternative="less")
        assert p < 1e-10

        holdout_budget = campaigns.loc[campaigns["is_holdout"], "budget"]
        peer_budget = campaigns.loc[
            campaigns["channel"].isin(config.HOLDOUT_CHANNELS) & ~campaigns["is_holdout"], "budget"]
        assert holdout_budget.median() < 0.4 * peer_budget.median()

    def test_leads_touched_by_more_than_one_campaign_exist(self, events, leads):
        """A lead that only ever sees one campaign makes first-touch,
        last-touch and linear attribution return the same answer. Multi-
        touch attribution needs a real multi-campaign path to exist."""
        per_lead = events.groupby("lead_id")["campaign_id"].nunique()
        share = (per_lead > 1).mean()
        assert share >= 0.10, f"only {share:.1%} of leads see more than one campaign"

    def test_cross_sub_channel_touch_paths_exist(self, events, leads):
        """Channel sub-attribution is only interesting if a lead sourced by
        one sub-channel can be touched by another."""
        lead_channel = leads.set_index("lead_id")["channel"]
        cross = events["channel"].to_numpy() != events["lead_id"].map(lead_channel).to_numpy()
        assert cross.sum() > 0
        assert 0.01 <= cross.mean() <= 0.20, f"cross-channel touch share {cross.mean():.2%}"

    def test_both_ends_of_the_engagement_distribution_exist(self, leads_with_touches):
        """Single-touch leads and deeply-engaged leads both have to be
        present, or the touch-volume gradient has nothing to run across."""
        touches = leads_with_touches["touches"]
        assert (touches == 1).sum() >= 1_000
        assert (touches >= 10).sum() >= 200

    def test_the_paid_cac_creep_incident_is_visible_at_campaign_grain(self, campaigns):
        """Injected incident #2 (config.CAC_CREEP_INCIDENT_*) is recorded on
        inbound_marketing as a whole in the coarse spend table, which cannot
        show which sub-channel it came from. At campaign grain it should be
        locatable to paid media in the incident window by a straightforward
        variance check."""
        start, end = (pd.Timestamp(d) for d in config.CAC_CREEP_INCIDENT_WINDOW)
        paid = campaigns[(campaigns["channel"] == "paid") & ~campaigns["is_holdout"]
                         & (campaigns["start_date"] >= pd.Timestamp(config.SIM_START))]
        in_window = paid[(paid["start_date"] <= end) & (paid["end_date"] >= start)]
        outside = paid[(paid["start_date"] > end) | (paid["end_date"] < start)]
        assert len(in_window) > 0
        assert in_window["budget"].median() > 1.3 * outside["budget"].median(), (
            f"incident-window paid budget median ${in_window['budget'].median():,.0f} vs "
            f"${outside['budget'].median():,.0f} outside it")


# =====================================================================
# Reproducibility
# =====================================================================

class TestReproducibility:
    def test_output_is_reproducible_from_the_seed_alone(self, accounts, market_universe):
        from generators import marketing_funnel, run_batch7

        def build():
            rng = np.random.default_rng(run_batch7.BATCH7_SEED)
            c = marketing_funnel.generate_campaigns(rng, accounts)
            lead_frame = marketing_funnel.generate_leads(rng, accounts, market_universe, c)
            e = marketing_funnel.generate_campaign_engagement_events(rng, lead_frame, c)
            return (c[marketing_funnel.CAMPAIGN_COLUMNS],
                    lead_frame[marketing_funnel.LEAD_COLUMNS],
                    e)

        first, second = build(), build()
        for a, b in zip(first, second):
            pd.testing.assert_frame_equal(a, b)


# =====================================================================
# NOT TESTED HERE -- deferred, deliberately
# =====================================================================
#
# Whether any particular attribution model (first-touch, last-touch, linear,
# time-decay, Markov) assigns credit correctly is a property of the Wave 2
# "Marketing attribution & channel mix" artifact, not of this raw data. What
# this suite guarantees is that the artifact will have something real to
# work on: every touch present and undeduplicated, multi-campaign and
# cross-sub-channel paths that actually exist, touch volume and recency that
# genuinely predict conversion, three sub-channels that are statistically
# distinct, and a holdout cell that is really suppressed. Model correctness
# belongs to that artifact's own build-time validation.
#
# The incrementality *read* itself -- what lift the holdout implies once
# confounders are controlled -- is likewise that artifact's job. This suite
# only asserts the control group exists and is genuinely excluded.
