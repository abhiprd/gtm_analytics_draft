"""Validation checks for batch 11 (lead_scoring_history), scoped per the
validate-gtm-data skill and the QA plan's test cases
(docs/acme-corp-phase1-data-qa-plan.md).

This batch fills the raw-data gap fact_leads.sql's own header comment names
("Point-in-time scoring belongs to lead_scoring_history (not yet
generated)") and Wave 7's "Lead/segmentation scoring -- model validation &
drift detection" artifact (build spec Section 8, item #11) is blocked on. It
reads market_universe.csv and leads.csv and writes neither back --
lead_scoring_history is delivered as one new event-grain table (score_id
grain, lead_id FK), so every correlational test here is checking whether the
new scoring events line up sensibly with data that was already fixed by
earlier batches, not whether this batch quietly changed them.

Originally staged as batch 10; renumbered to 11 after a sibling batch
built concurrently on this branch claimed batch 10 first for
experiments_registry/experiment_assignment -- see run_batch11.py's
module docstring.

Two things shape this batch's test profile specifically:

  * The scored value is a pure function of company_id's firmographics
    (employee band / industry / region, via market_universe) plus fresh
    noise -- never of is_converted/converted_date. The no-leakage tests
    below check that no scoring event on a converting lead lands on or
    after its converted_date, and separately (as a *post-hoc* check the
    generator itself never performs) that the resulting score still
    correlates with eventual conversion through the shared firmographic
    driver -- the same "mildly toward higher icp_fit_score" selection
    accounts.py already applies when choosing which companies convert.
  * `model_version` is a real, dateable change (region term folded into
    compute_fit_score() on MODEL_CUTOVER_DATE), not decoration -- the
    distributional tests below check that v2's scores are measurably more
    region-sensitive than v1's, not just that two label values exist.

Run: python3 -m pytest tests/test_phase1_batch11.py -v
"""
import numpy as np
import pandas as pd
import pytest

from generators.firmographics import COMMERCIAL_FIT_THRESHOLD, ENTERPRISE_FIT_THRESHOLD
from generators.lead_scoring import (
    MAX_ACTIVE_SCORING_DAYS,
    MODEL_CUTOVER_DATE,
    MODEL_VERSION_V1,
    MODEL_VERSION_V2,
)

DATA_DIR = "data/raw"


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture(scope="module")
def market_universe():
    return pd.read_csv(f"{DATA_DIR}/market_universe.csv")


@pytest.fixture(scope="module")
def leads():
    return pd.read_csv(f"{DATA_DIR}/leads.csv", parse_dates=["created_date", "converted_date"])


@pytest.fixture(scope="module")
def history():
    df = pd.read_csv(f"{DATA_DIR}/lead_scoring_history.csv", parse_dates=["scored_at"])
    return df


# =====================================================================
# A. Referential / structural integrity
# =====================================================================

class TestStructuralIntegrity:
    def test_score_id_is_unique(self, history):
        assert history["score_id"].is_unique

    def test_every_lead_id_resolves_to_leads(self, history, leads):
        assert set(history["lead_id"]) <= set(leads["lead_id"])

    def test_every_lead_has_at_least_one_scoring_event(self, history, leads):
        assert set(leads["lead_id"]) == set(history["lead_id"])

    def test_no_shared_timestamps_within_a_lead(self, history):
        assert not history.duplicated(["lead_id", "scored_at"]).any()

    def test_scored_at_is_chronological_within_a_lead(self, history):
        for _, group in history.groupby("lead_id"):
            dates = group.sort_values("score_id")["scored_at"].to_numpy()
            assert (dates[:-1] <= dates[1:]).all()

    def test_predicted_fit_score_within_bounds(self, history):
        assert history["predicted_fit_score"].between(0, 100).all()

    def test_no_negative_or_null_components_where_expected(self, history):
        assert history["employee_band_component"].notna().all()
        assert history["industry_component"].notna().all()
        assert history["noise_component"].notna().all()

    def test_model_version_is_one_of_the_two_declared_values(self, history):
        assert set(history["model_version"]) == {MODEL_VERSION_V1, MODEL_VERSION_V2}

    def test_predicted_segment_is_a_closed_vocabulary(self, history):
        assert set(history["predicted_segment"]) <= {"SMB", "Commercial", "Enterprise"}

    def test_region_component_is_null_iff_v1(self, history):
        is_v1 = history["model_version"] == MODEL_VERSION_V1
        assert (history["region_component"].isna() == is_v1).all()

    def test_model_version_matches_scored_at_relative_to_cutover(self, history):
        is_v2_by_date = history["scored_at"] >= MODEL_CUTOVER_DATE
        is_v2_by_label = history["model_version"] == MODEL_VERSION_V2
        assert (is_v2_by_date == is_v2_by_label).all()

    def test_every_scoring_event_is_on_or_after_its_leads_created_date(self, history, leads):
        merged = history.merge(leads[["lead_id", "created_date"]], on="lead_id")
        assert (merged["scored_at"] >= merged["created_date"]).all()


# =====================================================================
# No-leakage / point-in-time safety
# =====================================================================

class TestNoLeakage:
    def test_no_scoring_event_on_a_converting_lead_reaches_its_converted_date(self, history, leads):
        converted = leads.loc[leads["is_converted"], ["lead_id", "converted_date"]]
        merged = history.merge(converted, on="lead_id", how="inner")
        assert len(merged) > 0, "no converting leads carried into the merge -- fixture issue"
        assert (merged["scored_at"] < merged["converted_date"]).all()

    def test_non_converting_leads_stop_being_scored_within_the_cold_window(self, history, leads):
        """A non-converting lead's scoring window is capped at
        MAX_ACTIVE_SCORING_DAYS from created_date (or the observation
        window's end, whichever is sooner) -- it should never still be
        actively scored long after that."""
        non_converted = leads.loc[~leads["is_converted"], ["lead_id", "created_date"]]
        merged = history.merge(non_converted, on="lead_id", how="inner")
        age_days = (merged["scored_at"] - merged["created_date"]).dt.days
        assert age_days.max() <= MAX_ACTIVE_SCORING_DAYS + 1


# =====================================================================
# B. Distributional realism
# =====================================================================

class TestDistributionalRealism:
    def test_both_model_versions_actually_occur_at_non_trivial_volume(self, history):
        counts = history["model_version"].value_counts()
        assert counts[MODEL_VERSION_V1] > 1000
        assert counts[MODEL_VERSION_V2] > 1000

    def test_all_three_predicted_segments_occur(self, history):
        assert set(history["predicted_segment"]) == {"SMB", "Commercial", "Enterprise"}

    def test_v2_scores_are_measurably_more_region_sensitive_than_v1(self, history, leads, market_universe):
        """The genuine, dateable model change: v2 folds the region modifier
        into the score, v1 doesn't. The spread of mean predicted_fit_score
        across regions should be visibly wider under v2 than under v1 --
        not just present as two differently-labeled rows."""
        region_by_company = dict(zip(market_universe["company_id"], market_universe["region"]))
        lead_region = leads.set_index("lead_id")["company_id"].map(region_by_company)
        h = history.copy()
        h["region"] = h["lead_id"].map(lead_region)

        v1_means = h[h["model_version"] == MODEL_VERSION_V1].groupby("region")["predicted_fit_score"].mean()
        v2_means = h[h["model_version"] == MODEL_VERSION_V2].groupby("region")["predicted_fit_score"].mean()

        v1_spread = v1_means.max() - v1_means.min()
        v2_spread = v2_means.max() - v2_means.min()
        assert v2_spread > v1_spread + 2.0, (
            f"v2 region spread ({v2_spread:.1f}) not measurably wider than v1's ({v1_spread:.1f})")

    def test_predicted_fit_score_is_not_degenerate(self, history):
        """Guard against an accidental constant/near-constant column --
        real scoring noise plus firmographic variance should produce a
        healthy spread, not everything clustered on one value."""
        assert history["predicted_fit_score"].std() > 10.0


# =====================================================================
# C. Correlational validity -- the "meaningful results" tests
# =====================================================================

class TestCorrelationalValidity:
    def test_score_correlates_with_eventual_conversion_without_being_a_perfect_separator(
        self, history, leads
    ):
        """Checked here, never used by the generator: because accounts.py
        already selects converting companies with a mild tilt toward higher
        icp_fit_score within their tier, a lead's re-derived firmographic
        score should run measurably higher, on average, for leads that
        eventually convert -- without collapsing onto is_converted (the
        generator never reads it when computing the score)."""
        last_event = history.sort_values("scored_at").groupby("lead_id").tail(1)
        joined = last_event.merge(leads[["lead_id", "is_converted"]], on="lead_id")

        converted_scores = joined.loc[joined["is_converted"], "predicted_fit_score"]
        non_converted_scores = joined.loc[~joined["is_converted"], "predicted_fit_score"]

        assert converted_scores.mean() > non_converted_scores.mean(), (
            "converting leads' scores are not measurably higher than non-converting leads'")

        # Not a perfect separator: substantial overlap must remain on both sides.
        threshold = non_converted_scores.median()
        share_converted_below_median_noncvt = (converted_scores < threshold).mean()
        assert 0.15 < share_converted_below_median_noncvt < 0.85, (
            "score looks like it collapsed onto the outcome rather than "
            f"correlating with it ({share_converted_below_median_noncvt:.2%} of converted "
            "leads fall below the non-converted median)")

    def test_predicted_segment_agrees_directionally_with_icp_fit_score(self, history, leads, market_universe):
        """A lead whose company already carries a high market_universe
        icp_fit_score should be classified Enterprise/Commercial more often
        than one from a low-fit company -- the re-derived score should
        track the same underlying firmographic signal, not diverge from it."""
        region_by_company = market_universe.set_index("company_id")["icp_fit_score"]
        h = history.copy()
        h["icp_fit_score"] = h["lead_id"].map(leads.set_index("lead_id")["company_id"]).map(region_by_company)

        high_fit = h[h["icp_fit_score"] >= ENTERPRISE_FIT_THRESHOLD]
        low_fit = h[h["icp_fit_score"] < COMMERCIAL_FIT_THRESHOLD]

        high_fit_smb_rate = (high_fit["predicted_segment"] == "SMB").mean()
        low_fit_smb_rate = (low_fit["predicted_segment"] == "SMB").mean()
        assert high_fit_smb_rate < low_fit_smb_rate

    def test_noise_component_is_not_degenerate(self, history):
        """Fresh noise redrawn at each scoring event -- not a fixed offset
        repeated verbatim across events for the same lead."""
        multi_event_leads = history.groupby("lead_id").filter(lambda g: len(g) > 1)
        assert multi_event_leads.groupby("lead_id")["noise_component"].nunique().gt(1).any()


# =====================================================================
# D. Volume / sufficiency
# =====================================================================

class TestVolumeSufficiency:
    def test_enough_total_scoring_events_for_a_drift_analysis(self, history):
        assert len(history) > 50_000

    def test_enough_leads_carry_multiple_scoring_events(self, history):
        """A drift/model-validation artifact needs within-lead re-scoring,
        not just one snapshot per lead."""
        events_per_lead = history.groupby("lead_id").size()
        assert (events_per_lead > 1).sum() > 10_000

    def test_enough_volume_on_both_sides_of_the_model_cutover(self, history):
        counts = history["model_version"].value_counts()
        assert min(counts[MODEL_VERSION_V1], counts[MODEL_VERSION_V2]) > 20_000


# =====================================================================
# E. Edge-case-specific existence checks
# =====================================================================

class TestEdgeCases:
    def test_leads_whose_active_window_straddles_the_cutover_show_both_versions(self, history):
        """At least some leads should carry scoring events under both
        model versions within their own history -- a real re-scored
        population, not two disjoint eras with no overlap at the lead
        level."""
        version_counts = history.groupby("lead_id")["model_version"].nunique()
        assert (version_counts == 2).sum() > 100

    def test_converting_leads_with_a_short_lead_to_signup_gap_still_get_scored(self, history, leads):
        """Even a lead converting within a day or two of creation must
        resolve at least one valid pre-outcome scoring day."""
        converted = leads[leads["is_converted"]].copy()
        converted["gap_days"] = (converted["converted_date"] - converted["created_date"]).dt.days
        short_gap = converted[converted["gap_days"] <= 2]
        assert len(short_gap) > 0, "fixture has no short-gap converting leads to check"
        assert set(short_gap["lead_id"]) <= set(history["lead_id"])

    def test_non_converting_leads_with_a_long_life_get_multiple_scoring_events(self, history, leads):
        non_cvt = leads[~leads["is_converted"]]
        events_per_lead = history[history["lead_id"].isin(non_cvt["lead_id"])].groupby("lead_id").size()
        assert (events_per_lead >= 5).any()


# =====================================================================
# Reproducibility
# =====================================================================

class TestReproducibility:
    def test_output_is_reproducible_from_the_seed_alone(self, market_universe, leads):
        from generators import run_batch11
        from generators.lead_scoring import generate_lead_scoring_history

        def build():
            rng = np.random.default_rng(run_batch11.BATCH11_SEED)
            return generate_lead_scoring_history(rng, leads, market_universe).reset_index(drop=True)

        h1 = build()
        h2 = build()
        pd.testing.assert_frame_equal(h1, h2)


# =====================================================================
# NOT TESTED HERE -- deferred, deliberately
# =====================================================================
#
# Whether a real model-validation/drift-detection artifact built on this
# table would actually flag the v1->v2 cutover as a calibration break, and
# what drift threshold is appropriate for the unchanged-model-over-time
# question, are properties of that future artifact's own build-time
# validation (docs/acme-corp-analytics-methods.md's "Segment/lead scoring
# model" section, still TBD) -- not of this raw data. What this suite
# guarantees is that the artifact has something real to work on: every lead
# scored at least once with no outcome leakage, a genuine and measurable
# region-sensitivity change across the two model versions, and a real
# (not fabricated) correlation between the re-derived score and eventual
# conversion.
