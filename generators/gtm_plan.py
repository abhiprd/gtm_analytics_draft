"""gtm_plan generator -- FP&A/RevOps plan (target) values for the Layer-1
metrics.

Grain: one row per (layer1_metric, month), blended/company-wide -- no segment
cut. This is exactly what the Layer-1 scorecard displays (a single blended
figure per metric per period), so a segment-level plan would be inventing
detail nothing consumes. Ten of the eleven Layer-1 nodes get a plan row; see
config.PLAN_PILLAR_BY_METRIC for why Activation is excluded. 10 metrics x
config.N_MONTHS = 360 rows.

WHY THE PLAN IS NOT DERIVED FROM THE OTHER GENERATORS' OUTPUT
------------------------------------------------------------
A real plan is set *before* the period it covers, and is deliberately
decoupled from what actually happens -- that decoupling is the entire reason
a plan-vs-actual comparison carries information. If this module computed a
plan by reading the other generators' realized per-month draws, variance from
plan would be circular: trivially ~0 where the plan was copied, and
fabricated-looking where it was perturbed away from a value the "planner"
could not have known.

That does not weaken the project's causal-wiring rule. The rule governs
*outcome* columns -- win/loss, churn, usage growth -- which represent
observed behaviour and must therefore be functions of their real drivers. A
plan/target is exogenous by definition: it is an input to the period, not an
outcome of it.

What the rule does still demand is that the plan be genuinely grounded rather
than arbitrary. Every anchor below is computed from one of three sources, and
each is named at its definition:
  * the QA plan's benchmark reference table
    (docs/acme-corp-phase1-data-qa-plan.md, "Grounding requirements"),
    segment ranges rolled up to a blended figure using this simulation's own
    account-count and ACV-mix constants;
  * another plan line that the metric tree defines this one in terms of --
    used for exactly two rows, expansion_consumption_revenue and
    contraction_churned_revenue, which the tree's NRR/GRR formulas define as
    the flows those two rates are made of. They are derived from the
    benchmark-blended nrr/grr anchors rather than estimated separately, so
    the two halves of the same identity cannot describe different worlds
    (see _contraction_churn_share / _expansion_share); or
  * where the benchmark table has no row at all, an explicit resolved
    decision built from config.py's business-scale constants -- the same
    citation style config.py already uses for numbers the reference docs
    state as a rule or a range rather than a figure.

POINT-IN-TIME SAFETY
--------------------
Guaranteed by construction, and stated explicitly because every Phase 4
consumer depends on it. The plan for month M is produced by an annual
top-down process that runs before that plan year begins: it reads nothing but
config.py constants, the calendar, and a seeded rng. This module takes no
DataFrame arguments, performs no file I/O, and has no access to any realized
value from month M or later. There is no path by which a future observation
can leak into a plan row.

METHODOLOGY
-----------
An annual planning cycle, three cycles deep:
  * 2023, the first simulated year, has no prior in-simulation history to
    plan from, so each metric's monthly anchor is grounded directly in the
    benchmark table (blended) or in config.py's business-scale arithmetic.
  * 2024 and 2025 escalate the prior year's anchor by one metric-specific
    annual rate -- revenue lines growing, efficiency and durability lines
    improving modestly or holding near their benchmark band. Purely top-down;
    no realized value is consulted.
The two derived flow lines are the one exception to the single-rate shape:
expansion_consumption_revenue and contraction_churned_revenue are re-derived
per plan year from that year's own nrr/grr level, so that each year's flow
shares compound to that year's durability rows exactly rather than to the
2023 rows approximately. plan_anchors() still reports a single escalation
rate for them, as the compound annual rate the derivation works out to --
that figure is a summary of the three derived levels, not the mechanism.
Within a year the monthly values carry a mild intra-year ramp (dollar lines
only, as a plan built quarter-over-quarter would), this simulation's own
seasonality curve, and small independent seeded noise -- so the twelve months
inside a plan year are not a flat repeated number. Seasonality and the ramp
are both mean-normalized, so the year's average lands exactly on its anchor
and the grounding arithmetic above stays auditable.

UNITS
-----
Matched to what the Phase 2 marts already expose, so a future mart join is an
equals comparison rather than a unit conversion:
  * new_logo / expansion / contraction_churned_revenue -- USD, whole dollars
    of monthly MRR movement, matching mrr_by_account_month and
    mart_growth_bridge. Contraction+churn is stored as a POSITIVE magnitude,
    matching int_revenue_movements' contraction/churn buckets; the readout
    renders it with a leading minus, which is a display convention.
  * magic_number, am_efficiency -- dimensionless multiples.
  * consumption_payback -- months.
  * onboarding_cs_efficiency -- AM/CS touchpoints per automated Action, the
    metric tree's own orientation ("Manual AM/CS touchpoints / volume of
    automated Actions delivered") and the orientation
    mart_efficiency.onboarding_cs_efficiency_ratio computes. Lower is better.
    The design brief's sample readout quotes the reciprocal (Actions/touch)
    for readability; the stored value follows the tree and the mart.
  * nrr, grr, logo_retention -- decimal rates (1.15, not 115), matching
    mart_durability. These are ANNUAL-equivalent rates, which is what the
    benchmark table states and what the readout reports; mart_durability
    currently exposes all three at monthly grain, so the variance-diagnostic
    engine must annualise (or compute a trailing-twelve-month figure) before
    comparing. Flagged here rather than resolved by quietly planning a
    monthly rate no one would recognise as NRR.
"""
import numpy as np
import pandas as pd

from . import config

# =====================================================================
# Planning assumptions
#
# These live here rather than in config.py because they are used by this
# module alone -- they shape a plan, not the simulation. Each is either
# read off a config.py constant or flagged as this module's own resolved
# decision, matching config.py's citation style.
# =====================================================================

# Share of config.FINAL_TOTAL_CUSTOMERS that predates SIM_START. The QA plan
# calls for "a modest cohort of accounts seeded with already-established,
# staggered tenure" and config.EARLIEST_POSSIBLE_ACCOUNT_DATE gives that
# cohort a three-year runway, but neither states its size -- own resolved
# decision. Everything else is planned to be acquired inside the window.
PLAN_ESTABLISHED_COHORT_SHARE = 0.20

# Where that established cohort sits on the maturity curve at SIM_START,
# as a fraction of a fully-ramped, fully-migrated account's MRR. Staggered
# tenure means the cohort averages out mid-maturity rather than fully
# matured -- own resolved decision.
PLAN_ESTABLISHED_MATURITY_FACTOR = 0.75

# Year-over-year growth in new-account acquisition. Own resolved decision:
# strong but decelerating relative to the revenue base's own growth rate,
# which is the normal shape of a plan whose later years lean more on the
# installed base than on logo count.
PLAN_NEW_ACCOUNT_ANNUAL_GROWTH = 0.40

# A new account's first recognised month as a fraction of its segment
# baseline. Read directly off usage.py's ramp: the first ramp control value
# is 0.1 * USAGE_BASELINE_ACTIONS, climbing to the full baseline over
# config.ACTIVATION_RAMP_MONTHS. Planning new-logo revenue at the full
# baseline would overstate it several-fold.
PLAN_ENTRY_RAMP_FIRST_MONTH_FRACTION = 0.10

# THE TWO MONTHLY FLOW SHARES ARE DERIVED, NOT SET
# -------------------------------------------------
# Gross monthly expansion and gross monthly contraction+churn, each as a
# share of the revenue base, are what expansion_consumption_revenue and
# contraction_churned_revenue are planned off. They are NOT independent
# planning assumptions, and there is deliberately no constant for either
# here. docs/acme-corp-gtm-metric-tree.md's Durability pillar defines NRR
# and GRR as those exact flows:
#     GRR = (Starting - Contraction - Churn) / Starting
#     NRR = (Starting - Contraction - Churn + Expansion) / Starting
# so a share chosen independently of the nrr/grr anchors is a second,
# contradicting statement of the same fact. Both shares are therefore solved
# backwards out of the benchmark-blended nrr/grr anchors -- see
# _contraction_churn_share() and _expansion_share() below. The benchmark
# reference table is the authority in that direction and not the reverse:
# the QA plan records that of its durability rows "only the NRR row is
# backed by cited research."
#
# WHAT THE DERIVED EXPANSION SHARE DOES *NOT* RECONCILE WITH, for a future
# reader. A bottom-up read of config.py's three expansion mechanisms --
# ramp progression (each cohort climbing 0.1x -> 1.0x of baseline over
# config.ACTIVATION_RAMP_MONTHS), config.MONTHLY_ORGANIC_GROWTH_RANGE's
# overage growth, and segment migration stepping an account's MRR up a full
# band for the share config.MIG_RATE_* migrates -- lands near 9% of base per
# month, roughly 4.6x the ~1.95%/month the NRR anchor implies. The gap is
# real and is not split the difference: a benchmark NRR band describes a
# mature installed base, while the bottom-up figure is dominated by new
# cohorts ramping inside a revenue base planned to grow ~88% a year, which
# is a different population. The benchmark is used because it is the
# doc-grounded, cited one and because nrr/grr must reconcile to the same
# flows either way; the bottom-up figure is recorded here as the size of the
# modelling tension, not resolved.

# Fully-loaded annual AM cost, for the AM-efficiency denominator. Own
# resolved decision -- no comp or cost data exists anywhere in the raw
# sources (the same gap mart_efficiency flags when it leaves am_cost and
# magic_number null), so a plan for this metric has to assume one.
PLAN_AM_FULLY_LOADED_COST_ANNUAL = 180_000

# Expansion share of base used by the AM-efficiency numerator ONLY. This is
# the bottom-up 9%/month figure described in the flow-share note above, not
# the NRR-derived share the expansion plan line now uses. Kept separate and
# deliberately: am_efficiency's anchor is a standalone target built to land
# on a config-implied terminal figure, and re-pointing it at the derived
# share would move a metric this change is not scoped to touch. KNOWN
# DIVERGENCE: the metric tree defines AM efficiency as expansion consumption
# revenue / AM cost, so the numerator here is ~4.6x the expansion plan line
# for the same month. Resolve when am_efficiency's anchor is next revisited.
PLAN_AM_EXPANSION_SHARE_OF_BASE = 0.090

# Mild intra-year ramp for the dollar lines: the plan builds through the
# year rather than repeating one number twelve times. Expressed as the total
# spread from January to December, mean-normalised to 1.0 -- own resolved
# decision. Rate metrics get no ramp; a retention or efficiency target is
# set for the year, not ramped into.
PLAN_INTRA_YEAR_RAMP = 0.30

# How much of config.SEASONALITY_BY_MONTH each metric family carries. Dollar
# lines take it in full. Efficiency ratios take a damped share, since
# numerator and denominator both move with the season and partly cancel.
# Durability rates take none -- a retention plan is flat within a year.
PLAN_SEASONALITY_WEIGHT = {"revenue": 1.0, "efficiency": 0.25, "durability": 0.0}

# Month-to-month plan noise (multiplicative, 1-sigma). Tightest on the
# durability rates, which sit inside narrow benchmark bands.
PLAN_NOISE_SIGMA = {"revenue": 0.030, "efficiency": 0.015, "durability": 0.004}

PLAN_METRIC_FAMILY = {
    "new_logo_consumption_revenue": "revenue",
    "expansion_consumption_revenue": "revenue",
    "contraction_churned_revenue": "revenue",
    "magic_number": "efficiency",
    "consumption_payback": "efficiency",
    "onboarding_cs_efficiency": "efficiency",
    "am_efficiency": "efficiency",
    "nrr": "durability",
    "grr": "durability",
    "logo_retention": "durability",
}

# Metrics where a weaker month makes the number go UP, not down: payback
# lengthens and touch-per-Action rises when Action volume dips. Their
# seasonal factor is inverted.
PLAN_INVERSE_SEASONAL = {"consumption_payback", "onboarding_cs_efficiency"}

# Benchmark reference table midpoints (docs/acme-corp-phase1-data-qa-plan.md,
# "Grounding requirements"). SMB has no win-rate, magic-number or payback
# concept in that table, so those two roll up across Commercial and
# Enterprise only.
BENCHMARK_NRR = {"SMB": 0.965, "Commercial": 1.075, "Enterprise": 1.215}
BENCHMARK_GRR = {"SMB": 0.825, "Commercial": 0.900, "Enterprise": 0.935}
BENCHMARK_LOGO_RETENTION = {"SMB": 0.800, "Commercial": 0.905, "Enterprise": 0.950}
BENCHMARK_MAGIC_NUMBER = {"Commercial": 0.80, "Enterprise": 0.80}
BENCHMARK_CONSUMPTION_PAYBACK_MONTHS = {"Commercial": 16.0, "Enterprise": 11.0}

# Annual change applied to each 2023 anchor, compounding into 2024 and 2025.
# Sign follows the metric's own "better" direction. Bases, in order:
#   new_logo            -- PLAN_NEW_ACCOUNT_ANNUAL_GROWTH (logo count is the
#                          driver; entry MRR per logo is held flat).
#   expansion /
#   contraction_churned -- NOT entries in this table. Both lines are
#                          re-derived per plan year from that year's nrr/grr
#                          level against the planned revenue base, so their
#                          escalation is the product of two rates rather
#                          than one constant. plan_anchors() fills in the
#                          compound annual rate that derivation works out
#                          to, for reporting only.
#   magic_number        -- own resolved decision: modest annual improvement
#                          that keeps the plan inside the benchmark's
#                          ~0.7-0.9 band for all three years.
#   consumption_payback -- own resolved decision: shortens toward the
#                          benchmark-blended figure as the Enterprise mix
#                          deepens.
#   onboarding_cs_eff.  -- own resolved decision: converges toward the
#                          config-implied steady-state touch/Action ratio as
#                          the installed base finishes ramping.
#   am_efficiency       -- own resolved decision: AM book size grows faster
#                          than AM headcount, so the ratio improves slowly.
#   nrr / grr /
#   logo_retention      -- own resolved decisions: small annual improvement
#                          as revenue mix shifts toward Enterprise, whose
#                          benchmark rows are the strongest of the three.
PLAN_ANNUAL_CHANGE = {
    "new_logo_consumption_revenue": PLAN_NEW_ACCOUNT_ANNUAL_GROWTH,
    "magic_number": 0.030,
    "consumption_payback": -0.030,
    "onboarding_cs_efficiency": -0.070,
    "am_efficiency": 0.040,
    "nrr": 0.010,
    "grr": 0.008,
    "logo_retention": 0.015,
}


# =====================================================================
# Top-down derivations from config.py
# =====================================================================

def _segment_monthly_mrr() -> dict:
    """Steady-state MRR per account by segment, from config's usage
    baseline and per-Action price. Lands mid-band inside every
    config.ACV_RANGES band when annualised."""
    return {
        segment: actions * config.PRICE_PER_ACTION
        for segment, actions in config.USAGE_BASELINE_ACTIONS.items()
    }


def _entry_cohort_mix() -> dict:
    """Segment mix of accounts *as acquired*, solved backwards from the
    FINAL_* targets through config.MIG_RATE_*.

    This differs sharply from the final mix and the distinction matters: an
    account enters overwhelmingly as SMB and migrates up, so new-logo
    revenue per acquired logo is far below the final-mix blended figure.
    Planning off the final mix would overstate new logo several-fold.
    """
    entry_smb = config.FINAL_SMB / (1 - config.MIG_RATE_SMB_TO_COMMERCIAL)
    commercial_pool = config.FINAL_COMMERCIAL / (1 - config.MIG_RATE_COMMERCIAL_TO_ENTERPRISE)
    entry_commercial = commercial_pool - entry_smb * config.MIG_RATE_SMB_TO_COMMERCIAL
    entry_enterprise = config.FINAL_ENTERPRISE - commercial_pool * config.MIG_RATE_COMMERCIAL_TO_ENTERPRISE

    counts = {"SMB": entry_smb, "Commercial": entry_commercial, "Enterprise": entry_enterprise}
    total = sum(counts.values())
    return {segment: count / total for segment, count in counts.items()}


def _final_revenue_mix() -> dict:
    """Share of terminal MRR by segment -- the weighting used to blend the
    benchmark table's per-segment NRR/GRR/payback rows into one
    company-wide figure."""
    mrr = _segment_monthly_mrr()
    counts = {
        "SMB": config.FINAL_SMB,
        "Commercial": config.FINAL_COMMERCIAL,
        "Enterprise": config.FINAL_ENTERPRISE,
    }
    revenue = {segment: counts[segment] * mrr[segment] for segment in counts}
    total = sum(revenue.values())
    return {segment: value / total for segment, value in revenue.items()}


def _final_logo_mix() -> dict:
    """Share of terminal accounts by segment -- the weighting for logo
    retention, which is a count ratio, not a dollar ratio."""
    counts = {
        "SMB": config.FINAL_SMB,
        "Commercial": config.FINAL_COMMERCIAL,
        "Enterprise": config.FINAL_ENTERPRISE,
    }
    total = sum(counts.values())
    return {segment: count / total for segment, count in counts.items()}


def _blend(per_segment: dict, weights: dict) -> float:
    """Weighted blend, renormalised over whichever segments the benchmark
    table actually covers (it marks SMB 'n/a' for magic number and
    payback)."""
    covered = {s: w for s, w in weights.items() if s in per_segment}
    total_weight = sum(covered.values())
    return sum(per_segment[s] * w for s, w in covered.items()) / total_weight


def _terminal_base_mrr() -> float:
    mrr = _segment_monthly_mrr()
    return (
        config.FINAL_SMB * mrr["SMB"]
        + config.FINAL_COMMERCIAL * mrr["Commercial"]
        + config.FINAL_ENTERPRISE * mrr["Enterprise"]
    )


def _blended_entry_mrr() -> float:
    """Steady-state MRR of one newly acquired account, at the entry mix."""
    mrr = _segment_monthly_mrr()
    return sum(share * mrr[segment] for segment, share in _entry_cohort_mix().items())


def _base_mrr_plan() -> dict:
    """The planned consumption-revenue base, top-down.

    Anchored at both ends by config: it starts from the seeded established
    cohort's value at SIM_START and is planned to reach the terminal base
    implied by the FINAL_* account targets at SIM_END. One constant annual
    growth rate connects them. Returns the start-of-year base per plan year
    plus that growth rate.
    """
    established_accounts = config.FINAL_TOTAL_CUSTOMERS * PLAN_ESTABLISHED_COHORT_SHARE
    blended_mature_mrr = _terminal_base_mrr() / config.FINAL_TOTAL_CUSTOMERS
    start_base = established_accounts * blended_mature_mrr * PLAN_ESTABLISHED_MATURITY_FACTOR

    n_years = config.N_MONTHS // 12
    growth = (_terminal_base_mrr() / start_base) ** (1 / n_years) - 1

    start_of_year = {}
    base = start_base
    for offset in range(n_years):
        start_of_year[config.SIM_START.year + offset] = base
        base *= 1 + growth
    return {"start_of_year": start_of_year, "annual_growth": growth}


def _average_base_mrr(year: int) -> float:
    """Geometric midpoint of a plan year's opening and closing base -- the
    right average for a quantity compounding within the year."""
    plan = _base_mrr_plan()
    opening = plan["start_of_year"][year]
    closing = opening * (1 + plan["annual_growth"])
    return (opening * closing) ** 0.5


def _durability_plan_rate(metric: str, year: int) -> float:
    """The plan's own annual-equivalent nrr/grr level for `year`.

    Deliberately reconstructed from the same two inputs plan_anchors() and
    the monthly shaping loop use -- the benchmark-blended anchor and
    PLAN_ANNUAL_CHANGE -- rather than being a second copy of the number.
    This is the single point the two derived flow shares below read from, so
    a change to either benchmark table or to a durability escalation rate
    moves the flow lines with it automatically.
    """
    benchmark = {"nrr": BENCHMARK_NRR, "grr": BENCHMARK_GRR}[metric]
    anchor = _blend(benchmark, _final_revenue_mix())
    return anchor * (1 + PLAN_ANNUAL_CHANGE[metric]) ** (year - config.SIM_START.year)


def _contraction_churn_share(year: int) -> float:
    """Gross monthly contraction + churn as a share of the revenue base,
    solved out of that plan year's GRR.

    docs/acme-corp-gtm-metric-tree.md, Durability:
        GRR = (Starting - Contraction - Churn) / Starting
    so one month retains a (1 - share) fraction of the base and twelve of
    them compound:
        (1 - share) ** 12 = GRR      =>      share = 1 - GRR ** (1/12)
    Exact, not fitted. At the 2023 anchor this is ~0.76%/month.

    Worth holding in mind when reading the number, though it is not what
    sets it: the share covers two distinct mechanisms, config.ANNUAL_CHURN_RATE
    revenue-weighted as outright account loss, plus
    config.DECLINE_MONTHS_BEFORE_CHURN's pre-churn fade and ordinary
    month-to-month usage variance as within-account contraction. Totalling
    those two bottom-up would produce a second, competing statement of GRR,
    so the split is read out of GRR rather than into it.
    """
    return 1 - _durability_plan_rate("grr", year) ** (1 / 12)


def _expansion_share(year: int) -> float:
    """Gross monthly expansion as a share of the revenue base, solved out of
    that plan year's NRR netted against the contraction share above.

    docs/acme-corp-gtm-metric-tree.md, Durability:
        NRR = (Starting - Contraction - Churn + Expansion) / Starting
    so one month's net factor is (1 + expansion_share - contraction_share)
    and twelve of them compound:
        (1 + e - c) ** 12 = NRR      =>      e = NRR ** (1/12) - 1 + c
    Closed-form and exact -- both flows are expressed against the same
    starting base within a month, so netting them introduces no error of its
    own and no iterative solve is needed. At the 2023 anchors this is
    ~1.95%/month, against ~0.76% of contraction, i.e. a planned net +1.19%
    per month, which is what NRR 1.1525 means. See the flow-share note at
    the top of this module for how that compares with a bottom-up read.
    """
    return _durability_plan_rate("nrr", year) ** (1 / 12) - 1 + _contraction_churn_share(year)


# The two plan lines whose level is re-derived per plan year rather than
# escalated off a 2023 anchor by one rate.
_DERIVED_FLOW_SHARE = {
    "expansion_consumption_revenue": _expansion_share,
    "contraction_churned_revenue": _contraction_churn_share,
}


def _flow_line_level(metric: str, year: int) -> float:
    """That plan year's monthly dollar level for one of the two derived flow
    lines: the year's average revenue base times the year's derived share."""
    return _average_base_mrr(year) * _DERIVED_FLOW_SHARE[metric](year)


def _new_accounts_per_month(year: int) -> float:
    """Planned new-logo acquisitions per month.

    config.FINAL_TOTAL_CUSTOMERS net of the established cohort is the volume
    to be acquired inside the window; PLAN_NEW_ACCOUNT_ANNUAL_GROWTH shapes
    how it is spread across the three plan years.
    """
    in_window = config.FINAL_TOTAL_CUSTOMERS * (1 - PLAN_ESTABLISHED_COHORT_SHARE)
    n_years = config.N_MONTHS // 12
    growth = PLAN_NEW_ACCOUNT_ANNUAL_GROWTH
    year_one = in_window / sum((1 + growth) ** offset for offset in range(n_years))
    offset = year - config.SIM_START.year
    return year_one * (1 + growth) ** offset / 12


def _steady_state_touch_per_action() -> float:
    """config-implied touchpoints per automated Action at the terminal
    account population: config.AM_TOUCH_RATE_BASELINE against
    config.USAGE_BASELINE_ACTIONS. SMB has no AM at all, so it contributes
    Actions to the denominator and nothing to the numerator -- which is a
    real, meaningful zero, the same reading mart_efficiency takes."""
    touches = (
        config.FINAL_COMMERCIAL * config.AM_TOUCH_RATE_BASELINE["Commercial"]
        + config.FINAL_ENTERPRISE * config.AM_TOUCH_RATE_BASELINE["Enterprise"]
    )
    actions = (
        config.FINAL_SMB * config.USAGE_BASELINE_ACTIONS["SMB"]
        + config.FINAL_COMMERCIAL * config.USAGE_BASELINE_ACTIONS["Commercial"]
        + config.FINAL_ENTERPRISE * config.USAGE_BASELINE_ACTIONS["Enterprise"]
    )
    return touches / actions


def _terminal_am_efficiency() -> float:
    """config-implied expansion ARR per dollar of AM cost at the terminal
    population. AM headcount comes from config's book sizes
    (FINAL_COMMERCIAL / COMMERCIAL_BOOK_SIZE, FINAL_ENTERPRISE /
    ENTERPRISE_BOOK_SIZE); SMB has no AM coverage."""
    am_headcount = (
        config.FINAL_COMMERCIAL / config.COMMERCIAL_BOOK_SIZE
        + config.FINAL_ENTERPRISE / config.ENTERPRISE_BOOK_SIZE
    )
    am_cost_annual = am_headcount * PLAN_AM_FULLY_LOADED_COST_ANNUAL
    final_year = config.SIM_START.year + config.N_MONTHS // 12 - 1
    expansion_arr = _average_base_mrr(final_year) * PLAN_AM_EXPANSION_SHARE_OF_BASE * 12
    return expansion_arr / am_cost_annual


def plan_anchors() -> dict:
    """The 2023 monthly anchor for each of the ten metrics, and the annual
    rate that escalates it. Every value here is computed from config.py
    constants and the benchmark reference table -- nothing reads a
    generated CSV.
    """
    first_year = config.SIM_START.year
    last_year = first_year + config.N_MONTHS // 12 - 1
    n_escalations = last_year - first_year

    anchors = {
        # --- Growth (USD monthly MRR movement) ---------------------------
        # New logos acquired per month x that logo's steady-state MRR at the
        # entry mix x its first ramp month's fraction of baseline.
        "new_logo_consumption_revenue": (
            _new_accounts_per_month(first_year)
            * _blended_entry_mrr()
            * PLAN_ENTRY_RAMP_FIRST_MONTH_FRACTION
        ),
        # Both derived from the nrr/grr anchors below, not set here -- the
        # year's average revenue base x the monthly flow share that
        # compounds to that year's durability rate over twelve months.
        "expansion_consumption_revenue": _flow_line_level(
            "expansion_consumption_revenue", first_year),
        "contraction_churned_revenue": _flow_line_level(
            "contraction_churned_revenue", first_year),

        # --- Efficiency ---------------------------------------------------
        # Benchmark table: Commercial and Enterprise both ~0.7-0.9, SMB n/a.
        # Planned below the blended midpoint -- a company planning to grow
        # its revenue base ~88% a year is deliberately outspending its
        # steady-state efficiency. Own resolved decision on the discount.
        "magic_number": _blend(BENCHMARK_MAGIC_NUMBER, _final_revenue_mix()) * 0.9375,
        # Benchmark table: Commercial ~14-18mo, Enterprise ~9-13mo, SMB n/a.
        # Planned above the blended midpoint in year one, since the early
        # revenue mix is less Enterprise-weighted than the terminal mix the
        # blend uses. Own resolved decision on the premium.
        "consumption_payback": _blend(
            BENCHMARK_CONSUMPTION_PAYBACK_MONTHS, _final_revenue_mix()
        ) * 1.08,
        # No benchmark row exists. Anchored on the config-implied
        # steady-state ratio, marked up because year-one accounts are still
        # mid-ramp (fewer Actions per account, same AM cadence) so the ratio
        # starts worse and converges down. Own resolved decision on the
        # markup.
        "onboarding_cs_efficiency": _steady_state_touch_per_action() * 1.573,
        # No benchmark row exists. Set so the final plan year lands on the
        # config-implied terminal figure, working backwards through the
        # annual improvement rate. Own resolved decision throughout.
        "am_efficiency": _terminal_am_efficiency()
        / (1 + PLAN_ANNUAL_CHANGE["am_efficiency"]) ** n_escalations,

        # --- Durability (annual-equivalent decimal rates) -----------------
        # Benchmark table midpoints, revenue-weighted for the two dollar
        # ratios and logo-weighted for the count ratio.
        "nrr": _blend(BENCHMARK_NRR, _final_revenue_mix()),
        "grr": _blend(BENCHMARK_GRR, _final_revenue_mix()),
        "logo_retention": _blend(BENCHMARK_LOGO_RETENTION, _final_logo_mix()),
    }

    annual_change = dict(PLAN_ANNUAL_CHANGE)
    # The two derived flow lines carry two escalations at once: the revenue
    # base grows at base_growth, and the share of it they represent moves as
    # that year's nrr/grr improves (contraction shrinking faster than
    # expansion grows). That product is not one constant rate, so the level
    # is re-derived per year in generate_gtm_plan_targets() and the figure
    # reported here is the compound annual rate the three derived levels
    # work out to -- a summary of the derivation, not its mechanism.
    for metric in _DERIVED_FLOW_SHARE:
        first_level = _flow_line_level(metric, first_year)
        last_level = _flow_line_level(metric, last_year)
        annual_change[metric] = (last_level / first_level) ** (1 / n_escalations) - 1

    return {metric: (anchors[metric], annual_change[metric]) for metric in config.PLAN_LAYER1_METRICS}


# =====================================================================
# Monthly shaping
# =====================================================================

def _normalised_seasonality() -> dict:
    """config.SEASONALITY_BY_MONTH rescaled to mean exactly 1.0, so
    applying it cannot shift a plan year's average off its anchor."""
    mean = sum(config.SEASONALITY_BY_MONTH.values()) / len(config.SEASONALITY_BY_MONTH)
    return {month: factor / mean for month, factor in config.SEASONALITY_BY_MONTH.items()}


def _intra_year_ramp(month_of_year: int) -> float:
    """Linear January-to-December build, mean exactly 1.0 across the year."""
    position = (month_of_year - 1) / 11
    return 1 - PLAN_INTRA_YEAR_RAMP / 2 + PLAN_INTRA_YEAR_RAMP * position


def _round_for_metric(metric: str, value: float) -> float:
    """Plans are published at the precision a planner would state them."""
    family = PLAN_METRIC_FAMILY[metric]
    if family == "revenue":
        return float(round(value, -2))
    if metric == "consumption_payback":
        return float(round(value, 2))
    if metric == "onboarding_cs_efficiency":
        return float(round(value, 10))
    return float(round(value, 4))


def generate_gtm_plan_targets(rng: np.random.Generator) -> pd.DataFrame:
    """Build the blended monthly plan table.

    Grain: one row per (layer1_metric, month), month being the first of the
    month. Pure -- takes only an rng, reads no file, and touches no other
    generator's output, which is what makes the point-in-time guarantee in
    the module docstring structural rather than a promise.
    """
    anchors = plan_anchors()
    seasonality = _normalised_seasonality()
    months = pd.date_range(config.SIM_START, periods=config.N_MONTHS, freq="MS")

    rows = []
    for metric in config.PLAN_LAYER1_METRICS:
        anchor, annual_change = anchors[metric]
        family = PLAN_METRIC_FAMILY[metric]
        seasonal_weight = PLAN_SEASONALITY_WEIGHT[family]
        noise_sigma = PLAN_NOISE_SIGMA[family]
        ramp_applies = family == "revenue"

        for month in months:
            year_offset = month.year - config.SIM_START.year
            # The two derived flow lines are re-derived at each plan year's
            # own nrr/grr level rather than escalated off the 2023 anchor by
            # a single rate, so every year's flow shares compound to that
            # year's durability rows exactly, not just 2023's.
            annual_level = (_flow_line_level(metric, month.year)
                            if metric in _DERIVED_FLOW_SHARE
                            else anchor * (1 + annual_change) ** year_offset)

            seasonal = seasonality[month.month]
            if metric in PLAN_INVERSE_SEASONAL:
                seasonal = 1 / seasonal
            seasonal = 1 + seasonal_weight * (seasonal - 1)

            ramp = _intra_year_ramp(month.month) if ramp_applies else 1.0
            noise = float(rng.normal(1.0, noise_sigma))

            rows.append({
                "layer1_metric": metric,
                "month": month.date(),
                "plan_value": _round_for_metric(metric, annual_level * seasonal * ramp * noise),
                "pillar": config.PLAN_PILLAR_BY_METRIC[metric],
            })

    return pd.DataFrame(rows)
