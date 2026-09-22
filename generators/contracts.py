"""Shared contract/usage-intensity substrate for opportunities, usage, and
billing.

This exists so those three generators don't each independently invent an
account's usage level, committed volume, or churn timing -- if they did,
`opportunities.amount`, `usage_monthly`'s Actions, and `billing`'s committed
volume would be three unrelated random numbers instead of three views onto
the same account. Each account gets one latent `usage_scale` (build spec
Section 4's "causal wiring" rule applied at the account level), and this
module derives committed volume, contract terms, and the renewal/churn
outcome plan from it.

Outcome pre-commitment pattern (churn/retain, and win/loss in opportunities.py
use the same idea): the *decision* (retained vs. churned at each renewal
boundary) is drawn first, directly from the QA plan's benchmark GRR/logo-
retention targets (config.ANNUAL_CHURN_RATE), the same way batch 1 pre-
committed migration dates before usage existed. Downstream generators then
draw *supporting* detail (usage decline, stage stall, loss_reason) as a
function of that pre-committed outcome. This guarantees the target rates
land exactly on the benchmark table while still giving every downstream
diagnostic artifact a real, learnable relationship between drivers and
outcomes -- not the reverse (computing the outcome forward from independently
random features), which can't hit an exact target rate and is no more
"causal" in any way a validation test can tell the difference.
"""
import numpy as np
import pandas as pd

from . import config


def _account_usage_scale(rng: np.random.Generator, n: int) -> np.ndarray:
    """Per-account latent usage-intensity multiplier. Lognormal, mean ~1,
    clipped so no account is absurdly far from its segment baseline."""
    scale = rng.lognormal(mean=0.0, sigma=0.35, size=n)
    return np.clip(scale, 0.4, 2.5)


def _contract_start_dates(segment_history: pd.DataFrame) -> pd.Series:
    """Per account, the effective_date of the *last* segment_history row --
    i.e. when the account entered its current segment (build spec Section 2:
    migration resets the contract, opening a new renewal/expansion
    opportunity 'to formalize the bigger contract')."""
    last_rows = segment_history.sort_values("effective_date").groupby("account_id").last()
    return last_rows["effective_date"]


def build_contract_plan(rng: np.random.Generator, accounts: pd.DataFrame, segment_history: pd.DataFrame):
    """Returns (contract_plan_df, renewal_events_df).

    contract_plan_df: one row per account -- usage_scale, committed_actions_monthly
    (initial, at contract_start), contract_start_date, term_months (NaN for
    SMB, which has no contract), churn_date (nullable, all segments),
    is_censored.

    renewal_events_df: one row per Commercial/Enterprise renewal boundary
    actually reached (in order, stopping at churn) -- outcome in
    {retained_flat, retained_contraction, retained_expansion, churned},
    committed_actions_monthly (the new committed level as of that boundary).
    """
    n = len(accounts)
    usage_scale = _account_usage_scale(rng, n)
    baseline = accounts["segment"].map(config.USAGE_BASELINE_ACTIONS).to_numpy()
    committed_initial = baseline * config.COMMITTED_VOLUME_FACTOR * usage_scale

    plan = pd.DataFrame({
        "account_id": accounts["account_id"].to_numpy(),
        "segment": accounts["segment"].to_numpy(),
        "signup_date": accounts["signup_date"].to_numpy(),
        "usage_scale": usage_scale,
        "committed_actions_monthly": committed_initial,
    }).set_index("account_id")

    contract_start = _contract_start_dates(segment_history)
    plan["contract_start_date"] = pd.NaT
    plan.loc[contract_start.index, "contract_start_date"] = pd.to_datetime(contract_start)

    plan["term_months"] = np.nan
    is_commercial = plan["segment"] == "Commercial"
    is_enterprise = plan["segment"] == "Enterprise"
    plan.loc[is_commercial, "term_months"] = config.COMMERCIAL_TERM_MONTHS
    n_ent = int(is_enterprise.sum())
    ent_terms = rng.choice(
        list(config.ENTERPRISE_TERM_MONTHS_MIX.keys()),
        size=n_ent,
        p=list(config.ENTERPRISE_TERM_MONTHS_MIX.values()),
    )
    plan.loc[is_enterprise, "term_months"] = ent_terms

    plan["churn_date"] = pd.NaT
    renewal_rows = []

    # --- Commercial / Enterprise: churn only at a renewal boundary ---
    for account_id, row in plan[is_commercial | is_enterprise].iterrows():
        segment = row["segment"]
        annual_churn = config.ANNUAL_CHURN_RATE[segment]
        term_years = row["term_months"] / 12
        p_churn_at_boundary = 1 - (1 - annual_churn) ** term_years

        start = pd.Timestamp(row["contract_start_date"])
        boundary = start + pd.DateOffset(months=int(row["term_months"]))
        seq = 1
        committed = row["committed_actions_monthly"]
        while boundary <= pd.Timestamp(config.SIM_END):
            churns = rng.random() < p_churn_at_boundary
            if churns:
                renewal_rows.append({
                    "account_id": account_id, "segment": segment, "sequence_number": seq,
                    "boundary_date": boundary.date(), "outcome": "churned",
                    "committed_actions_monthly": committed,
                })
                plan.loc[account_id, "churn_date"] = boundary
                break
            else:
                outcome_roll = rng.random()
                if outcome_roll < 0.10:
                    outcome = "retained_contraction"
                    committed = committed * rng.uniform(0.75, 0.90)
                elif outcome_roll < 0.35:
                    outcome = "retained_expansion"
                    committed = committed * rng.uniform(1.25, 1.60)
                else:
                    outcome = "retained_flat"
                if segment == "Enterprise":
                    committed = committed * (1 + 0.05 * seq)  # graduated usage commitments, build spec Section 1
                renewal_rows.append({
                    "account_id": account_id, "segment": segment, "sequence_number": seq,
                    "boundary_date": boundary.date(), "outcome": outcome,
                    "committed_actions_monthly": committed,
                })
                seq += 1
                boundary = boundary + pd.DateOffset(months=int(row["term_months"]))

    # --- SMB: constant monthly hazard, no contract boundary required ---
    monthly_hazard = 1 - (1 - config.ANNUAL_CHURN_RATE["SMB"]) ** (1 / 12)
    is_smb = plan["segment"] == "SMB"
    for account_id, row in plan[is_smb].iterrows():
        grace_months = config.ACTIVATION_RAMP_MONTHS["SMB"]
        month = pd.Timestamp(row["signup_date"]) + pd.DateOffset(months=grace_months)
        while month <= pd.Timestamp(config.SIM_END):
            if rng.random() < monthly_hazard:
                plan.loc[account_id, "churn_date"] = month
                break
            month = month + pd.DateOffset(months=1)

    plan["is_censored"] = plan["churn_date"].isna()
    plan = plan.reset_index()
    renewal_events_df = pd.DataFrame(renewal_rows)
    return plan, renewal_events_df
