"""Shared constants for the Acme Corp Phase 1 generators.

Every distributional choice here should trace to a row in the QA plan's
benchmark reference table (docs/acme-corp-phase1-data-qa-plan.md) or to
build spec Section 1/4 (docs/acme-corp-gtm-portfolio-build-spec.md). Where a
number isn't stated verbatim in either doc, the comment next to it says so
explicitly -- these are the generator's own resolved decisions, made because
the docs specify a *range* or a *rule* but not an exact figure, not because
anything here re-derives or contradicts what's already settled.
"""
from datetime import date, timedelta

SEED = 42

# 36 months, monthly grain (build spec Section 4). SIM_END is the first of
# the last month in the window (Dec 2025), not the last calendar day --
# every "month" in this generator is addressed by its start date.
SIM_START = date(2023, 1, 1)
SIM_END = date(2025, 12, 1)
N_MONTHS = 36

# --- Account population -----------------------------------------------
# Current-state (as of SIM_END) account count targets, build spec Section 4
# ranges: SMB ~5,000-8,000, Commercial ~800-1,200, Enterprise ~150-250.
# Picked near the middle of each range.
FINAL_SMB = 6_500
FINAL_COMMERCIAL = 1_000
FINAL_ENTERPRISE = 200
FINAL_TOTAL_CUSTOMERS = FINAL_SMB + FINAL_COMMERCIAL + FINAL_ENTERPRISE

# Segment migration rates -- own resolved decision. Build spec Section 4 only
# says migration should happen for "a believable subset of accounts," not a
# rate. These two rates are solved backwards (see accounts.solve_entry_cohort_sizes)
# so that entry-cohort sizes, net of migration outflow, land exactly on the
# FINAL_* targets above.
MIG_RATE_SMB_TO_COMMERCIAL = 0.10
MIG_RATE_COMMERCIAL_TO_ENTERPRISE = 0.08

# Trigger-reason split within each migration wave -- own resolved decision.
# Both values must appear "at non-trivial frequency" (QA plan edge case /
# Test E); a 65-70/30-35 split comfortably clears that bar in both directions
# without making firmographic_rescore look like the primary path (usage
# growth crossing the threshold is the mechanically primary path per build
# spec Section 1's "or" ordering).
TRIGGER_SPLIT_SMB_TO_COMMERCIAL = {"usage_threshold": 0.70, "firmographic_rescore": 0.30}
TRIGGER_SPLIT_COMMERCIAL_TO_ENTERPRISE = {"usage_threshold": 0.65, "firmographic_rescore": 0.35}

# market_universe non-customer multiple -- QA plan Test D target is 10-50x.
# 15x keeps the universe at a manageable size while comfortably inside range.
NON_CUSTOMER_MULTIPLE = 15

# ACV bands, build spec Section 1 (used by later generators; recorded here
# since it's the one place all cross-cutting constants live).
ACV_RANGES = {
    "SMB": (0, 15_000),
    "Commercial": (15_000, 75_000),
    "Enterprise": (75_000, 750_000),
}

# --- Reps ----------------------------------------------------------------
# Headcounts, build spec Section 4 ranges: Commercial ISRs ~15-25, Enterprise
# AEs ~20-30, SEs ~1:3 AE ratio. AM headcount is deliberately NOT sized off
# these ranges -- see accounts_and_reps note in reps.py.
N_ISR = 20
N_AE = 24
SE_TO_AE_RATIO = 1 / 3

# AM headcount is sized to the *current-state* account population divided by
# the pooled/named book size from build spec Section 1's coverage-model table
# (Commercial: pooled book ~200 accounts/rep; Enterprise: named accounts
# ~20/rep) -- not tied to ISR/AE headcount. Section 2 makes AM the sole owner
# of the ongoing book (retention/expansion) while ISR/AE only carry
# new-business pipeline and hand off at Closed Won, so book size is an AM
# concept, not an ISR/AE one. Build spec Section 4 literally parenthesizes
# "(book ~200 accounts)" next to the ISR count and "(book ~20 accounts)" next
# to the AE count, which read the other way; this is flagged in the batch
# summary as a genuine ambiguity, resolved here in favor of internal
# consistency with Section 1 and Section 2's ownership model.
COMMERCIAL_BOOK_SIZE = 200
ENTERPRISE_BOOK_SIZE = 20

# Earliest possible account signup (accounts.py's "established" staggered-
# tenure cohort floor: SIM_START minus 3 years). Reps need at least one
# member per rep_type hired safely before this, or a small-headcount rep
# type (AM-Commercial=5, AM-Enterprise=10) has a real chance every member
# was hired *after* some early established account's created_date --
# violating "a rep can't be assigned to an opportunity created before they
# were hired." reps.py guarantees this explicitly rather than leaving it to
# chance.
EARLIEST_POSSIBLE_ACCOUNT_DATE = SIM_START - timedelta(days=365 * 3)

# --- Opportunities (batch 2) ---------------------------------------------
# Win-rate targets, QA plan benchmark reference table: Commercial ~25-35%,
# Enterprise ~20-30%. Picked near the middle of each range; lost-pipeline
# volume is solved backwards from these so won-count / (won+lost) lands on
# target. SMB has no win-rate concept (build spec Section 2) -- no lost
# new-business rows are generated for SMB.
NEW_BUSINESS_WIN_RATE_TARGET = {"Commercial": 0.30, "Enterprise": 0.25}

# Stage funnels, build spec Section 2. SMB gets no stage history at all
# (single immediate Closed Won, no cycle time). Renewal/expansion opportunities
# get a lighter stage list -- own resolved decision -- since they're not
# re-evaluating product fit from scratch the way a new-logo deal is.
NEW_BUSINESS_STAGES = {
    "Commercial": ["SAL", "SQO", "Proposal/Negotiation"],
    "Enterprise": ["SAL", "SQO", "POC", "Proposal/Negotiation"],
}
RENEWAL_EXPANSION_STAGES = ["Open", "Negotiation"]

# Sales-cycle length (days from opportunity creation to close), build spec
# Section 1: SMB instant-7 days, Commercial 14-45, Enterprise 60-180. Used as
# the (min, max) envelope for log-normal-ish stage-gap sampling.
CYCLE_LENGTH_DAYS = {"SMB": (0, 7), "Commercial": (14, 45), "Enterprise": (60, 180)}

# Stage regression -- QA plan edge case: "needs to exist for a small % of
# deals." Own resolved decision on the exact fraction.
STAGE_REGRESSION_RATE = 0.06

# Loss-reason mix -- own resolved decision; not stated numerically in either
# doc, only that the four values {competitive, no_decision, price, other}
# exist (build spec Section 2).
LOSS_REASON_MIX_NEW_BUSINESS = {"competitive": 0.35, "no_decision": 0.30, "price": 0.20, "other": 0.15}
LOSS_REASON_MIX_RENEWAL = {"no_decision": 0.40, "competitive": 0.20, "price": 0.25, "other": 0.15}

# Discount rate (list_price vs realized amount) -- own resolved decision,
# grounded only in the qualitative build spec note that Enterprise deals
# involve more negotiating leverage.
DISCOUNT_RATE_RANGE = {"SMB": (0.0, 0.05), "Commercial": (0.05, 0.20), "Enterprise": (0.10, 0.30)}

# POC pass rate on Enterprise new-business opportunities, conditioned on the
# deal's pre-committed win/loss outcome -- QA plan Test C wants POC pass to
# predict win rate, not just correlate weakly. Own resolved decision.
POC_PASS_RATE_GIVEN_WON = 0.82
POC_PASS_RATE_GIVEN_LOST = 0.28

# Injected incident #1 of the QA plan's required 3-5 (grounding requirement
# 3): a POC-process regression -- deals closing in this window get a
# depressed POC pass rate regardless of won/lost outcome, producing a
# detectable dip in Enterprise POC pass rate (and, as a knock-on, in that
# quarter's win rate) via a straightforward variance check. The remaining
# 2-4 incidents (a channel's CAC creeping up; a meetings-rise-without-SQO-
# conversion-rise decoupling period; an underperforming rep cohort) need
# marketing-spend and sales-engagement data this batch doesn't produce --
# deferred to that batch, flagged in the batch summary rather than skipped
# silently.
POC_REGRESSION_INCIDENT_WINDOW = (date(2025, 4, 1), date(2025, 6, 30))
POC_PASS_RATE_GIVEN_WON_INCIDENT = 0.60
POC_PASS_RATE_GIVEN_LOST_INCIDENT = 0.12

# Rep-ramp win-rate differential -- QA plan Test C: "ramping reps show
# measurably lower win rate than ramped reps, but not zero." Own resolved
# decision: ramping reps get this probability of being assigned to a WON deal
# (vs. a LOST one) relative to ramped reps' assignment probability.
RAMPING_REP_WIN_ASSIGNMENT_FACTOR = 0.55

# --- Contracts / renewals / churn (batch 2) -------------------------------
# Contract term, build spec Section 1: Commercial annual, Enterprise
# multi-year. Own resolved decision on the Enterprise split.
COMMERCIAL_TERM_MONTHS = 12
ENTERPRISE_TERM_MONTHS_MIX = {24: 0.70, 36: 0.30}

# Annualized churn targets, back-derived from the QA plan's GRR/logo-retention
# benchmark ranges (own resolved decision on the exact point picked within
# each range): Commercial GRR ~88-92% -> ~10% annual churn; Enterprise GRR
# ~92-95% -> ~6% annual churn; SMB logo retention ~75-85% -> ~20% annual churn
# (SMB has no contract/GRR concept, so logo retention is the closer proxy).
ANNUAL_CHURN_RATE = {"SMB": 0.20, "Commercial": 0.10, "Enterprise": 0.065}

# --- Usage (batch 2) -------------------------------------------------------
# Monthly Actions-consumed baseline by segment, at full ramp -- own resolved
# decision, scaled so a Commercial account's usage plausibly crosses the
# $6,250/mo Enterprise-migration threshold and an SMB account's crosses the
# $1,250/mo Commercial-migration threshold under the pricing below.
PRICE_PER_ACTION = 0.05  # $ per Action -- own resolved decision, backs both usage-value and billing
# Weighted so aggregate ARR lands near the build spec's ~65-70% Enterprise
# share despite Enterprise being only ~2.6% of accounts (200/7700) -- solved
# by working backward from the target share given each segment's account
# count, then checking the resulting per-account ACV still falls inside
# config.ACV_RANGES (it does, comfortably mid-band for all three).
USAGE_BASELINE_ACTIONS = {"SMB": 4_500, "Commercial": 34_000, "Enterprise": 650_000}
MONTHLY_SPEND_MIGRATION_THRESHOLD = {"SMB_TO_COMMERCIAL": 1_250, "COMMERCIAL_TO_ENTERPRISE": 6_250}

# Activation ramp -- own resolved decision: months to reach full baseline
# usage from signup, by segment (TTFA/onboarding is much faster for
# self-serve SMB than for a high-touch Enterprise rollout).
ACTIVATION_RAMP_MONTHS = {"SMB": 2, "Commercial": 3, "Enterprise": 5}

# Months of usage decline before a churn_date, and workflow-chain completion
# rate healthy vs. declining -- own resolved decisions. The declining range
# is the ingestion-without-completion / silent-churn proxy (build spec
# Section 2's "workflow chain under-utilization").
DECLINE_MONTHS_BEFORE_CHURN = 4
COMPLETION_RATE_HEALTHY = (0.85, 0.98)
COMPLETION_RATE_DECLINING = (0.35, 0.65)
# Segment-specific: SMB's NRR target is *below* 100% (~96-97%), so its organic
# growth needs to be the weakest -- churn dominates expansion for a self-serve
# product with no AM relationship driving expansion. Enterprise needs the
# strongest, since multi-year contracts rarely even reach a renewal boundary
# within a 12-month lookback -- organic overage growth is its main NRR driver.
MONTHLY_ORGANIC_GROWTH_RANGE = {
    "SMB": (0.006, 0.013),
    "Commercial": (0.006, 0.014),
    "Enterprise": (0.007, 0.018),
}

# Mild company-wide seasonality by calendar month -- own resolved decision,
# build spec Section 4: "36 months monthly grain, quarterly seasonality."
SEASONALITY_BY_MONTH = {
    1: 1.05, 2: 1.02, 3: 1.00, 4: 1.00, 5: 0.98, 6: 0.95,
    7: 0.90, 8: 0.92, 9: 1.00, 10: 1.03, 11: 1.00, 12: 0.85,
}

# --- Billing (batch 2) ------------------------------------------------------
# Committed Action volume as a multiple of the account's baseline monthly
# usage -- own resolved decision. Committed minimum sits meaningfully below
# typical usage so overage billing (usage above commitment) is a common,
# growing event as usage organically grows post-ramp -- this is the main
# NRR driver for multi-year Enterprise contracts specifically, since most
# Enterprise accounts won't hit a renewal boundary within any given
# 12-month lookback at all (24-36mo terms). Needed for both Expansion's
# "overage realization" metric and for NRR to land near the QA plan's
# ~118-125% Enterprise target without requiring unrealistically frequent
# renewal-driven expansion.
COMMITTED_VOLUME_FACTOR = 0.65

# --- Support tickets (batch 3) ---------------------------------------------
# Ticket rate baseline (tickets/account/month), by segment -- own resolved
# decision. Enterprise's more complex integrations produce more tickets in
# absolute terms despite white-glove AM coverage; SMB's self-serve model
# means tickets are its only support channel, so its baseline sits above what
# product complexity alone would suggest.
TICKET_RATE_BASELINE = {"SMB": 0.12, "Commercial": 0.18, "Enterprise": 0.35}
# Onboarding-period multiplier -- QA plan: onboarding-period tickets are
# normal, not a risk signal. Applied for ACTIVATION_RAMP_MONTHS[segment]
# months after signup.
TICKET_ONBOARDING_MULTIPLIER = 2.5
# Pre-churn multiplier/severity shift -- applied only in a data-derived
# "fading" window (see support_tickets.py's _declining_accounts), the same
# DECLINE_MONTHS_BEFORE_CHURN concept usage.py uses for the usage-decline
# pattern, so ticket volume/severity move with the same real trajectory
# rather than an independent signal keyed off a hidden churn flag.
TICKET_PRECHURN_MULTIPLIER = 2.2
SEVERITY_MIX_BASELINE = {"low": 0.55, "medium": 0.30, "high": 0.12, "critical": 0.03}
SEVERITY_MIX_PRECHURN = {"low": 0.25, "medium": 0.35, "high": 0.28, "critical": 0.12}
RESOLUTION_HOURS_RANGE = {"low": (1, 24), "medium": (4, 72), "high": (12, 120), "critical": (1, 48)}
CSAT_RESPONSE_RATE = 0.45  # fraction of resolved tickets that get a CSAT score -- realistic survey response rate, own decision
CSAT_MEAN_BY_SEVERITY = {"low": 4.5, "medium": 4.0, "high": 3.2, "critical": 2.6}  # 1-5 scale, own decision

# --- AM activity (batch 3) --------------------------------------------------
# Touchpoint cadence (contacts/account/month) -- build spec Section 5: QBR
# cadence for Enterprise, check-in cadence for Commercial. No AM for SMB
# (self-serve, build spec Section 1) -- this table doesn't cover SMB at all.
# Grounded against typical high-touch (~quarterly QBR + monthly check-ins)
# vs. mid-touch (~bi-monthly check-ins) AM motions -- own resolved decision.
AM_TOUCH_RATE_BASELINE = {"Commercial": 0.6, "Enterprise": 1.3}
AM_TOUCH_PRECHURN_MULTIPLIER = 1.6  # AM escalates outreach as an account shows decline -- own decision
SENTIMENT_MEAN_BASELINE = 3.8  # 1-5 scale, healthy-account baseline -- own decision
SENTIMENT_MEAN_PRECHURN = 2.3
SENTIMENT_SIGMA = 0.6

# --- Marketing spend (batch 3) ----------------------------------------------
# Blended target CAC per channel ($/new account) -- back-solved loosely
# against the QA plan's Consumption Payback benchmark (CAC / utilized-Action
# margin ~= payback months), since neither doc states CAC in dollars
# directly. self_serve is product-led with near-zero paid acquisition cost;
# outbound_sdr's channel spend here covers tooling/data enrichment only, NOT
# rep headcount cost -- no rep-cost source exists yet, so outbound_sdr's true
# CAC (and Magic Number / AM Efficiency generally) stay genuinely incomplete
# after this batch. Flagged here rather than silently assumed away.
TARGET_CAC_BY_CHANNEL = {"inbound_marketing": 1_400, "outbound_sdr": 600, "self_serve": 60}
MARKETING_SPEND_NOISE_SIGMA = 0.15  # month-to-month noise around the target-CAC-implied spend -- own decision

# Injected incident #2 of the QA plan's required 3-5 (grounding requirement
# 3; batch 2's config comment deferred this exact incident here for lack of
# marketing-spend data at the time): a channel's CAC creeping up --
# inbound_marketing spend rises without a matching rise in new-account
# volume (volume is already fixed by batch 1's signups, not regenerated
# here), so realized CAC visibly climbs in this window, detectable via a
# straightforward spend/volume variance check.
CAC_CREEP_INCIDENT_CHANNEL = "inbound_marketing"
CAC_CREEP_INCIDENT_WINDOW = (date(2024, 9, 1), date(2024, 11, 30))
CAC_CREEP_INCIDENT_SPEND_MULTIPLIER = 1.8

# --- Product logins / engagement frequency (batch 4) ------------------------
# QA plan health-score section: login/engagement frequency must be
# reinterpreted, not taken at face value -- a fully-automated, "set and
# forget" workflow can be perfectly healthy with almost no logins. The
# mechanism that makes that edge case actually exist in the data: each
# account's login intensity is its own latent draw (LOGIN_INTENSITY_SIGMA,
# below), independent of contracts.py's usage_scale by construction -- drawn
# from this module's own rng stream, never derived from usage. That
# independence is what lets a high-usage, low-login "automated but healthy"
# cohort exist (QA plan Test E), rather than logins just being usage
# relabeled.
#
# Baseline login rate (sessions/account/month) by segment -- own resolved
# decision. Higher for SMB (self-serve, UI-dependent, no AM relationship to
# fall back on) than Enterprise (larger accounts more often run
# integrations/automation rather than manual UI use).
LOGIN_RATE_BASELINE = {"SMB": 3.5, "Commercial": 2.5, "Enterprise": 1.8}
# Per-account latent login-intensity multiplier -- lognormal, mean ~1.
LOGIN_INTENSITY_SIGMA = 0.45
# Onboarding window/multiplier -- QA plan: "weight it higher in an account's
# first ~90 days, lower after." Implemented as a genuinely higher observed
# frequency during onboarding (new users actively learning the product),
# not just a downstream scoring-weight artifact. A fixed 90-day window
# (not config.ACTIVATION_RAMP_MONTHS, which varies 2/3/5 months by segment)
# since the QA plan states this one in days, specifically.
LOGIN_ONBOARDING_DAYS = 90
LOGIN_ONBOARDING_MULTIPLIER = 2.0
# Pre-churn multiplier -- applied in the same data-derived "fading" window
# support_tickets.py/am_activity.py use, so login frequency genuinely
# declines alongside usage/tickets/sentiment for a disengaging account --
# the opposite direction from tickets/AM activity (which rise as a
# reactive/intervention signal), since a login is a direct behavioral
# signal, not a response to one. This is what distinguishes real
# disengagement from an automated-but-healthy account's stable-low rate.
LOGIN_PRECHURN_MULTIPLIER = 0.4

# --- GTM plan / targets (batch 5) -------------------------------------------
# The closed set of Layer-1 metrics that carry an FP&A plan value, and the
# pillar each belongs to. Node names and pillar assignment come straight from
# docs/acme-corp-gtm-metric-tree.md -- this is the tree's own vocabulary in
# snake_case, not a second naming scheme.
#
# Ten of the tree's eleven Layer-1 nodes are here. Activation (TTFA) is
# deliberately absent: it is the one Layer-1 metric the leadership readout
# reports against a trailing baseline ("2.4d last month") rather than a plan
# figure, so a plan row for it would be a value nothing consumes. The
# remaining constants that shape these plan values live in gtm_plan.py, next
# to the reasoning that sets them -- they are single-module planning
# assumptions, not cross-cutting simulation parameters.
PLAN_PILLAR_BY_METRIC = {
    "new_logo_consumption_revenue": "Growth",
    "expansion_consumption_revenue": "Growth",
    "contraction_churned_revenue": "Growth",
    "magic_number": "Efficiency",
    "consumption_payback": "Efficiency",
    "onboarding_cs_efficiency": "Efficiency",
    "am_efficiency": "Efficiency",
    "nrr": "Durability",
    "grr": "Durability",
    "logo_retention": "Durability",
}
PLAN_LAYER1_METRICS = tuple(PLAN_PILLAR_BY_METRIC)

# --- Marketing funnel / attribution (batch 7) -------------------------------
# The finer sub-channel split the metric tree's "Pipeline generated" node is
# built on (Organic/content, Paid, Community/events), which marketing.py's
# module docstring names as deferred for lack of leads/campaigns data. These
# three names are the tree's own vocabulary in snake_case, not a second
# taxonomy: `channel` on accounts stays the coarse 3-value acquisition field
# (self_serve / inbound_marketing / outbound_sdr), and these three are a
# decomposition of `inbound_marketing` specifically -- the tree explicitly
# routes outbound SDR and segment-graduation volume elsewhere, and self-serve
# is product-led rather than campaign-sourced.
MARKETING_SUB_CHANNELS = ("organic", "paid", "community")
MARKETING_SUB_CHANNEL_PARENT = "inbound_marketing"

# Sub-channel mix of inbound-sourced new logos, at the two ends of the
# account population's signup range -- own resolved decision. Interpolated
# linearly by signup date. Shape: a PLG-first company whose earliest inbound
# volume is overwhelmingly organic/docs-led, layering on paid demand gen and
# then DevRel/community as the GTM org scales. Neither doc states a mix, only
# that the three sub-channels exist and carry separate owners.
SUB_CHANNEL_MIX_ANCHORS = (date(2019, 1, 1), date(2026, 1, 1))
SUB_CHANNEL_MIX_START = {"organic": 0.62, "paid": 0.24, "community": 0.14}
SUB_CHANNEL_MIX_END = {"organic": 0.34, "paid": 0.44, "community": 0.22}

# Sub-channel x segment affinity multiplier applied on top of the mix above.
# Channel and segment stay orthogonal as a *rule* (no channel implies a
# segment, and every sub-channel produces accounts in all three segments) --
# this is a tilt, not a partition. Grounded in build spec Section 1's
# touch-model gradient: self-directed docs/SEO discovery skews toward smaller
# organisations, DevRel/event relationships toward larger ones.
SUB_CHANNEL_SEGMENT_AFFINITY = {
    "organic": {"SMB": 1.25, "Commercial": 1.00, "Enterprise": 0.55},
    "paid": {"SMB": 1.00, "Commercial": 1.10, "Enterprise": 0.90},
    "community": {"SMB": 0.55, "Commercial": 1.00, "Enterprise": 1.90},
}

# Lead -> customer conversion rate by sub-channel -- own resolved decision,
# grounded against the typical B2B SaaS MQL-to-customer range (low single
# digits for broad top-of-funnel, materially higher for pre-qualified flow).
# A `lead` here is a marketing-qualified record, not a raw visitor, so these
# sit at the upper end of that range. The spread is the point: self-directed
# organic/docs leads arrive with intent, community/event leads arrive with a
# relationship already formed, and paid reach is the broadest and least
# qualified of the three. This is the first of the four axes that make
# QA plan Test C's "channels should not look statistically identical"
# true at organic/paid/community grain.
LEAD_CONVERSION_RATE = {"organic": 0.055, "paid": 0.032, "community": 0.085}

# Lead-to-signup gap (days) -- test C axis two. Median by sub-channel, scaled
# by a segment factor consistent with build spec Section 1's sales-cycle
# gradient (SMB instant-7d, Commercial 14-45d, Enterprise 60-180d). Organic
# leads self-serve quickly; community/event leads sit in a nurture cycle
# between the event and the decision.
LEAD_TO_SIGNUP_MEDIAN_DAYS = {"organic": 18, "paid": 32, "community": 65}
LEAD_TO_SIGNUP_SEGMENT_FACTOR = {"SMB": 0.70, "Commercial": 1.15, "Enterprise": 1.90}
LEAD_TO_SIGNUP_SIGMA = 0.55
LEAD_TO_SIGNUP_MAX_DAYS = 400

# Touch volume -- test C axis three, and the causal-wiring mechanism the whole
# table exists for. Mean touches for a non-converting, non-holdout lead, by
# sub-channel: content channels accumulate many low-weight touches (docs
# pages, blog posts); paid is a short click path; community is event-centric,
# a handful of heavier interactions. TOUCH_CONVERSION_LIFT is what makes
# touch volume a real predictor of conversion rather than decoration -- an
# engaged lead is touched several times more often than one that goes quiet,
# so bucketing leads by touch count produces a genuine conversion gradient.
TOUCHES_BASE = {"organic": 3.4, "paid": 1.9, "community": 2.6}
TOUCH_CONVERSION_LIFT = 2.6
TOUCH_INTENSITY_SIGMA = 0.35
# A non-converting lead goes quiet shortly after it is created; a converting
# one keeps being touched right up to signup. That difference is what makes
# touch *recency* (measured at a common horizon after lead creation) a
# predictor alongside touch count.
NONCONVERT_TOUCH_DECAY_MEAN_DAYS = 9
NONCONVERT_TOUCH_WINDOW_MAX_DAYS = 45

# Share of a lead's non-first touches that come from a campaign other than the
# one that sourced it, and the share of those that cross sub-channels. Without
# this every lead would sit under exactly one campaign and multi-touch
# attribution downstream would have nothing to attribute -- a single-campaign
# lead makes first-touch, last-touch and linear attribution identical by
# construction. The first touch is always the sourcing campaign, which is what
# `leads.channel` records.
CROSS_CAMPAIGN_TOUCH_RATE = 0.22
CROSS_CHANNEL_TOUCH_SHARE = 0.30

# Campaign cost multiplier against the parent channel's blended target CAC
# (TARGET_CAC_BY_CHANNEL["inbound_marketing"]) -- test C axis four. Weighted
# by the sub-channel mix these reconcile to ~1.0x, so the finer split stays
# consistent with the coarse CAC already implied by
# marketing_spend_by_channel_month rather than restating it differently.
CAMPAIGN_COST_MULTIPLIER = {"organic": 0.55, "paid": 1.55, "community": 1.00}
CAMPAIGN_BUDGET_NOISE_SIGMA = 0.18
CAMPAIGN_BASELINE_BUDGET_SHARE = 0.15  # zero-conversion quarter floor, mirroring marketing.py's baseline-cost rule

# Campaign calendar density. The marketing org scales up at the start of the
# simulation window; before that the account population is the established
# staggered-tenure cohort accounts.py seeds, whose inbound volume is far
# lower, so a mature campaign calendar back-dated over it would leave most
# campaigns with no conversions at all.
CAMPAIGNS_PER_QUARTER_EARLY = {"organic": 1, "paid": 2, "community": 1}
CAMPAIGNS_PER_QUARTER_MATURE = {"organic": 2, "paid": 4, "community": 3}
CAMPAIGN_REACH_SIGMA = 0.40
MIN_LEADS_PER_CAMPAIGN = 20

# Holdout / incrementality control group (build spec Section 4: campaigns
# carry "holdout/control-group flags for specific periods -- incrementality
# testing needs a deliberately-excluded group somewhere in the data").
# Only paid and community run holdouts: organic/SEO cannot be switched off
# for a randomly chosen cell, so a holdout flag on an organic campaign would
# be a flag with no operational meaning.
#
# The suppression is a real behavioural consequence, not a label. A holdout
# cell's leads receive the campaign treatment withheld -- HOLDOUT_TOUCH_
# SUPPRESSION fewer touches -- and convert at HOLDOUT_CONVERSION_SUPPRESSION
# of the treated rate, which is the baseline (non-incremental) conversion the
# test exists to measure. 0.35 implies a ~65% incremental lift, inside the
# range real paid-media incrementality tests report for mid-funnel programs.
HOLDOUT_CHANNELS = ("paid", "community")
HOLDOUT_QUARTERS = ("2023Q3", "2024Q2", "2025Q1")
HOLDOUT_CONVERSION_SUPPRESSION = 0.35
HOLDOUT_TOUCH_SUPPRESSION = 0.40
HOLDOUT_BUDGET_SHARE = 0.10  # spend is withheld from the control cell, not merely re-labelled

# Lead score composite. Built from real drivers already in the data --
# firmographic fit (market_universe.icp_fit_score, the same score the whole
# universe carries) and observed engagement depth -- plus a sub-channel
# quality term, so the score correlates with conversion instead of being
# independent noise. Test C axis five: the three sub-channels carry visibly
# different score distributions.
LEAD_SCORE_WEIGHTS = {"firmographic": 0.40, "behavioral": 0.42, "channel": 0.18}
LEAD_SCORE_CHANNEL_QUALITY = {"organic": 60.0, "paid": 45.0, "community": 70.0}
LEAD_SCORE_TOUCH_SCALE = 4.0
LEAD_SCORE_NOISE_SD = 4.5

# Inbound lead flow skews below the prospect universe's average firmographic
# fit -- broad top-of-funnel pulls in a long tail of small, poor-fit
# companies, which is the reason lead scoring exists at all. Implemented as a
# downward tilt on the icp_fit_score of the market_universe companies drawn
# as non-converting leads, giving the firmographic term of lead_score real
# discriminating power without overstating it.
NONCONVERT_LEAD_ICP_TILT = 45.0

# Closed event-type vocabulary per sub-channel. Each maps onto a Layer-3
# diagnostic the metric tree already names: docs/blog traffic and
# docs-traffic-to-signup (organic), click -> lead conversion and retargeting
# (paid), event attendance and community engagement depth (community).
CAMPAIGN_EVENT_TYPES = {
    "organic": ("organic_search_visit", "docs_view", "blog_view", "content_download"),
    "paid": ("ad_click", "landing_page_view", "retargeting_click", "paid_asset_download"),
    "community": ("event_registration", "event_attendance", "community_join", "community_post"),
}
# The touch that creates the lead record, per sub-channel. Fixing this also
# enforces the one intra-lead ordering constraint in the vocabulary: an
# `event_attendance` can never precede its `event_registration`.
CAMPAIGN_FIRST_TOUCH_TYPE = {
    "organic": "organic_search_visit",
    "paid": "ad_click",
    "community": "event_registration",
}
CAMPAIGN_FOLLOWUP_TYPE_MIX = {
    "organic": {"docs_view": 0.45, "blog_view": 0.28, "content_download": 0.17, "organic_search_visit": 0.10},
    "paid": {"landing_page_view": 0.46, "retargeting_click": 0.30, "paid_asset_download": 0.16, "ad_click": 0.08},
    "community": {"event_attendance": 0.40, "community_post": 0.26, "community_join": 0.20, "event_registration": 0.14},
}
