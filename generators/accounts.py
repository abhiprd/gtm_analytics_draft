"""accounts + account_segment_history generator.

Build spec Section 1: segment entry is decided by firmographic-fit scoring
at signup, "independent of acquisition channel." Section 5: `accounts`
(current segment, firmographic fields incl. region/industry) is "the
customer subset of market_universe," linked via company_id.
`account_segment_history` carries an initial row at account creation (not
just at migration), trigger_reason in {initial_firmographic, initial_default,
usage_threshold, firmographic_rescore}. Migration rules (Section 1): SMB ->
Commercial at ~$1,250/mo sustained usage or firmographic re-scoring;
Commercial -> Enterprise at ~$6,250/mo or re-scoring; no skip-level
migration; migrations take effect the 1st of the month following the
trigger (QA plan), no proration.

This module must run against a market_universe DataFrame already scored by
firmographics.compute_fit_score/fit_tier, mutating it in place to set
is_customer / was_ever_customer / account_id -- entry segment is that same
fit_tier, not a separately re-derived decision (build spec Section 5).

Design note carried forward to the usage/billing generator (next batch):
migration timing here is committed *before* usage_monthly exists, since the
QA plan calls for account_segment_history in this batch. The usage
generator must treat each usage_threshold-triggered migration's
(account_id, effective_date) as a target to grow into -- i.e. the account's
usage curve should cross the ~$1,250/mo or ~$6,250/mo threshold in the two
months immediately preceding that date -- rather than generating usage
independently and hoping it lines up. That's the causal-wiring contract
between the two batches.
"""
from datetime import timedelta

import numpy as np
import pandas as pd

from . import config

CHANNELS_BY_SEGMENT = {
    "SMB": ["self_serve", "inbound_marketing"],
    "Commercial": ["self_serve", "inbound_marketing"],
    "Enterprise": ["self_serve", "inbound_marketing", "outbound_sdr"],
}
# Channel-mix probabilities within each segment -- own resolved decision;
# neither doc gives a numeric split, only that outbound SDR is Enterprise-
# only and channel/segment must stay orthogonal (satisfied here since
# self_serve/inbound_marketing appear, with different weights, in all three
# segments -- no channel implies a segment or vice versa).
CHANNEL_PROBS_BY_SEGMENT = {
    "SMB": [0.75, 0.25],
    "Commercial": [0.55, 0.45],
    "Enterprise": [0.35, 0.40, 0.25],
}


def solve_entry_cohort_sizes() -> dict:
    """Back-solves entry-cohort sizes and migration-wave sizes so that,
    net of migration outflow, current-state counts land exactly on
    config.FINAL_*. See config.py's comment on MIG_RATE_*.
    """
    r1 = config.MIG_RATE_SMB_TO_COMMERCIAL
    r2 = config.MIG_RATE_COMMERCIAL_TO_ENTERPRISE

    e_smb = round(config.FINAL_SMB / (1 - r1))
    m1 = round(e_smb * r1)
    pool_comm = round(config.FINAL_COMMERCIAL / (1 - r2))
    e_comm = pool_comm - m1
    m2 = round(pool_comm * r2)
    e_ent = config.FINAL_ENTERPRISE - m2

    return {
        "E_smb": e_smb, "E_comm": e_comm, "E_ent": e_ent,
        "m1_smb_to_comm": m1, "m2_comm_to_ent": m2,
    }


def _sample_signup_dates(rng: np.random.Generator, n: int):
    """~20% already-established before SIM_START (QA plan: "seed a modest
    cohort of accounts with already-established, staggered tenure at
    simulation start"), ~80% sign up progressively during the window with a
    modest upward growth trend (build spec Section 5 realism rules:
    seasonality/growth, not a flat rate)."""
    n_established = int(round(n * 0.20))
    n_new = n - n_established

    established_start = config.SIM_START - timedelta(days=365 * 3)
    established_span = (config.SIM_START - established_start).days
    established_dates = [
        established_start + timedelta(days=int(d))
        for d in rng.integers(0, established_span, size=n_established)
    ]

    month_weights = np.linspace(1, 3, config.N_MONTHS)
    month_probs = month_weights / month_weights.sum()
    month_idx = rng.choice(config.N_MONTHS, size=n_new, p=month_probs)
    day_offset = rng.integers(0, 28, size=n_new)
    new_dates = [
        (pd.Timestamp(config.SIM_START) + pd.DateOffset(months=int(m)) + pd.Timedelta(days=int(d))).date()
        for m, d in zip(month_idx, day_offset)
    ]

    dates = established_dates + new_dates
    rng.shuffle(dates)
    return dates


def _sample_channel(rng: np.random.Generator, segment: str) -> str:
    options = CHANNELS_BY_SEGMENT[segment]
    probs = CHANNEL_PROBS_BY_SEGMENT[segment]
    return rng.choice(options, p=probs)


def _random_month_start_between(rng: np.random.Generator, earliest, latest):
    """A uniformly random month-start date in [earliest, latest] -- migration
    effective_dates are always the 1st of a month (QA plan: no proration)."""
    earliest_p = pd.Timestamp(earliest).to_period("M")
    latest_p = pd.Timestamp(latest).to_period("M")
    n_months = (latest_p - earliest_p).n + 1
    if n_months <= 0:
        return latest_p.start_time.date()
    offset = int(rng.integers(0, n_months))
    return (earliest_p + offset).start_time.date()


def _pick_from_tier(rng: np.random.Generator, market_universe: pd.DataFrame, tier: str, n: int) -> np.ndarray:
    """Weighted-random selection of n company_ids from a fit tier -- weighting
    mildly toward higher icp_fit_score within the tier (better fits convert
    at a somewhat higher rate), own resolved decision, not a stated rule."""
    pool = market_universe.loc[market_universe["fit_tier"] == tier]
    if len(pool) < n:
        raise ValueError(
            f"fit tier '{tier}' has only {len(pool)} companies, need {n} -- "
            "adjust firmographics.py's band/industry distributions"
        )
    weights = pool["icp_fit_score"].to_numpy(dtype=float)
    weights = weights - weights.min() + 1.0
    probs = weights / weights.sum()
    chosen = rng.choice(pool.index.to_numpy(), size=n, replace=False, p=probs)
    return chosen


def generate_accounts_and_segment_history(rng: np.random.Generator, market_universe: pd.DataFrame):
    cohorts = solve_entry_cohort_sizes()

    ent_idx = _pick_from_tier(rng, market_universe, "Enterprise", cohorts["E_ent"])
    comm_idx = _pick_from_tier(rng, market_universe, "Commercial", cohorts["E_comm"])
    smb_idx = _pick_from_tier(rng, market_universe, "SMB", cohorts["E_smb"])

    entry_rows = (
        [(i, "Enterprise") for i in ent_idx]
        + [(i, "Commercial") for i in comm_idx]
        + [(i, "SMB") for i in smb_idx]
    )
    n_accounts = len(entry_rows)
    signup_dates = _sample_signup_dates(rng, n_accounts)

    account_ids = [f"ACC-{i:06d}" for i in range(n_accounts)]
    accounts_rows = []
    history_rows = []

    for account_id, (mu_idx, entry_segment), signup_date in zip(account_ids, entry_rows, signup_dates):
        mu_row = market_universe.loc[mu_idx]
        trigger_reason = "initial_default" if entry_segment == "SMB" else "initial_firmographic"

        accounts_rows.append({
            "account_id": account_id,
            "company_id": mu_row["company_id"],
            "segment": entry_segment,  # updated to current segment after migrations, below
            "employee_count_band": mu_row["employee_count_band"],
            "industry": mu_row["industry"],
            "region": mu_row["region"],
            "channel": _sample_channel(rng, entry_segment),
            "signup_date": signup_date,
            "icp_fit_score": mu_row["icp_fit_score"],
            "is_personal_email_domain": mu_row["is_personal_email_domain"],
        })
        history_rows.append({
            "account_id": account_id,
            "segment": entry_segment,
            "effective_date": signup_date,
            "trigger_reason": trigger_reason,
        })

        market_universe.loc[mu_idx, "is_customer"] = True
        market_universe.loc[mu_idx, "was_ever_customer"] = True
        market_universe.loc[mu_idx, "account_id"] = account_id

    accounts_df = pd.DataFrame(accounts_rows)
    account_id_to_row = {r["account_id"]: r for r in accounts_rows}

    # --- Wave 1: SMB -> Commercial -----------------------------------
    smb_account_ids = [account_ids[i] for i, (_, seg) in enumerate(entry_rows) if seg == "SMB"]
    smb_signup = {aid: account_id_to_row[aid]["signup_date"] for aid in smb_account_ids}
    runway_cutoff_1 = pd.Timestamp(config.SIM_END) - pd.DateOffset(months=4)
    eligible_1 = [aid for aid in smb_account_ids if pd.Timestamp(smb_signup[aid]) <= runway_cutoff_1]
    n_m1 = cohorts["m1_smb_to_comm"]
    if len(eligible_1) < n_m1:
        raise ValueError(f"only {len(eligible_1)} SMB accounts eligible for migration, need {n_m1}")
    m1_ids = rng.choice(eligible_1, size=n_m1, replace=False)

    reasons_1 = rng.choice(
        list(config.TRIGGER_SPLIT_SMB_TO_COMMERCIAL.keys()),
        size=n_m1,
        p=list(config.TRIGGER_SPLIT_SMB_TO_COMMERCIAL.values()),
    )
    commercial_start_date = {}  # account_id -> date it became Commercial (entry or migration)
    for aid in [account_ids[i] for i, (_, seg) in enumerate(entry_rows) if seg == "Commercial"]:
        commercial_start_date[aid] = account_id_to_row[aid]["signup_date"]

    for aid, reason in zip(m1_ids, reasons_1):
        earliest = (pd.Timestamp(smb_signup[aid]) + pd.DateOffset(months=2)).to_period("M").start_time.date()
        eff_date = _random_month_start_between(rng, earliest, config.SIM_END)
        history_rows.append({
            "account_id": aid, "segment": "Commercial",
            "effective_date": eff_date, "trigger_reason": reason,
        })
        commercial_start_date[aid] = eff_date

    # --- Wave 2: Commercial -> Enterprise -----------------------------
    runway_cutoff_2 = pd.Timestamp(config.SIM_END) - pd.DateOffset(months=3)
    eligible_2 = [aid for aid, d in commercial_start_date.items() if pd.Timestamp(d) <= runway_cutoff_2]
    n_m2 = cohorts["m2_comm_to_ent"]
    if len(eligible_2) < n_m2:
        raise ValueError(f"only {len(eligible_2)} Commercial accounts eligible for migration, need {n_m2}")
    m2_ids = rng.choice(eligible_2, size=n_m2, replace=False)

    reasons_2 = rng.choice(
        list(config.TRIGGER_SPLIT_COMMERCIAL_TO_ENTERPRISE.keys()),
        size=n_m2,
        p=list(config.TRIGGER_SPLIT_COMMERCIAL_TO_ENTERPRISE.values()),
    )
    final_segment = {aid: "Commercial" for aid in commercial_start_date}
    for aid in [account_ids[i] for i, (_, seg) in enumerate(entry_rows) if seg == "Enterprise"]:
        final_segment[aid] = "Enterprise"

    for aid, reason in zip(m2_ids, reasons_2):
        earliest = (pd.Timestamp(commercial_start_date[aid]) + pd.DateOffset(months=2)).to_period("M").start_time.date()
        eff_date = _random_month_start_between(rng, earliest, config.SIM_END)
        history_rows.append({
            "account_id": aid, "segment": "Enterprise",
            "effective_date": eff_date, "trigger_reason": reason,
        })
        final_segment[aid] = "Enterprise"

    # Reconcile accounts.segment to the *current* (as of SIM_END) state.
    accounts_df = accounts_df.set_index("account_id")
    for aid, seg in final_segment.items():
        accounts_df.loc[aid, "segment"] = seg
    accounts_df = accounts_df.reset_index()

    history_df = pd.DataFrame(history_rows).sort_values(["account_id", "effective_date"]).reset_index(drop=True)

    market_universe = market_universe.drop(columns=["fit_tier"])
    return accounts_df, history_df, market_universe
