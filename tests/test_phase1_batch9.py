"""Validation checks for batch 9 (the territory dimension), scoped per the
validate-gtm-data skill and the QA plan's test cases
(docs/acme-corp-phase1-data-qa-plan.md).

This batch fills the territory gap dim_market_universe.sql and
mart_tam_whitespace.sql both named explicitly in their own header comments,
the prerequisite for Wave 5's "Territory / account coverage & routing"
artifact (build spec Section 8, item #21). It reads market_universe.csv and
users.csv and writes neither back -- territory is delivered as two new
lookup tables (company_territory.csv, rep_territory.csv), so every
correlational test here is checking whether the *new* territory assignment
lines up sensibly with data that was already fixed by earlier batches, not
whether this batch quietly changed them.

Two things shape this batch's test profile specifically:

  * Territory is a deterministic sub-division of `region`
    (generators/territories.py's design decision) -- the referential tests
    below check that mapping holds losslessly in both directions, not just
    that the schema's five values are used.
  * Rep territory headcount is *deliberately* imbalanced against each
    territory's company-population share (own resolved decision,
    documented in territories.py) -- the distributional/correlational tests
    below assert that real imbalance is present, the same "independently-
    random / artificially uniform columns are a bug" bar this project holds
    every other outcome column to, applied here to a structural assignment.

Run: python3 -m pytest tests/test_phase1_batch9.py -v
"""
import numpy as np
import pandas as pd
import pytest

from generators import config
from generators.territories import (
    REGION_FOR_TERRITORY,
    REP_TERRITORY_TARGET_COUNTS,
    TERRITORIES,
    TERRITORY_ELIGIBLE_REP_TYPES,
)

DATA_DIR = "data/raw"


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture(scope="module")
def market_universe():
    return pd.read_csv(f"{DATA_DIR}/market_universe.csv")


@pytest.fixture(scope="module")
def users():
    return pd.read_csv(f"{DATA_DIR}/users.csv", parse_dates=["hire_date"])


@pytest.fixture(scope="module")
def accounts():
    return pd.read_csv(f"{DATA_DIR}/accounts.csv")


@pytest.fixture(scope="module")
def company_territory():
    return pd.read_csv(f"{DATA_DIR}/company_territory.csv")


@pytest.fixture(scope="module")
def rep_territory():
    return pd.read_csv(f"{DATA_DIR}/rep_territory.csv")


# =====================================================================
# A. Referential / structural integrity
# =====================================================================

class TestStructuralIntegrity:
    def test_company_territory_has_exactly_one_row_per_market_universe_company(
        self, company_territory, market_universe
    ):
        assert company_territory["company_id"].is_unique
        assert set(company_territory["company_id"]) == set(market_universe["company_id"])

    def test_rep_territory_has_exactly_one_row_per_isr_ae_rep(self, rep_territory, users):
        assert rep_territory["rep_id"].is_unique
        eligible = set(users.loc[users["rep_type"].isin(TERRITORY_ELIGIBLE_REP_TYPES), "rep_id"])
        assert set(rep_territory["rep_id"]) == eligible

    def test_no_se_or_am_rep_appears_in_rep_territory(self, rep_territory, users):
        excluded_types = {"SE", "AM-Commercial", "AM-Enterprise"}
        excluded_ids = set(users.loc[users["rep_type"].isin(excluded_types), "rep_id"])
        assert not (set(rep_territory["rep_id"]) & excluded_ids)

    def test_territory_values_are_within_the_declared_set(self, company_territory, rep_territory):
        assert set(company_territory["territory"]) <= set(TERRITORIES)
        assert set(rep_territory["territory"]) <= set(TERRITORIES)

    def test_no_nulls_anywhere(self, company_territory, rep_territory):
        assert not company_territory.isna().any().any()
        assert not rep_territory.isna().any().any()

    def test_every_companys_territory_maps_back_to_its_own_region(
        self, company_territory, market_universe
    ):
        """Territory is a deterministic sub-division of region (never
        independently random) -- every row's territory must resolve to
        exactly the region that same company already carries."""
        merged = company_territory.merge(market_universe[["company_id", "region"]], on="company_id")
        implied_region = merged["territory"].map(REGION_FOR_TERRITORY)
        assert (implied_region == merged["region"]).all()

    def test_na_east_and_na_west_only_ever_appear_on_north_america_companies(
        self, company_territory, market_universe
    ):
        merged = company_territory.merge(market_universe[["company_id", "region"]], on="company_id")
        na_territories = merged[merged["territory"].isin(["NA-East", "NA-West"])]
        assert (na_territories["region"] == "North America").all()

    def test_every_account_resolves_a_territory_via_its_company_id(self, accounts, company_territory):
        """accounts.company_id links to market_universe (build spec Section
        5) -- every account must be able to resolve a territory through
        that same join, since dim_accounts is expected to expose it."""
        assert set(accounts["company_id"]) <= set(company_territory["company_id"])


# =====================================================================
# B. Distributional realism
# =====================================================================

class TestDistributionalRealism:
    def test_every_declared_territory_actually_occurs_in_company_territory(self, company_territory):
        assert set(company_territory["territory"]) == set(TERRITORIES)

    def test_every_declared_territory_actually_occurs_in_rep_territory(self, rep_territory):
        assert set(rep_territory["territory"]) == set(TERRITORIES)

    def test_company_territory_sizes_are_grounded_against_region_shares(
        self, company_territory, market_universe
    ):
        """North America's overall population share (REGION_PROBS ~55%)
        should land close to NA-East + NA-West combined; EMEA/APAC/LATAM
        should each land close to their own single-territory share."""
        region_share = market_universe["region"].value_counts(normalize=True)
        territory_share = company_territory["territory"].value_counts(normalize=True)

        na_combined = territory_share.get("NA-East", 0) + territory_share.get("NA-West", 0)
        assert abs(na_combined - region_share["North America"]) < 0.03

        for territory, region in [("EMEA", "EMEA"), ("APAC", "APAC"), ("LATAM", "LATAM")]:
            assert abs(territory_share.get(territory, 0) - region_share[region]) < 0.02

    def test_na_split_is_uneven_not_a_coin_flip(self, company_territory, market_universe):
        """NA_TERRITORY_SPLIT is a deliberate 56/44 weighting, not 50/50 --
        the split should be measurably off-center, within its grounded
        range, not exactly even."""
        merged = company_territory.merge(market_universe[["company_id", "region"]], on="company_id")
        na = merged[merged["region"] == "North America"]
        east_share = (na["territory"] == "NA-East").mean()
        assert 0.52 <= east_share <= 0.60, f"NA-East share {east_share:.2%} not near the grounded 56% target"

    def test_rep_territory_counts_match_the_grounded_targets_exactly(self, rep_territory, users):
        for (rep_type, territory), expected in REP_TERRITORY_TARGET_COUNTS.items():
            rep_ids = set(users.loc[users["rep_type"] == rep_type, "rep_id"])
            actual = rep_territory[
                rep_territory["rep_id"].isin(rep_ids) & (rep_territory["territory"] == territory)
            ]
            assert len(actual) == expected, (
                f"({rep_type}, {territory}) expected {expected} reps, got {len(actual)}")

    def test_rep_territory_sizes_are_not_artificially_uniform(self, rep_territory):
        """Real territories carry real imbalance -- reject a dataset where
        every territory happens to get the same headcount (123200/5 company
        rows split five equal ways would be the 'uniform' failure mode this
        guards against)."""
        counts = rep_territory["territory"].value_counts()
        assert counts.max() / counts.min() >= 3.0, (
            f"rep headcount spread too tight to be real imbalance: {dict(counts)}")


# =====================================================================
# C. Correlational validity -- the "meaningful results" tests
# =====================================================================

class TestCorrelationalValidity:
    def test_apac_is_measurably_under_resourced_relative_to_its_market_share(
        self, company_territory, rep_territory
    ):
        """The deliberate coverage-gap finding this batch bakes in (own
        resolved decision, territories.py's module docstring): APAC's
        rep-headcount share should sit well below its company-population
        share -- a genuine under-coverage signal a future territory/routing
        diagnostic should be able to detect, not an artifact of noise."""
        company_share = company_territory["territory"].value_counts(normalize=True)
        rep_share = rep_territory["territory"].value_counts(normalize=True)
        ratio = rep_share["APAC"] / company_share["APAC"]
        assert ratio < 0.75, f"APAC rep-share/company-share ratio {ratio:.2f} not clearly under-resourced"

    def test_not_every_territory_is_proportionally_staffed(self, company_territory, rep_territory):
        """At least one territory's rep-share/company-share ratio must sit
        outside a tight band around 1.0 -- if every territory came out
        proportionally staffed, there would be nothing for a coverage/
        routing diagnostic to find."""
        company_share = company_territory["territory"].value_counts(normalize=True)
        rep_share = rep_territory["territory"].value_counts(normalize=True)
        ratios = {t: rep_share[t] / company_share[t] for t in TERRITORIES}
        assert any(r < 0.85 or r > 1.15 for r in ratios.values()), ratios

    def test_each_territory_carries_both_isr_and_ae_reps(self, rep_territory, users):
        """Design decision: a territory covers both Commercial (ISR) and
        Enterprise (AE) new-business motion, not one or the other."""
        merged = rep_territory.merge(users[["rep_id", "rep_type"]], on="rep_id")
        for territory in TERRITORIES:
            types_present = set(merged.loc[merged["territory"] == territory, "rep_type"])
            assert types_present == {"ISR", "AE"}, f"{territory} carries {types_present}, expected both ISR and AE"


# =====================================================================
# D. Volume / sufficiency
# =====================================================================

class TestVolumeSufficiency:
    def test_every_territory_has_a_large_enough_company_population_for_tam_math(
        self, company_territory
    ):
        counts = company_territory["territory"].value_counts()
        assert (counts >= 5_000).all(), f"a territory's company volume is too thin for TAM/whitespace math: {dict(counts)}"

    def test_every_territory_has_at_least_one_customer_account(self, accounts, company_territory):
        merged = accounts.merge(company_territory, on="company_id", how="left")
        counts = merged["territory"].value_counts()
        assert set(counts.index) == set(TERRITORIES)
        assert (counts >= 1).all()

    def test_every_territory_has_at_least_two_account_owning_reps(self, rep_territory):
        counts = rep_territory["territory"].value_counts()
        assert (counts >= 2).all(), f"a territory has too few reps to be a real coverage unit: {dict(counts)}"


# =====================================================================
# E. Edge-case-specific existence checks
# =====================================================================

class TestEdgeCases:
    def test_both_na_sub_territories_exist_as_distinct_values(self, company_territory):
        assert "NA-East" in set(company_territory["territory"])
        assert "NA-West" in set(company_territory["territory"])

    def test_non_na_regions_are_not_further_subdivided(self, company_territory, market_universe):
        """EMEA/APAC/LATAM each map to exactly one territory value -- only
        North America is split."""
        merged = company_territory.merge(market_universe[["company_id", "region"]], on="company_id")
        for region in ["EMEA", "APAC", "LATAM"]:
            territories_seen = set(merged.loc[merged["region"] == region, "territory"])
            assert territories_seen == {region}

    def test_smb_accounts_appear_in_every_territory(self, accounts, company_territory):
        """Territory is orthogonal to segment (same invariant as
        channel/segment) -- SMB accounts, which carry no rep at all, must
        still resolve a territory through company_id like every other
        segment, and shouldn't be concentrated in only one or two."""
        smb = accounts[accounts["segment"] == "SMB"]
        merged = smb.merge(company_territory, on="company_id", how="left")
        assert merged["territory"].notna().all()
        assert merged["territory"].nunique() == len(TERRITORIES)


# =====================================================================
# Reproducibility
# =====================================================================

class TestReproducibility:
    def test_output_is_reproducible_from_the_seed_alone(self, market_universe, users):
        from generators import run_batch9
        from generators.territories import assign_company_territory, assign_rep_territory

        def build():
            rng = np.random.default_rng(run_batch9.BATCH9_SEED)
            ct = assign_company_territory(rng, market_universe["region"].to_numpy())
            rt = assign_rep_territory(rng, users)
            return pd.Series(ct).reset_index(drop=True), rt.reset_index(drop=True)

        ct1, rt1 = build()
        ct2, rt2 = build()
        pd.testing.assert_series_equal(ct1, ct2)
        pd.testing.assert_frame_equal(rt1, rt2)


# =====================================================================
# NOT TESTED HERE -- deferred, deliberately
# =====================================================================
#
# Whether territory-level whitespace/ICP-fit concentration actually produces
# a usable prioritization for Wave 5's routing artifact, and whether the
# APAC under-coverage signal this batch bakes in maps to a real rebalancing
# recommendation, are properties of that future artifact's own build-time
# validation, not of this raw data. What this suite guarantees is that the
# artifact has something real to work on: every company and every
# account-owning rep carries a territory that traces losslessly back to
# region, territory sizes are grounded against the region distribution
# rather than picked, and rep coverage is genuinely (not proportionally)
# imbalanced across territories.
