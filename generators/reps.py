"""users (reps) + quota_history + rep_status_history generator.

Build spec Section 5 (CRM): `users` (reps: rep_type [ISR/AE/SE/AM-Commercial/
AM-Enterprise], hire_date, book size), `quota_history` (rep, effective_date,
amount), `rep_status_history` (rep, status, effective_date). Build spec
Section 4: headcount ranges and the ramp step-function (consumed by later
generators, not computed here -- this module only establishes who the reps
are and when they joined/left).

Column-naming note: neither doc names a primary key for `users`, so this
uses `rep_id` (an obvious, unclaimed name) and reuses it as the FK column in
quota_history/rep_status_history instead of the docs' shorthand "rep",
matching the effective_date naming both tables already share.
"""
from datetime import timedelta

import numpy as np
import pandas as pd

from . import config


def _stagger_hire_dates(rng: np.random.Generator, n: int):
    """~65% already tenured before SIM_START, ~35% hired during the window --
    own resolved decision, mirroring the QA plan's staggered-tenure
    requirement for accounts so reps don't all look brand-new in month 1
    either. The last 2 months of the window are excluded from "during"
    hires so every hire has at least some tenure to observe ramp against.
    """
    n_pre = int(round(n * 0.65))
    n_during = n - n_pre

    pre_start = config.SIM_START - timedelta(days=365 * 4)
    pre_span_days = (config.SIM_START - pre_start).days
    pre_dates = [pre_start + timedelta(days=int(d)) for d in rng.integers(0, pre_span_days, size=n_pre)]

    during_month = rng.integers(0, config.N_MONTHS - 2, size=n_during)
    during_day = rng.integers(0, 28, size=n_during)
    during_dates = [
        (pd.Timestamp(config.SIM_START) + pd.DateOffset(months=int(m)) + pd.Timedelta(days=int(d))).date()
        for m, d in zip(during_month, during_day)
    ]

    dates = pre_dates + during_dates
    rng.shuffle(dates)
    return dates


def _guarantee_earliest_rep_per_type(rep_type: np.ndarray, hire_date: list) -> list:
    """A small rep_type headcount (AM-Commercial=5, AM-Enterprise=10) has a
    real chance every member of that type ends up hired after the earliest
    possible account signup date, purely by chance in the staggered-hire
    draw -- opportunities.py can then only assign a rep hired *after* the
    opportunity's own created_date. Force the earliest-hired rep of each
    type to predate the earliest possible account (config.
    EARLIEST_POSSIBLE_ACCOUNT_DATE) by a safety margin, so every rep_type
    always has at least one eligible rep for any in-window opportunity.
    """
    hire_date = list(hire_date)
    safe_cutoff = config.EARLIEST_POSSIBLE_ACCOUNT_DATE - timedelta(days=180)
    for rtype in set(rep_type):
        idx = [i for i, t in enumerate(rep_type) if t == rtype]
        min_idx = min(idx, key=lambda i: hire_date[i])
        if hire_date[min_idx] > safe_cutoff:
            hire_date[min_idx] = safe_cutoff
    return hire_date


def _book_sizes(rng: np.random.Generator, rep_type: np.ndarray) -> np.ndarray:
    book_size = np.full(len(rep_type), np.nan)
    is_am_comm = rep_type == "AM-Commercial"
    is_am_ent = rep_type == "AM-Enterprise"
    book_size[is_am_comm] = np.round(
        rng.normal(config.COMMERCIAL_BOOK_SIZE, 25, size=is_am_comm.sum())
    ).clip(120, 280)
    book_size[is_am_ent] = np.round(
        rng.normal(config.ENTERPRISE_BOOK_SIZE, 4, size=is_am_ent.sum())
    ).clip(10, 30)
    # ISR/AE/SE: new-business/support capacity, not a persistent book -- left
    # null. Flagged in the batch summary as a genuine reading of Section 4
    # vs. Section 1/2's ownership model; see config.py's comment on the
    # same ambiguity.
    return book_size


def generate_reps(rng: np.random.Generator, n_am_commercial: int, n_am_enterprise: int):
    n_se = round(config.N_AE * config.SE_TO_AE_RATIO)
    specs = (
        [("ISR", "Commercial")] * config.N_ISR
        + [("AE", "Enterprise")] * config.N_AE
        + [("SE", "Enterprise")] * n_se
        + [("AM-Commercial", "Commercial")] * n_am_commercial
        + [("AM-Enterprise", "Enterprise")] * n_am_enterprise
    )
    order = rng.permutation(len(specs))
    specs = [specs[i] for i in order]

    n_total = len(specs)
    rep_type = np.array([s[0] for s in specs])
    segment = np.array([s[1] for s in specs])
    hire_date = _stagger_hire_dates(rng, n_total)
    hire_date = _guarantee_earliest_rep_per_type(rep_type, hire_date)
    book_size = _book_sizes(rng, rep_type)

    users_df = pd.DataFrame({
        "rep_id": [f"REP-{i:05d}" for i in range(n_total)],
        "rep_type": rep_type,
        "segment": segment,
        "hire_date": hire_date,
        "book_size": book_size,
    })
    # Re-key rep_id by hire_date so ids don't leak generation order -- cosmetic only.
    users_df = users_df.sort_values("hire_date").reset_index(drop=True)
    users_df["rep_id"] = [f"REP-{i:05d}" for i in range(n_total)]

    quota_history_df = _generate_quota_history(rng, users_df)
    rep_status_history_df = _generate_rep_status_history(rng, users_df)
    return users_df, quota_history_df, rep_status_history_df


# Quarterly new-business ARR quota ranges by rep_type -- own resolved
# decision, sized to be plausible against each segment's ACV band
# (config.ACV_RANGES) for a rep closing a handful of deals per quarter.
# Only ISR/AE carry quota: they're the new-business, quota-bearing roles
# per build spec Section 2; AM comp isn't described as quota-based in either
# doc, so quota_history is scoped to ISR/AE only here.
_QUOTA_BASE_RANGE = {"ISR": (150_000, 220_000), "AE": (400_000, 700_000)}


def _generate_quota_history(rng: np.random.Generator, users_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for rep in users_df.itertuples():
        if rep.rep_type not in _QUOTA_BASE_RANGE:
            continue
        lo, hi = _QUOTA_BASE_RANGE[rep.rep_type]
        base = rng.uniform(lo, hi)
        start_q = pd.Timestamp(rep.hire_date).to_period("Q").start_time
        q_dates = pd.period_range(start_q, pd.Timestamp(config.SIM_END), freq="Q").start_time
        for i, q in enumerate(q_dates):
            step_up = 1 + 0.02 * i  # quota is time-varying, not static (build spec Section 5) -- modest ~2%/quarter step-up, own decision
            rows.append({
                "rep_id": rep.rep_id,
                "effective_date": q.date(),
                "amount": round(base * step_up, -2),
            })
    return pd.DataFrame(rows)


def _generate_rep_status_history(rng: np.random.Generator, users_df: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"rep_id": rep.rep_id, "status": "active", "effective_date": rep.hire_date}
        for rep in users_df.itertuples()
    ]

    # A modest fraction depart mid-simulation -- own decision. This batch
    # only records the departure event; atomic account/opportunity
    # reassignment (the QA plan's "no orphaned ownership" edge case) is
    # deferred to the opportunities generator, since accounts don't carry a
    # rep-owner field until that batch introduces ownership.
    cutoff = pd.Timestamp(config.SIM_END) - pd.DateOffset(months=6)
    eligible = users_df[pd.to_datetime(users_df["hire_date"]) <= cutoff]
    n_depart = int(round(len(eligible) * 0.12))
    depart_idx = rng.choice(eligible.index.to_numpy(), size=n_depart, replace=False)

    for idx in depart_idx:
        rep = users_df.loc[idx]
        min_date = pd.Timestamp(rep["hire_date"]) + pd.DateOffset(months=6)
        max_date = pd.Timestamp(config.SIM_END)
        span_days = max((max_date - min_date).days, 1)
        depart_date = (min_date + pd.Timedelta(days=int(rng.integers(0, span_days)))).date()
        rows.append({"rep_id": rep["rep_id"], "status": "departed", "effective_date": depart_date})

    return pd.DataFrame(rows).sort_values(["rep_id", "effective_date"]).reset_index(drop=True)
