"""Firmographic-fit scoring shared by market_universe and account entry.

Build spec Section 5: `market_universe.icp_fit_score` is "computed with the
same logic as lead_scoring_history but applied to the whole universe, not
just inbound leads." Build spec Section 1: segment entry is decided by this
same firmographic-fit score, run "at signup or lead creation regardless of
how the account arrived" -- strong Enterprise-fit -> Enterprise, Commercial-
fit -> Commercial, no strong signal (personal email domain, unmatched
company) -> defaults to SMB. This module is that one shared scoring
function, so market_universe and accounts.py never redefine the logic
independently.

The specific weights, bands, and thresholds below are the generator's own
resolved decisions -- neither doc specifies a formula, only the qualitative
rule ("strong signal" vs "no strong signal") and the requirement that the
result be noisy, not perfectly deterministic (build spec Section 4).
"""
import numpy as np

EMPLOYEE_BANDS = ["1-10", "11-50", "51-200", "201-1000", "1001-5000", "5001-20000", "20000+"]
EMPLOYEE_BAND_PROBS = [0.45, 0.25, 0.15, 0.09, 0.04, 0.015, 0.005]
EMPLOYEE_BAND_WEIGHT = {
    "1-10": 5, "11-50": 15, "51-200": 35, "201-1000": 55,
    "1001-5000": 75, "5001-20000": 90, "20000+": 98,
}

INDUSTRIES = [
    "Technology/SaaS", "Financial Services", "Healthcare", "Manufacturing",
    "Retail/E-commerce", "Professional Services", "Media/Entertainment",
    "Logistics/Supply Chain", "Public Sector", "Education",
]
INDUSTRY_PROBS = [0.12, 0.10, 0.10, 0.10, 0.14, 0.14, 0.08, 0.08, 0.06, 0.08]
INDUSTRY_WEIGHT = {
    "Technology/SaaS": 70, "Financial Services": 80, "Healthcare": 60,
    "Manufacturing": 65, "Retail/E-commerce": 35, "Professional Services": 40,
    "Media/Entertainment": 45, "Logistics/Supply Chain": 55,
    "Public Sector": 60, "Education": 30,
}

REGIONS = ["North America", "EMEA", "APAC", "LATAM"]
REGION_PROBS = [0.55, 0.25, 0.15, 0.05]
REGION_MODIFIER = {"North America": 3, "EMEA": 1, "APAC": 0, "LATAM": -3}

ENTERPRISE_FIT_THRESHOLD = 72
COMMERCIAL_FIT_THRESHOLD = 40

# Companies in the smallest employee band get a chance of being flagged as a
# personal-email-domain signup -- build spec Section 1's "unmatched company"
# / personal-email default-to-SMB path made explicit and auditable, rather
# than left purely implicit in a low fit_score. Own resolved decision: no
# probability is stated in either doc.
PERSONAL_EMAIL_DOMAIN_PROB_BY_BAND = {"1-10": 0.20}


def sample_firmographics(rng: np.random.Generator, n: int):
    """Draw employee_band, industry, region, is_personal_email_domain for n companies."""
    employee_band = rng.choice(EMPLOYEE_BANDS, size=n, p=EMPLOYEE_BAND_PROBS)
    industry = rng.choice(INDUSTRIES, size=n, p=INDUSTRY_PROBS)
    region = rng.choice(REGIONS, size=n, p=REGION_PROBS)
    band_prob = np.array([PERSONAL_EMAIL_DOMAIN_PROB_BY_BAND.get(b, 0.0) for b in employee_band])
    is_personal_email_domain = rng.random(n) < band_prob
    return employee_band, industry, region, is_personal_email_domain


def compute_fit_score(employee_band, industry, region, rng: np.random.Generator):
    """icp_fit_score, 0-100. One function backs both market_universe's
    icp_fit_score and the account entry-segment decision."""
    n = len(employee_band)
    emp_w = np.array([EMPLOYEE_BAND_WEIGHT[b] for b in employee_band])
    ind_w = np.array([INDUSTRY_WEIGHT[i] for i in industry])
    reg_m = np.array([REGION_MODIFIER[r] for r in region])
    noise = rng.normal(0, 7, size=n)  # keeps entry/migration non-deterministic, build spec Section 4
    score = 0.6 * emp_w + 0.3 * ind_w + reg_m + noise
    return np.clip(score, 0, 100)


def fit_tier(score: np.ndarray, is_personal_email_domain: np.ndarray):
    """Maps score (+ hard override) to 'Enterprise' / 'Commercial' / 'SMB'.

    personal_email_domain is a hard override to SMB regardless of score --
    build spec Section 1 names it as its own "no strong signal" condition,
    not merely a contributor to a low score.
    """
    tier = np.where(
        score >= ENTERPRISE_FIT_THRESHOLD, "Enterprise",
        np.where(score >= COMMERCIAL_FIT_THRESHOLD, "Commercial", "SMB"),
    )
    tier = np.where(is_personal_email_domain, "SMB", tier)
    return tier
