"""lead_scoring_history generator -- Phase 1 scoring/testing-infrastructure
table (build spec Section 5).

Build spec grounding
---------------------
Section 5 names `lead_scoring_history` as "(lead, scored_at, model_version,
predicted_segment, score components -- stored separately from the eventual
observed outcome, so a scoring model can be validated against what actually
happened)." The same section describes `market_universe.icp_fit_score` as
"computed with the same logic as lead_scoring_history but applied to the
whole universe, not just inbound leads" -- i.e. this table is not a new
scoring methodology, it is `firmographics.compute_fit_score()` re-applied to
the `leads.csv` population over time instead of once to the whole universe.

Design decision -- re-scoring cadence
--------------------------------------
The model this table applies is purely firmographic (employee band,
industry, region), the same three inputs `compute_fit_score()` already
consumes. A lead's firmographic inputs essentially never change day to day,
so there is nothing for an engagement-triggered re-score to react to --
unlike `leads.lead_score` (composite of firmographic fit *and* touch
engagement, intentionally not reproduced here; see fact_leads.sql's
point-in-time warning), a purely firmographic model is naturally a periodic
batch job, not an event-triggered one. Every lead is scored on a ~30-day
cadence (RESCORE_CADENCE_DAYS, jittered) starting shortly after
`created_date`, for as long as it stays in the "active, unresolved" pool:
until `converted_date` for a converting lead, or for MAX_ACTIVE_SCORING_DAYS
(6 months) for a non-converting one, after which point a real lead-scoring
operation would consider it gone cold and stop spending a scoring cycle on
it.

Design decision -- model_version
----------------------------------
Build spec Section 5's own framing settles this rather than requiring a new
narrative: `market_universe.icp_fit_score` already *is*
`compute_fit_score()`'s current, real, region-aware formula
(0.6*employee_band_weight + 0.3*industry_weight + region_modifier + noise).
Fabricating unrelated version churn on top of that (a formula that was never
actually run) would be exactly the decoration CLAUDE.md's
"independently-random columns are a bug" rule warns against, extended to a
fabricated column instead of a fabricated value.

What *is* real and checkable: the region modifier is the newest term in
`compute_fit_score()` -- a company's employee band and industry decide the
bulk of its fit, region is a smaller, later-considered adjustment. This
module encodes that as a genuine model version change: `MODEL_VERSION_V1`
(pre-MODEL_CUTOVER_DATE) is the same formula with the region term not yet
folded in; `MODEL_VERSION_V2` (from MODEL_CUTOVER_DATE onward) is
`compute_fit_score()` exactly, region term included, current production
logic. No new weights are invented for v1 -- it reuses the identical
EMPLOYEE_BAND_WEIGHT/INDUSTRY_WEIGHT coefficients and simply omits the
region term, so the two versions are the same model at two real points in
its own history, not two unrelated formulas. This gives the eventual
model-validation/drift artifact both framings the task raised as legitimate:
a real, dateable version change with a measurably different score
distribution (region's contribution is present in v2 and structurally
absent, not merely zero, in v1 -- `region_component` is null for v1 rows),
*and*, within each version's own regime, an unchanged-model calibration
question as the scored lead population's composition shifts over time.

No-leakage invariant
---------------------
The score and predicted_segment are a pure function of company_id's
firmographics (via market_universe, joined by company_id -- identical join
key `generate_leads` already uses for icp_fit_score) plus fresh noise drawn
at scoring time. `leads.is_converted` / `converted_date` are read only to
bound *when* a lead is still in the active-scoring window (the same
"censoring", not "scoring", role converted_date already plays for touch
placement in campaign_engagement_events) -- never to compute the score or
predicted_segment themselves. Every scoring event for a converting lead
lands strictly before its converted_date, so nothing here could have seen
the outcome it is later validated against.
"""
import numpy as np
import pandas as pd

from . import config
from .firmographics import (
    COMMERCIAL_FIT_THRESHOLD,
    ENTERPRISE_FIT_THRESHOLD,
    EMPLOYEE_BAND_WEIGHT,
    INDUSTRY_WEIGHT,
    REGION_MODIFIER,
)

LEAD_SCORING_COLUMNS = [
    "score_id", "lead_id", "scored_at", "model_version", "predicted_segment",
    "predicted_fit_score", "employee_band_component", "industry_component",
    "region_component", "noise_component",
]

# The region term was folded into compute_fit_score() partway through the
# simulation window (own resolved decision -- neither doc dates this). Set
# near the window's midpoint so both regimes carry enough volume to compare.
MODEL_CUTOVER_DATE = pd.Timestamp("2024-07-01")
MODEL_VERSION_V1 = "lead_fit_v1_preregion"   # employee band + industry only
MODEL_VERSION_V2 = "lead_fit_v2_region_aware"  # == compute_fit_score() exactly

# Same noise scale compute_fit_score() itself uses -- re-scoring noise isn't
# a newly invented distribution, it's the same generator noise redrawn at
# each scoring event.
SCORE_NOISE_SD = 7.0

RESCORE_CADENCE_DAYS = 30
RESCORE_JITTER_DAYS = 3
FIRST_SCORE_LAG_MAX_DAYS = 6
MAX_ACTIVE_SCORING_DAYS = 180  # ~6 months; a non-converting lead goes cold


def _observation_end() -> pd.Timestamp:
    """Mirrors marketing_funnel._observation_end()'s convention (SIM_END is
    the first of the final month; the last observable day is its month
    end) -- self-contained here rather than reaching into that module's
    private helper."""
    return pd.Timestamp(config.SIM_END) + pd.offsets.MonthEnd(0)


def _score_events_for_lead(rng: np.random.Generator, created_date: pd.Timestamp,
                            is_converted: bool, converted_date, obs_end: pd.Timestamp) -> list:
    """Every scored_at date for one lead: created_date + a short pickup lag,
    then every ~30 days while the lead is still active, capped by the
    lead's own resolution (conversion) or by going cold."""
    if is_converted:
        window_end = pd.Timestamp(converted_date) - pd.Timedelta(days=1)
    else:
        window_end = min(created_date + pd.Timedelta(days=MAX_ACTIVE_SCORING_DAYS), obs_end)
    window_end = max(window_end, created_date)  # a same-day gap gives a single valid day

    lag = int(rng.integers(0, FIRST_SCORE_LAG_MAX_DAYS + 1))
    first = min(created_date + pd.Timedelta(days=lag), window_end)

    events = [first]
    cursor = first
    while True:
        step = int(rng.integers(RESCORE_CADENCE_DAYS - RESCORE_JITTER_DAYS,
                                 RESCORE_CADENCE_DAYS + RESCORE_JITTER_DAYS + 1))
        nxt = cursor + pd.Timedelta(days=step)
        if nxt > window_end:
            break
        events.append(nxt)
        cursor = nxt
    return events


def generate_lead_scoring_history(rng: np.random.Generator, leads: pd.DataFrame,
                                   market_universe: pd.DataFrame) -> pd.DataFrame:
    """One row per lead per scoring event (event grain).

    `leads` must carry lead_id, company_id, created_date, converted_date,
    is_converted -- exactly the columns published in leads.csv (LEAD_COLUMNS
    in marketing_funnel.py). `market_universe` supplies employee_count_band /
    industry / region / is_personal_email_domain by company_id, the same
    join key `generate_leads` already uses for icp_fit_score.
    """
    firmo = market_universe.set_index("company_id")[
        ["employee_count_band", "industry", "region", "is_personal_email_domain"]
    ]
    obs_end = _observation_end()

    rows = []
    for lead in leads.itertuples(index=False):
        company = firmo.loc[lead.company_id]
        emp_w = EMPLOYEE_BAND_WEIGHT[company["employee_count_band"]]
        ind_w = INDUSTRY_WEIGHT[company["industry"]]
        reg_m = REGION_MODIFIER[company["region"]]
        is_personal_email = bool(company["is_personal_email_domain"])

        created_ts = pd.Timestamp(lead.created_date)
        converted_ts = pd.Timestamp(lead.converted_date) if bool(lead.is_converted) else None

        scored_dates = _score_events_for_lead(
            rng, created_ts, bool(lead.is_converted), converted_ts, obs_end,
        )

        for scored_at in scored_dates:
            is_v2 = scored_at >= MODEL_CUTOVER_DATE
            emp_component = 0.6 * emp_w
            ind_component = 0.3 * ind_w
            noise = float(rng.normal(0.0, SCORE_NOISE_SD))

            if is_v2:
                reg_component = float(reg_m)
                raw_score = emp_component + ind_component + reg_component + noise
                model_version = MODEL_VERSION_V2
            else:
                reg_component = np.nan  # not computed by this model version
                raw_score = emp_component + ind_component + noise
                model_version = MODEL_VERSION_V1

            fit_score = float(np.clip(raw_score, 0.0, 100.0))
            # Same classification rule fit_tier() applies (personal-email
            # hard override, then the shared 72/40 thresholds) -- inlined
            # rather than called per-row to avoid per-event array overhead
            # across a few hundred thousand scoring events.
            if is_personal_email:
                segment = "SMB"
            elif fit_score >= ENTERPRISE_FIT_THRESHOLD:
                segment = "Enterprise"
            elif fit_score >= COMMERCIAL_FIT_THRESHOLD:
                segment = "Commercial"
            else:
                segment = "SMB"

            rows.append({
                "lead_id": lead.lead_id,
                "scored_at": scored_at.date(),
                "model_version": model_version,
                "predicted_segment": segment,
                "predicted_fit_score": round(fit_score, 1),
                "employee_band_component": round(emp_component, 1),
                "industry_component": round(ind_component, 1),
                "region_component": round(reg_component, 1) if not np.isnan(reg_component) else np.nan,
                "noise_component": round(noise, 1),
            })

    history = pd.DataFrame(rows)
    history = history.sort_values(["lead_id", "scored_at"], kind="mergesort").reset_index(drop=True)
    history["score_id"] = [f"LS-{i + 1:07d}" for i in range(len(history))]
    return history[LEAD_SCORING_COLUMNS]
