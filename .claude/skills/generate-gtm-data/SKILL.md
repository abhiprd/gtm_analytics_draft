---
name: generate-gtm-data
description: Use when writing or extending Phase 1 raw data generators for the Acme Corp GTM portfolio (accounts, opportunities, usage, marketing, billing, market universe, etc.). Encodes the resolved edge-case decisions, grounding requirements, and causal-wiring rules from acme-corp-phase1-data-qa-plan.md so every generator follows the same rules instead of rediscovering them independently.
---

# Generating Acme Corp GTM data

Before writing any generator code, read `docs/acme-corp-phase1-data-qa-plan.md` in full — this skill summarizes it, but the QA plan is the source of truth.

## Non-negotiable rules for every generator

1. **Causal wiring, not independent randomness.** Every outcome column (win/loss, churn, usage growth) must be generated as a function of real drivers already in the data (segment, rep ramp status, deal characteristics, health-score trajectory, activation speed) — never independently sampled. If you can't name the causal function, the field isn't ready to generate.
2. **Event grain, not pre-aggregated.** Generate individual activities, individual touches, individual scoring events. Aggregation happens in dbt.
3. **Enforce every stated invariant as you generate, not as a post-hoc check:**
   - Downstream Actions ≤ upstream Actions per account per period
   - No negative volumes anywhere
   - `opportunity_stage_history` chronological per opportunity (a small % may show stage regression — see QA plan)
   - `account_segment_history` chronological, non-overlapping, no gaps
   - SMB accounts: exactly 0 or 1 opportunity record, always Closed Won, never Closed Lost
4. **Seed every source of randomness.** Reproducibility is required, not optional.
5. **Inject 3–5 deliberate incidents across the 36-month window** (a POC-process regression, a channel's CAC creeping up, a meetings-rise-without-SQO-rise decoupling period, an underperforming rep cohort) — calibrated to be detectable by a straightforward variance check, not blatant. A dataset with only steady-state noise gives every downstream diagnostic artifact nothing to find.
6. **Ground every distributional parameter against the benchmark reference table** in the QA plan (win rate ranges, NRR ~118% Enterprise / ~97% SMB, sales-cycle length by segment, etc.) — don't pick a number because it seems plausible; pick it because it matches a stated target.

## Resolved decisions to apply without re-litigating

- No segment downgrade — failed-activation accounts churn entirely at first contract end
- Segment migrations take effect the 1st of the month following the trigger
- Expansion opportunities are a discrete AM-initiated event (renegotiated committed minimum) — plain overage billing never spawns an opportunity
- Renewal timing respects actual contract term (annual Commercial, multi-year Enterprise)
- Rep ramp is a step function: 50% / 75% / 100% across quarters 1–2, not a cliff
- Rep departures trigger explicit, atomic account/opportunity reassignment — never leave an ownership gap
- Seed a modest cohort of accounts with already-established, staggered tenure at simulation start — don't let month 1 look like everyone just signed up
- `market_universe`: `is_customer` tracks current status; a separate flag tracks "was ever a customer." Firmographic distribution must be calibrated against real segment/ACV bands, and volume should be 10–50x the actual customer count so whitespace percentages are meaningful, not trivial.

## Health-score-specific rule (product-specific, easy to get wrong)

Login/engagement frequency is **not** a reliable standalone health signal for this product — a fully automated, "set and forget" workflow can be perfectly healthy with almost no logins. Weight login/engagement higher in an account's first ~90 days, lower after. Support ticket volume needs lifecycle context (onboarding-period tickets are normal; the same volume at month 14 is a signal) — don't treat raw ticket count as inherently negative.

## Before marking any generator done

Run the `validate-gtm-data` skill's test suite against the output. A generator is not complete because it runs without errors — it's complete when the QA plan's test cases (referential integrity, distributional realism, correlational validity, volume sufficiency, edge-case existence) all pass.
