# LTV by entry segment -- as of 2025-12-31 (data through 2025-12-31)

*modeled lifetime view, a projection from observed rates; non-additive overlay on Consumption payback.*

Modeled five-year lifetime value per new account, discounted: SMB $15.8K ($14.7K to $20.3K); Commercial $223.1K ($125.9K to $270.2K); Enterprise $1.14M ($1.03M to $1.52M).

## Lifetime value per new account (60 months, 10% a year, 80% margin)

| Entry segment | Evidence | LTV central | Range | Observed share | Retention at month 60 | Projection starts after month |
|---|---|---|---|---|---|---|
| SMB | point | $15.8K | $14.7K to $20.3K | 57% | 42.2% (39.6% to 44.8%, observed) | 30 |
| Commercial | range | $223.1K | $125.9K to $270.2K | 48% | 67.4% (51.8% to 78.9%, projected) | 33 |
| Enterprise | directional | $1.14M | $1.03M to $1.52M | 51% | 78.0% (51.2% to 94.4%, projected) | 25 |

## CAC and LTV:CAC

CAC window 2023-01-01 to 2025-12-01 (36 months).

| Entry segment | New accounts | Marketing-only CAC | Rep cost per logo | Rep-loaded CAC | LTV:CAC marketing-only | LTV:CAC rep-loaded (range) | How to read |
|---|---|---|---|---|---|---|---|
| SMB | 5773 | $454 | none (no reps) | $454 | 34.7x (not decision-grade) | same figure: no reps in this segment | a floor on cost (no marketing headcount in the data) and a data-generation CAC parameter: read as 'far above any threshold', not as a precise multiple |
| Commercial | 297 | $776 | $31.1K | $31.8K | 288x (not decision-grade) | 7.0x (4.0x to 8.5x) (not decision-grade) | usable as a range against the rep-loaded cost only; the marketing-only ratio omits the reps, who are the acquisition cost |
| Enterprise | 90 | $967 | $338.0K | $338.9K | 1,182x (not decision-grade) | 3.4x (3.0x to 4.5x) (not decision-grade) | directional only: 5 churn events, thin tail; the marketing-only ratio omits the reps, who are the acquisition cost |

Decision-grade rule: A rep-loaded LTV:CAC is decision-grade only if (1) the segment's evidence grade is 'point', (2) rep cost is loaded wherever the segment has acquisition reps, and (3) no more than half of the LTV is revenue earned after the account moves up a segment. The marketing-only ratio is decision-grade only where the segment has no acquisition reps and the same three conditions hold. PROPOSED, not yet confirmed.

## Revenue earned after an account moves up a segment

| Entry segment | Share of LTV after the move | Accounts moved up | LTV:CAC rep-loaded | Inside the entry segment only | If account-management cost were netted |
|---|---|---|---|---|---|
| SMB | 60% | 722 of 7222 (10.0%) | 34.7x | 13.9x | 33.3x |
| Commercial | 72% | 38 of 365 (10.4%) | 7.0x | 1.9x | 6.5x |

Account-management cost over the CAC window: Commercial $1.67M of $29.73M segment revenue (5.62%); Enterprise $5.70M of $104.52M segment revenue (5.45%). That is too small to explain the gap between the two ratios; the gap is how the upside of the few accounts that move up is credited.

## SMB by acquisition channel

Acquisition channel shows no detectable difference in retention (log-rank p = 0.17 for SMB self_serve vs inbound_marketing, a 3.9-point gap in month-60 survival; p = 0.09 for Commercial) or in revenue per surviving SMB account (Mann-Whitney p = 0.20 to 0.83 at months 6, 12, 24, 36), and the generators do not use channel in churn or usage. This is an absence of evidence on synthetic data, not proof of no effect. Enterprise is untested (channel cut suppressed on 5 churn events; a test on that few accounts is not interpretable). The channel difference in LTV:CAC is a CAC difference.

| Age (months) | Accounts self_serve / inbound | Mean MRR self_serve / inbound | Median MRR self_serve / inbound | Mann-Whitney p |
|---|---|---|---|---|
| 6 | 4089 / 1406 | $312 / $344 | $218 / $215 | 0.83 |
| 12 | 2960 / 1003 | $420 / $387 | $235 / $231 | 0.20 |
| 24 | 1418 / 484 | $642 / $502 | $277 / $266 | 0.30 |
| 36 | 639 / 214 | $847 / $586 | $324 / $299 | 0.35 |

| Channel | Accounts | Churn events | LTV (segment-wide) | LTV with channel's own survival | Marketing-only CAC | LTV:CAC |
|---|---|---|---|---|---|---|
| inbound_marketing | 1849 | 474 | $15.8K | $15.4K | $1.6K | 9.9x |
| self_serve | 5373 | 1310 | $15.8K | $15.9K | $62 | 256x |

Not shown: Commercial (suppressed: 44 churn events in the whole segment, so a channel cut would rest on a handful of events); Enterprise (suppressed: 5 churn events in the whole segment); SMB outbound_sdr (no SMB account was acquired through outbound_sdr; its 18 accounts are all Enterprise (tooling spend only, no SDR headcount in the data)).

## Backtest (fit through the origin, compared with what happened)

- **SMB** (origin 2022-12-31, fit observed through month 34):

  | Month | Projected | Band | Realized (Kaplan-Meier) | Pooled ratio | Gap (pp) | Inside band |
  |---|---|---|---|---|---|---|
  | 36 | 60.8% | 55.7% to 65.7% | 58.9% | 58.9% | -1.9 | yes |
  | 42 | 55.9% | 49.6% to 61.8% | 54.5% | 54.5% | -1.4 | yes |
  | 48 | 51.4% | 44.2% to 58.2% | 50.2% | 50.9% | -1.1 | yes |
  | 54 | 47.2% | 39.3% to 54.8% | 46.0% | 45.9% | -1.2 | yes |
  | 60 | 43.4% | 35.0% to 51.6% | 42.9% | 44.8% | -0.6 | yes |

  - 36-month LTV on 1449 accounts: projected $6.6K vs realized $7.4K (-11.1%); retention-only +1.0%, MRR-only -11.9%.
  - 60-month LTV on 517 accounts: projected $10.0K vs realized $14.8K (-32.0%); retention-only +0.1%, MRR-only -32.3%.

- **Commercial** (origin 2022-12-31, fit observed through month 17):

  | Month | Projected | Band | Realized (Kaplan-Meier) | Pooled ratio | Gap (pp) | Inside band |
  |---|---|---|---|---|---|---|
  | 36 | 66.4% | 44.9% to 84.5% | 77.9% | 77.9% | +11.6 | yes |
  | 42 | 61.4% | 38.3% to 81.4% | 73.5% | 71.9% | +12.1 | yes |
  | 48 | 56.9% | 32.7% to 78.4% | 73.5% | 70.8% | +16.7 | yes |

  - 36-month LTV on 68 accounts: projected $70.5K vs realized $70.7K (-0.3%); retention-only -5.2%, MRR-only +5.3%.

- **Enterprise**: unavailable at origin 2022-12-31 (fewer than 30 accounts are at risk at the first transition).

## Drift assessment (proposed rule, one checkpoint)

- SMB: {"flag": false, "max_abs_gap_pp_months_48_60": 1.13, "limit_pp": 5.0, "marks_outside_band": []}
- Commercial: {"flag": false, "marks_outside_band": [], "note": "held to its own band (a range segment); directional"}
- Enterprise: {"flag": null, "backtestable": false, "accounts_at_risk_month_36": 23, "reason": "not backtestable until 30 accounts have reached month 36"}

## Checks

- [PASS] account_revenue_rows_start_at_signup_and_are_contiguous: 7700 accounts: 0 without revenue, 0 not starting at age 0, 0 with gaps
- [PASS] at_risk_and_active_counts_tie_to_retention_cohorts: max abs count difference 0 over 210 segment-ages
- [PASS] oldest_cohort_margin_adjusted_revenue_ties_to_fact_revenue_monthly: max relative difference 9.85e-16; Kaplan-Meier vs alive fraction max 3.33e-16; SMB: 517 accounts, $14,778.47 vs $14,778.47; Commercial: 25 accounts, $145,672.88 vs $145,672.88; Enterprise: 6 accounts, $1,901,918.74 vs $1,901,918.74
- [PASS] marketing_allocation_sums_back_to_spend: allocated $2,936,472.18 vs spend $2,936,472.18
- [PASS] new_accounts_by_channel_month_tie_to_fact_marketing_spend: 0 of 108 channel-months differ
- [PASS] won_new_business_logos_equal_entry_accounts_commercial_enterprise: max abs difference 0 (Commercial, Enterprise)
- [PASS] acquisition_rep_cost_ties_to_fact_rep_monthly_cost: module $39,640,930.14 vs SQL $39,640,930.14; AM roles excluded
- [PASS] am_cost_share_inputs_tie_to_the_facts: AM cost $7,373,308.30 vs SQL $7,373,308.30; Commercial and Enterprise revenue $134,253,927.15 vs SQL $134,253,927.15
- [PASS] ltv_node_stays_a_non_additive_overlay_with_no_children: registry additive=False, children=[], parent=consumption_payback, source_mart=None; tree marks it non-additive
- [PASS] gross_margin_constant_ties_to_the_dbt_var: dbt var 0.80, module 0.8, mart_efficiency reads the var: True, no 0.80 literal: True
- [PASS] horizon_discount_rate_and_margin_equal_the_metric_tree: tree states a 5-year horizon, 10% annual discount rate and ~80% margin; module 60 months, 0.1, 0.8
- [PASS] channel_retention_signal_not_overclaimed: log-rank p 0.170 (SMB self_serve vs inbound_marketing): no difference; LTV basis stated per channel row
- [PASS] backtest_fit_on_truncated_frames_equals_a_direct_reading_at_the_origin: origin 2022-12-31: max abs LTV difference $0.00 across the three segments
- [PASS] no_lookahead_reading_unchanged_by_post_2025-12-31_data: reading on marts with every post-cut fact corrupted is identical to the untouched reading
- [PASS] no_lookahead_reading_unchanged_by_post_2023-06-30_data: reading on marts with every post-cut fact corrupted is identical to the untouched reading
- [PASS] synthetic_known_answer_scenarios: 11 of 11 scenarios match their known answers
- [PASS] backtest_realized_ltv_equals_survival_times_mrr_identity: on accounts with the horizon fully observed, realized discounted margin per account equals the alive-fraction x mean-MRR sum (no censoring), for every backtest horizon
- [PASS] backtest_smb_retention_within_the_proposed_drift_rule: SMB realized retention at months 48 and 60 within 5pp of the projection and inside its band: max abs gap 1.13 pp
- [PASS] backtest_smb_36_month_ltv_error_within_limit: projected 36-month discounted margin per account $6.6K vs realized $7.4K (-11.1%; limit +/-25%); retention-only error +1.0%, MRR-only error -11.9%
- [INFO] backtest_smb_60_month_ltv_error_reported_without_a_limit: projected 60-month discounted margin per account $10.0K vs realized $14.8K (-32.0%, n = 517); the horizon the headline uses; the error is the MRR path (MRR-only -32.3%, retention-only +0.1%); no limit is set
- [INFO] backtest_commercial_realized_inside_band_directional: Commercial, fit through month 17 at the origin, 3 marks; max abs gap 16.66 pp; reported, gates nothing
- [INFO] backtest_enterprise_not_backtestable: Enterprise: 23 accounts have reached month 36 (needs 30); fewer than 30 accounts are at risk at the first transition

## Caveats

- A modeled lifetime view, not an observed value: the oldest accounts are 71 months old, and a large part of every segment's five-year value is projection (see observed_share).
- Per-account MRR rises with account age and with calendar time, and the two cannot be separated in this history, so the MRR path is the largest single uncertainty; the central path assumes no growth beyond what recent vintages have shown.
- Acquisition channel shows no detectable retention or revenue difference in this synthetic data (an absence of evidence, not proof); the channel split is a CAC split.
- The CAC spread by channel is a data-generation parameter, not an observed market price; SMB marketing-only LTV:CAC is very large by construction and is a floor on cost (no marketing headcount in the data), so read it as a direction, not a multiple.
- Marketing-only LTV:CAC is not decision-grade for Commercial or Enterprise: their reps are the acquisition cost.
- Pre-2023 vintages have no CAC (marketing spend starts 2023-01); they supply the retention tail and the MRR path, never an LTV:CAC.
- Commercial and Enterprise tails are thin (22 and 6 accounts at month 60): their LTVs are ranges, and Enterprise is directional only.
- Entry-segment LTV includes the MRR of accounts that migrated up; the account-management cost of serving and expanding them is not netted.
