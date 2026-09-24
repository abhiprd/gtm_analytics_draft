# Acme Corp — Phase 1 raw data: edge cases, grounding, and test cases

Companion to `acme-corp-gtm-portfolio-build-spec.md`. This document exists so Phase 1 generation gets validated against explicit rules before anything downstream (dbt, the tree, any of the 22 artifacts) gets built on top of it — catching a bad generator assumption after Phase 4 is built is much more expensive than catching it here.

---

## Design decisions

- **No segment downgrade path.** An account that fails to activate churns out entirely at first contract end rather than demoting to a lower segment. Migration stays one-directional.
- **Mid-month migrations take effect the 1st of the following month.** No proration.
- **Expansion opportunities are a discrete AM-initiated event** (renegotiating a higher committed minimum) — metered overage within the existing commitment is billing-only, never spawns an opportunity.
- **Renewal timing respects actual contract term** — annual for Commercial, multi-year for Enterprise.
- **Rep ramp is a step function** (50% / 75% / 100% across quarters 1–2), not a hard cliff.
- **Rep departures trigger explicit account reassignment** to another rep on the same team/segment, logged as a handoff event — no orphaned ownership.
- **A modest cohort of accounts is seeded with already-established, staggered tenure at simulation start** — avoids an "everyone is new in month 1" artifact.
- **Currency is USD only.** No FX modeling.
- **No re-trial for SMB** — one signup per account for this simulation's scope.
- **`market_universe` carries "was ever a customer" separately from "is currently a customer.**"

---

## Edge cases by domain

### Segment & migration
- Firmographic-rescore migrations must actually fire in the generator independent of usage growth — don't let this trigger_reason value go unused because the usage-threshold path is mechanically easier to implement.
- Verify both trigger_reason categories (`usage_threshold`, `firmographic_rescore`) appear at non-trivial frequency, not just as a schema value that never occurs.

### Funnel & opportunities
- Every {channel} × {segment} combination must produce internally consistent records — an Enterprise-fit self-serve account gets full POC-stage opportunity treatment, not SMB single-Closed-Won treatment, even though product access started as a trial.
- Stage regression (backward movement, e.g., SQO → disqualified → re-qualified) needs to exist for a small % of deals — stage history that's always monotonic looks artificially clean.
- Deal "stall" patterns (long, variable time stuck in one stage, especially POC) need to be genuinely variable, not a fixed duration — this is the exact mechanism the sample readout's drill-down story depends on.
- `forecast_category` is the deal's final close-time call, not a relabelling of the outcome. It must be built from drivers that were genuinely visible when that call was made — how far through its segment's cycle envelope the deal ran, loss reason, POC outcome, discount depth, the renewal's own outcome, and the owner's ramp status — and mapped probabilistically, so it stays correlated with the outcome without becoming a perfect separator in either direction. A blanket `Commit` on every win (or an outcome-independent draw on every loss) makes the field either a duplicate of `is_won` or decoration; neither gives pipeline-review or forecast-accuracy analytics anything real to read. SMB new business and migration-driven expansions are the two deliberate exceptions, `Commit` by construction: a same-day self-serve signup has no forecast cadence, and a migration expansion formalises a committed minimum usage has already crossed — neither has a losing branch. Distinct from `fact_forecast_submissions`, which is a weekly point-in-time series and is forbidden from reading anything fixed at close; the two are built independently and neither reads the other.

### Usage & workflow data
- Invariant: downstream (completion) Actions ≤ upstream (trigger) Actions, per account per period, always.
- Invariant: utilized Action volume ≥ 0; committed Action volume ≥ 0.
- At least a meaningful subset of accounts must show sustained near-zero usage before their renewal date — without this, silent-churn detection has nothing real to catch.

### Revenue & billing
- No negative revenue; no utilized volume exceeding some implausible multiple of committed volume without a corresponding migration event.

### Rep/capacity
- No opportunity or account ownership gap when a rep departs — reassignment must be atomic with the departure event.
- New hires mid-quarter get a full ramp period starting from hire date, not prorated against the quarter boundary.
- `quota_history` amounts must be **derived from the opportunity generator's realized deal supply**, never set independently of it. Quota sized against an ACV band alone is the causal-wiring failure grounding requirement 2 forbids, applied to a target instead of a probability: it makes attainment a function of an arbitrary constant rather than of rep productivity, and a structurally unreachable quota leaves every downstream capacity and attainment diagnostic measuring a definitional mismatch instead of capacity. The derivation is opportunities closed per fully-ramped rep-quarter × that segment's realized win rate × average won deal size, measured over the simulation window only (earlier quarters carry a back-dated won-deal tail with no lost pipeline and understate supply).

### Health score (product-specific)
- Login/engagement frequency must be reinterpreted, not taken at face value — weight it higher in an account's first ~90 days, lower afterward, or a fully-automated healthy account gets flagged as at-risk for behaving exactly as the product intends.
- Support ticket volume needs lifecycle context (onboarding-period tickets ≠ same volume 14 months in) — severity alone doesn't resolve this ambiguity.

### Time window
- Right-censored accounts (still active, un-churned, un-renewed when the 36-month window ends) are expected — flag them as censored in any lifecycle/survival analysis rather than treating them as missing or as an error.

### Market universe
- Firmographic distribution must be calibrated against real segment/ACV bands — an uncalibrated universe produces nonsensical whitespace and ICP-fit numbers.

### Plan & variance
- `gtm_plan_targets` must cover exactly the closed set of ten plan-bearing Layer-1 metrics for every month in the simulation window, with no gaps — a missing (metric, month) row silently breaks whichever week's readout lands on it.
- Plan values must be genuinely independent of that period's realized actuals — generated top-down from the benchmark reference table and this simulation's business-scale constants, never derived from another generator's output for the same month. A plan that peeked at the actual would make "variance from plan" circular rather than a real comparison.

### Forecasting
- `fact_forecast_submissions` is scoped to Commercial/Enterprise opportunities only — SMB closes near-instantly with no stage history and no real weekly forecast cadence to snapshot. Every snapshot date is a Friday, and only for weeks the opportunity is actually open (between `created_date` and `close_date`).
- `rep_forecast_category` and `manager_forecast_category` must both trace to one shared, point-in-time win-propensity signal built only from what is genuinely knowable as of that Friday (current stage, stage-relative stall, POC outcome once revealed, rep ramp status) — never from `is_won` or `close_date`, which is the future relative to any snapshot before close.
- The two categories must diverge in a specific, directional way, not just add independent noise to the same signal: the rep call carries a real optimism bias on top of the shared propensity, the manager call is better calibrated, and both directions of disagreement (rep above manager, manager above rep) must actually occur — a taxonomy where only one direction fires isn't modeling a real rep/manager relationship, it's modeling a one-sided correction.
- `cro_forecast_adjustments`' `adjustment_amount` and `reason` must trace to a real, computed pipeline-coverage signal for that segment/period (open pipeline relative to remaining target or historical close rates), not an independent draw — a thin-coverage period should land a negative, coverage-shortfall-reasoned adjustment more often than a coin flip would produce.

### Marketing attribution
- The organic/paid/community taxonomy on `campaigns`, `leads` and `campaign_engagement_events` decomposes the `inbound_marketing` value of `accounts.channel`. It is not a second, competing channel field: it carries no `self_serve` volume (product-led) and no `outbound_sdr` volume (tracked under win rate), and channel still stays orthogonal to segment — each sub-channel produces accounts in all three segments, with a firmographic tilt rather than a partition.
- Every account acquired through `inbound_marketing` must be explained by exactly one converting lead, created strictly earlier than that account's `signup_date`. A lead created the same day as the signup it explains leaves no funnel behind it to attribute. The check runs in both directions — a converting lead resolving to a real account is not sufficient if part of the inbound population has no lead at all.
- Non-converting lead volume must be sized off a stated lead-to-customer conversion rate per sub-channel, not picked. The companies behind those leads come from `market_universe`'s non-customer population rather than being invented, so every lead carries real firmographics; a company that is or ever was a customer is excluded, since its lead is the converting one.
- `campaign_engagement_events` is touch grain and is never deduplicated to one row per lead or per campaign. A lead that only ever sees one campaign makes first-touch, last-touch and linear attribution return the same answer, so multi-campaign and cross-sub-channel touch paths both have to actually occur.
- No touch attributed as pre-conversion evidence may fall on or after its lead's `converted_date`, no touch may fall outside its own campaign's window, and touches must be strictly ordered within a lead — two touches sharing a timestamp leave a lead's first-touch and last-touch position ambiguous, which is exactly what attribution reads.
- `leads.lead_score` is the lead's composite as of its terminal state, not a point-in-time score: it reads observed engagement depth, so it is not a valid feature for predicting the conversion it already reflects. Point-in-time scoring belongs to `lead_scoring_history`, and this column is not a substitute for it.
- The campaign calendar is anchored to the account population's real signup range rather than to the simulation window — the established staggered-tenure cohort predates `SIM_START` and its leads still need a campaign to attach to.
- Holdout campaigns must be genuinely suppressed, not merely flagged. The control cell's leads have the campaign treatment withheld, so they are touched less and convert materially worse than treated leads in the same sub-channel and the same period; the gap between the two is the incremental lift the test exists to measure. Only channels that can actually be switched off for a chosen cell carry a holdout — a flag on an organic/SEO campaign would have no operational meaning.

---

## Grounding requirements

1. **Benchmark reference table** — every generator parameter should trace to a row here; if a distributional realism test fails, check this table before assuming the generator is wrong.

   | Metric | SMB | Commercial | Enterprise | Basis |
   |---|---|---|---|---|
   | ACV range | $0–15K | $15–75K | $75–750K | Set in build spec Section 1 |
   | Sales cycle | Instant–7 days | 14–45 days | 60–180 days | Set in build spec Section 1 |
   | Win rate (new business) | n/a — no win-rate concept | ~25–35% | ~20–30% | Typical SaaS new-business range; Enterprise lower given longer, higher-stakes cycles |
   | NRR | ~96–97% | ~105–110% | ~118–125% | Research-grounded (segment NRR spread, cited during metric-tree design) |
   | GRR | ~80–85% | ~88–92% | ~92–95% | Estimated, consistent with the NRR spread and typical B2B SaaS GRR |
   | Logo retention (annual) | ~75–85% | ~88–93% | ~93–97% | Estimated, consistent with touch-model intensity |
   | Magic number | n/a | ~0.7–0.9 | ~0.7–0.9 | "Good" SaaS range from Efficiency-pillar research |
   | Consumption payback | n/a | ~14–18 mo | ~9–13 mo | Estimated — Enterprise's larger ACV amortizes its higher CAC faster despite costing more to acquire |

   Only the NRR row is backed by cited research; the rest are reasoned estimates for internal consistency, not sourced benchmarks.

   The table above is keyed by segment. The marketing funnel's parameters are keyed by sub-channel instead, so they trace to this companion table rather than to a row above:

   | Parameter | Organic/content | Paid | Community/events | Basis |
   |---|---|---|---|---|
   | Lead → customer conversion | ~5–6% | ~3% | ~8% | Typical B2B SaaS MQL-to-customer range; spread reflects intent quality — self-directed organic arrives with intent, community/event leads with a relationship already formed, paid reach is the broadest and least qualified |
   | Lead-to-signup gap (median) | ~2 weeks | ~1 month | ~2 months | Consistent with build spec Section 1's sales-cycle gradient, scaled by segment on top |
   | Touches per lead | Highest | Lowest | Middle | Content channels accumulate many low-weight touches; paid is a short click path; community is event-centric, a handful of heavier interactions |
   | CAC, as a multiple of blended inbound CAC | ~0.55x | ~1.55x | ~1.0x | Weighted by the sub-channel mix these reconcile to ~1.0x, keeping the finer split consistent with the coarse CAC `marketing_spend_by_channel_month` already implies rather than restating it differently |
   | Holdout conversion, as a share of treated | n/a — not held out | ~35% | ~35% | Implies ~65% incremental lift, inside the range paid-media incrementality tests report for mid-funnel programs |

   None of these is a sourced benchmark either; same caveat as above.
2. **Causal wiring is mandatory, not optional.** Win probability, churn probability, usage growth, and marketing conversion must be generated as actual functions of their real drivers (ramp status, deal characteristics, POC outcome, health-score trajectory, activation speed, touch volume and recency) — independently-random columns produce a dataset with nothing for any diagnostic artifact to find.
3. **3–5 deliberately injected incidents across the 36 months** — a POC-process regression, a channel's CAC creeping up, a meetings-rise-without-SQO-conversion-rise decoupling period, an underperforming rep cohort. Calibrated to be detectable, not blatant.
4. **Explicit signal-to-noise targets** — e.g., health-score inputs should predict eventual churn at roughly 65–80% AUC. States the generator's success criterion instead of hoping the output lands somewhere reasonable.

---

## Test cases

### A. Referential / structural integrity
- Every `opportunities.account_id` resolves to a real account
- `opportunity_stage_history` is chronologically ordered per opportunity
- `account_segment_history` rows are chronological, non-overlapping, no gaps
- SMB accounts have exactly 0 or 1 opportunity record, never more
- Downstream Actions ≤ upstream Actions in every `fact_workflow_chain_events` account-period
- No orphaned account/opportunity ownership after any rep departure
- `gtm_plan_targets` has exactly one row per (layer1_metric, month) for all ten plan-bearing metrics across the full simulation window, no duplicates, no gaps, no nulls
- Every converting `leads.account_id` resolves to a real account acquired through `inbound_marketing`, and every such account is explained by exactly one converting lead — checked in both directions
- Every `leads.company_id` resolves to `market_universe`; a converting lead's company matches its account's, and non-converting leads draw only from companies that are neither current nor former customers
- Every `campaign_engagement_events.lead_id` and `campaign_id` resolves, every lead carries at least one touch, and every event's `channel` and `event_type` match its campaign's channel and that channel's closed event vocabulary
- Every touch falls on or after its lead's `created_date`, strictly before its `converted_date`, and inside its own campaign's window; touches are strictly ordered within a lead, with no shared timestamps
- `campaigns.is_holdout` is set only on channels and periods the holdout program actually defines
- Every `fact_forecast_submissions.opportunity_id` resolves to a real Commercial/Enterprise opportunity, no SMB opportunity appears, no duplicate (opportunity_id, snapshot_date) pairs, every snapshot_date falls on a Friday inside that opportunity's open window
- Every `cro_forecast_adjustments.reason` is one of the closed set the generator defines, and every row's `period`/`segment` pair is a real evaluated period

### B. Distributional realism
- ACV falls within its segment's defined range; flag and investigate outliers
- Aggregate revenue mix lands near ~65–70% Enterprise ARR (tolerance band, not exact)
- Win rate, sales-cycle length, and churn rate by segment land within the benchmark reference table's ranges
- ISR and AE quota attainment over the simulation window each land in a **70–120%** band — quota set at fully-ramped rep productivity is genuinely missed and genuinely beaten, so the band is wide enough to admit real variance and narrow enough to catch quota decoupling from deal supply in either direction. The table above has no quota row; this band is the generator's own documented resolved decision, grounded in the conventional SaaS practice of setting a target at (not far above) median rep capacity so a majority of reps land between roughly 60% and 100% with real spread on both sides
- NRR/GRR by segment land near the grounding targets (~118% / ~97%)
- `gtm_plan_targets` values land within a defensible range per metric — the benchmark reference table's ranges (blended to a company-wide figure) for the six metrics it covers, and the generator's own documented resolved-decision range for `new_logo_consumption_revenue`, `am_efficiency` and `onboarding_cs_efficiency`, which the table has no row for. `expansion_consumption_revenue` and `contraction_churned_revenue` are neither: the metric tree defines NRR and GRR as those exact flows, so both lines are *derived* from this table's blended NRR/GRR rows (`contraction_share = 1 − GRR**(1/12)`, `expansion_share = NRR**(1/12) − 1 + contraction_share`) and their band is the envelope that derivation produces against the planned revenue base. A plan whose flow rows and durability rows state the same identity two different ways is a bug, so the reconciliation between them is asserted directly rather than left to the range check

- Lead-to-customer conversion rate, lead-to-signup gap, touches per lead and CAC each land inside the sub-channel companion table's band, and total campaign budget over the simulation window reconciles with `marketing_spend_by_channel_month`'s `inbound_marketing` total — the two are independently built views of the same money at different grains, so exact agreement isn't expected, but a large divergence means the finer split has drifted from the coarse figure several Efficiency-pillar metrics already read
- Every value in each sub-channel's event vocabulary actually occurs — an event type that exists only as a schema value and never fires is the same defect flagged above for migration `trigger_reason`

### C. Correlational validity — the "meaningful results" tests
- POC pass = true shows a statistically higher close rate than POC pass = false
- Accounts that eventually churn show a measurably declining health-score trend in the months prior, distinguishable from non-churning accounts
- A naive churn model built on health-score inputs beats random chance by a meaningful, bounded margin (target AUC 0.65–0.80 — not ~0.5, not ~0.98)
- Ramping reps show measurably lower win rate than ramped reps, but not zero
- Realized win rate rises strictly with `forecast_category` rank (Omitted < Pipeline < Best Case < Commit) while no category is a perfect separator — a Commit that always closed, or a lower category that never did, means the field has collapsed onto `is_won`; equal rates across categories mean it is independent noise. The named drivers must be visible in the output too: a `no_decision` loss sits at a lower average rank than a `price` loss, and a ramping rep's Commit converts measurably worse than a ramped rep's
- Channels show genuinely different CAC/conversion profiles from each other — organic, paid, and community should not look statistically identical. This is asserted at that grain, on `campaigns`/`leads`, since `accounts.channel` carries the coarse acquisition taxonomy and contains none of those three values. Checked pairwise and statistically across five axes — conversion rate, touch volume, lead-to-signup gap, CAC, and lead-score distribution — with no two sub-channels alike on all five at once
- Touch volume and touch recency predict conversion: bucketing leads by touch count produces a monotonically rising conversion rate, and a lead still being touched weeks after creation converts far better than one that went quiet within days. Without both, multi-touch attribution has no real signal to attribute and every attribution model reduces to a reweighting of noise
- `leads.lead_score` correlates with eventual conversion by a meaningful, bounded margin and rises with both of its drivers (firmographic fit and engagement depth) — a composite carrying no outcome signal is independent noise; one that nearly determines the outcome has collapsed onto it
- Opportunities where the manager downgrades a confident rep call close at a measurably lower rate than opportunities where rep and manager agree — the gap is the actual point of carrying two categories instead of one, and it must hold across new-business and renewal/expansion cuts separately, not just in aggregate where one cut could be masking the other
- At least one injected incident period is detectable by a straightforward variance check (confirms the injected-incident mechanism actually works before relying on it)

### D. Volume/sufficiency for modeling
- Minimum N of Closed-Won and Closed-Lost per segment per quarter, sufficient to train/validate a win-probability model
- Churned accounts present in large enough number for reasonable class balance (not a 99.9/0.1 split, which is unlearnable)
- Enough distinct reps with enough deals each that rep-level productivity signal isn't dominated by single-rep noise
- `market_universe` non-customer volume is a large enough multiple of customer volume (aim for 10–50x, not 2–3x) that whitespace percentages are meaningful
- Minimum leads, conversions and campaigns per sub-channel sufficient to fit a channel-level attribution model, with enough total touch volume that multi-touch paths aren't dominated by single-lead noise, and inbound conversions spread across the whole window rather than concentrated in one period
- The holdout cell carries enough leads on its own for its suppressed conversion rate to be separable from noise — an incrementality test on a handful of leads is not a test
- Enough opportunities carry enough weekly snapshots across their open window that a rep-vs-manager-gap analysis isn't dominated by a handful of long-cycle deals

### E. Edge-case-specific existence checks
- At least some segment migrations are `firmographic_rescore`-triggered, not only `usage_threshold`
- At least some accounts show the sustained-near-zero-usage-before-renewal pattern
- At least some deals show stage regression
- At least some reps depart mid-simulation with a clean reassignment, zero ownership gap
- High-automation, low-login, high-Actions accounts exist and are **not** predominantly mis-flagged as at-risk — this directly validates the health-score reweighting logic above
- Both directions of rep/manager forecast disagreement occur (rep more confident than manager, and manager more confident than rep) — not just the one-sided optimism-correction case
- All four `cro_forecast_adjustments.reason` values occur at least once, not just as unused schema values
- Holdout/control cells exist, per the build spec's incrementality requirement, and are genuinely suppressed rather than merely flagged: measured like-for-like against treated campaigns in the same sub-channels and quarters, the control cell is touched significantly less, converts materially worse, and carries a withheld rather than a re-labelled budget
- Leads touched by more than one campaign exist, and so do touch paths crossing sub-channels — both ends of the engagement distribution (single-touch leads and deeply-engaged leads) are present
- The injected CAC-creep incident is locatable to paid media at campaign grain, not only visible as an aggregate rise across `inbound_marketing` — the coarse spend table cannot show which sub-channel a cost creep came from

**Deferred**: whether `gtm_plan_targets` actually produces real, detectable variance once compared against computed actuals (some months genuinely ahead of plan, some genuinely behind, not every metric drifting the same direction every month) can't be checked at the Phase 1 raw-data layer — there's no "actual" to compare against until Phase 2's marts exist. That correctness check belongs to the Phase 4 variance-diagnostic engine's own build-time validation, not to this suite.

**Deferred**: whether any particular attribution model — first-touch, last-touch, linear, time-decay, Markov — assigns credit correctly, and what incremental lift the holdout cells imply once confounders are controlled, are properties of the marketing attribution & channel mix artifact rather than of this raw data. What the raw layer can guarantee, and does, is that the artifact has something real to work on: every touch present and undeduplicated, multi-campaign and cross-sub-channel paths that actually exist, touch volume and recency that genuinely predict conversion, three sub-channels that are statistically distinct, and a control group that is really suppressed. Model correctness belongs to that artifact's own build-time validation.
