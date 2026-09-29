"""Validation checks for batch 12 (experiments_registry, experiment_assignment),
scoped per the validate-gtm-data skill and the QA plan's test cases
(docs/acme-corp-phase1-data-qa-plan.md).

This batch does not generate a new randomized mechanism -- it catalogs the
one real, already-running experiment in this raw data (the paid/community
holdout program `generators/marketing_funnel.py` already generates and
`analytics/marketing_attribution.py` already independently validated) as a
structured `experiments_registry` row, and re-derives the real per-lead
assignment already fixed by that program's `is_holdout` flag as
`experiment_assignment`. See `generators/experiments.py`'s module docstring
for the full design-decision reasoning (why catalog-only, not a second
invented experiment).

Because this batch is a deterministic replay of an already-real mechanism
plus a restatement of already-published, already-validated numbers, the
test profile here leans structural/referential rather than distributional:
the real distributional and correlational claims about the holdout program
itself (suppression is real, touches are withheld, budget is withheld) are
`tests/test_phase1_batch7.py`'s job and are not re-litigated wholesale here.
What this suite adds is specific to what this batch itself computes: that
`experiment_assignment.arm` genuinely traces to `campaigns.is_holdout` of
each lead's real first-touch campaign (not a fabricated parallel
assignment), and that the registry's stated result and guardrails hold
against the real assignment population this batch produces.

Run: python3 -m pytest tests/test_phase1_batch12.py -v
"""
import numpy as np
import pandas as pd
import pytest

from generators import config
from generators.experiments import (
    EXPERIMENT_ID,
    MARKETING_HOLDOUT_SIGNIFICANCE_Z,
    _first_touch_campaign,
    build_experiment_assignment,
    build_experiments_registry,
)

DATA_DIR = "data/raw"


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
def registry():
    return pd.read_csv(f"{DATA_DIR}/experiments_registry.csv")


@pytest.fixture(scope="module")
def assignment():
    return pd.read_csv(f"{DATA_DIR}/experiment_assignment.csv", parse_dates=["assigned_date"])


@pytest.fixture(scope="module")
def assignment_with_outcome(assignment, leads):
    return assignment.merge(leads[["lead_id", "is_converted"]], on="lead_id", how="left")


# =====================================================================
# A. Referential / structural integrity
# =====================================================================

class TestStructuralIntegrity:
    def test_registry_has_exactly_one_row(self, registry):
        """Design decision (generators/experiments.py docstring): this
        registry catalogs the one real, already-running randomized
        experiment in this data. Not a schema limit -- a real second
        experiment would add a second row -- but nothing here should
        silently duplicate or fragment the one real entry."""
        assert len(registry) == 1
        assert registry.loc[0, "experiment_id"] == EXPERIMENT_ID

    def test_registry_has_no_nulls(self, registry):
        assert not registry.isna().any().any()

    def test_assignment_id_is_unique(self, assignment):
        assert assignment["assignment_id"].is_unique

    def test_assignment_has_exactly_one_row_per_lead(self, assignment):
        """One lead, one first-touch campaign, one arm -- never two rows
        disagreeing about the same lead's assignment."""
        assert assignment["lead_id"].is_unique

    def test_every_assignment_experiment_id_resolves_to_the_registry(self, assignment, registry):
        assert set(assignment["experiment_id"]) <= set(registry["experiment_id"])

    def test_every_assignment_lead_id_resolves_to_a_real_lead(self, assignment, leads):
        assert set(assignment["lead_id"]) <= set(leads["lead_id"])

    def test_every_assignment_campaign_id_resolves_to_a_real_campaign(self, assignment, campaigns):
        assert set(assignment["first_touch_campaign_id"]) <= set(campaigns["campaign_id"])

    def test_account_id_is_populated_iff_the_lead_converted(self, assignment_with_outcome):
        assert (assignment_with_outcome["account_id"].notna()
                == assignment_with_outcome["is_converted"]).all()

    def test_arm_is_one_of_the_two_declared_values(self, assignment):
        assert set(assignment["arm"]) == {"treatment", "control"}

    def test_channel_is_scoped_to_the_holdout_channels(self, assignment):
        assert set(assignment["channel"]) <= set(config.HOLDOUT_CHANNELS)

    def test_cell_quarter_is_scoped_to_the_holdout_quarters(self, assignment):
        assert set(assignment["cell_quarter"]) <= set(config.HOLDOUT_QUARTERS)

    def test_assignment_arm_traces_to_the_real_is_holdout_flag(
        self, assignment, campaigns
    ):
        """The load-bearing correctness test for this whole batch: arm must
        equal the *real* campaigns.is_holdout of the lead's real first-touch
        campaign, independently re-derived here rather than trusted from
        the generator's own internal check -- a fabricated parallel
        assignment is exactly what this batch is not supposed to produce."""
        holdout_by_campaign = dict(zip(campaigns["campaign_id"], campaigns["is_holdout"]))
        implied = assignment["first_touch_campaign_id"].map(holdout_by_campaign)
        expected_arm = implied.map({True: "control", False: "treatment"})
        assert (assignment["arm"] == expected_arm).all()

    def test_assignment_matches_an_independent_first_touch_derivation(
        self, assignment, events
    ):
        """Independently re-derive first-touch-campaign-per-lead from the
        raw event stream (not via generators.experiments, to avoid trusting
        the same code path twice) and confirm it agrees with what's on
        disk."""
        independent = _first_touch_campaign(events).set_index("lead_id")["first_touch_campaign_id"]
        on_disk = assignment.set_index("lead_id")["first_touch_campaign_id"]
        common = on_disk.index.intersection(independent.index)
        assert (on_disk.loc[common] == independent.loc[common]).all()

    def test_assigned_date_matches_the_leads_own_created_date(self, assignment, leads):
        merged = assignment.merge(
            leads[["lead_id", "created_date"]], on="lead_id", suffixes=("", "_lead"))
        assert (pd.to_datetime(merged["assigned_date"])
                == pd.to_datetime(merged["created_date"])).all()


# =====================================================================
# B. Distributional realism
# =====================================================================

class TestDistributionalRealism:
    def test_every_cell_the_program_defines_has_both_arms_present(self, assignment):
        """6 cells (2 holdout channels x 3 holdout quarters) -- every one
        must carry both a treatment and a control population, or the
        contrast this table exists to support doesn't exist for that cell."""
        counts = assignment.groupby(["channel", "cell_quarter", "arm"]).size().unstack(fill_value=0)
        assert len(counts) == len(config.HOLDOUT_CHANNELS) * len(config.HOLDOUT_QUARTERS)
        assert (counts["treatment"] > 0).all()
        assert (counts["control"] > 0).all()

    def test_control_share_is_well_below_half(self, assignment):
        """The holdout is a minority carve-out (HOLDOUT_BUDGET_SHARE = 10%
        of a cell's normal spend), not a 50/50 split -- control volume
        should sit well under treatment volume in aggregate."""
        share = (assignment["arm"] == "control").mean()
        assert 0.05 < share < 0.35, f"control share {share:.2%} outside a plausible minority-carve-out band"

    def test_registrys_designed_effect_size_matches_config(self, registry):
        expected = round(1.0 - config.HOLDOUT_CONVERSION_SUPPRESSION, 4)
        assert registry.loc[0, "designed_effect_size"] == pytest.approx(expected)

    def test_registrys_cell_quarters_match_config_exactly(self, registry):
        assert registry.loc[0, "cell_quarters"] == "; ".join(config.HOLDOUT_QUARTERS)

    def test_registrys_start_and_end_date_are_real_calendar_dates_spanning_the_holdout_campaigns(
        self, registry, campaigns
    ):
        """start_date/end_date must be real, parseable calendar dates (not
        the quarter-label strings cell_quarters carries) -- typed like
        every other start_date/end_date in this project, so dbt's staging
        try_cast(... as date) succeeds rather than silently nulling out."""
        start_date = pd.Timestamp(registry.loc[0, "start_date"])
        end_date = pd.Timestamp(registry.loc[0, "end_date"])
        assert start_date <= end_date
        holdout = campaigns[campaigns["is_holdout"]]
        assert start_date == pd.Timestamp(holdout["start_date"].min())
        assert end_date == pd.Timestamp(holdout["end_date"].max())


# =====================================================================
# C. Correlational validity -- the "meaningful results" tests
# =====================================================================

class TestCorrelationalValidity:
    def test_control_converts_measurably_worse_than_treatment_overall(
        self, assignment_with_outcome
    ):
        """The whole reason this table exists: arm must correlate with a
        real outcome gap, not just carry a label. Checked directly against
        raw is_converted (not the point-in-time-resolved rate
        analytics/marketing_attribution.py uses, which is that module's own
        job) -- even the unscoped rate should show control converting
        measurably worse."""
        rates = assignment_with_outcome.groupby("arm")["is_converted"].mean()
        assert rates["control"] < rates["treatment"]
        assert rates["control"] / rates["treatment"] <= 0.65, (
            f"control/treatment conversion ratio {rates['control'] / rates['treatment']:.2f} "
            "not a clear enough suppression signal")

    def test_control_converts_worse_in_every_individual_cell(self, assignment_with_outcome):
        """Not just true in aggregate -- every one of the 6 cells should
        show the same direction, matching the QA plan's edge-case
        requirement that suppression is real and consistent, not an
        artifact of pooling."""
        rates = assignment_with_outcome.groupby(
            ["channel", "cell_quarter", "arm"])["is_converted"].mean().unstack()
        assert (rates["control"] <= rates["treatment"]).all(), rates

    def test_registry_result_is_reported_as_significant(self, registry):
        assert bool(registry.loc[0, "result_significant"])
        assert registry.loc[0, "result_z"] >= MARKETING_HOLDOUT_SIGNIFICANCE_Z

    def test_registry_result_sits_near_its_own_designed_target(self, registry):
        """Sanity bound on the reused number itself -- not a re-derivation,
        just confirming the pasted-in result and the config-derived design
        target are in the same neighborhood, catching a transcription error
        against analytics-methods.md."""
        result = registry.loc[0, "result_value"]
        designed = registry.loc[0, "designed_effect_size"]
        assert abs(result - designed) < 3 * registry.loc[0, "result_se"]


# =====================================================================
# D. Volume / sufficiency
# =====================================================================

class TestVolumeSufficiency:
    def test_total_control_volume_clears_the_registrys_own_guardrail(self, assignment):
        """The registry's own stated guardrail: resolved_control_cell_lead
        _volume >= 300. Checked against the real assignment table, not
        just asserted in the registry's text."""
        control_n = (assignment["arm"] == "control").sum()
        assert control_n >= 300, f"only {control_n} control leads -- below the registry's own floor"

    def test_every_individual_cells_control_volume_is_non_trivial(self, assignment):
        """QA plan Test D: 'the holdout cell carries enough leads on its
        own for its suppressed conversion rate to be separable from
        noise' -- applied per cell, not just pooled."""
        control = assignment[assignment["arm"] == "control"]
        counts = control.groupby(["channel", "cell_quarter"]).size()
        assert (counts >= 15).all(), f"a holdout cell is too thin to be separable from noise: {dict(counts)}"


# =====================================================================
# E. Edge-case-specific existence checks
# =====================================================================

class TestEdgeCases:
    def test_both_holdout_channels_appear_in_the_assignment_population(self, assignment):
        assert set(assignment["channel"]) == set(config.HOLDOUT_CHANNELS)

    def test_all_three_holdout_quarters_appear_in_the_assignment_population(self, assignment):
        assert set(assignment["cell_quarter"]) == set(config.HOLDOUT_QUARTERS)

    def test_converting_and_non_converting_leads_both_appear_in_each_arm(
        self, assignment_with_outcome
    ):
        for arm in ("treatment", "control"):
            sub = assignment_with_outcome[assignment_with_outcome["arm"] == arm]
            assert sub["is_converted"].any(), f"{arm} has no conversions at all"
            assert (~sub["is_converted"]).any(), f"{arm} is all conversions"


# =====================================================================
# Reproducibility
# =====================================================================

class TestReproducibility:
    def test_assignment_is_a_deterministic_function_of_its_inputs(self, campaigns, leads, events):
        """No randomness is drawn in this batch (see run_batch12.py's
        docstring) -- rebuilding from the same inputs must produce a
        byte-identical result, not just a statistically similar one."""
        a1 = build_experiment_assignment(campaigns, leads, events).reset_index(drop=True)
        a2 = build_experiment_assignment(campaigns, leads, events).reset_index(drop=True)
        pd.testing.assert_frame_equal(a1, a2)

    def test_registry_is_a_pure_function_with_no_hidden_state(self, campaigns):
        r1 = build_experiments_registry(campaigns)
        r2 = build_experiments_registry(campaigns)
        pd.testing.assert_frame_equal(r1, r2)


# =====================================================================
# NOT TESTED HERE -- deferred, deliberately
# =====================================================================
#
# Whether the holdout program's suppression mechanics themselves are real
# (withheld touches, withheld budget, isolated cells) is
# tests/test_phase1_batch7.py's job, not this one's -- this batch reads
# campaigns/leads/campaign_engagement_events as already-fixed inputs and
# does not regenerate or re-validate them. Whether the *point-in-time
# -resolved* incrementality estimate (censored-cell exclusion, the
# two-proportion z-test, the delta-method standard error) is itself correct
# is analytics/marketing_attribution.py's own build-time validation
# (run_build_time_validation(), documented in docs/acme-corp-analytics-
# methods.md) -- this suite deliberately reuses that module's published
# result rather than re-deriving or re-checking the statistic itself, which
# is the whole point of not recomputing a second, potentially-diverging
# number.
