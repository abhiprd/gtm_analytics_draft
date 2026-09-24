"""campaigns / leads / campaign_engagement_events generators.

Build spec Section 4 (Marketing automation): `leads`, `campaigns` "with
holdout/control-group flags for specific periods -- incrementality testing
needs a deliberately-excluded group somewhere in the data",
`campaign_engagement_events` -- "channel sub-attribution (organic/paid/
community), not a flat channel field, captured at raw touch grain (every
touch, not deduplicated to one) so multi-touch attribution is possible
later."

This is the data marketing.py's module docstring names as missing: the
coarse `marketing_spend_by_channel_month` carries spend at the 3-value
acquisition taxonomy on `accounts.channel`, because the finer organic/paid/
community split the metric tree's "Pipeline generated" node is built on
needs exactly the leads/campaigns tables produced here.

Relationship to what already exists
-----------------------------------
These three tables explain the inbound-sourced account population that
already exists; they do not invent a parallel one. Every account with
`channel == "inbound_marketing"` gets exactly one converting lead, whose
`created_date` precedes that account's `signup_date` by a real, channel- and
segment-dependent gap. Nothing in `accounts.csv` is read except
account_id / company_id / segment / channel / signup_date, and nothing in it
is written back -- same backwards-from-real-volume pattern marketing.py uses
for spend.

The sub-channel taxonomy is a decomposition of `inbound_marketing`, not a
replacement for it. `self_serve` accounts are product-led and campaign-
sourced only incidentally; `outbound_sdr` volume is tracked under win rate
per the metric tree's own note. Neither is represented here.

Grain
-----
* `campaigns` -- one row per campaign (a channel program running over a
  defined window). Not event grain: a campaign genuinely is a period-level
  object in a marketing automation system, the same way monthly spend is.
* `leads` -- one row per lead.
* `campaign_engagement_events` -- one row per touch. Every touch, not
  deduplicated to one per lead or one per campaign: a lead is touched
  several times, by more than one campaign and sometimes across
  sub-channels, which is what leaves anything for multi-touch attribution to
  attribute. Deduplicating here would make first-touch, last-touch and
  linear attribution identical by construction.

Point-in-time safety
--------------------
* No touch on a converting lead postdates its conversion. Touches are placed
  on `[created_date, converted_date - 1 day]`, so every attributed
  pre-conversion touch is strictly before the signup day, with no
  same-day ambiguity to resolve downstream.
* No touch on any lead postdates the observation window's last day.
* Every touch is attributed only to a campaign whose window actually covers
  that touch's date -- a touch never lands on a campaign that had not
  started or had already ended.
* `leads.lead_score` is the lead's composite as of its terminal state
  (conversion, or the end of its engagement), NOT a point-in-time score. It
  reads observed engagement depth, so a model that used it to predict
  conversion would leak. The build spec's separate `lead_scoring_history`
  table is where point-in-time scoring belongs; it is not produced here, and
  this column is not a substitute for it.

Causal wiring
-------------
Touch volume is the mechanism, not a decorative column. A lead's touch count
is drawn from a mean that is `TOUCHES_BASE[channel]` scaled by whether the
lead converts (`TOUCH_CONVERSION_LIFT`), whether it sits in a holdout cell
(`HOLDOUT_TOUCH_SUPPRESSION`), and its own latent engagement intensity. The
result is a real gradient: bucket leads by touch count and conversion rate
rises monotonically across the buckets. Recency moves with it -- a
non-converting lead's touches decay away within days of creation, while a
converting lead is touched right up to signup, so at a common horizon after
lead creation a converting lead's last touch is the more recent one.

`lead_score` is then a composite of that observed engagement depth and the
company's firmographic fit (`icp_fit_score`, already carried on every
market_universe row), never an independent draw.

The three sub-channels differ on five axes, each with its own rationale in
config.py: conversion rate, lead-to-signup gap, touch volume, cost per
acquisition, and lead-score distribution. That is QA plan Test C's
"organic, paid and community should not look statistically identical" made
true at the finer grain, rather than only at the coarse 3-value one.

Holdouts
--------
A holdout campaign is a genuinely suppressed control cell, not a flag. Its
leads receive the campaign treatment withheld (fewer touches, and no
cross-campaign touches at all -- the cell stays isolated), its budget is
withheld rather than re-labelled, and it converts at
`HOLDOUT_CONVERSION_SUPPRESSION` of its channel's treated rate. The gap
between the two is the incremental lift an incrementality test is there to
measure, and it is checkable directly from the published tables.
"""
import numpy as np
import pandas as pd

from . import config

CAMPAIGN_COLUMNS = ["campaign_id", "name", "channel", "start_date", "end_date", "budget", "is_holdout"]
LEAD_COLUMNS = ["lead_id", "account_id", "company_id", "channel", "created_date",
                "lead_score", "converted_date", "is_converted"]
EVENT_COLUMNS = ["event_id", "lead_id", "campaign_id", "channel", "event_type", "event_timestamp"]

# Campaign name pools, cycled per quarter. Cosmetic labels rather than
# distributional parameters, so they live here rather than in config.py --
# but they are deliberately the recognisable programs each sub-channel's
# owner in the metric tree would actually run, not generic filler.
CAMPAIGN_NAME_POOL = {
    "organic": ("Docs SEO Program", "Technical Blog Series", "Solution Guide Refresh"),
    "paid": ("Search Ads - Workflow Automation", "LinkedIn ABM - Enterprise",
             "Retargeting - Docs Visitors", "Review Site Paid Placement"),
    "community": ("Developer Meetup Series", "Quarterly Product Webinar",
                  "Community Slack Growth", "Partner Conference Booth"),
}
HOLDOUT_NAME = {"paid": "Paid Holdout Cell", "community": "Community Holdout Cell"}

# Touch timestamps land inside a business-hours band rather than uniformly
# over 24h -- an ordering-stable convention, not a modelled diurnal curve.
TOUCH_HOUR_RANGE = (8, 21)


# =====================================================================
# Calendar helpers
# =====================================================================

def _observation_end() -> pd.Timestamp:
    """Last day of the simulation window. config.SIM_END is the *first* of
    the final month by this project's convention, so the last observable day
    is that month's end."""
    return pd.Timestamp(config.SIM_END) + pd.offsets.MonthEnd(0)


def _quarter_label(ts: pd.Timestamp) -> str:
    return f"{ts.year}Q{ts.quarter}"


def _quarter_grid(start: pd.Timestamp, end: pd.Timestamp) -> list:
    periods = pd.period_range(start, end, freq="Q")
    return [(p.start_time, p.end_time.normalize()) for p in periods]


def _campaign_calendar_bounds(accounts: pd.DataFrame) -> tuple:
    """The calendar is anchored to the account population's real signup
    range, not to config.SIM_START. accounts.py deliberately seeds a cohort
    with established, staggered tenure predating the window, and those
    accounts had to be marketed to as well -- a calendar starting at
    SIM_START would leave their leads with no campaign to attach to.
    """
    inbound = accounts[accounts["channel"] == config.MARKETING_SUB_CHANNEL_PARENT]
    earliest_signup = pd.Timestamp(inbound["signup_date"].min())
    start = earliest_signup - pd.Timedelta(days=config.LEAD_TO_SIGNUP_MAX_DAYS)
    return start, _observation_end()


def _sub_channel_mix(signup_ts: pd.Timestamp) -> dict:
    """Linear interpolation between the two mix anchors in config."""
    lo, hi = (pd.Timestamp(d) for d in config.SUB_CHANNEL_MIX_ANCHORS)
    t = (signup_ts - lo).days / (hi - lo).days
    t = min(max(t, 0.0), 1.0)
    return {
        ch: config.SUB_CHANNEL_MIX_START[ch] + t * (config.SUB_CHANNEL_MIX_END[ch] - config.SUB_CHANNEL_MIX_START[ch])
        for ch in config.MARKETING_SUB_CHANNELS
    }


def _channel_weights(signup_ts: pd.Timestamp, segment: str) -> np.ndarray:
    mix = _sub_channel_mix(signup_ts)
    weights = np.array([
        mix[ch] * config.SUB_CHANNEL_SEGMENT_AFFINITY[ch][segment]
        for ch in config.MARKETING_SUB_CHANNELS
    ])
    return weights / weights.sum()


# =====================================================================
# campaigns
# =====================================================================

def generate_campaigns(rng: np.random.Generator, accounts: pd.DataFrame) -> pd.DataFrame:
    """One row per campaign.

    Grain: campaign. A campaign is a period-level object in the source
    system (a program with a window and an allocated budget), so this is the
    correct grain rather than a pre-aggregation of something finer -- the
    same reasoning marketing.py applies to monthly spend.

    Point-in-time safety: a campaign's `budget` is set from the *planned*
    inbound volume its window is expected to source, computed
    deterministically from the account population's signup dates and the
    sub-channel mix -- never from the conversions this batch's own lead
    assignment happens to land on it. Realised cost per acquisition
    therefore varies around the target rather than equalling it by
    construction, which is what leaves a campaign-efficiency diagnostic
    something real to find.

    Returns the published columns plus `reach_weight`, which
    `generate_leads` consumes to size each campaign's share of its
    channel-quarter. The orchestrator writes `CAMPAIGN_COLUMNS`.
    """
    start, end = _campaign_calendar_bounds(accounts)
    mature_from = pd.Timestamp(config.SIM_START)

    incident_start, incident_end = (pd.Timestamp(d) for d in config.CAC_CREEP_INCIDENT_WINDOW)
    planned = _planned_conversions_by_channel_quarter(accounts)

    rows = []
    seq = 0
    for q_start, q_end in _quarter_grid(start, end):
        label = _quarter_label(q_start)
        density = (config.CAMPAIGNS_PER_QUARTER_MATURE if q_start >= mature_from
                   else config.CAMPAIGNS_PER_QUARTER_EARLY)

        for channel in config.MARKETING_SUB_CHANNELS:
            specs = []
            for i in range(density[channel]):
                name_pool = CAMPAIGN_NAME_POOL[channel]
                specs.append({
                    "name": f"{name_pool[i % len(name_pool)]} {label}",
                    "is_holdout": False,
                    # Index 0 spans the full quarter so every date inside the
                    # calendar is covered by at least one campaign per
                    # sub-channel -- a touch must always have an active
                    # campaign to attribute to.
                    "start_date": q_start if i == 0 else q_start + pd.Timedelta(days=int(rng.integers(0, 11))),
                    "end_date": q_end if i == 0 else q_end - pd.Timedelta(days=int(rng.integers(0, 8))),
                })
            if channel in config.HOLDOUT_CHANNELS and label in config.HOLDOUT_QUARTERS:
                specs.append({
                    "name": f"{HOLDOUT_NAME[channel]} {label}",
                    "is_holdout": True,
                    "start_date": q_start,
                    "end_date": q_end,
                })

            reach = rng.lognormal(0.0, config.CAMPAIGN_REACH_SIGMA, size=len(specs))
            planned_q = planned.get((channel, label), 0.0)
            # Conversion share within a quarter is proportional to reach,
            # with the holdout cell's share suppressed -- that suppression is
            # what makes its realised conversion rate genuinely lower than
            # its treated peers' rather than merely labelled so.
            conv_weight = np.array([
                r * (config.HOLDOUT_CONVERSION_SUPPRESSION if s["is_holdout"] else 1.0)
                for r, s in zip(reach, specs)
            ])
            conv_share = conv_weight / conv_weight.sum()

            for spec, reach_weight, share in zip(specs, reach, conv_share):
                seq += 1
                expected_conversions = planned_q * share
                cost_mult = config.CAMPAIGN_COST_MULTIPLIER[channel]
                parent_cac = config.TARGET_CAC_BY_CHANNEL[config.MARKETING_SUB_CHANNEL_PARENT]
                noise = rng.lognormal(0.0, config.CAMPAIGN_BUDGET_NOISE_SIGMA)
                budget = max(expected_conversions, config.CAMPAIGN_BASELINE_BUDGET_SHARE) * parent_cac * cost_mult * noise

                if spec["is_holdout"]:
                    budget *= config.HOLDOUT_BUDGET_SHARE
                # The CAC-creep incident config already records on
                # inbound_marketing as a whole (marketing.py raises coarse
                # spend across the channel in this window). Paid media is
                # where a cost-per-acquisition creep originates, and the
                # coarse table cannot show that; carrying the same multiplier
                # here on paid campaigns only localises the already-recorded
                # incident rather than restating or contradicting it.
                elif channel == "paid" and spec["start_date"] <= incident_end and spec["end_date"] >= incident_start:
                    budget *= config.CAC_CREEP_INCIDENT_SPEND_MULTIPLIER

                rows.append({
                    "campaign_id": f"CMP-{seq:05d}",
                    "name": spec["name"],
                    "channel": channel,
                    "start_date": spec["start_date"].date(),
                    "end_date": spec["end_date"].date(),
                    "budget": round(budget, 2),
                    "is_holdout": bool(spec["is_holdout"]),
                    "reach_weight": float(reach_weight),
                })

    return pd.DataFrame(rows)


def _planned_conversions_by_channel_quarter(accounts: pd.DataFrame) -> dict:
    """Expected inbound conversions per (sub-channel, quarter), used only to
    size campaign budgets.

    Deterministic -- no rng. Each inbound account contributes its
    sub-channel mix weight to the quarter its lead would have been created
    in at that channel/segment's median gap. This is the planning view a
    budget is set against, not the realised assignment `generate_leads`
    produces.
    """
    inbound = accounts[accounts["channel"] == config.MARKETING_SUB_CHANNEL_PARENT]
    planned = {}
    for acc in inbound.itertuples():
        signup_ts = pd.Timestamp(acc.signup_date)
        weights = _channel_weights(signup_ts, acc.segment)
        for channel, weight in zip(config.MARKETING_SUB_CHANNELS, weights):
            gap = config.LEAD_TO_SIGNUP_MEDIAN_DAYS[channel] * config.LEAD_TO_SIGNUP_SEGMENT_FACTOR[acc.segment]
            label = _quarter_label(signup_ts - pd.Timedelta(days=gap))
            planned[(channel, label)] = planned.get((channel, label), 0.0) + float(weight)
    return planned


# =====================================================================
# leads
# =====================================================================

def _active_campaign_index(campaigns: pd.DataFrame) -> dict:
    """(channel, quarter label) -> list of campaign records, for fast
    lookup of which campaigns were running on a given date. Campaigns are
    quarter-aligned, so a date's candidates are always inside its own
    quarter's bucket."""
    index = {}
    for c in campaigns.itertuples():
        label = _quarter_label(pd.Timestamp(c.start_date))
        index.setdefault((c.channel, label), []).append(c)
    return index


def _campaigns_active_on(index: dict, channel: str, ts: pd.Timestamp) -> list:
    bucket = index.get((channel, _quarter_label(ts)), [])
    return [c for c in bucket if pd.Timestamp(c.start_date) <= ts <= pd.Timestamp(c.end_date)]


def generate_leads(rng: np.random.Generator, accounts: pd.DataFrame,
                   market_universe: pd.DataFrame, campaigns: pd.DataFrame) -> pd.DataFrame:
    """One row per lead.

    Grain: lead. Converting leads are anchored 1:1 to the inbound-sourced
    accounts that already exist; non-converting leads are the rest of the
    funnel those conversions came out of.

    Point-in-time safety: a converting lead's `created_date` is strictly
    earlier than its account's `signup_date` (the gap is clamped to at least
    one day), so no lead is created simultaneously with the conversion it
    explains. No lead is created after the observation window ends.

    `lead_score` is explicitly NOT point-in-time -- see the module docstring.

    Returns the published columns plus `primary_campaign_id` and
    `touch_count`, which `generate_campaign_engagement_events` consumes. The
    orchestrator writes `LEAD_COLUMNS`.
    """
    index = _active_campaign_index(campaigns)
    holdout_by_campaign = dict(zip(campaigns["campaign_id"], campaigns["is_holdout"]))
    obs_end = _observation_end()

    inbound = accounts[accounts["channel"] == config.MARKETING_SUB_CHANNEL_PARENT]
    icp_by_company = dict(zip(market_universe["company_id"], market_universe["icp_fit_score"]))

    records = []

    # --- converting leads: exactly one per existing inbound account -------
    conversions_per_campaign = {}
    for acc in inbound.itertuples():
        signup_ts = pd.Timestamp(acc.signup_date)
        weights = _channel_weights(signup_ts, acc.segment)
        channel = str(rng.choice(config.MARKETING_SUB_CHANNELS, p=weights))

        median_gap = (config.LEAD_TO_SIGNUP_MEDIAN_DAYS[channel]
                      * config.LEAD_TO_SIGNUP_SEGMENT_FACTOR[acc.segment])
        gap = int(round(rng.lognormal(np.log(median_gap), config.LEAD_TO_SIGNUP_SIGMA)))
        gap = min(max(gap, 1), config.LEAD_TO_SIGNUP_MAX_DAYS)
        created_ts = signup_ts - pd.Timedelta(days=gap)

        candidates = _campaigns_active_on(index, channel, created_ts)
        weights_c = np.array([
            c.reach_weight * (config.HOLDOUT_CONVERSION_SUPPRESSION if c.is_holdout else 1.0)
            for c in candidates
        ])
        chosen = candidates[int(rng.choice(len(candidates), p=weights_c / weights_c.sum()))]
        conversions_per_campaign[chosen.campaign_id] = conversions_per_campaign.get(chosen.campaign_id, 0) + 1

        records.append({
            "account_id": acc.account_id,
            "company_id": acc.company_id,
            "channel": channel,
            "created_ts": created_ts,
            "converted_ts": signup_ts,
            "is_converted": True,
            "primary_campaign_id": chosen.campaign_id,
            "icp_fit_score": float(acc.icp_fit_score),
            "is_holdout": bool(chosen.is_holdout),
        })

    # --- non-converting leads --------------------------------------------
    # Pool size per campaign is the conversions it actually sourced divided
    # by the rate it should convert at -- the channel's rate, suppressed for
    # a holdout cell. That construction is what makes the holdout's realised
    # conversion rate genuinely lower: it carries a full-sized lead pool
    # against a deliberately small number of conversions.
    pool_sizes = {}
    for c in campaigns.itertuples():
        converted = conversions_per_campaign.get(c.campaign_id, 0)
        rate = config.LEAD_CONVERSION_RATE[c.channel]
        if c.is_holdout:
            rate *= config.HOLDOUT_CONVERSION_SUPPRESSION
        implied = converted / rate * rng.lognormal(0.0, 0.10)
        pool_sizes[c.campaign_id] = max(int(round(implied)), config.MIN_LEADS_PER_CAMPAIGN)

    n_noncvt = sum(max(pool_sizes[c.campaign_id] - conversions_per_campaign.get(c.campaign_id, 0), 0)
                   for c in campaigns.itertuples())
    noncvt_companies = _sample_noncustomer_companies(rng, market_universe, n_noncvt)

    cursor = 0
    for c in campaigns.itertuples():
        n = max(pool_sizes[c.campaign_id] - conversions_per_campaign.get(c.campaign_id, 0), 0)
        if n == 0:
            continue
        win_start, win_end = pd.Timestamp(c.start_date), min(pd.Timestamp(c.end_date), obs_end)
        span = max((win_end - win_start).days, 0)
        offsets = rng.integers(0, span + 1, size=n)
        for offset in offsets:
            company_id = noncvt_companies[cursor]
            cursor += 1
            records.append({
                "account_id": None,
                "company_id": company_id,
                "channel": c.channel,
                "created_ts": win_start + pd.Timedelta(days=int(offset)),
                "converted_ts": pd.NaT,
                "is_converted": False,
                "primary_campaign_id": c.campaign_id,
                "icp_fit_score": float(icp_by_company[company_id]),
                "is_holdout": bool(c.is_holdout),
            })

    leads = pd.DataFrame(records)
    leads = leads.sort_values("created_ts", kind="mergesort").reset_index(drop=True)
    leads["lead_id"] = [f"LD-{i + 1:06d}" for i in range(len(leads))]

    # --- touch count: the causal driver ----------------------------------
    base = leads["channel"].map(config.TOUCHES_BASE).to_numpy(dtype=float)
    lift = np.where(leads["is_converted"].to_numpy(), config.TOUCH_CONVERSION_LIFT, 1.0)
    suppression = np.where(leads["is_holdout"].to_numpy(), config.HOLDOUT_TOUCH_SUPPRESSION, 1.0)
    intensity = rng.lognormal(0.0, config.TOUCH_INTENSITY_SIGMA, size=len(leads))
    mean_touches = base * lift * suppression * intensity
    # Every lead exists because of at least one touch, so the count is one
    # plus a Poisson draw on the remainder rather than a bare Poisson that
    # could return zero.
    leads["touch_count"] = 1 + rng.poisson(np.clip(mean_touches - 1.0, 0.05, None))

    # --- lead score: composite of real drivers, never an independent draw -
    w = config.LEAD_SCORE_WEIGHTS
    behavioral = 100.0 * (1.0 - np.exp(-leads["touch_count"].to_numpy() / config.LEAD_SCORE_TOUCH_SCALE))
    channel_quality = leads["channel"].map(config.LEAD_SCORE_CHANNEL_QUALITY).to_numpy(dtype=float)
    score = (w["firmographic"] * leads["icp_fit_score"].to_numpy()
             + w["behavioral"] * behavioral
             + w["channel"] * channel_quality
             + rng.normal(0.0, config.LEAD_SCORE_NOISE_SD, size=len(leads)))
    leads["lead_score"] = np.round(np.clip(score, 0.0, 100.0), 1)

    leads["created_date"] = leads["created_ts"].dt.date
    leads["converted_date"] = leads["converted_ts"].dt.date
    return leads


def _sample_noncustomer_companies(rng: np.random.Generator, market_universe: pd.DataFrame, n: int) -> list:
    """Draw the companies behind non-converting leads from the existing
    prospect universe rather than inventing identifiers.

    market_universe is already the calibrated firmographic universe the
    build spec defines for exactly this purpose, so a non-converting lead
    gets a real `icp_fit_score`, employee band, industry and region -- which
    is what lets lead_score carry a firmographic term at all. Companies that
    are, or ever were, customers are excluded: their lead is the converting
    one generated above.

    The draw is tilted toward lower firmographic fit. Broad inbound pulls in
    a long tail of small, poor-fit companies, which is the reason a lead
    score exists; without the tilt the converting and non-converting
    populations would carry identical fit distributions and the firmographic
    term would be pure noise.
    """
    pool = market_universe[
        ~market_universe["is_customer"].astype(bool)
        & ~market_universe["was_ever_customer"].astype(bool)
    ]
    if n > len(pool):
        raise ValueError(f"need {n} non-customer companies, universe has {len(pool)}")
    weights = np.exp(-pool["icp_fit_score"].to_numpy(dtype=float) / config.NONCONVERT_LEAD_ICP_TILT)
    picks = rng.choice(len(pool), size=n, replace=False, p=weights / weights.sum())
    return pool["company_id"].to_numpy()[picks].tolist()


# =====================================================================
# campaign_engagement_events
# =====================================================================

def generate_campaign_engagement_events(rng: np.random.Generator, leads: pd.DataFrame,
                                        campaigns: pd.DataFrame) -> pd.DataFrame:
    """One row per touch -- every touch, never deduplicated.

    Grain: touch. A lead appears as many times as it was touched, under as
    many campaigns as touched it. The first touch is always the campaign
    that sourced the lead (which is what `leads.channel` records); later
    touches may come from another concurrently-running campaign, and a
    minority cross sub-channels, so multi-touch attribution has a genuine
    multi-campaign path to attribute rather than a single-campaign one where
    every attribution model returns the same answer.

    Point-in-time safety, enforced as the touches are placed rather than
    checked afterwards:

    * On a converting lead every touch falls in
      `[created_date, converted_date - 1 day]` -- strictly before the signup
      day, so no touch can be mistaken for a post-conversion interaction and
      there is no same-day ordering ambiguity.
    * On every lead, no touch falls after the observation window's last day.
    * Every touch is attributed to a campaign whose window covers that
      touch's own date; if the sourcing campaign has ended by then, another
      campaign active on that date takes the touch.
    """
    index = _active_campaign_index(campaigns)
    campaign_by_id = {c.campaign_id: c for c in campaigns.itertuples()}
    obs_end = _observation_end()
    hour_lo, hour_hi = TOUCH_HOUR_RANGE

    rows = []
    seq = 0
    for lead in leads.itertuples():
        created_ts = lead.created_ts
        n = int(lead.touch_count)

        if lead.is_converted:
            # Window is closed at converted_date - 1 day: the last touch is
            # the one immediately preceding signup, never simultaneous with
            # it.
            span = max((lead.converted_ts - created_ts).days - 1, 0)
            if n == 1:
                offsets = np.array([0])
            else:
                # Last touch sits in the final fifth of the window, so a
                # converting lead's most recent touch is genuinely recent
                # relative to its decision.
                last = int(rng.integers(int(span * 0.8), span + 1)) if span > 0 else 0
                middle = rng.integers(0, span + 1, size=n - 2) if n > 2 else np.array([], dtype=int)
                offsets = np.concatenate([[0], middle, [last]])
        else:
            # A lead that never converts goes quiet within days of being
            # created -- this is what makes touch recency a predictor
            # alongside touch volume.
            window = int(min(rng.exponential(config.NONCONVERT_TOUCH_DECAY_MEAN_DAYS),
                             config.NONCONVERT_TOUCH_WINDOW_MAX_DAYS))
            cap = max((obs_end - created_ts).days, 0)
            window = min(window, cap)
            tail = rng.integers(0, window + 1, size=n - 1) if n > 1 else np.array([], dtype=int)
            offsets = np.concatenate([[0], tail])

        offsets = np.sort(offsets)
        seconds = np.sort(rng.integers(hour_lo * 3600, hour_hi * 3600, size=len(offsets)))
        previous = None
        for i, (offset, second) in enumerate(zip(offsets, seconds)):
            touch_ts = created_ts + pd.Timedelta(days=int(offset), seconds=int(second))
            # Touches within a lead are strictly ordered, not merely sorted.
            # Two touches sharing a timestamp would leave the first-touch and
            # last-touch position of a lead ambiguous, which is precisely the
            # thing multi-touch attribution reads.
            if previous is not None and touch_ts <= previous:
                touch_ts = previous + pd.Timedelta(seconds=1)
            previous = touch_ts

            # Campaign windows are day-grained, so resolve against the
            # touch's calendar day rather than its timestamp.
            campaign = _resolve_touch_campaign(rng, index, campaign_by_id, lead,
                                               touch_ts.normalize(), is_first=(i == 0))
            event_type = (config.CAMPAIGN_FIRST_TOUCH_TYPE[campaign.channel] if i == 0
                          else _draw_followup_type(rng, campaign.channel))
            seq += 1
            rows.append({
                "event_id": f"EVT-{seq:08d}",
                "lead_id": lead.lead_id,
                "campaign_id": campaign.campaign_id,
                "channel": campaign.channel,
                "event_type": event_type,
                "event_timestamp": touch_ts,
            })

    return pd.DataFrame(rows, columns=EVENT_COLUMNS)


def _resolve_touch_campaign(rng, index, campaign_by_id, lead, touch_ts, is_first):
    primary = campaign_by_id[lead.primary_campaign_id]
    if is_first:
        return primary

    # A holdout cell stays isolated: no cross-campaign touch leaks into the
    # control group, or the incrementality read would be contaminated. A
    # deliberate simplification -- real holdouts leak -- documented rather
    # than left implicit.
    if not lead.is_holdout and rng.random() < config.CROSS_CAMPAIGN_TOUCH_RATE:
        if rng.random() < config.CROSS_CHANNEL_TOUCH_SHARE:
            others = [ch for ch in config.MARKETING_SUB_CHANNELS if ch != primary.channel]
            channel = others[int(rng.integers(0, len(others)))]
        else:
            channel = primary.channel
        candidates = [c for c in _campaigns_active_on(index, channel, touch_ts) if not c.is_holdout]
        if candidates:
            return candidates[int(rng.integers(0, len(candidates)))]

    if pd.Timestamp(primary.start_date) <= touch_ts <= pd.Timestamp(primary.end_date):
        return primary
    # The sourcing campaign has ended by the time of this touch -- attribute
    # it to whichever campaign in the same sub-channel was actually running,
    # so no touch lands outside its campaign's window.
    fallback = _campaigns_active_on(index, primary.channel, touch_ts)
    if lead.is_holdout:
        fallback = [c for c in fallback if c.is_holdout] or fallback
    return fallback[int(rng.integers(0, len(fallback)))] if fallback else primary


def _draw_followup_type(rng: np.random.Generator, channel: str) -> str:
    mix = config.CAMPAIGN_FOLLOWUP_TYPE_MIX[channel]
    types = list(mix)
    return types[int(rng.choice(len(types), p=[mix[t] for t in types]))]
