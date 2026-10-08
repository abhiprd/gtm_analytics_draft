# Acme Corp — GTM health metric tree

## Growth — consumption revenue growth
`Starting consumption revenue + New logo − Contraction − Churn + Expansion` (± segment migration, nets to zero)

### New logo consumption revenue — marketing + sales
`Pipeline generated × win rate × avg initial commitment`, by segment

**Pipeline generated** — marketing
`Σ over channels (channel volume × channel-to-lead rate × lead-to-PQL rate)`
- Organic/content — content/SEO team
  - Organic traffic growth, by source (docs, blog, SEO)
  - Content publish velocity and engagement per piece
  - Docs traffic → signup conversion rate
  - Branded vs. non-branded organic search split
  - SEO ranking movement for target keywords
- Paid — demand gen/paid media
  - Spend and CPL/CPC/CPM by campaign
  - Paid conversion rate (click → signup/lead)
  - Paid pipeline ROAS (pipeline $ ÷ spend)
- Community/events — community/DevRel
  - Community active-member growth (Slack/Discord)
  - Event/webinar attendance and event-sourced pipeline
  - Community-to-paid conversion rate (prospects)
- Outbound SDR and segment-graduation volume — tracked under win rate and the company model's migration branch, not duplicated here

**Win rate** — ISR/AE
`Closed won ÷ (won + lost)`, new-business only, by segment
- Stage-to-stage conversion (SAL → SQO → POC → Proposal → Close)
- POC pass rate (Enterprise)
- Rep capacity / ramp mix
- Loss-reason mix (competitive / no-decision / price)

**Avg initial commitment** — sales
Realized deal size at close, by segment
- Discount rate vs. list
- Deal-size trend within segment band

**Marketing–sales handoff quality** — marketing ops + sales ops (diagnostic overlay on the above three, not a fourth multiplicative factor)
- MQL response SLA (time to first sales touch)
- MQL → SAL acceptance rate
- Lead recycling / nurture re-qualification rate

**Brand & awareness** (leading indicator, not summed into the pipeline math)
- Branded search volume trend
- Direct traffic share
- Share of voice vs. named competitors

### Activation — product/CS, shared driver for new-logo conversion and future expansion
`Days from provisioning to first production Action` (TTFA), by segment
- Onboarding completion rate
- Time-to-first-integration / first successful run
- Quickstart/docs content engagement rate — content/docs team

### Expansion consumption revenue — AM
`Wallet share progression × overage realization`, by segment

**Wallet share progression** — AM/product
% of an account's total addressable workflow footprint running through Acme Corp
- Workflow migration rate (new business processes onboarded per quarter)
- AM touch effectiveness (recommitment conversations)
- Existing-account community engagement depth — community/DevRel

**Overage realization** — AM/billing
Overage billing realized against usage crossing committed minimums

### Contraction + churned consumption revenue — AM
Driven by account health decline and lost renewals, by segment

**Workflow chain under-utilization** — product/AM (silent-churn proxy)
Upstream/trigger Actions occur but downstream/completion Actions sit idle
- Ingestion-without-completion rate
- Mid-chain workflow abandonment
- Declining share of full-chain vs. partial-chain runs

**Account health score**
- Usage trend (account-relative baseline)
- Support ticket volume / severity
- Engagement / login frequency
- AM sentiment notes

**Cyclical/planned usage dip vs. structural churn** — product/AM
Normalized against the account's own historical baseline or cohort
- Account-specific baseline deviation
- Cohort comparison (same account type, same period last cycle)

**Renewal win rate** (`opportunity_type = renewal`)
- Time-to-respond on churn-risk flag
- Loud (explicit cancellation) vs. silent (non-renewal) mix

## Efficiency — is the touch model paying for itself

### Magic number — by segment
`Net new ARR ÷ prior-period S&M cost` (numerator covered under Growth; S&M cost expanded below)

**S&M cost**
- Cost per channel activity (cost/MQL, cost/SDR meeting)
- Rep fully-loaded cost, incl. ramp
- Marketing spend allocation by channel

### Consumption payback — by segment (utilized Actions only, not billed)
`CAC ÷ utilized-Action margin` — excludes committed-but-unused capacity; flat ~80% gross margin assumed
- CAC by channel (unblended)
- Utilized vs. committed Action volume

**LTV by segment × acquisition channel** — AM/finance (**non-additive** diagnostic overlay on payback, not a mathematical child — payback is a single-window recovery ratio; LTV extends the same CAC-efficiency question over the account's full modeled life)
`Cumulative margin-adjusted revenue over a modeled retention-weighted horizon, by segment × acquisition channel` — 5-year horizon, flat 10% annual discount rate, same ~80% gross margin assumption as Consumption payback (reused, not re-derived). Built from a retention-curve input (Kaplan-Meier logo survival by entry segment, observed while enough accounts are at risk and extended forward past that point by a constant monthly hazard; compounding GRR is rejected, because monthly GRR counts month-to-month usage contraction, not whether the account is still a customer — `retention_cohorts.py` already tested acquisition channel as a retention driver and found no comparable differentiation, and this node's channel cut is shown for SMB only, where it carries signal through CAC, not through differential retention), an expansion-trajectory input (observed MRR per surviving account by age, which embeds expansion, overage and segment graduation; wallet share progression is not computable, so nothing is modeled from it), and the LTV : CAC ratio against both CAC bases: marketing-only, and rep-loaded (ISR cost for Commercial, AE and SE cost for Enterprise per won logo; AM cost excluded). LTV is by entry segment; Commercial and Enterprise are ranges, Enterprise directional only, and the marketing-only ratio is not decision-grade where reps are the acquisition cost. `mart_efficiency.blended_cac`, and so Consumption payback, stays marketing-only (the same fully-loaded-cost gap that already caveats payback and its `level_comparability: caveated` status); don't present this ratio as more trustworthy than the payback figure it extends.

These three drivers are kept as prose inside this one node, deliberately not broken out as separate Layer-3 tree items: Consumption payback is one of `variance_diagnostic.py`'s explicitly two-layer-deep branches (enforced at import time by `_verify_tree_integrity()`, alongside Onboarding/CS efficiency, Activation, and Logo retention) — giving LTV its own Layer-3 children would push that branch to three layers and fail the check on import, not just misreport. If a future revision needs the retention-curve/expansion-trajectory/ratio breakdown as real, independently-computable tree nodes, that requires first changing consumption_payback's depth invariant in code, not just editing this markdown file.

Acquisition channel persists as a stable account attribute through to the revenue and retention fact tables: `dim_accounts.channel` covers all 7,700 accounts with no nulls, so the channel cut needs no raw-data or mart prerequisite.

### Onboarding/CS efficiency — AM/CS, by segment
`Manual AM/CS touchpoints ÷ volume of automated Actions delivered`
- AM touchpoint volume (book size, ramp status, check-in cadence)
- Automated Action volume delivered (usage growth, account count)

### AM efficiency — AM, by segment
`Expansion consumption revenue ÷ AM cost` (numerator covered under Growth; AM cost expanded below)
- See Growth — expansion revenue drivers
- AM cost by segment (comp, ramp status, book size)

## Durability — is what we sold sticking

### NRR — by segment
`(Starting − Contraction − Churn + Expansion) ÷ Starting consumption revenue`
- See Growth — expansion, contraction, churn drivers

### GRR — by segment
`(Starting − Contraction − Churn) ÷ Starting consumption revenue`
- See Growth — contraction, churn drivers

### Logo retention — by segment
`Retained accounts ÷ starting accounts`
- Tenure-at-churn (early vs. late lifecycle)
- Churn reason category (loud vs. silent)
