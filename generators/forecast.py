"""fact_forecast_submissions + cro_forecast_adjustments generator.

Build spec Section 5, "Forecasting": `fact_forecast_submissions`
(opportunity, snapshot_date, rep_forecast_category,
manager_forecast_category -- "a weekly snapshot, not a single mutable
field, since the gap between rep and manager categorization is itself a
signal"); `cro_forecast_adjustments` (period, segment, adjustment_amount,
reason, timestamp -- "a logged, reasoned override, never silent").

WHAT THIS TABLE IS, AND WHAT IT IS NOT
--------------------------------------
A forecast submission is a *judgement recorded at a point in time*, not a
property of the deal. Two people look at the same open opportunity on the
same Friday and file two categorisations of it; the deal closes weeks or
months later. Everything here therefore follows one rule: a row dated
`snapshot_date` may depend only on what was observable on or before
`snapshot_date`.

That rule is what makes the table worth generating at all. The project's
standing requirement (CLAUDE.md, QA plan grounding requirement 2) is that
outcome-adjacent columns be actual functions of their real drivers rather
than independent draws. A forecast category is outcome-adjacent in a
specific way: it must carry genuine information about the eventual
outcome, but only the information a forecaster could actually have had.
Both halves matter. A category drawn independently of everything gives a
downstream forecast model nothing to learn; a category derived from the
realized outcome gives it a leak to exploit and teaches it nothing about
forecasting.

THE LATENT WIN PROPENSITY
-------------------------
Both categories are drawn from one latent per-(opportunity, snapshot)
win propensity, built on the log-odds scale from drivers that are
genuinely observable as of the snapshot and that genuinely move the
outcome in the data already generated upstream:

  * The segment/type's trailing realized close rate over the twelve
    months before the snapshot -- the forecaster's live prior, shrunk
    toward the benchmark base rate so a thin trailing window falls back
    to the benchmark instead of chasing noise. This is the one place any
    `is_won` value is read, and only ever for a *different* opportunity
    that had already closed before the snapshot date: a real forecaster
    knows how the team's last four quarters landed, and that knowledge is
    the single most-used input to a forecast call.
  * Current stage, from `opportunity_stage_history` -- the latest stage
    whose `entered_date` is on or before the snapshot. Later stage reads
    as higher confidence. This is the standard forecasting driver and the
    main reason a deal's category firms up as it ages.
  * Stage-relative stall -- days in the current stage against the days a
    deal of this segment and type would typically spend in one stage
    (its expected cycle length, config.CYCLE_LENGTH_DAYS and the
    renewal/expansion notice windows, divided by its stage count). Time
    piling up in one stage reads as lower confidence.
  * POC outcome (Enterprise new business), once the POC has actually
    concluded -- gated on the deal having moved past the POC stage, or
    having sat in it at least _POC_REVEAL_LAG_DAYS. The weight is the
    Bayesian log-likelihood ratio implied by config.POC_PASS_RATE_GIVEN_
    WON / _GIVEN_LOST, so a revealed pass moves the propensity by exactly
    as much as the upstream generator's own conditional rates justify.
  * Rep ramp status at the snapshot (hire_date vs. snapshot_date, first
    two quarters ramping per build spec Section 4). Two separate effects,
    deliberately not conflated: a ramping rep's deals carry a genuinely
    lower propensity (below), and a ramping rep reports more optimistically
    on top of that (further below).
  * Account usage trajectory (renewal and expansion only) -- the last
    complete month's Actions against the three months before it, read from
    `usage_monthly`. An account whose consumption is fading ahead of its
    renewal is the single strongest observable signal in this data, and it
    is observable: usage for a month is known once that month has ended.
    Not applied to new business, where the buyer is not yet consuming
    anything.
  * One per-opportunity latent effect, constant across that opportunity's
    snapshots, so successive weekly calls on the same deal are correlated
    rather than independently re-rolled.

DELIBERATELY NOT USED AS PROPENSITY INPUTS
------------------------------------------
  * `is_won` of the opportunity being forecast, or of any opportunity
    that had not already closed on the snapshot date. The trailing close
    rate above is the only use of the column, and it is bounded to
    strictly-prior closes by construction (see _TrailingCloseRate).
  * `loss_reason` -- an outcome field, populated only at close.
  * `opportunities.forecast_category` -- a single close-time field, not a
    point-in-time series. This module derives nothing from it and shares
    no generation logic with it; it reuses only the four-value vocabulary
    (Commit / Best Case / Pipeline / Omitted), which is the taxonomy
    already established for this schema.
  * `amount`, `list_price`, `discount_rate` -- `amount` is the final
    negotiated figure (opportunities.py sets it together with
    `discount_rate` at generation time, from the account's committed
    volume for a won deal and from a separate draw for a lost one), so
    none of the three can be treated as a stable pre-close observation.
    `amount` appears in this module in exactly one place -- the aggregate
    dollar roll-ups behind the CRO overlay -- because a coverage ratio is
    by definition computed on CRM-stated deal sizes, and that roll-up is
    a top-down judgement about a whole segment-quarter, never a per-deal
    win prediction.
  * `close_date` -- used only to terminate an opportunity's snapshot
    series (a submission exists only while the deal is open, which is a
    structural property of any CRM snapshot table) and never as an input
    to the propensity. Cycle length is drawn from the same distribution
    for won and lost deals upstream, so the length of the series carries
    no outcome information either.

REP VS. MANAGER
---------------
The rep's call is the propensity plus a systematic optimism bias, plus
that rep's own persistent bias, plus the wider noise of a single person
reading their own deal. The manager's call is the same propensity, near
calibrated, with tighter noise -- and an explicit skepticism rule: a
confident rep call (Commit or Best Case) on a deal whose underlying
propensity is weak gets pulled down at least one notch most of the time.

That rule is the mechanism behind the property the build spec is after
when it calls the rep/manager gap "itself a signal": opportunities where
the manager downgrades a confident rep call must actually close at a
lower rate than opportunities where the two agree. Because the downgrade
is triggered by a weak propensity, and the propensity is built from
drivers that genuinely move the outcome upstream, the gap is a real
relationship in the data rather than a decorative one.

GRAIN
-----
  * `fact_forecast_submissions` -- one row per (opportunity_id,
    snapshot_date). Weekly (Friday, the standing forecast call), for
    every Commercial and Enterprise opportunity, for every Friday the
    opportunity was open. SMB is out of scope by construction: build spec
    Section 1 gives it a no-touch motion closing in 0-7 days with no rep
    and no stage history, so there is no weekly forecast cadence for an
    SMB deal to have.

    Snapshot dates are bounded to the 36-month simulation window (build
    spec Section 4, config.SIM_START through the end of config.SIM_END's
    month): the weekly forecast call is a process that runs across the
    reporting period the rest of the portfolio reports on, the same
    window gtm_plan_targets covers. Opportunities belonging to the
    established-tenure cohort that seeds the simulation with history
    (QA plan design decisions) closed before that window opened and carry
    no submissions.
  * `cro_forecast_adjustments` -- at most one row per (period, segment),
    period being a fiscal quarter and segment being Commercial or
    Enterprise. Sparse by design: an override is logged only when the
    top-down read of that segment-quarter actually differs materially
    from the bottoms-up roll-up.

The latent propensity is deliberately not stored. Recovering it from the
two categorisations is the downstream forecast artifact's job.
"""
import numpy as np
import pandas as pd

from . import config

# =====================================================================
# Forecast taxonomy
#
# The four-value vocabulary already used by opportunities.forecast_category
# and by the leadership readout. Ordered weakest to strongest; the index
# is the rank the rep/manager comparison is made on.
# =====================================================================
FORECAST_CATEGORIES = ("Omitted", "Pipeline", "Best Case", "Commit")
_RANK = {name: i for i, name in enumerate(FORECAST_CATEGORIES)}

# Probability cut points mapping a perceived win probability to a
# category -- own resolved decision. Neither reference doc states cut
# points; these are the conventional pipeline-review bands (a Commit is a
# deal the owner would be surprised to lose; Omitted is one they have
# effectively written off), chosen so that a new-business deal sitting at
# its segment's base win rate (config.NEW_BUSINESS_WIN_RATE_TARGET, 25-30%)
# lands in Pipeline at creation and has to earn its way up.
_CATEGORY_CUTS = ((0.70, "Commit"), (0.40, "Best Case"), (0.15, "Pipeline"))

# Standing weekly forecast call. Friday is the convention this simulation
# adopts (own resolved decision); what matters downstream is that every
# opportunity is snapshotted on the same weekly grid, so a segment-wide
# roll-up on any given call date reads every open deal as of the same day.
_SNAPSHOT_FREQ = "W-FRI"


def _window_bounds():
    """The 36-month reporting window (build spec Section 4). config.SIM_END
    is the first of the last month in the window, so the exclusive upper
    bound is the first of the month after it."""
    start = pd.Timestamp(config.SIM_START)
    end = pd.Timestamp(config.SIM_END) + pd.DateOffset(months=1)
    return start, end

# =====================================================================
# Base win rates -- the forecaster's prior before any deal-specific
# evidence, by (segment, opportunity_type).
# =====================================================================
# New business: the QA plan benchmark table's win-rate row, as carried in
# config. Renewal: the complement of config.ANNUAL_CHURN_RATE, which is
# itself back-derived from the benchmark table's GRR/logo-retention rows.
# Expansion: own resolved decision. QA plan design decisions make an
# expansion opportunity a discrete AM-initiated event that formalises a
# committed minimum the account's own usage has already crossed, so it
# closes at a rate near the renewal ceiling rather than anywhere near a
# new-logo rate.
_EXPANSION_BASE_WIN_RATE = 0.92


def _base_win_rate(segment: str, opportunity_type: str) -> float:
    if opportunity_type == "new_business":
        return config.NEW_BUSINESS_WIN_RATE_TARGET[segment]
    if opportunity_type == "renewal":
        return 1.0 - config.ANNUAL_CHURN_RATE[segment]
    return _EXPANSION_BASE_WIN_RATE


# Trailing realized close rate: how the same segment and opportunity type
# actually landed over the twelve months before the call. Own resolved
# decision on both constants. Twelve months is the standard trailing
# window a forecast review quotes; the shrinkage pseudo-count expresses
# how much evidence it takes to move off the benchmark prior, and it
# removes any need for a hard minimum-sample cutoff -- a window holding
# nothing yields the benchmark exactly.
_TRAILING_WINDOW_DAYS = 365
_TRAILING_SHRINKAGE_PSEUDOCOUNT = 40


class _TrailingCloseRate:
    """Shrunk trailing close rate per (segment, opportunity_type), as of a
    date.

    This is the one component that reads `is_won`, and the read is bounded
    structurally: closes are indexed by `close_date` and every query takes
    a strict `close_date < as_of` slice, so no opportunity still open on
    the call date -- the one being forecast included -- can contribute.
    The pool is also bounded to the reporting window, because the
    established-tenure cohort that seeds the simulation carries won deals
    without their matching lost pipeline and is not a close rate anyone
    could have quoted.
    """

    def __init__(self, opportunities: pd.DataFrame, window_start: pd.Timestamp):
        self._index = {}
        pool = opportunities[opportunities["close_date"] >= window_start]
        for key, group in pool.groupby(["segment", "opportunity_type"], sort=False):
            ordered = group.sort_values("close_date")
            dates = ordered["close_date"].to_numpy()
            wins = np.concatenate([[0.0], np.cumsum(ordered["is_won"].to_numpy(dtype=float))])
            self._index[key] = (dates, wins)

    def rate(self, segment: str, opportunity_type: str, as_of: pd.Timestamp) -> float:
        base = _base_win_rate(segment, opportunity_type)
        entry = self._index.get((segment, opportunity_type))
        if entry is None:
            return base
        dates, wins = entry
        hi = int(np.searchsorted(dates, np.datetime64(as_of), side="left"))
        lo = int(np.searchsorted(
            dates, np.datetime64(as_of - pd.Timedelta(days=_TRAILING_WINDOW_DAYS)), side="left"
        ))
        n = hi - lo
        won = wins[hi] - wins[lo]
        k = _TRAILING_SHRINKAGE_PSEUDOCOUNT
        return float((won + k * base) / (n + k))


# =====================================================================
# Propensity driver weights, on the log-odds scale
# =====================================================================
# Stage progression. Own resolved decision: moving from pre-first-stage to
# the final pre-close stage multiplies the odds by roughly five, which
# takes a Commercial new-business deal from its 30% base to about 68% by
# Proposal/Negotiation. This is the forecaster's standard heuristic, and
# it is applied because a forecaster applies it -- not because stage
# position is claimed to be the dominant outcome driver.
_W_STAGE = 1.6

# Stall. Own resolved decision on the coefficient; the shape is a capped
# log ratio so a deal at twice its expected time-in-stage takes a bounded
# hit rather than an unbounded one. The QA plan calls deal stall "the
# exact mechanism the sample readout's drill-down story depends on," so it
# has to be visible in the forecast read, not just in stage history.
_W_STALL = 0.7
_STALL_CAP = 1.5

# POC. Not a chosen coefficient: the Bayesian log-likelihood ratio implied
# by the upstream generator's own conditional POC rates
# (config.POC_PASS_RATE_GIVEN_WON / _GIVEN_LOST). Using the standing rates
# rather than config.POC_*_INCIDENT is deliberate -- a forecaster reading a
# POC result during the injected POC-regression window applies the prior
# they have, which is exactly why that window is detectable downstream.
_POC_LOG_LR = {
    "pass": float(np.log(config.POC_PASS_RATE_GIVEN_WON / config.POC_PASS_RATE_GIVEN_LOST)),
    "fail": float(np.log((1 - config.POC_PASS_RATE_GIVEN_WON) / (1 - config.POC_PASS_RATE_GIVEN_LOST))),
}
# Days a deal must have sat in the POC stage before its result is treated
# as known, if it has not already moved past it -- own resolved decision.
_POC_REVEAL_LAG_DAYS = 14

# Rep ramp, performance effect. Not a chosen coefficient either: the
# log-odds gap that opportunities.py's own assignment weighting produces.
# That module assigns ramping reps to won deals at relative weight
# config.RAMPING_REP_WIN_ASSIGNMENT_FACTOR and to lost deals at relative
# weight 1, so a ramping rep's odds ratio against a ramped rep's is
# FACTOR**2 and the log-odds penalty is -2*log(FACTOR).
_W_RAMP = float(-2 * np.log(config.RAMPING_REP_WIN_ASSIGNMENT_FACTOR))

# First two quarters after hire = ramping (build spec Section 4, "unramped
# reps at ~50% quota capacity for first 2 quarters"), evaluated at the
# snapshot rather than at deal creation -- a rep genuinely crosses the
# line mid-deal, and the forecast read should move when they do.
_RAMP_FULL_DAYS = 180

# Account usage trajectory (renewal/expansion). Own resolved decision on
# the coefficient, calibrated against the separation
# config.DECLINE_MONTHS_BEFORE_CHURN produces upstream: an account fading
# into non-renewal runs its last complete month well under its prior
# quarter, a retained account runs at or above it. The clip bounds keep a
# single noisy month from saturating the term in either direction.
_W_USAGE = 4.0
_USAGE_RATIO_FLOOR = 0.35
_USAGE_RATIO_CEIL = 1.35
_USAGE_LOOKBACK_MONTHS = 3

# Per-opportunity latent effect -- deal-specific factors no column
# captures (champion strength, competitive pressure, budget climate).
# Constant across an opportunity's snapshots, so its weekly calls are
# correlated. Own resolved decision on the spread.
_OPP_LATENT_SIGMA = 0.50

# =====================================================================
# Rep vs. manager calibration
# =====================================================================
# Standing rep optimism, log-odds. Own resolved decision: sales forecast
# submissions convert below their stated confidence as a matter of course,
# so the bias is systematic and positive rather than symmetric noise.
_REP_OPTIMISM = 0.55
# A ramping rep carries roughly double the standing optimism -- less
# calibrated pattern-matching against deals they have not yet seen close.
# Own resolved decision; kept strictly separate from _W_RAMP above, which
# is what actually happens to the deal.
_RAMPING_REP_EXTRA_OPTIMISM = 0.55
# Persistent per-rep bias: some reps sandbag, some over-call, and they do
# it consistently. This is what gives the CRO overlay's sandbagging read
# something real to detect.
_REP_BIAS_SIGMA = 0.35
# A single person reading their own deal is noisier than a manager reading
# a book of them.
_REP_NOISE_SIGMA = 0.45
_MANAGER_NOISE_SIGMA = 0.25
# Managers are better calibrated but not disinterested.
_MANAGER_OPTIMISM = 0.10
# Explicit skepticism rule: a confident rep call gets pulled down when the
# deal's own evidence reads materially below what a deal of its kind
# currently reads -- its trailing prior, less this log-odds margin.
#
# Two properties of the rule are load-bearing rather than cosmetic:
#
#   * It reads the evidence NET OF STAGE POSITION. A manager discounting a
#     late-stage deal is discounting its evidence, not the fact that it is
#     late-stage, and keying the rule on the net figure is what makes the
#     downgrade select on the drivers that actually move the outcome
#     (stall, rep ramp, POC result, usage trajectory) rather than on how
#     far along the deal happens to be.
#   * The margin is wide, not a hairline. A manager overrules a rep when
#     the discrepancy is worth overruling; a deal reading a hair under par
#     gets left alone. A hairline margin sweeps in every marginally-below
#     deal and dilutes the downgrade population with deals that are only
#     incidentally weak, which is exactly what would turn the rep/manager
#     gap into a decorative column instead of an informative one.
#
# The rule's other half, and the half that makes the first one mean
# anything: on a deal that is NOT reading weak, a manager sitting one
# notch under the rep usually just signs off on the rep's call. Without
# it, "manager below rep" would be dominated by the standing optimism gap
# -- a difference of habit that is the same on a strong deal and a weak
# one -- and a disagreement would carry no information about the deal.
# With it, disagreement concentrates on the deals the evidence actually
# flags, which is what the build spec means in calling the rep/manager
# gap a signal.
#
# Own resolved decisions on the margin, the catch rate and the sign-off
# rate; neither rate is 1, because a manager who caught every over-call
# would make the rep's submission redundant and one who rubber-stamped
# every healthy deal would never be the more calibrated of the two.
_MANAGER_SKEPTICISM_MARGIN = 0.60
_MANAGER_DOWNGRADE_PROB = 0.75
_MANAGER_CONCUR_PROB = 0.80


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return float(np.log(p / (1 - p)))


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _categorize(p: float) -> str:
    for cut, name in _CATEGORY_CUTS:
        if p >= cut:
            return name
    return "Omitted"


# Expected end-to-end cycle length in days by (segment, opportunity_type).
# New business reads config.CYCLE_LENGTH_DAYS directly (build spec Section
# 1's cycle-length row). Renewal and expansion read the notice windows
# opportunities.py opens those deals on -- renewal 30-90 days ahead of a
# Commercial term boundary and 60-150 ahead of an Enterprise one,
# expansion 14-46 days ahead of the migration it formalises -- taken at
# their midpoints.
_EXPECTED_CYCLE_DAYS = {
    ("Commercial", "new_business"): float(np.mean(config.CYCLE_LENGTH_DAYS["Commercial"])),
    ("Enterprise", "new_business"): float(np.mean(config.CYCLE_LENGTH_DAYS["Enterprise"])),
    ("Commercial", "renewal"): 60.0,
    ("Enterprise", "renewal"): 105.0,
    ("Commercial", "expansion"): 30.0,
    ("Enterprise", "expansion"): 30.0,
}


def _stage_list(segment: str, opportunity_type: str):
    if opportunity_type == "new_business":
        return config.NEW_BUSINESS_STAGES[segment]
    return config.RENEWAL_EXPANSION_STAGES


def _month_ordinal(ts: pd.Timestamp) -> int:
    return ts.year * 12 + ts.month - 1


def _usage_by_account_month(usage_monthly: pd.DataFrame) -> dict:
    """{(account_id, month_ordinal): actions_consumed}, for point-in-time
    lookback. Keyed on ordinal rather than date so the "three months
    before the last complete month" window is plain integer arithmetic."""
    months = pd.to_datetime(usage_monthly["month"])
    ordinals = months.dt.year * 12 + months.dt.month - 1
    return dict(zip(zip(usage_monthly["account_id"], ordinals), usage_monthly["actions_consumed"]))


def _usage_trend_ratio(usage_lookup: dict, account_id, snapshot_ts: pd.Timestamp):
    """Last complete month's Actions over the mean of the three months
    before it, or None where the history is not there yet.

    Point-in-time safe: the numerator month ends strictly before
    `snapshot_ts`, so nothing read here was still in progress on the
    snapshot date.
    """
    if account_id is None or (isinstance(account_id, float) and np.isnan(account_id)):
        return None
    last_complete = _month_ordinal(snapshot_ts) - 1
    numerator = usage_lookup.get((account_id, last_complete))
    if numerator is None:
        return None
    prior = [
        usage_lookup.get((account_id, last_complete - k))
        for k in range(1, _USAGE_LOOKBACK_MONTHS + 1)
    ]
    if any(value is None for value in prior):
        return None
    baseline = float(np.mean(prior))
    if baseline <= 0:
        return None
    return float(numerator) / baseline


def _stage_as_of(stage_rows, snapshot_ts: pd.Timestamp):
    """(stage_name, entered_date) of the latest stage entered on or before
    the snapshot, or (None, None) if the deal has not entered its first
    stage yet. `stage_rows` is pre-sorted by entered_date."""
    current = (None, None)
    for stage, entered in stage_rows:
        if entered <= snapshot_ts:
            current = (stage, entered)
        else:
            break
    return current


def _snapshot_dates(created_ts: pd.Timestamp, close_ts: pd.Timestamp, grid: pd.DatetimeIndex):
    """Every forecast-call date the opportunity was open for: on or after
    creation, strictly before close. A deal closing on a call date is
    resolved by that call, not forecast by it. The grid itself is already
    bounded to the reporting window, so an opportunity that closed before
    the window opened yields nothing."""
    lo = grid.searchsorted(created_ts, side="left")
    hi = grid.searchsorted(close_ts, side="left")
    return grid[lo:hi]


def generate_forecast_submissions(rng: np.random.Generator, opportunities: pd.DataFrame,
                                   stage_history: pd.DataFrame, reps: pd.DataFrame,
                                   usage_monthly: pd.DataFrame) -> pd.DataFrame:
    """Weekly rep and manager forecast categorisations of every open
    Commercial/Enterprise opportunity.

    Grain: one row per (opportunity_id, snapshot_date), snapshot_date on a
    weekly Friday grid, emitted for every call date between the
    opportunity's created_date (inclusive) and its close_date (exclusive).
    SMB is excluded by construction -- build spec Section 1 gives it a
    no-touch motion with no rep, no stage history and a 0-7 day cycle, so
    it has no weekly forecast cadence.

    Point-in-time safety: every driver behind a row dated `snapshot_date`
    was observable on that date. Current stage and days-in-stage come from
    stage rows already entered; POC outcome is gated on the POC having
    concluded; rep ramp status is evaluated against the snapshot date; the
    usage ratio reads only months that had already ended. `is_won`,
    `loss_reason`, `amount`, `discount_rate`, `list_price` and the
    close-time `forecast_category` field are not read at all, and
    `close_date` only bounds the series. See the module docstring for the
    full input/exclusion list.

    Real drivers feeding the latent propensity: current stage and
    stage-relative stall (opportunity_stage_history against
    config.CYCLE_LENGTH_DAYS), POC outcome once revealed (Enterprise new
    business, weighted by config.POC_PASS_RATE_GIVEN_WON/_GIVEN_LOST),
    rep ramp status (users.hire_date against the snapshot, weighted by
    config.RAMPING_REP_WIN_ASSIGNMENT_FACTOR), and account usage
    trajectory for renewal/expansion (usage_monthly). Rep optimism bias
    and manager calibration are applied on top of that one propensity, so
    the two columns are correlated readings of the same deal rather than
    two independent draws.
    """
    in_scope = opportunities[opportunities["segment"].isin(["Commercial", "Enterprise"])].copy()
    in_scope["created_date"] = pd.to_datetime(in_scope["created_date"])
    in_scope["close_date"] = pd.to_datetime(in_scope["close_date"])

    stage_history = stage_history.copy()
    stage_history["entered_date"] = pd.to_datetime(stage_history["entered_date"])
    stage_history = stage_history.sort_values(["opportunity_id", "entered_date"])
    stages_by_opp = {
        opportunity_id: list(zip(group["stage"], group["entered_date"]))
        for opportunity_id, group in stage_history.groupby("opportunity_id", sort=False)
    }

    hire_date_by_rep = dict(zip(reps["rep_id"], pd.to_datetime(reps["hire_date"])))
    usage_lookup = _usage_by_account_month(usage_monthly)
    window_start, window_end = _window_bounds()
    trailing = _TrailingCloseRate(in_scope, window_start)

    # Persistent per-rep optimism/sandbagging bias, drawn once. A rep who
    # over-calls does it every week, which is what makes a segment-quarter
    # sandbagging pattern detectable rather than a run of coincidences.
    rep_bias = dict(zip(reps["rep_id"], rng.normal(0.0, _REP_BIAS_SIGMA, size=len(reps))))

    grid = pd.date_range(window_start, window_end - pd.Timedelta(days=1), freq=_SNAPSHOT_FREQ)

    rows = []
    for opp in in_scope.itertuples():
        snapshots = _snapshot_dates(opp.created_date, opp.close_date, grid)
        if len(snapshots) == 0:
            continue

        segment, opp_type = opp.segment, opp.opportunity_type
        stages = _stage_list(segment, opp_type)
        n_stages = len(stages)
        expected_stage_days = _EXPECTED_CYCLE_DAYS[(segment, opp_type)] / n_stages
        opp_latent = float(rng.normal(0.0, _OPP_LATENT_SIGMA))
        stage_rows = stages_by_opp.get(opp.opportunity_id, [])
        hire_ts = hire_date_by_rep.get(opp.rep_id)
        bias = rep_bias.get(opp.rep_id, 0.0)

        poc_index = stages.index("POC") if "POC" in stages else None

        # Per-snapshot judgement noise, drawn in one block per opportunity.
        rep_noise = rng.normal(0.0, _REP_NOISE_SIGMA, size=len(snapshots))
        manager_noise = rng.normal(0.0, _MANAGER_NOISE_SIGMA, size=len(snapshots))
        downgrade_roll = rng.random(size=len(snapshots))

        for i, snapshot_ts in enumerate(snapshots):
            prior_logit = _logit(trailing.rate(segment, opp_type, snapshot_ts))
            latent = prior_logit + opp_latent

            stage_name, entered = _stage_as_of(stage_rows, snapshot_ts)
            if stage_name is None or stage_name not in stages:
                stage_index = -1
                days_in_stage = (snapshot_ts - opp.created_date).days
            else:
                stage_index = stages.index(stage_name)
                days_in_stage = (snapshot_ts - entered).days
            progress = (stage_index + 1) / n_stages
            stage_term = _W_STAGE * (progress - 0.5)
            latent += stage_term

            if days_in_stage > expected_stage_days:
                stall = min(np.log(days_in_stage / expected_stage_days), _STALL_CAP)
                latent -= _W_STALL * stall

            # POC result, only once the POC has actually concluded.
            if poc_index is not None and opp.poc_outcome in _POC_LOG_LR:
                past_poc = stage_index > poc_index
                sat_in_poc = stage_index == poc_index and days_in_stage >= _POC_REVEAL_LAG_DAYS
                if past_poc or sat_in_poc:
                    latent += _POC_LOG_LR[opp.poc_outcome]

            is_ramping = hire_ts is not None and (snapshot_ts - hire_ts).days < _RAMP_FULL_DAYS
            if is_ramping:
                latent -= _W_RAMP

            if opp_type in ("renewal", "expansion"):
                ratio = _usage_trend_ratio(usage_lookup, opp.account_id, snapshot_ts)
                if ratio is not None:
                    clipped = min(max(ratio, _USAGE_RATIO_FLOOR), _USAGE_RATIO_CEIL)
                    latent += _W_USAGE * (clipped - 1.0)

            # The deal's own evidence, net of how far along it is -- what
            # the manager's skepticism rule reads.
            evidence_latent = latent - stage_term

            rep_latent = (
                latent + _REP_OPTIMISM + bias + rep_noise[i]
                + (_RAMPING_REP_EXTRA_OPTIMISM if is_ramping else 0.0)
            )
            rep_category = _categorize(float(_sigmoid(rep_latent)))

            manager_latent = latent + _MANAGER_OPTIMISM + manager_noise[i]
            manager_category = _categorize(float(_sigmoid(manager_latent)))

            if _RANK[rep_category] >= _RANK["Best Case"]:
                reads_weak = evidence_latent < prior_logit - _MANAGER_SKEPTICISM_MARGIN
                if reads_weak:
                    if downgrade_roll[i] < _MANAGER_DOWNGRADE_PROB:
                        capped = FORECAST_CATEGORIES[_RANK[rep_category] - 1]
                        if _RANK[manager_category] > _RANK[capped]:
                            manager_category = capped
                elif (_RANK[manager_category] == _RANK[rep_category] - 1
                        and downgrade_roll[i] < _MANAGER_CONCUR_PROB):
                    manager_category = rep_category

            rows.append({
                "opportunity_id": opp.opportunity_id,
                "snapshot_date": snapshot_ts.date(),
                "rep_forecast_category": rep_category,
                "manager_forecast_category": manager_category,
            })

    return pd.DataFrame(rows, columns=[
        "opportunity_id", "snapshot_date", "rep_forecast_category", "manager_forecast_category",
    ])


# =====================================================================
# CRO overlay
# =====================================================================
# Weighted value of a dollar of pipeline by the manager's category -- the
# conventional expected-value weighting a bottoms-up roll-up applies.
# Own resolved decision on the exact weights; they bracket the category
# cut points above rather than restating them, since a roll-up weight is
# an accounting convention, not a probability estimate.
_CATEGORY_WEIGHT = {"Commit": 0.90, "Best Case": 0.60, "Pipeline": 0.30, "Omitted": 0.05}

# Pipeline coverage: open pipeline dollars per dollar of weighted
# bottoms-up forecast. Measured against the weighted roll-up rather than
# against committed dollars alone, because a Commit-only denominator
# reads a segment's commit discipline as much as its pipeline depth.
#
# The sufficiency bar is segment-specific, and has to be: coverage scales
# with cycle length, and config.CYCLE_LENGTH_DAYS puts Enterprise at
# 60-180 days against Commercial's 14-45, so an Enterprise quarter
# structurally carries more open pipeline behind each forecast dollar
# than a Commercial one. A single blended bar would read every Commercial
# quarter as thin and every Enterprise quarter as rich -- it would be
# measuring cycle length, not pipeline health. Each level is therefore
# set at its own segment's standing coverage, so the bar flags a quarter
# that is thin for that segment. Own resolved decision on both -- neither
# reference doc states a coverage target.
_COVERAGE_TARGET = {"Commercial": 1.8, "Enterprise": 2.7}
_COVERAGE_UPSIDE_MULTIPLE = 1.20
_COVERAGE_SENSITIVITY = 0.35
_UPSIDE_SENSITIVITY = 0.30

# Sandbagging: reps filing *below* their managers, measured as this
# segment-quarter's mean rep-minus-manager rank gap against the trailing
# mean of every prior quarter in the same segment. A trailing baseline,
# not an all-history one, so the read uses only what had already been
# filed. The first quarter of a segment has no baseline and cannot
# trigger this reason.
_SANDBAG_GAP_THRESHOLD = 0.09
_SANDBAG_SENSITIVITY = 0.55

# Late-stage slippage: the share of the weighted forecast sitting in
# deals already open longer than their segment/type's expected cycle at
# the time of the call -- pipeline that is being carried for the quarter
# while already running late.
_SLIPPAGE_SHARE_THRESHOLD = 0.18
_SLIPPAGE_SENSITIVITY = 0.60

# An override is logged only if it moves the bottoms-up number by at
# least this share of it -- a CRO does not file a rounding error.
_MATERIALITY_SHARE = 0.02
# The CRO's judgement is not a formula; the magnitude carries a modest
# multiplicative draw around what the signal implies. The sign and the
# reason are set by the signal, never by the draw.
_ADJUSTMENT_NOISE_SIGMA = 0.18

CRO_ADJUSTMENT_REASONS = (
    "pipeline_coverage_shortfall",
    "rep_sandbagging_pattern",
    "late_stage_slippage_risk",
    "named_account_upside",
)


def _first_call_date(quarter_start: pd.Timestamp, grid: pd.DatetimeIndex) -> pd.Timestamp:
    idx = grid.searchsorted(quarter_start, side="left")
    return grid[idx] if idx < len(grid) else None


def generate_cro_forecast_adjustments(rng: np.random.Generator, opportunities: pd.DataFrame,
                                       submissions: pd.DataFrame) -> pd.DataFrame:
    """Logged, reasoned CRO overrides of the bottoms-up forecast.

    Grain: at most one row per (period, segment), period being a fiscal
    quarter and segment being Commercial or Enterprise -- the two segments
    that file a bottoms-up forecast at all. Sparse by design: a row exists
    only where the top-down read differs from the roll-up by at least
    _MATERIALITY_SHARE of it, so the presence of an override is itself
    informative.

    Point-in-time safety: each quarter is read at its first forecast call,
    from the manager categories filed on that call and from deal age as of
    that date. Nothing from later in the quarter, and no realized outcome,
    is visible to the read. The sandbagging baseline is a trailing mean
    over prior quarters only.

    Real drivers feeding the adjustment: pipeline coverage (open pipeline
    dollars against committed dollars at the call), the rep-minus-manager
    rank gap against its own trailing baseline, and the share of committed
    dollars in deals already past their expected cycle length
    (config.CYCLE_LENGTH_DAYS and the renewal/expansion notice windows).
    The dominant signal sets both the sign and the logged reason; only the
    magnitude carries a seeded draw. A thin-coverage quarter therefore
    draws a negative, coverage-reasoned override as a matter of mechanism,
    not of chance.
    """
    opps = opportunities[opportunities["segment"].isin(["Commercial", "Enterprise"])].copy()
    opps["created_date"] = pd.to_datetime(opps["created_date"])
    opps["close_date"] = pd.to_datetime(opps["close_date"])

    subs = submissions.copy()
    subs["snapshot_date"] = pd.to_datetime(subs["snapshot_date"])
    subs_by_date = {
        (opportunity_id, snapshot): (rep, manager)
        for opportunity_id, snapshot, rep, manager in zip(
            subs["opportunity_id"], subs["snapshot_date"],
            subs["rep_forecast_category"], subs["manager_forecast_category"],
        )
    }

    window_start, window_end = _window_bounds()
    grid = pd.date_range(window_start, window_end - pd.Timedelta(days=1), freq=_SNAPSHOT_FREQ)
    quarters = pd.period_range(
        window_start.to_period("Q"), (window_end - pd.Timedelta(days=1)).to_period("Q"), freq="Q"
    )

    trailing_gaps = {"Commercial": [], "Enterprise": []}
    rows = []

    for quarter in quarters:
        quarter_start = quarter.start_time
        quarter_end = quarter.end_time
        call_date = _first_call_date(quarter_start, grid)
        if call_date is None:
            continue

        for segment in ("Commercial", "Enterprise"):
            open_deals = opps[
                (opps["segment"] == segment)
                & (opps["created_date"] <= call_date)
                & (opps["close_date"] > call_date)
                & (opps["close_date"] <= quarter_end)
            ]
            filed = [
                (deal, subs_by_date[(deal.opportunity_id, call_date)])
                for deal in open_deals.itertuples()
                if (deal.opportunity_id, call_date) in subs_by_date
            ]
            if not filed:
                continue

            pipeline_amount = sum(deal.amount for deal, _ in filed)
            bottoms_up = sum(deal.amount * _CATEGORY_WEIGHT[mgr] for deal, (_, mgr) in filed)
            if bottoms_up <= 0:
                continue

            target = _COVERAGE_TARGET[segment]
            coverage = pipeline_amount / bottoms_up
            gap = float(np.mean([_RANK[rep] - _RANK[mgr] for _, (rep, mgr) in filed]))
            baseline = float(np.mean(trailing_gaps[segment])) if trailing_gaps[segment] else None
            trailing_gaps[segment].append(gap)

            slipping = sum(
                deal.amount * _CATEGORY_WEIGHT[mgr] for deal, (_, mgr) in filed
                if (call_date - deal.created_date).days
                > _EXPECTED_CYCLE_DAYS[(segment, deal.opportunity_type)]
            )
            slipping_share = slipping / bottoms_up

            # Every candidate override the call's own numbers support; the
            # largest-magnitude one is the one that gets logged.
            candidates = []
            if coverage < target:
                shortfall = 1.0 - coverage / target
                candidates.append((
                    -bottoms_up * _COVERAGE_SENSITIVITY * shortfall, "pipeline_coverage_shortfall",
                ))
            if baseline is not None and gap < baseline - _SANDBAG_GAP_THRESHOLD:
                candidates.append((
                    bottoms_up * _SANDBAG_SENSITIVITY * (baseline - gap), "rep_sandbagging_pattern",
                ))
            if slipping_share > _SLIPPAGE_SHARE_THRESHOLD:
                candidates.append((
                    -bottoms_up * _SLIPPAGE_SENSITIVITY
                    * (slipping_share - _SLIPPAGE_SHARE_THRESHOLD), "late_stage_slippage_risk",
                ))
            if coverage > target * _COVERAGE_UPSIDE_MULTIPLE:
                candidates.append((
                    bottoms_up * _UPSIDE_SENSITIVITY * (coverage / target - 1.0),
                    "named_account_upside",
                ))
            if not candidates:
                continue

            amount, reason = max(candidates, key=lambda c: abs(c[0]))
            amount *= float(np.exp(rng.normal(0.0, _ADJUSTMENT_NOISE_SIGMA)))
            if abs(amount) < _MATERIALITY_SHARE * bottoms_up:
                continue

            # Filed the same business day as the call, late in the day --
            # the override is made after the roll-up has been reviewed.
            timestamp = call_date + pd.Timedelta(
                hours=int(rng.integers(15, 19)), minutes=int(rng.integers(0, 60))
            )
            rows.append({
                "period": f"{quarter.year}-Q{quarter.quarter}",
                "segment": segment,
                "adjustment_amount": round(float(amount), 2),
                "reason": reason,
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            })

    return pd.DataFrame(rows, columns=["period", "segment", "adjustment_amount", "reason", "timestamp"])
