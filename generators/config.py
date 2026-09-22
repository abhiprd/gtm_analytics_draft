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
