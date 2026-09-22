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

### Usage & workflow data
- Invariant: downstream (completion) Actions ≤ upstream (trigger) Actions, per account per period, always.
- Invariant: utilized Action volume ≥ 0; committed Action volume ≥ 0.
- At least a meaningful subset of accounts must show sustained near-zero usage before their renewal date — without this, silent-churn detection has nothing real to catch.

### Revenue & billing
- No negative revenue; no utilized volume exceeding some implausible multiple of committed volume without a corresponding migration event.

### Rep/capacity
- No opportunity or account ownership gap when a rep departs — reassignment must be atomic with the departure event.
- New hires mid-quarter get a full ramp period starting from hire date, not prorated against the quarter boundary.

### Health score (product-specific)
- Login/engagement frequency must be reinterpreted, not taken at face value — weight it higher in an account's first ~90 days, lower afterward, or a fully-automated healthy account gets flagged as at-risk for behaving exactly as the product intends.
- Support ticket volume needs lifecycle context (onboarding-period tickets ≠ same volume 14 months in) — severity alone doesn't resolve this ambiguity.

### Time window
- Right-censored accounts (still active, un-churned, un-renewed when the 36-month window ends) are expected — flag them as censored in any lifecycle/survival analysis rather than treating them as missing or as an error.

### Market universe
- Firmographic distribution must be calibrated against real segment/ACV bands — an uncalibrated universe produces nonsensical whitespace and ICP-fit numbers.

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
2. **Causal wiring is mandatory, not optional.** Win probability, churn probability, and usage growth must be generated as actual functions of their real drivers (ramp status, deal characteristics, POC outcome, health-score trajectory, activation speed) — independently-random columns produce a dataset with nothing for any diagnostic artifact to find.
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

### B. Distributional realism
- ACV falls within its segment's defined range; flag and investigate outliers
- Aggregate revenue mix lands near ~65–70% Enterprise ARR (tolerance band, not exact)
- Win rate, sales-cycle length, and churn rate by segment land within the benchmark reference table's ranges
- NRR/GRR by segment land near the grounding targets (~118% / ~97%)

### C. Correlational validity — the "meaningful results" tests
- POC pass = true shows a statistically higher close rate than POC pass = false
- Accounts that eventually churn show a measurably declining health-score trend in the months prior, distinguishable from non-churning accounts
- A naive churn model built on health-score inputs beats random chance by a meaningful, bounded margin (target AUC 0.65–0.80 — not ~0.5, not ~0.98)
- Ramping reps show measurably lower win rate than ramped reps, but not zero
- Channels show genuinely different CAC/conversion profiles from each other — organic, paid, and community should not look statistically identical
- At least one injected incident period is detectable by a straightforward variance check (confirms the injected-incident mechanism actually works before relying on it)

### D. Volume/sufficiency for modeling
- Minimum N of Closed-Won and Closed-Lost per segment per quarter, sufficient to train/validate a win-probability model
- Churned accounts present in large enough number for reasonable class balance (not a 99.9/0.1 split, which is unlearnable)
- Enough distinct reps with enough deals each that rep-level productivity signal isn't dominated by single-rep noise
- `market_universe` non-customer volume is a large enough multiple of customer volume (aim for 10–50x, not 2–3x) that whitespace percentages are meaningful

### E. Edge-case-specific existence checks
- At least some segment migrations are `firmographic_rescore`-triggered, not only `usage_threshold`
- At least some accounts show the sustained-near-zero-usage-before-renewal pattern
- At least some deals show stage regression
- At least some reps depart mid-simulation with a clean reassignment, zero ownership gap
- High-automation, low-login, high-Actions accounts exist and are **not** predominantly mis-flagged as at-risk — this directly validates the health-score reweighting logic above
