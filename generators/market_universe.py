"""market_universe generator -- Phase 1 market-intelligence table.

Build spec Section 5: prospect company records including non-customers --
employee-count band, industry, region, `is_customer` flag linking to
`accounts` when true, `icp_fit_score`. "Every real customer account should
also have a corresponding market_universe row marked is_customer = true, so
penetration is a clean ratio." Volume needs to be "tens of thousands of
rows"; QA plan Test D additionally wants the non-customer:customer ratio at
10-50x specifically (config.NON_CUSTOMER_MULTIPLE).

This module only builds the raw universe (firmographics + icp_fit_score +
fit_tier). accounts.py selects which rows become customers -- entry segment
must come from the *same* fit_tier computed here, per build spec Section 5's
"same logic ... applied to the whole universe" -- and mutates is_customer /
was_ever_customer / account_id in place on the returned DataFrame.
"""
import numpy as np
import pandas as pd

from . import config
from .firmographics import sample_firmographics, compute_fit_score, fit_tier


def generate_market_universe(rng: np.random.Generator) -> pd.DataFrame:
    n_customers = config.FINAL_TOTAL_CUSTOMERS
    n_non_customers = n_customers * config.NON_CUSTOMER_MULTIPLE
    n_total = n_customers + n_non_customers

    employee_band, industry, region, is_personal_email = sample_firmographics(rng, n_total)
    score = compute_fit_score(employee_band, industry, region, rng)
    tier = fit_tier(score, is_personal_email)

    df = pd.DataFrame({
        "company_id": [f"CO-{i:07d}" for i in range(n_total)],
        "employee_count_band": employee_band,
        "industry": industry,
        "region": region,
        "is_personal_email_domain": is_personal_email,
        "icp_fit_score": np.round(score, 1),
        "fit_tier": tier,  # generation-time helper; dropped before CSV write, see run_foundation.py
        "is_customer": False,
        "was_ever_customer": False,
        "account_id": pd.array([None] * n_total, dtype="string"),
    })
    return df
