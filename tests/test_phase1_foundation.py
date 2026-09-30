"""Validation checks for the foundational Phase 1 batch (users, quota_history,
rep_status_history, market_universe, accounts, account_segment_history).

Scoped per the validate-gtm-data skill and the QA plan's test cases
(docs/acme-corp-phase1-data-qa-plan.md) to what's checkable at this stage --
no opportunities/usage/billing exist yet, so correlational-validity and
volume-sufficiency tests that depend on those (win rate, churn AUC, CAC by
channel, etc.) aren't run here; they belong with the generators that
produce those tables.

Run: python3 -m pytest tests/test_phase1_foundation.py -v
"""
import pandas as pd
import pytest

DATA_DIR = "data/raw"


@pytest.fixture(scope="module")
def users():
    return pd.read_csv(f"{DATA_DIR}/users.csv")


@pytest.fixture(scope="module")
def quota_history():
    return pd.read_csv(f"{DATA_DIR}/quota_history.csv")


@pytest.fixture(scope="module")
def rep_status_history():
    return pd.read_csv(f"{DATA_DIR}/rep_status_history.csv")


@pytest.fixture(scope="module")
def market_universe():
    return pd.read_csv(f"{DATA_DIR}/market_universe.csv")


@pytest.fixture(scope="module")
def accounts():
    return pd.read_csv(f"{DATA_DIR}/accounts.csv")


@pytest.fixture(scope="module")
def segment_history():
    df = pd.read_csv(f"{DATA_DIR}/account_segment_history.csv")
    df["effective_date"] = pd.to_datetime(df["effective_date"])
    return df


# =====================================================================
# A. Referential / structural integrity (QA plan Test A, adapted to this
# batch's tables)
# =====================================================================

class TestReferentialIntegrity:
    def test_accounts_company_id_resolves_to_market_universe(self, accounts, market_universe):
        assert accounts["company_id"].isin(market_universe["company_id"]).all()

    def test_every_account_has_exactly_one_market_universe_row(self, accounts, market_universe):
        mu_customers = market_universe[market_universe["is_customer"]]
        assert set(accounts["account_id"]) == set(mu_customers["account_id"])
        assert mu_customers["company_id"].is_unique

    def test_market_universe_account_id_backlink_consistent(self, accounts, market_universe):
        merged = market_universe[market_universe["is_customer"]].merge(
            accounts[["account_id", "company_id"]], on="account_id", suffixes=("_mu", "_acc")
        )
        assert (merged["company_id_mu"] == merged["company_id_acc"]).all()

    def test_segment_history_account_id_resolves_to_accounts(self, accounts, segment_history):
        assert segment_history["account_id"].isin(accounts["account_id"]).all()

    def test_every_account_has_a_segment_history_row(self, accounts, segment_history):
        assert set(accounts["account_id"]) <= set(segment_history["account_id"])

    def test_segment_history_chronological_non_overlapping_no_gaps(self, segment_history):
        """Each account's rows are strictly increasing in effective_date (no
        duplicate-date rows, no out-of-order rows) -- with one row per
        transition and no explicit end_date, "non-overlapping/no gaps" reduces
        to strict monotonicity per account."""
        bad_accounts = []
        for account_id, grp in segment_history.groupby("account_id"):
            dates = grp.sort_values("effective_date")["effective_date"].tolist()
            if len(dates) != len(set(dates)) or dates != sorted(dates):
                bad_accounts.append(account_id)
        assert not bad_accounts, f"{len(bad_accounts)} accounts have non-chronological/duplicate history rows"

    def test_segment_history_first_row_is_an_initial_trigger(self, segment_history):
        first_rows = segment_history.sort_values("effective_date").groupby("account_id").first()
        assert first_rows["trigger_reason"].isin(["initial_firmographic", "initial_default"]).all()

    def test_segment_history_non_first_rows_are_migration_triggers(self, segment_history):
        sorted_df = segment_history.sort_values(["account_id", "effective_date"])
        non_first = sorted_df.groupby("account_id").apply(lambda g: g.iloc[1:], include_groups=False)
        if len(non_first):
            assert non_first["trigger_reason"].isin(["usage_threshold", "firmographic_rescore"]).all()

    def test_quota_history_rep_id_resolves_to_users(self, users, quota_history):
        assert quota_history["rep_id"].isin(users["rep_id"]).all()

    def test_rep_status_history_rep_id_resolves_to_users(self, users, rep_status_history):
        assert rep_status_history["rep_id"].isin(users["rep_id"]).all()

    def test_every_rep_has_an_initial_active_status_row(self, users, rep_status_history):
        first_rows = rep_status_history.sort_values("effective_date").groupby("rep_id").first()
        assert (first_rows["status"] == "active").all()
        assert set(users["rep_id"]) == set(rep_status_history["rep_id"])


# =====================================================================
# B. Distributional realism (QA plan Test B, scoped to segment mix -- ACV/
# win-rate/NRR/GRR checks need opportunities/billing, not built yet)
# =====================================================================

class TestDistributionalRealism:
    def test_segment_mix_within_build_spec_ranges(self, accounts):
        counts = accounts["segment"].value_counts()
        assert 5_000 <= counts.get("SMB", 0) <= 8_000
        assert 800 <= counts.get("Commercial", 0) <= 1_200
        assert 150 <= counts.get("Enterprise", 0) <= 250

    def test_no_segment_other_than_the_three_named_values(self, accounts):
        assert set(accounts["segment"].unique()) == {"SMB", "Commercial", "Enterprise"}

    def test_rep_headcounts_within_build_spec_ranges(self, users):
        counts = users["rep_type"].value_counts()
        assert 15 <= counts.get("ISR", 0) <= 25
        assert 20 <= counts.get("AE", 0) <= 30
        ae, se = counts.get("AE", 0), counts.get("SE", 0)
        assert abs(se / ae - 1 / 3) < 0.05

    def test_am_book_sizes_plausible(self, users):
        am_comm = users[users["rep_type"] == "AM-Commercial"]["book_size"]
        am_ent = users[users["rep_type"] == "AM-Enterprise"]["book_size"]
        assert am_comm.between(100, 300).all()
        assert am_ent.between(8, 32).all()


# =====================================================================
# Rep compensation (QA plan, "Rep compensation and fully-loaded cost"):
# annual_ote_usd / fully_loaded_annual_cost_usd on users.csv
# =====================================================================

class TestRepCompensation:
    def test_comp_columns_present_and_positive(self, users):
        assert {"annual_ote_usd", "fully_loaded_annual_cost_usd"} <= set(users.columns)
        assert users["annual_ote_usd"].notna().all() and (users["annual_ote_usd"] > 0).all()
        assert users["fully_loaded_annual_cost_usd"].notna().all()

    def test_ote_inside_rep_type_band(self, users):
        from generators import config
        for rep_type, (lo, hi) in config.REP_OTE_BAND.items():
            ote = users.loc[users["rep_type"] == rep_type, "annual_ote_usd"]
            assert len(ote) > 0 and ote.between(lo, hi).all(), rep_type

    def test_fully_loaded_cost_is_ote_times_documented_loading(self, users):
        from generators import config
        load = 1 + config.REP_LOADING_BENEFITS_TAX + config.REP_LOADING_MANAGEMENT_OPS \
            + users["rep_type"].map(config.REP_LOADING_TOOLING_TE)
        assert ((users["fully_loaded_annual_cost_usd"] - users["annual_ote_usd"] * load).abs() <= 1.0).all()

    def test_role_ordering_reflects_real_comp_structure(self, users):
        mean = users.groupby("rep_type")["annual_ote_usd"].mean()
        assert mean["AE"] > mean["SE"] > mean["ISR"]
        assert mean["AM-Enterprise"] > mean["AM-Commercial"]
        assert mean["AE"] > mean["AM-Enterprise"]

    def test_ote_is_a_function_of_seniority_not_independent_noise(self, users):
        """Within a rep_type, OTE rises with tenure (the band-position driver).
        Pooled Spearman across the roles that have tenure spread must be
        clearly positive; a column drawn independently of tenure would sit
        near zero."""
        from generators import config
        u = users.copy()
        u["tenure_years"] = (pd.Timestamp(config.SIM_END) - pd.to_datetime(u["hire_date"])).dt.days / 365.25
        u["ote_position"] = u.groupby("rep_type")["annual_ote_usd"].transform(
            lambda s: (s - s.mean()) / s.std(ddof=0))
        rho = u["tenure_years"].rank().corr(u["ote_position"].rank())
        assert rho > 0.4, rho

    def test_am_ote_rises_with_book_size(self, users):
        am = users[users["rep_type"] == "AM-Enterprise"]
        assert am["book_size"].corr(am["annual_ote_usd"], method="spearman") > 0

    def test_comp_uses_independent_rng_stream(self):
        """Adding compensation must not consume a single draw from the shared
        generator: the state after generate_reps is identical whether or not
        _generate_rep_compensation runs."""
        import numpy as np
        from generators import reps as reps_mod

        def next_draw(patch_comp):
            rng = np.random.default_rng(42)
            original = reps_mod._generate_rep_compensation
            if patch_comp:
                reps_mod._generate_rep_compensation = lambda users_df, quota_df: users_df
            try:
                reps_mod.generate_reps(rng, 5, 10)
            finally:
                reps_mod._generate_rep_compensation = original
            return rng.random()

        assert next_draw(False) == next_draw(True)

    def test_comp_generation_is_deterministic(self):
        import numpy as np
        from generators import reps as reps_mod
        a = reps_mod.generate_reps(np.random.default_rng(42), 5, 10)[0]
        b = reps_mod.generate_reps(np.random.default_rng(42), 5, 10)[0]
        pd.testing.assert_frame_equal(a, b)


# =====================================================================
# E. Edge-case existence (QA plan Test E, the checks applicable pre-usage/
# billing)
# =====================================================================

class TestEdgeCaseExistence:
    def test_both_migration_trigger_reasons_fire_at_non_trivial_frequency(self, segment_history):
        counts = segment_history["trigger_reason"].value_counts()
        assert counts.get("usage_threshold", 0) >= 50
        assert counts.get("firmographic_rescore", 0) >= 50

    def test_no_segment_downgrades_anywhere(self, segment_history):
        """No account's segment sequence ever moves backward (Enterprise -> Commercial/SMB,
        or Commercial -> SMB) across its history rows."""
        rank = {"SMB": 0, "Commercial": 1, "Enterprise": 2}
        bad_accounts = []
        for account_id, grp in segment_history.groupby("account_id"):
            ranks = grp.sort_values("effective_date")["segment"].map(rank).tolist()
            if ranks != sorted(ranks):
                bad_accounts.append(account_id)
        assert not bad_accounts, f"{len(bad_accounts)} accounts show a segment downgrade"

    def test_no_skip_level_migration(self, segment_history):
        """An account whose entry segment is SMB must pass through Commercial
        before ever reaching Enterprise (no SMB -> Enterprise direct row)."""
        bad_accounts = []
        for account_id, grp in segment_history.groupby("account_id"):
            segs = grp.sort_values("effective_date")["segment"].tolist()
            if segs[0] == "SMB" and "Enterprise" in segs:
                comm_pos = segs.index("Commercial") if "Commercial" in segs else None
                ent_pos = segs.index("Enterprise")
                if comm_pos is None or comm_pos > ent_pos:
                    bad_accounts.append(account_id)
        assert not bad_accounts, f"{len(bad_accounts)} accounts skip-level migrated"

    def test_market_universe_non_customer_volume_10_to_50x(self, market_universe):
        n_customers = market_universe["is_customer"].sum()
        n_non_customers = (~market_universe["is_customer"]).sum()
        ratio = n_non_customers / n_customers
        assert 10 <= ratio <= 50, f"non-customer:customer ratio is {ratio:.1f}x"

    def test_some_reps_depart_mid_simulation(self, rep_status_history):
        assert (rep_status_history["status"] == "departed").sum() >= 1

    def test_migrations_take_effect_on_month_start(self, segment_history):
        """No proration -- every migration effective_date (non-initial rows) is the 1st of a month."""
        sorted_df = segment_history.sort_values(["account_id", "effective_date"])
        non_first = sorted_df.groupby("account_id").apply(lambda g: g.iloc[1:], include_groups=False)
        if len(non_first):
            assert (non_first["effective_date"].dt.day == 1).all()
