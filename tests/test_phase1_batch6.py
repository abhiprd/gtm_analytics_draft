"""Validation checks for batch 6 (fact_forecast_submissions,
cro_forecast_adjustments), scoped per the validate-gtm-data skill and the
QA plan's test cases (docs/acme-corp-phase1-data-qa-plan.md).

This batch is the forecasting source system -- the weekly bottoms-up
submission history and the logged CRO overlay the Wave-2 Forecast artifact
is built on. Its test profile differs from the prior batches in one way
that shapes everything below: the table's whole reason for existing is a
*relationship*, not a population. The build spec specifies a weekly
snapshot rather than a single mutable field "since the gap between rep and
manager categorization is itself a signal," and a gap that does not
predict the outcome is a decorative column, not a signal. Category C is
therefore the centre of this suite rather than a supporting section.

The thresholds below are written out independently rather than imported
from generators.forecast, so a failure means the generated data left its
defensible range -- not that a constant was moved and the test moved with
it.

Run: python3 -m pytest tests/test_phase1_batch6.py -v
"""
import numpy as np
import pandas as pd
import pytest

from generators import config, forecast

DATA_DIR = "data/raw"

FORECAST_CATEGORIES = {"Omitted", "Pipeline", "Best Case", "Commit"}
RANK = {"Omitted": 0, "Pipeline": 1, "Best Case": 2, "Commit": 3}
CONFIDENT = RANK["Best Case"]

CRO_REASONS = {
    "pipeline_coverage_shortfall",
    "rep_sandbagging_pattern",
    "late_stage_slippage_risk",
    "named_account_upside",
}

# Minimum win-rate gap between "rep and manager agreed on a confident
# call" and "manager downgraded a confident rep call." Stated well below
# what the generator produces, so the assertion fails on a mechanism that
# has broken rather than on ordinary sampling movement -- but far enough
# above zero that a gap surviving only as noise does not pass.
MIN_GAP_ALL = 0.12
MIN_GAP_NEW_BUSINESS = 0.05

# No forecast category may collapse to a rounding error or swallow the
# table -- a degenerate mix would give a downstream model one class to
# learn.
MIN_CATEGORY_SHARE = 0.05
MAX_CATEGORY_SHARE = 0.60


@pytest.fixture(scope="module")
def submissions():
    return pd.read_csv(f"{DATA_DIR}/fact_forecast_submissions.csv", parse_dates=["snapshot_date"])


@pytest.fixture(scope="module")
def adjustments():
    return pd.read_csv(f"{DATA_DIR}/cro_forecast_adjustments.csv", parse_dates=["timestamp"])


@pytest.fixture(scope="module")
def opportunities():
    return pd.read_csv(
        f"{DATA_DIR}/opportunities.csv", parse_dates=["created_date", "close_date"]
    )


@pytest.fixture(scope="module")
def reps():
    return pd.read_csv(f"{DATA_DIR}/users.csv", parse_dates=["hire_date"])


@pytest.fixture(scope="module")
def in_scope(opportunities):
    return opportunities[opportunities["segment"].isin(["Commercial", "Enterprise"])]


@pytest.fixture(scope="module")
def window():
    start = pd.Timestamp(config.SIM_START)
    return start, start + pd.DateOffset(months=config.N_MONTHS)


@pytest.fixture(scope="module")
def joined(submissions, opportunities):
    return submissions.merge(
        opportunities[[
            "opportunity_id", "account_id", "segment", "opportunity_type",
            "rep_id", "poc_outcome", "is_won", "created_date", "close_date",
        ]],
        on="opportunity_id", how="left",
    )


@pytest.fixture(scope="module")
def final_calls(joined):
    """The last call filed on each opportunity before it closed -- the
    submission a bottoms-up forecast for that period would have been built
    on, and the one the rep/manager gap is judged at."""
    ordered = joined.sort_values(["opportunity_id", "snapshot_date"])
    final = ordered.groupby("opportunity_id", as_index=False).last()
    final["rep_rank"] = final["rep_forecast_category"].map(RANK)
    final["manager_rank"] = final["manager_forecast_category"].map(RANK)
    return final


def _gap(final, mask=None):
    """Win rate where the manager downgraded a confident rep call, against
    win rate where the two agreed on one. Both sides are conditioned on
    the same confident rep call, so the comparison isolates the manager's
    disagreement rather than the difference between a confident deal and a
    written-off one."""
    subset = final if mask is None else final[mask]
    confident = subset["rep_rank"] >= CONFIDENT
    downgraded = subset[confident & (subset["manager_rank"] < subset["rep_rank"])]
    agreed = subset[confident & (subset["manager_rank"] == subset["rep_rank"])]
    return downgraded, agreed


# =====================================================================
# A. Referential / structural integrity
# =====================================================================

class TestStructuralIntegrity:
    def test_submission_columns_are_exactly_as_specified(self, submissions):
        assert list(submissions.columns) == [
            "opportunity_id", "snapshot_date",
            "rep_forecast_category", "manager_forecast_category",
        ]

    def test_adjustment_columns_are_exactly_as_specified(self, adjustments):
        assert list(adjustments.columns) == [
            "period", "segment", "adjustment_amount", "reason", "timestamp",
        ]

    def test_no_nulls_in_either_table(self, submissions, adjustments):
        assert not submissions.isna().any().any()
        assert not adjustments.isna().any().any()

    def test_every_opportunity_id_resolves(self, submissions, opportunities):
        assert submissions["opportunity_id"].isin(opportunities["opportunity_id"]).all()

    def test_no_smb_opportunity_is_forecast(self, joined):
        """SMB is no-touch, closes in 0-7 days and carries no rep or stage
        history (build spec Section 1), so it has no weekly forecast
        cadence for a submission to belong to."""
        assert set(joined["segment"]) == {"Commercial", "Enterprise"}

    def test_grain_is_one_row_per_opportunity_and_snapshot(self, submissions):
        assert not submissions.duplicated(["opportunity_id", "snapshot_date"]).any()

    def test_every_snapshot_falls_inside_its_opportunitys_open_window(self, joined):
        """A submission is a judgement on an open deal: never before it
        existed, never on or after the day it resolved."""
        assert (joined["snapshot_date"] >= joined["created_date"]).all()
        assert (joined["snapshot_date"] < joined["close_date"]).all()

    def test_every_snapshot_is_on_the_weekly_call_day(self, submissions):
        assert (submissions["snapshot_date"].dt.weekday == 4).all()

    def test_cadence_is_weekly_with_no_gaps_while_a_deal_is_open(self, submissions):
        """Consecutive calls on the same opportunity are exactly seven days
        apart -- a missing week would mean a deal silently dropped off the
        forecast and reappeared."""
        ordered = submissions.sort_values(["opportunity_id", "snapshot_date"])
        deltas = ordered.groupby("opportunity_id")["snapshot_date"].diff().dropna()
        assert (deltas == pd.Timedelta(days=7)).all()

    def test_snapshots_stay_inside_the_reporting_window(self, submissions, window):
        start, end = window
        assert submissions["snapshot_date"].min() >= start
        assert submissions["snapshot_date"].max() < end

    def test_every_opportunity_open_on_a_call_date_is_covered(self, submissions, in_scope, window):
        """The complement of the window rule: no Commercial or Enterprise
        deal that was open on an in-window call date is missing from the
        table. A partial population would bias every roll-up built on it."""
        start, end = window
        grid = pd.date_range(start, end - pd.Timedelta(days=1), freq="W-FRI")
        expected = {
            row.opportunity_id for row in in_scope.itertuples()
            if grid.searchsorted(row.close_date, "left") > grid.searchsorted(row.created_date, "left")
        }
        assert set(submissions["opportunity_id"]) == expected

    def test_categories_come_from_the_established_closed_set(self, submissions):
        """The same four-value vocabulary opportunities.forecast_category
        uses -- one taxonomy for the schema, not two."""
        assert set(submissions["rep_forecast_category"]) <= FORECAST_CATEGORIES
        assert set(submissions["manager_forecast_category"]) <= FORECAST_CATEGORIES

    def test_adjustment_grain_is_one_row_per_period_and_segment(self, adjustments):
        assert not adjustments.duplicated(["period", "segment"]).any()

    def test_adjustment_periods_are_well_formed_quarters_in_window(self, adjustments, window):
        start, end = window
        periods = adjustments["period"].map(lambda p: pd.Period(p.replace("-", ""), freq="Q"))
        assert adjustments["period"].str.match(r"^\d{4}-Q[1-4]$").all()
        assert periods.min().start_time >= start
        assert periods.max().end_time < end

    def test_adjustment_segments_match_the_forecasting_population(self, adjustments):
        assert set(adjustments["segment"]) <= {"Commercial", "Enterprise"}

    def test_adjustment_reasons_come_from_the_closed_set(self, adjustments):
        assert set(adjustments["reason"]) <= CRO_REASONS

    def test_every_adjustment_is_timestamped_inside_its_own_period(self, adjustments):
        """An override is logged when it is made, at the quarter's own
        forecast call -- never backdated into a period it did not belong
        to."""
        periods = adjustments["period"].map(lambda p: pd.Period(p.replace("-", ""), freq="Q"))
        assert (adjustments["timestamp"] >= periods.map(lambda p: p.start_time)).all()
        assert (adjustments["timestamp"] <= periods.map(lambda p: p.end_time)).all()

    def test_no_adjustment_is_a_silent_zero(self, adjustments):
        """Build spec Section 5: a logged, reasoned override. A zero-dollar
        row would be a reason with no override attached."""
        assert (adjustments["adjustment_amount"] != 0).all()


# =====================================================================
# B. Distributional realism
# =====================================================================

class TestDistributionalRealism:
    @pytest.mark.parametrize("column", ["rep_forecast_category", "manager_forecast_category"])
    def test_category_mix_is_not_degenerate(self, submissions, column):
        mix = submissions[column].value_counts(normalize=True)
        assert set(mix.index) == FORECAST_CATEGORIES, f"{column} is missing a category entirely"
        assert mix.min() >= MIN_CATEGORY_SHARE, f"{column} smallest share {mix.min():.3f}"
        assert mix.max() <= MAX_CATEGORY_SHARE, f"{column} largest share {mix.max():.3f}"

    @pytest.mark.parametrize("column", ["rep_forecast_category", "manager_forecast_category"])
    def test_every_segment_sees_every_category(self, joined, column):
        for segment, group in joined.groupby("segment"):
            assert set(group[column]) == FORECAST_CATEGORIES, f"{segment}/{column}"

    def test_reps_are_systematically_more_optimistic_than_managers(self, submissions):
        """The standing bias the build spec's rep/manager split exists to
        capture. Asserted as a direction plus a floor on how often the two
        actually differ -- a table where they almost never disagree carries
        no gap to read."""
        rep_rank = submissions["rep_forecast_category"].map(RANK)
        manager_rank = submissions["manager_forecast_category"].map(RANK)
        above = (rep_rank > manager_rank).mean()
        below = (manager_rank > rep_rank).mean()
        assert rep_rank.mean() > manager_rank.mean()
        assert above > below
        assert 0.05 < above < 0.45, f"rep-above-manager share {above:.3f}"

    def test_managers_sometimes_read_a_deal_more_favourably_than_the_rep(self, submissions):
        """Disagreement runs both ways. A gap that only ever points one
        direction would be a mechanical offset, not a judgement."""
        rep_rank = submissions["rep_forecast_category"].map(RANK)
        manager_rank = submissions["manager_forecast_category"].map(RANK)
        assert (manager_rank > rep_rank).sum() > 0

    def test_disagreement_is_at_most_one_notch_in_the_common_case(self, submissions):
        """Two people reading the same deal land next to each other far
        more often than three bands apart."""
        rep_rank = submissions["rep_forecast_category"].map(RANK)
        manager_rank = submissions["manager_forecast_category"].map(RANK)
        spread = (rep_rank - manager_rank).abs()
        assert (spread <= 1).mean() > 0.90

    def test_confidence_firms_up_as_a_deal_approaches_close(self, joined):
        """A forecast read that did not move with the deal's progress would
        mean stage and stall were not reaching the categorisation at all."""
        ordered = joined.sort_values(["opportunity_id", "snapshot_date"])
        multi = ordered.groupby("opportunity_id").filter(lambda g: len(g) > 1)
        first = multi.groupby("opportunity_id").first()
        last = multi.groupby("opportunity_id").last()
        assert (last["manager_forecast_category"].map(RANK).mean()
                > first["manager_forecast_category"].map(RANK).mean())

    def test_longer_cycle_segments_carry_more_forecast_calls(self, joined):
        """config.CYCLE_LENGTH_DAYS puts Enterprise new business at 60-180
        days against Commercial's 14-45, so an Enterprise deal should sit
        on the forecast for materially more weeks."""
        new_business = joined[joined["opportunity_type"] == "new_business"]
        calls = new_business.groupby(["segment", "opportunity_id"]).size()
        assert calls.loc["Enterprise"].mean() > 2 * calls.loc["Commercial"].mean()

    def test_adjustments_are_sparse_relative_to_the_submission_history(self, adjustments, submissions):
        """An override is an exception, not a standing line item."""
        assert len(adjustments) < 0.01 * len(submissions)
        quarters = config.N_MONTHS // 3
        assert len(adjustments) <= quarters * 2

    def test_adjustment_reasons_carry_the_sign_they_describe(self, adjustments):
        """A coverage shortfall or a slippage risk cuts the forecast; a
        sandbagging pattern or named-account upside raises it. A row whose
        reason and sign disagree would make the log unreadable."""
        signs = adjustments.groupby("reason")["adjustment_amount"].agg(["min", "max"])
        for reason in ("pipeline_coverage_shortfall", "late_stage_slippage_risk"):
            if reason in signs.index:
                assert signs.loc[reason, "max"] < 0, f"{reason} is not a cut"
        for reason in ("rep_sandbagging_pattern", "named_account_upside"):
            if reason in signs.index:
                assert signs.loc[reason, "min"] > 0, f"{reason} is not a raise"


# =====================================================================
# C. Correlational validity -- the "meaningful results" tests
#
# The reason this table exists. Build spec Section 5 specifies a weekly
# snapshot rather than a mutable field because "the gap between rep and
# manager categorization is itself a signal." These are the checks that
# the gap is one.
# =====================================================================

class TestCorrelationalValidity:
    def test_manager_downgrade_predicts_a_lower_win_rate(self, final_calls):
        """THE check for this batch. Among opportunities the rep called
        confidently, the ones the manager marked down must actually close
        at a materially lower rate than the ones the manager agreed with.
        Without this the two columns are decoration and every forecast
        model built on them is learning noise."""
        downgraded, agreed = _gap(final_calls)
        assert len(downgraded) > 100 and len(agreed) > 100
        gap = agreed["is_won"].mean() - downgraded["is_won"].mean()
        assert gap > MIN_GAP_ALL, (
            f"downgraded {downgraded['is_won'].mean():.3f} (n={len(downgraded)}) vs "
            f"agreed {agreed['is_won'].mean():.3f} (n={len(agreed)}), gap {gap:.3f}")

    def test_manager_downgrade_predicts_a_lower_win_rate_within_new_business(self, final_calls):
        """The same property inside new business alone, where the outcome
        is genuinely uncertain. Renewal and expansion close at a far higher
        base rate, so a pooled result could in principle be carried by
        opportunity-type mix; this is the check that it is not."""
        mask = final_calls["opportunity_type"] == "new_business"
        downgraded, agreed = _gap(final_calls, mask)
        assert len(downgraded) > 50 and len(agreed) > 50
        gap = agreed["is_won"].mean() - downgraded["is_won"].mean()
        assert gap > MIN_GAP_NEW_BUSINESS, (
            f"downgraded {downgraded['is_won'].mean():.3f} (n={len(downgraded)}) vs "
            f"agreed {agreed['is_won'].mean():.3f} (n={len(agreed)}), gap {gap:.3f}")

    def test_manager_downgrade_predicts_a_lower_win_rate_in_both_segments(self, final_calls):
        """Commercial and Enterprise are forecast by different roles on
        different cycle lengths. The property has to hold in each, or it is
        a property of the segment mix."""
        for segment in ("Commercial", "Enterprise"):
            mask = final_calls["segment"] == segment
            downgraded, agreed = _gap(final_calls, mask)
            assert len(downgraded) > 30 and len(agreed) > 30, segment
            gap = agreed["is_won"].mean() - downgraded["is_won"].mean()
            assert gap > MIN_GAP_NEW_BUSINESS, f"{segment} gap {gap:.3f}"

    def test_the_manager_is_the_better_calibrated_of_the_two(self, final_calls):
        """The rep files the optimistic read and the manager the calibrated
        one, so the manager's final category must track the realized
        outcome at least as closely as the rep's."""
        rep_corr = final_calls["rep_rank"].corr(final_calls["is_won"].astype(float))
        manager_corr = final_calls["manager_rank"].corr(final_calls["is_won"].astype(float))
        assert manager_corr > rep_corr
        assert manager_corr > 0.25

    def test_win_rate_rises_monotonically_with_the_final_manager_category(self, final_calls):
        """The categories have to mean what they say: a Commit must close
        more often than a Best Case, which must close more often than a
        Pipeline, and so on."""
        by_category = final_calls.groupby("manager_rank")["is_won"].mean()
        assert list(by_category.index) == sorted(by_category.index)
        assert by_category.is_monotonic_increasing, by_category.to_dict()

    def test_ramping_reps_file_more_optimistically_than_ramped_reps(self, joined, reps):
        """QA plan grounding requirement 2 applied to this table's own
        driver. Measured as the rep's call against the manager's on the
        same deal, so it isolates the rep's optimism from the deal quality
        a ramping rep is separately assigned -- the two are distinct
        effects and the generator keeps them distinct."""
        merged = joined.merge(reps[["rep_id", "hire_date"]], on="rep_id", how="left")
        merged = merged[merged["hire_date"].notna()]
        ramping = (merged["snapshot_date"] - merged["hire_date"]).dt.days < 180
        gap = (merged["rep_forecast_category"].map(RANK)
               - merged["manager_forecast_category"].map(RANK))
        assert ramping.sum() > 200, "too few ramping-rep calls to read"
        assert gap[ramping].mean() > gap[~ramping].mean()

    def test_ramping_reps_carry_genuinely_weaker_deals(self, final_calls, reps):
        """The other half of the same driver, and the reason the two are
        not conflated: a ramping rep both reports more optimistically
        (above) and actually closes less (here), matching the QA plan's
        "ramping reps show measurably lower win rate than ramped reps, but
        not zero."""
        merged = final_calls.merge(reps[["rep_id", "hire_date"]], on="rep_id", how="left")
        merged = merged[merged["hire_date"].notna()]
        ramping = (merged["snapshot_date"] - merged["hire_date"]).dt.days < 180
        assert 0 < merged.loc[ramping, "is_won"].mean() < merged.loc[~ramping, "is_won"].mean()

    def test_a_failed_poc_shows_up_in_the_manager_call(self, final_calls):
        """The POC result is revealed mid-cycle and is the strongest
        observable driver on an Enterprise new-business deal, so it must
        reach the forecast read rather than stopping at the stage history."""
        enterprise = final_calls[
            (final_calls["segment"] == "Enterprise")
            & (final_calls["opportunity_type"] == "new_business")
            & final_calls["poc_outcome"].isin(["pass", "fail"])
        ]
        by_outcome = enterprise.groupby("poc_outcome")["manager_rank"].mean()
        assert by_outcome["pass"] > by_outcome["fail"]

    def test_a_fading_account_shows_up_in_its_renewal_forecast(self, final_calls):
        """Usage trajectory is the observable that distinguishes a renewal
        that will close from one that will not, so a renewal the account
        went on to churn out of must read weaker at its final call than one
        it renewed."""
        renewals = final_calls[final_calls["opportunity_type"] == "renewal"]
        by_outcome = renewals.groupby("is_won")["manager_rank"].mean()
        assert by_outcome[True] > by_outcome[False]


# =====================================================================
# D. Point-in-time safety
#
# A forecast submission dated `snapshot_date` may depend only on what was
# observable on that date. These assert the guarantee behaviourally --
# by changing an input the generator must not be reading and requiring
# the output not to move -- rather than by inspecting source text.
# =====================================================================

class TestPointInTimeSafety:
    @pytest.fixture(scope="class")
    def inputs(self):
        opportunities = pd.read_csv(
            f"{DATA_DIR}/opportunities.csv", parse_dates=["created_date", "close_date"]
        )
        stage_history = pd.read_csv(
            f"{DATA_DIR}/opportunity_stage_history.csv", parse_dates=["entered_date"]
        )
        users = pd.read_csv(f"{DATA_DIR}/users.csv", parse_dates=["hire_date"])
        usage = pd.read_csv(f"{DATA_DIR}/usage_monthly.csv", parse_dates=["month"])
        return opportunities, stage_history, users, usage

    def _generate(self, inputs, opportunities=None):
        base, stage_history, users, usage = inputs
        return forecast.generate_forecast_submissions(
            np.random.default_rng(config.SEED + 5000),
            base if opportunities is None else opportunities,
            stage_history, users, usage,
        )

    def test_output_is_reproducible_from_the_seed_alone(self, inputs):
        pd.testing.assert_frame_equal(self._generate(inputs), self._generate(inputs))

    def test_close_time_only_fields_are_not_read(self, inputs):
        """`amount`, `list_price`, `discount_rate` and `loss_reason` are
        all fixed at close, and the single-valued `forecast_category` is a
        close-time field rather than a point-in-time series. Scrambling
        every one of them must leave the submissions untouched -- which
        also demonstrates this table is not a re-derivation of the existing
        forecast_category column."""
        opportunities, _, _, _ = inputs
        scrambled = opportunities.copy()
        rng = np.random.default_rng(0)
        for column in ("amount", "list_price", "discount_rate", "loss_reason", "forecast_category"):
            scrambled[column] = rng.permutation(scrambled[column].to_numpy())
        pd.testing.assert_frame_equal(self._generate(inputs), self._generate(inputs, scrambled))

    def test_the_trailing_close_rate_cannot_see_an_unresolved_deal(self, inputs):
        """The one component that reads `is_won` reads it only for deals
        that had already closed. Flipping the outcome of every deal still
        open on a given date must leave that date's trailing rate
        unchanged."""
        opportunities, _, _, _ = inputs
        in_scope = opportunities[opportunities["segment"].isin(["Commercial", "Enterprise"])]
        window_start = pd.Timestamp(config.SIM_START)
        as_of = pd.Timestamp("2024-07-05")

        flipped = in_scope.copy()
        still_open = flipped["close_date"] >= as_of
        flipped.loc[still_open, "is_won"] = ~flipped.loc[still_open, "is_won"].astype(bool)
        assert still_open.sum() > 0

        before = forecast._TrailingCloseRate(in_scope, window_start)
        after = forecast._TrailingCloseRate(flipped, window_start)
        for segment in ("Commercial", "Enterprise"):
            for opportunity_type in ("new_business", "renewal", "expansion"):
                assert before.rate(segment, opportunity_type, as_of) == pytest.approx(
                    after.rate(segment, opportunity_type, as_of)
                ), f"{segment}/{opportunity_type}"

    def test_usage_read_stops_at_the_last_complete_month(self, inputs):
        """The renewal/expansion driver reads consumption, which is only
        knowable once a month has ended. The month a snapshot falls in must
        be invisible to it."""
        _, _, _, usage = inputs
        lookup = forecast._usage_by_account_month(usage)
        account_id = usage["account_id"].iloc[0]
        snapshot = pd.Timestamp("2024-06-21")
        current_month = forecast._month_ordinal(snapshot)
        baseline = forecast._usage_trend_ratio(lookup, account_id, snapshot)

        poisoned = dict(lookup)
        poisoned[(account_id, current_month)] = 10 ** 9
        assert forecast._usage_trend_ratio(poisoned, account_id, snapshot) == baseline


# =====================================================================
# E. Volume / sufficiency for modeling
# =====================================================================

class TestVolumeSufficiency:
    def test_enough_submissions_to_model_on(self, submissions):
        assert len(submissions) > 10_000
        assert submissions["opportunity_id"].nunique() > 2_000

    def test_every_segment_and_opportunity_type_is_represented(self, joined):
        counts = joined.groupby(["segment", "opportunity_type"]).size()
        expected = {
            (segment, opportunity_type)
            for segment in ("Commercial", "Enterprise")
            for opportunity_type in ("new_business", "renewal", "expansion")
        }
        assert set(counts.index) == expected
        assert counts.min() > 200, counts.to_dict()

    def test_multiple_calls_per_deal_so_a_trajectory_exists(self, submissions):
        """A single snapshot per deal would make this a mutable field with
        extra steps -- the build spec's reason for a snapshot series is
        that the read moves over the life of the deal."""
        per_opportunity = submissions.groupby("opportunity_id").size()
        assert per_opportunity.median() >= 3
        assert (per_opportunity > 1).mean() > 0.80

    def test_both_outcomes_are_present_under_every_final_category(self, final_calls):
        """A category that only ever resolves one way gives a model a
        deterministic rule instead of a probability."""
        outcomes = final_calls.groupby("manager_forecast_category")["is_won"].nunique()
        assert (outcomes == 2).all(), outcomes.to_dict()


# =====================================================================
# F. Edge-case-specific existence checks
# =====================================================================

class TestEdgeCaseExistence:
    def test_every_cro_reason_actually_occurs(self, adjustments):
        """A closed set with a value that never fires is a schema comment,
        not a category -- the same standard the QA plan sets for
        `trigger_reason`."""
        assert set(adjustments["reason"]) == CRO_REASONS

    def test_overrides_run_in_both_directions(self, adjustments):
        assert (adjustments["adjustment_amount"] > 0).any()
        assert (adjustments["adjustment_amount"] < 0).any()

    def test_both_segments_receive_overrides(self, adjustments):
        assert set(adjustments["segment"]) == {"Commercial", "Enterprise"}

    def test_some_quarters_receive_no_override_at_all(self, adjustments):
        """The overlay is a logged exception. If every segment-quarter
        carried one, the absence of a row would stop being informative."""
        quarters = config.N_MONTHS // 3
        assert len(adjustments) < quarters * 2

    def test_a_deal_can_move_between_categories_over_its_life(self, submissions):
        """Some deals firm up, some fall apart. A table where every
        opportunity carried one unchanging category would have no
        trajectory for a forecast model to read."""
        moved = submissions.groupby("opportunity_id")["manager_forecast_category"].nunique() > 1
        assert moved.mean() > 0.25

    def test_some_deals_are_written_off_before_they_close(self, joined):
        """Omitted has to be reachable while a deal is still technically
        open, or the category is unused in practice."""
        assert (joined["manager_forecast_category"] == "Omitted").sum() > 100
