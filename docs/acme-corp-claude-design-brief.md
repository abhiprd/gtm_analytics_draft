# Brief: Acme Corp — GTM health metric tree + weekly readout deck

## Context

This is a portfolio artifact demonstrating a GTM analytics diagnostic framework: a rigorous "metric tree" (every parent metric is the actual mathematical result of its children, not just a related grouping) applied to a consumption-based B2B SaaS company, plus a sample weekly executive readout built on top of it. Audience is professional (think: something a VP/CRO of GTM analytics would actually present or receive) — polished and credible, not playful.

A first pass of this deck was built with a hand-coded script (pptxgenjs), which produces a working `.pptx` but relies on manual coordinate placement rather than true layout — it's structurally prone to the kind of spacing/overlap issues a proper design tool avoids by construction. That's why this is being handed off. The content below is final and shouldn't need re-reporting; the ask is a better-designed, better-laid-out version of the same material.

## What this deck has to communicate

1. **A metric tree**, not a metrics dashboard. Revenue health is decomposed into three pillars — Growth, Efficiency, Durability — each broken into top-level (Layer 1) metrics, each of those broken into Layer 2 drivers, and some Layer 2 nodes further broken into Layer 3 root-cause leaves. The entire point of the artifact is that a reader can always tell what layer they're looking at and how it connects upward to its parent. If the hierarchy isn't legible at a glance on every slide, the deck has failed its brief regardless of how polished it looks.
2. **A sample weekly readout** built on that exact tree — proof the tree is usable in an operating cadence, not just a diagram. It needs its front matter (reporting period, audience) and full executive summary included, not summarized down for slide space.

## Design requirements and lessons from the first pass

- **Every pillar needs a parallel "map" moment**: a place where all of that pillar's Layer-1 nodes appear side by side, each shown as a complete unit — name, owner, formula, and its direct children. Efficiency and Durability naturally worked this way (3 nodes each, shallow enough to fit one slide); Growth has 4 Layer-1 nodes and much deeper sub-structure, and it's tempting to skip straight into its sub-branches without ever showing the Layer-1 map. Don't skip it — Growth needs the exact same "here's what this level means" treatment before diving deeper, or it reads as structurally inconsistent with the other two pillars.
- **Level badges/labels must be unambiguous everywhere.** A reader should never have to guess whether a card is a Layer 1, 2, or 3 node. Whatever visual system marks this (badge, indent depth, breadcrumb, color) needs to be consistent across every slide, including the readout slides.
- **Don't force uniform depth.** Some branches genuinely only go two layers deep (e.g., Consumption Payback's two children are leaves, full stop) while others go three (e.g., Win Rate has leaf-level detail beneath it). Don't pad a shallow branch with invented content to make it "match" a deeper one, and don't flatten a deep branch to match a shallow one.
- **Avoid uneven card fill.** Cards with 2 bullets and cards with 5 bullets sitting at the same fixed height produce awkward, unbalanced whitespace. Size to content, or handle variable content length gracefully (this is something a real design tool should do natively rather than needing manual per-card height tuning).
- **No accent stripes, edge bars, or color bars as a design motif.** If pillars need color-coding, use it in the title text or a small identifier (dot, badge) — not a stripe down the edge of a card or slide.
- **Overlays vs. formula terms need to stay visually distinct.** In the New Logo branch specifically, two nodes (marketing–sales handoff quality, brand & awareness) are diagnostic overlays that sit alongside the three actual multiplicative factors (pipeline generated, win rate, avg commitment) — they should never look like a 4th and 5th factor in the equation. Both are explicitly labeled as non-additive in the content below; that distinction needs to survive visually, not just in a caption.
- **Readout drill-downs vary week to week; the Layer 1 scorecard does not.** The weekly readout has two structurally different things happening: a fixed set of 11 Layer-1 metric cards that appear identically every week (value, vs. plan, status), and a variable set of drill-downs that only appear for whichever Layer-1 metrics actually deviated that week. Don't let the design imply the drill-downs are also a fixed, exhaustive set.

## Suggested color/style starting point (adjust freely — better design judgment here is the whole point of this handoff)

First pass used a navy/teal/terracotta palette (navy = Growth, teal = Efficiency, terracotta = Durability), safe-list serif headers (Cambria) over sans body (Calibri), white cards on a light neutral background. Keep, discard, or improve as fits — nothing here is load-bearing except the content and the hierarchy legibility requirement above.

---

## Content — Part 1: the metric tree

**Company: Acme Corp**

### Growth — consumption revenue growth
`Starting consumption revenue + New logo − Contraction − Churn + Expansion` (± segment migration, nets to zero)

**New logo consumption revenue** — owner: marketing + sales
`Pipeline generated × win rate × avg initial commitment`, by segment

- **Pipeline generated** — marketing
  `Σ over channels (channel volume × channel-to-lead rate × lead-to-PQL rate)`
  - *Organic/content* — content/SEO team
    - Organic traffic growth, by source (docs, blog, SEO)
    - Content publish velocity and engagement per piece
    - Docs traffic → signup conversion rate
    - Branded vs. non-branded organic search split
    - SEO ranking movement for target keywords
  - *Paid* — demand gen/paid media
    - Spend and CPL/CPC/CPM by campaign
    - Paid conversion rate (click → signup/lead)
    - Paid pipeline ROAS (pipeline $ ÷ spend)
  - *Community/events* — community/DevRel
    - Community active-member growth (Slack/Discord)
    - Event/webinar attendance and event-sourced pipeline
    - Community-to-paid conversion rate (prospects)
  - Outbound SDR and segment-graduation volume — tracked under win rate and the migration model, not duplicated here
- **Win rate** — ISR/AE
  `Closed won ÷ (won + lost)`, new-business only, by segment
  - Stage-to-stage conversion (SAL → SQO → POC → Proposal → Close)
  - POC pass rate (Enterprise)
  - Rep capacity / ramp mix
  - Loss-reason mix (competitive / no-decision / price)
- **Avg initial commitment** — sales
  Realized deal size at close, by segment
  - Discount rate vs. list
  - Deal-size trend within segment band
- **Marketing–sales handoff quality** — marketing ops + sales ops — *diagnostic overlay, not a 4th multiplicative factor*
  - MQL response SLA (time to first sales touch)
  - MQL → SAL acceptance rate
  - Lead recycling / nurture re-qualification rate
- **Brand & awareness** — *leading indicator, not summed into the pipeline math*
  - Branded search volume trend
  - Direct traffic share
  - Share of voice vs. named competitors

**Activation** — owner: product/CS, shared driver for new-logo conversion and future expansion
`Days from provisioning to first production Action` (TTFA), by segment
- Onboarding completion rate
- Time-to-first-integration / first successful run
- Quickstart/docs content engagement rate — content/docs team

**Expansion consumption revenue** — owner: AM
`Wallet share progression × overage realization`, by segment
- **Wallet share progression** — AM/product
  % of an account's total addressable workflow footprint running through Acme Corp
  - Workflow migration rate (new business processes onboarded per quarter)
  - AM touch effectiveness (recommitment conversations)
  - Existing-account community engagement depth — community/DevRel
- **Overage realization** — AM/billing
  Overage billing realized against usage crossing committed minimums

**Contraction + churned consumption revenue** — owner: AM
Driven by account health decline and lost renewals, by segment
- **Workflow chain under-utilization** — product/AM (silent-churn proxy)
  Upstream/trigger Actions occur but downstream/completion Actions sit idle
  - Ingestion-without-completion rate
  - Mid-chain workflow abandonment
  - Declining share of full-chain vs. partial-chain runs
- **Account health score**
  - Usage trend (account-relative baseline)
  - Support ticket volume / severity
  - Engagement / login frequency
  - AM sentiment notes
- **Cyclical/planned usage dip vs. structural churn** — product/AM
  Normalized against the account's own historical baseline or cohort
  - Account-specific baseline deviation
  - Cohort comparison (same account type, same period last cycle)
- **Renewal win rate** (`opportunity_type = renewal`)
  - Time-to-respond on churn-risk flag
  - Loud (explicit cancellation) vs. silent (non-renewal) mix

### Efficiency — is the touch model paying for itself

**Magic number** — by segment
`Net new ARR ÷ prior-period S&M cost` (numerator covered under Growth; S&M cost expanded below)
- **S&M cost**
  - Cost per channel activity (cost/MQL, cost/SDR meeting)
  - Rep fully-loaded cost, incl. ramp
  - Marketing spend allocation by channel

**Consumption payback** — by segment (utilized Actions only, not billed)
`CAC ÷ utilized-Action margin` — excludes committed-but-unused capacity; flat ~80% gross margin assumed
- CAC by channel (unblended)
- Utilized vs. committed Action volume

**Onboarding/CS efficiency** — AM/CS, by segment
`Manual AM/CS touchpoints ÷ volume of automated Actions delivered`
- AM touchpoint volume (book size, ramp status, check-in cadence)
- Automated Action volume delivered (usage growth, account count)

**AM efficiency** — AM, by segment
`Expansion consumption revenue ÷ AM cost` (numerator covered under Growth; AM cost expanded below)
- See Growth — expansion revenue drivers
- AM cost by segment (comp, ramp status, book size)

### Durability — is what we sold sticking

**NRR** — by segment
`(Starting − Contraction − Churn + Expansion) ÷ Starting consumption revenue`
- See Growth — expansion, contraction, churn drivers

**GRR** — by segment
`(Starting − Contraction − Churn) ÷ Starting consumption revenue`
- See Growth — contraction, churn drivers

**Logo retention** — by segment
`Retained accounts ÷ starting accounts`
- Tenure-at-churn (early vs. late lifecycle)
- Churn reason category (loud vs. silent)

---

## Content — Part 2: the weekly readout

**Reporting period:** August 24 – August 30, 2026
**Audience:** Chief Revenue Officer · GTM leadership team

**Executive summary:**

Expansion and NRR are both ahead of plan on Enterprise wallet-share growth. New logo ARR missed plan by 12% — Enterprise win rate dropped to 24%, and it's a POC problem, not competitive loss. Consumption payback lengthened to 14.2 months: paid-channel CAC actually fell 6% on stronger organic-assisted conversion, offset by higher SE cost onboarding two large Enterprise accounts through POC.

Contraction/churn came in $15K worse than plan — one Enterprise account cut its committed Action volume at renewal; AM notes cite internal resistance to retiring a legacy scheduler despite a completed technical migration.

**Layer 1 — Growth**

| Metric | Value | vs. plan | Status |
|---|---|---|---|
| New logo consumption revenue | $185K | $210K plan | Behind |
| Activation (TTFA, blended) | 2.1 days | 2.4d last month | Ahead |
| Expansion consumption revenue | $310K | $290K plan | Ahead |
| Contraction + churned revenue | −$95K | −$80K plan | Behind |

**Layer 1 — Efficiency**

| Metric | Value | vs. plan | Status |
|---|---|---|---|
| Magic number (blended) | 0.81 | 0.75 plan | Ahead |
| Consumption payback (blended) | 14.2 mo | 13.0mo plan | Behind |
| Onboarding/CS efficiency (blended) | 71.4K Actions/touch | 66.0K plan | Ahead |
| AM efficiency (blended) | 4.2x | 3.8x plan | Ahead |

**Layer 1 — Durability**

| Metric | Value | vs. plan | Status |
|---|---|---|---|
| NRR | 121% | 119% plan | Ahead |
| GRR | 93% | 94% plan | Behind |
| Logo retention | 97.2% | 97.0% plan | On track |

**This week's drill-downs** (only these three Layer-1 nodes had a Layer-2 child that was a real outlier — the rest are on-plan or explained elsewhere)

1. **New logo consumption revenue** — $185K vs. $210K plan
   - Layer 2: pipeline generated and avg initial commitment are within 2% of plan; win rate is the outlier — 24% this week vs. 31% trailing 8-week average
   - Layer 3, two siblings under win rate: POC pass rate dropped 68% → 54%; separately, 3 of the last 5 losses are coded no-decision, not competitive

2. **Contraction + churned revenue** — −$95K vs. −$80K plan (also the source of this week's GRR miss — GRR reuses this same node, so it doesn't get a separate drill-down)
   - Layer 2: workflow chain under-utilization, account health score, and cyclical/structural churn are all within normal range; renewal win rate is the outlier — 78% of renewal-weighted $ retained vs. an 85% trailing average
   - Layer 3, two siblings under renewal win rate: time-to-respond on the churn-risk flag was within SLA; the mix leans loud — one Enterprise account's explicit reduction, citing internal resistance to retiring a legacy scheduler despite a completed technical migration

3. **Consumption payback** — 14.2 months vs. 13.0mo plan (tree only goes to Layer 2 here — don't invent a Layer 3)
   - Layer 2: CAC by channel is the outlier — Enterprise-channel CAC rose from added SE time on two POC-heavy deals, while paid-channel CAC fell 6%; utilized-vs-committed Action volume is flat vs. plan, not a contributor this week

---

## Suggested slide flow (starting point, not a requirement)

1. Title
2. Pillar overview (Growth, Efficiency, Durability — one line each)
3. Growth — pillar map (all 4 Layer-1 nodes as parallel complete units)
4. Growth — New logo revenue: pipeline generated (3 channels)
5. Growth — New logo revenue: win rate, commitment, and the two overlays
6. Growth — activation and expansion
7. Growth — contraction and churned revenue
8. Efficiency (4 Layer-1 nodes as parallel complete units)
9. Durability (3 Layer-1 nodes as parallel complete units)
10. Weekly readout — reporting period, audience, executive summary
11. Weekly readout — Layer 1 scorecard (11 metrics)
12. Weekly readout — this week's drill-downs
