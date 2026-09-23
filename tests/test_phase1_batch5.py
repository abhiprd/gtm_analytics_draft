"""Validation checks for batch 5 (gtm_plan_targets), scoped per the
validate-gtm-data skill and the QA plan's test cases
(docs/acme-corp-phase1-data-qa-plan.md).

This batch is the FP&A/RevOps plan layer -- the target values the Phase 4
variance-diagnostic engine measures each Layer-1 metric against. Two things
make its test profile different from every prior batch:

  * There is no referential integrity to check against another table. A plan
    row points at a metric name and a month, not at an account or an
    opportunity. Structural integrity here means the closed metric set, the
    complete month grid, and no duplicates.
  * The correlational question this table exists to support -- does variance
    from plan actually surface real misses -- cannot be answered here. That
    is a property of the engine that consumes the plan, not of the plan, and
    it belongs to the variance-diagnostic engine's own build-time
    validation. No stand-in check is asserted in its place.

The distributional bands below are written out independently rather than
imported from generators.gtm_plan, so a test failure means the plan left its
defensible range -- not that a constant was moved and the test moved with it.

Run: python3 -m pytest tests/test_phase1_batch5.py -v
"""
import inspect

import pandas as pd
import pytest

from generators import config, gtm_plan

DATA_DIR = "data/raw"

EXPECTED_METRICS = {
    "new_logo_consumption_revenue",
    "expansion_consumption_revenue",
    "contraction_churned_revenue",
    "magic_number",
    "consumption_payback",
    "onboarding_cs_efficiency",
    "am_efficiency",
    "nrr",
    "grr",
    "logo_retention",
}

EXPECTED_PILLARS = {
    "new_logo_consumption_revenue": "Growth",
    "expansion_consumption_revenue": "Growth",
    "contraction_churned_revenue": "Growth",
    "magic_number": "Efficiency",
    "consumption_payback": "Efficiency",
    "onboarding_cs_efficiency": "Efficiency",
    "am_efficiency": "Efficiency",
    "nrr": "Durability",
    "grr": "Durability",
    "logo_retention": "Durability",
}

# Defensible range per metric, across all 36 planned months.
#
# Benchmark-backed (docs/acme-corp-phase1-data-qa-plan.md, "Grounding
# requirements"), taken as the full segment envelope so any blended figure
# must sit inside it:
#   magic_number          Commercial and Enterprise both ~0.7-0.9
#   consumption_payback   Commercial ~14-18mo, Enterprise ~9-13mo
#   nrr                   SMB ~96-97%, Commercial ~105-110%, Enterprise ~118-125%
#   grr                   SMB ~80-85%, Commercial ~88-92%, Enterprise ~92-95%
#   logo_retention        SMB ~75-85%, Commercial ~88-93%, Enterprise ~93-97%
#
# No benchmark row exists for the rest; these bands come from the resolved
# decisions gtm_plan.py documents:
#   new_logo -- the planned revenue base runs from ~$1.4M to ~$9.7M MRR
#     across the window (config.FINAL_* account targets x
#     config.USAGE_BASELINE_ACTIONS x config.PRICE_PER_ACTION), and new logo
#     is planned as acquisitions per month x entry MRR x first-ramp-month
#     fraction, so it has a wide but bounded range across three years.
#   expansion / contraction -- these two are NOT free ranges. Both are
#     planned as a share of that same base, and the share is DERIVED from
#     the benchmark-blended nrr/grr anchors rather than chosen: the metric
#     tree defines GRR as (Starting - Contraction - Churn) / Starting and
#     NRR as that plus Expansion, so the monthly shares are
#     1 - grr**(1/12) (~0.76%/mo, falling to ~0.63% as the grr plan
#     improves) and nrr**(1/12) - 1 + that (~1.95%/mo). Applied to the base
#     those give annual levels of ~$39K/$74K/$140K (expansion) and
#     ~$15K/$26K/$44K (contraction+churn) per month, and the monthly
#     shaping terms widen each by at most x0.67-x1.35 (seasonality x
#     intra-year ramp x 3 sigma of noise). The bands below are those
#     envelopes rounded outward.
#     WHY THESE TWO BANDS ARE NARROW, AND MUST STAY NARROW: a band sized
#     instead for plausible-looking standalone monthly shares -- say 9.0% of
#     base for expansion and 5.3% for contraction+churn -- works out to
#     roughly (120_000, 1_000_000) and (70_000, 600_000), and a band that
#     wide admits values that contradict the nrr/grr rows sitting in the
#     same table. A 5.3%/month gross revenue loss compounds to an annual GRR
#     of ~0.51 against a grr row stating ~0.91; a 9.0%/5.3% pair compounds
#     to an NRR of ~1.55 against an nrr row stating ~1.15. These bands are
#     the envelope of the derivation above and nothing wider, so a drift
#     back toward an independently-chosen share fails here rather than
#     passing as "in range."
#   onboarding_cs_efficiency -- config's terminal steady state is
#     ~4.45e-6 touches/Action (config.AM_TOUCH_RATE_BASELINE against
#     config.USAGE_BASELINE_ACTIONS at the FINAL_* counts). A plan should sit
#     above that floor while the base is still ramping, and never at more
#     than roughly twice it.
#   am_efficiency -- config's book sizes imply ~15 AMs at terminal scale; the
#     plan sits between two and four and a half times expansion ARR per
#     dollar of AM cost.
PLAN_VALUE_RANGE = {
    "new_logo_consumption_revenue": (5_000, 30_000),
    "expansion_consumption_revenue": (25_000, 190_000),
    "contraction_churned_revenue": (10_000, 60_000),
    "magic_number": (0.70, 0.90),
    "consumption_payback": (9.0, 18.0),
    "onboarding_cs_efficiency": (4.4e-6, 9.0e-6),
    "am_efficiency": (2.0, 4.5),
    "nrr": (0.96, 1.25),
    "grr": (0.80, 0.95),
    "logo_retention": (0.75, 0.97),
}

# Direction each metric's plan moves year over year, per gtm_plan.py's
# documented escalation assumptions. +1 means later plan years are higher.
EXPECTED_YOY_DIRECTION = {
    "new_logo_consumption_revenue": +1,
    "expansion_consumption_revenue": +1,
    "contraction_churned_revenue": +1,
    "magic_number": +1,
    "consumption_payback": -1,
    "onboarding_cs_efficiency": -1,
    "am_efficiency": +1,
    "nrr": +1,
    "grr": +1,
    "logo_retention": +1,
}


@pytest.fixture(scope="module")
def plan():
    return pd.read_csv(f"{DATA_DIR}/gtm_plan_targets.csv", parse_dates=["month"])


@pytest.fixture(scope="module")
def expected_months():
    return pd.date_range(config.SIM_START, periods=config.N_MONTHS, freq="MS")


# =====================================================================
# A. Referential / structural integrity
# =====================================================================

class TestStructuralIntegrity:
    def test_row_count_is_exactly_ten_metrics_by_thirty_six_months(self, plan):
        assert len(plan) == 360

    def test_columns_are_exactly_as_specified(self, plan):
        assert list(plan.columns) == ["layer1_metric", "month", "plan_value", "pillar"]

    def test_no_nulls_anywhere(self, plan):
        assert not plan.isna().any().any()

    def test_metric_set_is_the_expected_closed_set(self, plan):
        assert set(plan["layer1_metric"]) == EXPECTED_METRICS

    def test_activation_has_no_plan_row(self, plan):
        """Activation is the one Layer-1 node the readout reports against a
        trailing baseline rather than a plan figure. Any spelling of it
        appearing here would mean a plan value was invented for it."""
        assert not plan["layer1_metric"].str.contains("activation", case=False).any()

    def test_no_duplicate_metric_month_pairs(self, plan):
        assert not plan.duplicated(["layer1_metric", "month"]).any()

    def test_every_metric_covers_every_month_with_no_gaps(self, plan, expected_months):
        for metric in EXPECTED_METRICS:
            months = set(plan.loc[plan["layer1_metric"] == metric, "month"])
            assert months == set(expected_months), f"{metric} has month gaps"

    def test_every_month_is_the_first_of_its_month(self, plan):
        assert (plan["month"].dt.day == 1).all()

    def test_pillar_matches_the_metric_tree(self, plan):
        mapped = plan.groupby("layer1_metric")["pillar"].unique()
        for metric, pillars in mapped.items():
            assert list(pillars) == [EXPECTED_PILLARS[metric]], f"{metric} pillar mismatch"

    def test_pillar_counts_match_the_tree_minus_activation(self, plan):
        """Growth has four Layer-1 nodes in the tree; Activation is the
        excluded one, so Growth contributes three here. Efficiency four,
        Durability three."""
        counts = plan.drop_duplicates("layer1_metric")["pillar"].value_counts().to_dict()
        assert counts == {"Efficiency": 4, "Growth": 3, "Durability": 3}


# =====================================================================
# B. Distributional realism
# =====================================================================

class TestDistributionalRealism:
    def test_every_plan_value_falls_in_its_defensible_range(self, plan):
        for metric, (low, high) in PLAN_VALUE_RANGE.items():
            values = plan.loc[plan["layer1_metric"] == metric, "plan_value"]
            assert values.min() >= low, f"{metric} min {values.min()} below {low}"
            assert values.max() <= high, f"{metric} max {values.max()} above {high}"

    def test_all_plan_values_are_positive(self, plan):
        """Contraction + churn is stored as a positive magnitude, matching
        int_revenue_movements' contraction/churn buckets -- the readout's
        leading minus is a display convention, not the stored sign."""
        assert (plan["plan_value"] > 0).all()

    def test_monthly_values_within_a_plan_year_are_not_flat(self, plan):
        """Seasonality, the intra-year ramp and seeded noise should give
        every metric genuine month-to-month movement inside a plan year."""
        for metric in EXPECTED_METRICS:
            subset = plan[plan["layer1_metric"] == metric]
            for year, group in subset.groupby(subset["month"].dt.year):
                assert group["plan_value"].nunique() > 1, f"{metric} {year} is flat"

    def test_monthly_variation_stays_modest(self, plan):
        """A plan varies month to month but does not swing wildly -- a
        within-year coefficient of variation above ~25% would mean the
        seasonality or noise term had broken loose."""
        for metric in EXPECTED_METRICS:
            subset = plan[plan["layer1_metric"] == metric]
            for year, group in subset.groupby(subset["month"].dt.year):
                cv = group["plan_value"].std() / group["plan_value"].mean()
                assert cv < 0.25, f"{metric} {year} coefficient of variation {cv:.2f}"

    def test_year_over_year_direction_matches_the_planning_assumption(self, plan):
        """Compared on annual means, so seasonality and noise cannot flip
        the result of a genuine escalation."""
        for metric, direction in EXPECTED_YOY_DIRECTION.items():
            subset = plan[plan["layer1_metric"] == metric]
            annual = subset.groupby(subset["month"].dt.year)["plan_value"].mean()
            diffs = annual.diff().dropna()
            assert (diffs * direction > 0).all(), f"{metric} moves against its plan direction"

    def test_grr_plan_never_exceeds_nrr_plan(self, plan):
        """Structural: GRR is NRR without the expansion term, so a plan
        where GRR sits above NRR would be internally inconsistent
        regardless of where each lands in its benchmark band."""
        wide = plan.pivot(index="month", columns="layer1_metric", values="plan_value")
        assert (wide["grr"] < wide["nrr"]).all()

    def test_expansion_and_contraction_lines_reconcile_with_nrr_and_grr(self, plan):
        """The flows and the rates made out of those flows must describe one
        world, not two. The metric tree defines

            GRR = (Starting - Contraction - Churn) / Starting
            NRR = (Starting - Contraction - Churn + Expansion) / Starting

        so a month's contraction+churn share of the base is
        1 - grr**(1/12) and its expansion share is nrr**(1/12) - 1 + that.
        Both dollar lines are that share times the SAME revenue base, so
        their ratio must equal the ratio of the two shares -- a check that
        needs nothing but the published table, no generator internals.

        Compared on annual means because both sides are noisy at monthly
        grain and the noise is amplified asymmetrically: a 0.4% wiggle in a
        published grr moves the implied monthly contraction share by ~4%
        (the twelfth root sits against a share of ~0.008), on top of each
        dollar line's own independent 3% draw. Annual means cancel both and
        agree to ~0.4%; the 2% tolerance is that with headroom.

        This is the guard that a range check cannot provide. Standalone
        monthly shares of 9.0% expansion and 5.3% contraction+churn sit
        inside any plausible dollar band while putting this ratio at 1.70
        against an implied ~2.57 -- a 34% break, which only a reconciliation
        catches.
        """
        wide = plan.pivot(index="month", columns="layer1_metric", values="plan_value")
        annual = wide.groupby(wide.index.year).mean()
        contraction_share = 1 - annual["grr"] ** (1 / 12)
        expansion_share = annual["nrr"] ** (1 / 12) - 1 + contraction_share
        observed = (annual["expansion_consumption_revenue"]
                    / annual["contraction_churned_revenue"])
        implied = expansion_share / contraction_share
        for year in annual.index:
            assert abs(observed[year] / implied[year] - 1) < 0.02, (
                f"{year}: expansion/contraction dollar ratio {observed[year]:.3f} does not "
                f"reconcile with the nrr/grr rows' implied {implied[year]:.3f}")

    def test_gross_retention_rates_stay_below_one(self, plan):
        """GRR and logo retention cannot exceed 100% by definition; only
        NRR can, and the blended plan should, given the Enterprise revenue
        weight."""
        wide = plan.pivot(index="month", columns="layer1_metric", values="plan_value")
        assert (wide["grr"] < 1.0).all()
        assert (wide["logo_retention"] < 1.0).all()
        assert (wide["nrr"] > 1.0).all()


# =====================================================================
# C. Point-in-time safety -- by construction
# =====================================================================

class TestPointInTimeSafety:
    """A plan is set before the period it covers. If this generator could
    read another generator's realized output, variance from plan would be
    circular and every Phase 4 drill-down built on it would be meaningless.
    These checks assert the guarantee structurally rather than statistically.
    """

    def test_generator_takes_only_an_rng(self):
        params = list(inspect.signature(gtm_plan.generate_gtm_plan_targets).parameters)
        assert params == ["rng"], f"unexpected inputs: {params}"

    def test_module_performs_no_file_io(self):
        source = inspect.getsource(gtm_plan)
        for forbidden in ("read_csv", "read_parquet", "open(", "Path(", "data/raw"):
            assert forbidden not in source, f"gtm_plan.py references {forbidden!r}"

    def test_module_imports_nothing_beyond_numpy_pandas_and_config(self):
        source = inspect.getsource(gtm_plan)
        imports = [
            line.strip() for line in source.splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        assert imports == ["import numpy as np", "import pandas as pd", "from . import config"]

    def test_orchestrator_loads_no_prior_batch_output(self):
        from generators import run_batch5

        source = inspect.getsource(run_batch5)
        assert not hasattr(run_batch5, "_load_prior_batches")
        assert "pd.read_csv" not in source

    def test_output_is_reproducible_from_the_seed_alone(self):
        import numpy as np

        first = gtm_plan.generate_gtm_plan_targets(np.random.default_rng(config.SEED + 4000))
        second = gtm_plan.generate_gtm_plan_targets(np.random.default_rng(config.SEED + 4000))
        pd.testing.assert_frame_equal(first, second)


# =====================================================================
# D. Volume / sufficiency
# =====================================================================

class TestVolumeSufficiency:
    def test_full_thirty_six_month_history_per_metric(self, plan):
        """The variance-diagnostic engine needs a complete plan series to
        compute a variance for every Layer-1 metric in every reporting
        period, with no month it has to skip."""
        assert (plan.groupby("layer1_metric").size() == config.N_MONTHS).all()


# =====================================================================
# NOT TESTED HERE -- deferred, deliberately
# =====================================================================
#
# The QA plan's category C (correlational validity) has no entry for this
# table and should not be given a stand-in one. The question that matters --
# whether variance from plan actually surfaces real misses, and whether an
# ±8% threshold picks out the right Layer-1 nodes -- is a property of the
# variance-diagnostic engine, not of the plan values it reads. It is
# answerable only once that engine exists, against the marts, and belongs to
# its own build-time validation.
