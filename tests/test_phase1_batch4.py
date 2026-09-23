"""Validation checks for batch 4 (product_logins), scoped per the
validate-gtm-data skill and the QA plan's test cases
(docs/acme-corp-phase1-data-qa-plan.md).

This batch exists specifically to make the QA plan's health-score edge
case testable: "high-automation, low-login, high-Actions accounts exist
and are not predominantly mis-flagged as at-risk." Most of this file's
correlational-validity tests exist to confirm that cohort is real in the
data, not asserted.

Run: python3 -m pytest tests/test_phase1_batch4.py -v
"""
import pandas as pd
import pytest

from generators import config

DATA_DIR = "data/raw"


@pytest.fixture(scope="module")
def accounts():
    return pd.read_csv(f"{DATA_DIR}/accounts.csv", parse_dates=["signup_date"])


@pytest.fixture(scope="module")
def usage_monthly():
    return pd.read_csv(f"{DATA_DIR}/usage_monthly.csv", parse_dates=["month"])


@pytest.fixture(scope="module")
def subscriptions():
    return pd.read_csv(f"{DATA_DIR}/subscriptions.csv", parse_dates=["start_date", "end_date"])


@pytest.fixture(scope="module")
def logins():
    return pd.read_csv(f"{DATA_DIR}/product_logins.csv", parse_dates=["login_date"])


@pytest.fixture(scope="module")
def churn_date_by_account(subscriptions):
    last_rows = subscriptions.sort_values("start_date").groupby("account_id").last()
    churned = last_rows[last_rows["status"] == "churned"]
    return dict(zip(churned.index, churned["end_date"]))


# =====================================================================
# A. Referential / structural integrity
# =====================================================================

class TestReferentialIntegrity:
    def test_login_account_id_resolves(self, logins, accounts):
        assert logins["account_id"].isin(accounts["account_id"]).all()

    def test_login_id_unique(self, logins):
        assert logins["login_id"].is_unique

    def test_no_login_before_signup(self, logins, accounts):
        merged = logins.merge(accounts[["account_id", "signup_date"]], on="account_id")
        assert (merged["login_date"] >= merged["signup_date"]).all()

    def test_no_login_after_churn(self, logins, churn_date_by_account):
        depart = logins["account_id"].map(churn_date_by_account)
        assert not (depart.notna() & (logins["login_date"] > depart)).any()


# =====================================================================
# B. Distributional realism
# =====================================================================

class TestDistributionalRealism:
    def test_login_rate_roughly_tracks_segment_baseline(self, logins, accounts):
        """Loose sanity check, not a tight benchmark-table check (no cited
        source for login cadence) -- catches a badly broken rate, not
        fine-tunes it. SMB should show the highest per-account rate and
        Enterprise the lowest, matching config.LOGIN_RATE_BASELINE's
        ordering."""
        merged = logins.merge(accounts[["account_id", "segment"]], on="account_id", suffixes=("", "_acct"))
        rate_by_segment = merged.groupby("segment").size() / accounts.groupby("segment").size()
        assert rate_by_segment["SMB"] > rate_by_segment["Enterprise"]

    def test_every_account_has_at_least_some_logins_or_is_very_short_lived(self, logins, accounts, subscriptions):
        """Almost every account should show up at least once -- a
        complete absence of logins for a long-lived account would mean
        the generator's rate collapsed to zero somewhere, not a genuine
        automated-but-healthy pattern (which is low, not zero, per
        LOGIN_RATE_BASELINE's floor)."""
        covered = set(logins["account_id"].unique())
        uncovered = set(accounts["account_id"]) - covered
        assert len(uncovered) / len(accounts) < 0.05


# =====================================================================
# C. Correlational validity -- the "meaningful results" tests
# =====================================================================

class TestCorrelationalValidity:
    def test_login_intensity_independent_of_usage_volume(self, logins, usage_monthly):
        """The core mechanism this batch relies on: login count and usage
        volume must NOT be strongly correlated, or the automated-but-
        healthy cohort (high usage, low logins) couldn't exist -- logins
        would just be usage relabeled."""
        usage_totals = usage_monthly.groupby("account_id")["actions_consumed"].sum()
        login_totals = logins.groupby("account_id").size()
        combined = pd.DataFrame({"usage": usage_totals, "logins": login_totals}).fillna(0)
        corr = combined["usage"].corr(combined["logins"])
        assert abs(corr) < 0.25, f"usage/login correlation is {corr:.2f}, too strong for an independent signal"

    def test_onboarding_window_shows_higher_login_rate(self, logins, accounts):
        merged = logins.merge(accounts[["account_id", "signup_date"]], on="account_id")
        days_since_signup = (merged["login_date"] - merged["signup_date"]).dt.days
        onboarding = merged[days_since_signup <= config.LOGIN_ONBOARDING_DAYS]
        post = merged[days_since_signup > config.LOGIN_ONBOARDING_DAYS]
        n_accounts = accounts["account_id"].nunique()
        onboarding_rate = len(onboarding) / (n_accounts * config.LOGIN_ONBOARDING_DAYS)
        # post-onboarding window is open-ended per account; use a fixed
        # comparison horizon long enough to be a stable estimate
        post_rate = len(post) / (n_accounts * 300)
        assert onboarding_rate > post_rate

    def test_prechurn_accounts_show_lower_login_rate_than_their_own_baseline(self, logins, accounts, churn_date_by_account):
        """Within-account comparison (each churned account vs. its own
        pre-decline-window rate), not a cross-account average against
        never-churned accounts -- the latter is noisy since it mixes in
        unrelated per-account intensity variance. Mirrors the
        prechurn-vs-baseline pattern used for tickets/AM sentiment."""
        signup_by_account = dict(zip(accounts["account_id"], pd.to_datetime(accounts["signup_date"])))
        counts = (
            logins.assign(
                bucket=logins.apply(
                    lambda r: (
                        "prechurn"
                        if r["account_id"] in churn_date_by_account
                        and 0 <= (churn_date_by_account[r["account_id"]] - r["login_date"]).days <= config.DECLINE_MONTHS_BEFORE_CHURN * 30
                        else "other"
                    ),
                    axis=1,
                )
            )
            .groupby(["account_id", "bucket"])
            .size()
            .unstack(fill_value=0)
        )

        lower_count, total = 0, 0
        window_days = config.DECLINE_MONTHS_BEFORE_CHURN * 30
        for account_id, churn_ts in churn_date_by_account.items():
            signup_ts = signup_by_account.get(account_id)
            if signup_ts is None:
                continue
            window_start = churn_ts - pd.Timedelta(days=window_days)
            prechurn_days = max((churn_ts - max(window_start, signup_ts)).days, 0)
            other_days = max((window_start - signup_ts).days, 0)
            if prechurn_days == 0 or other_days == 0 or account_id not in counts.index:
                continue
            n_prechurn = counts.loc[account_id].get("prechurn", 0)
            n_other = counts.loc[account_id].get("other", 0)
            prechurn_rate = n_prechurn / prechurn_days
            other_rate = n_other / other_days
            total += 1
            if prechurn_rate < other_rate:
                lower_count += 1

        assert total > 0
        assert lower_count / total > 0.65, f"only {lower_count}/{total} churned accounts show lower prechurn login rate"

    def test_high_usage_low_login_cohort_exists(self, logins, usage_monthly, accounts):
        """QA plan Test E, the reason this batch exists: 'high-automation,
        low-login, high-Actions accounts exist.' Top-quartile usage,
        bottom-quartile login count."""
        usage_totals = usage_monthly.groupby("account_id")["actions_consumed"].sum()
        login_totals = logins.groupby("account_id").size().reindex(accounts["account_id"], fill_value=0)

        high_usage_cutoff = usage_totals.quantile(0.75)
        low_login_cutoff = login_totals.quantile(0.25)
        high_usage = set(usage_totals[usage_totals >= high_usage_cutoff].index)
        low_login = set(login_totals[login_totals <= low_login_cutoff].index)

        cohort = high_usage & low_login
        assert len(cohort) >= 50, f"only {len(cohort)} high-usage/low-login accounts found"


# =====================================================================
# D. Volume / sufficiency for modeling
# =====================================================================

class TestVolumeSufficiency:
    def test_enough_logins_for_modeling(self, logins):
        assert len(logins) >= 10_000
