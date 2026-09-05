---
name: validate-gtm-data
description: Use after running any Phase 1 generator or dbt build for the Acme Corp GTM portfolio, before treating the output as usable. Runs the test suite defined in acme-corp-phase1-data-qa-plan.md — referential integrity, distributional realism, correlational validity, volume sufficiency, and edge-case existence checks — and reports which category failed so it's fixed at the source rather than patched downstream.
---

# Validating Acme Corp GTM data

Read `docs/acme-corp-phase1-data-qa-plan.md`'s "Test cases" section in full before running or writing checks — this skill is the execution guide, not a replacement for it.

## Run in this order — stop and fix before moving to the next category

**1. Referential / structural integrity** (fastest, most fundamental — nothing else is worth checking if this fails)
- Every foreign key resolves
- `opportunity_stage_history` and `account_segment_history` are chronologically valid per entity
- SMB accounts have exactly 0 or 1 opportunity, always Closed Won
- Downstream ≤ upstream Actions in every `fact_workflow_chain_events` row
- No orphaned ownership after any rep departure

**2. Distributional realism** (checks against the QA plan's benchmark reference table)
- ACV within each segment's defined range
- Aggregate revenue mix near ~65–70% Enterprise ARR
- Win rate, sales-cycle length, and churn rate by segment within benchmark ranges
- NRR/GRR by segment near ~118% Enterprise / ~97% SMB

**3. Correlational validity — the category that actually matters for whether downstream artifacts will work**
- POC pass = true shows a measurably higher close rate than POC pass = false
- Eventually-churned accounts show a measurably declining health-score trend beforehand
- A naive churn classifier on health-score inputs lands at ~0.65–0.80 AUC — not ~0.5 (no signal) and not ~0.98 (unrealistically deterministic)
- Ramping reps show measurably lower win rate than ramped reps, but not zero
- Channels show genuinely different CAC/conversion profiles from each other
- At least one injected incident is detectable via a straightforward variance check

**4. Volume / sufficiency**
- Minimum N of Closed-Won and Closed-Lost per segment per quarter for model training
- Churned accounts present in a learnable class balance, not a 99.9/0.1 split
- Enough distinct reps with enough deals each that single-rep noise doesn't dominate
- `market_universe` non-customer volume is 10–50x customer volume

**5. Edge-case existence** (confirms the QA plan's designed-in messiness actually generated, not just that the schema allows it)
- Both `firmographic_rescore` and `usage_threshold` migration triggers appear at non-trivial frequency
- The sustained-near-zero-usage-before-renewal pattern exists in some accounts
- Some deals show stage regression
- Some reps depart mid-simulation with clean reassignment
- High-automation, low-login, high-Actions accounts exist and are **not** predominantly flagged at-risk (validates the health-score reweighting)

## Reporting

When a check fails, report which of the 5 categories it's in and point back to the exact QA plan section — don't just report "test failed." These fixes almost always belong in the generator itself, not as a downstream patch.
