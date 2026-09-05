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
