# LTV by entry segment -- as of 2025-06-30 (data through 2025-06-30)

*modeled lifetime view, a projection from observed rates; non-additive overlay on Consumption payback.*

Modeled five-year lifetime value per new account, discounted: SMB $15.6K ($13.5K to $21.4K); Commercial $202.6K ($118.6K to $269.0K); Enterprise $1.15M ($1.01M to $1.48M).

## Lifetime value per new account (60 months, 10% a year, 80% margin)

| Entry segment | Evidence | LTV central | Range | Observed share | Retention at month 60 | Projection starts after month |
|---|---|---|---|---|---|---|
| SMB | point | $15.6K | $13.5K to $21.4K | 47% | 42.7% (39.6% to 45.8%, observed) | 28 |
| Commercial | range | $202.6K | $118.6K to $269.0K | 40% | 67.8% (49.2% to 81.3%, projected) | 28 |
| Enterprise | directional | $1.15M | $1.01M to $1.48M | 43% | 80.4% (49.0% to 96.0%, projected) | 21 |

## CAC and LTV:CAC

CAC window 2023-01-01 to 2025-06-01 (30 months).

| Entry segment | New accounts | Marketing-only CAC | Rep cost per logo | Rep-loaded CAC | LTV:CAC marketing-only | LTV:CAC rep-loaded (range) | How to read |
|---|---|---|---|---|---|---|---|
| SMB | 4413 | $460 | none (no reps) | $460 | 33.9x (not decision-grade) | same figure: no reps in this segment | a floor on cost (no marketing headcount in the data) and a data-generation CAC parameter: read as 'far above any threshold', not as a precise multiple |
| Commercial | 226 | $806 | $33.6K | $34.4K | 252x (not decision-grade) | 5.9x (3.4x to 7.8x) (not decision-grade) | usable as a range against the rep-loaded cost only; the marketing-only ratio omits the reps, who are the acquisition cost |
| Enterprise | 67 | $952 | $369.0K | $370.0K | 1,206x (not decision-grade) | 3.1x (2.7x to 4.0x) (not decision-grade) | directional only: 5 churn events, thin tail; the marketing-only ratio omits the reps, who are the acquisition cost |

Decision-grade rule: A rep-loaded LTV:CAC is decision-grade only if (1) the segment's evidence grade is 'point', (2) rep cost is loaded wherever the segment has acquisition reps, and (3) no more than half of the LTV is revenue earned after the account moves up a segment. The marketing-only ratio is decision-grade only where the segment has no acquisition reps and the same three conditions hold. PROPOSED, not yet confirmed.

## Revenue earned after an account moves up a segment

| Entry segment | Share of LTV after the move | Accounts moved up | LTV:CAC rep-loaded | Inside the entry segment only | If account-management cost were netted |
|---|---|---|---|---|---|
| SMB | 55% | 436 of 5862 (7.4%) | 33.9x | 15.4x | 32.3x |
| Commercial | 69% | 23 of 294 (7.8%) | 5.9x | 1.8x | 5.4x |

Account-management cost over the CAC window: Commercial $1.30M of $19.81M segment revenue (6.59%); Enterprise $4.63M of $69.14M segment revenue (6.69%). That is too small to explain the gap between the two ratios; the gap is how the upside of the few accounts that move up is credited.

## SMB by acquisition channel

Acquisition channel shows no detectable difference in retention (log-rank p = 0.12 for SMB self_serve vs inbound_marketing, a 3.9-point gap in month-60 survival; p = 0.17 for Commercial) or in revenue per surviving SMB account (Mann-Whitney p = 0.22 to 0.36 at months 6, 12, 24, 36), and the generators do not use channel in churn or usage. This is an absence of evidence on synthetic data, not proof of no effect. Enterprise is untested (channel cut suppressed on 5 churn events; a test on that few accounts is not interpretable). The channel difference in LTV:CAC is a CAC difference.

| Age (months) | Accounts self_serve / inbound | Mean MRR self_serve / inbound | Median MRR self_serve / inbound | Mann-Whitney p |
|---|---|---|---|---|
| 6 | 3244 / 1106 | $298 / $287 | $218 / $213 | 0.33 |
| 12 | 2280 / 779 | $367 / $354 | $236 / $232 | 0.22 |
| 24 | 1055 / 361 | $528 / $464 | $278 / $266 | 0.31 |
| 36 | 530 / 174 | $731 / $567 | $323 / $299 | 0.36 |

| Channel | Accounts | Churn events | LTV (segment-wide) | LTV with channel's own survival | Marketing-only CAC | LTV:CAC |
|---|---|---|---|---|---|---|
| inbound_marketing | 1501 | 364 | $15.6K | $15.1K | $1.6K | 9.7x |
| self_serve | 4361 | 983 | $15.6K | $15.7K | $61 | 255x |

Not shown: Commercial (suppressed: 44 churn events in the whole segment, so a channel cut would rest on a handful of events); Enterprise (suppressed: 5 churn events in the whole segment); SMB outbound_sdr (no SMB account was acquired through outbound_sdr; its 18 accounts are all Enterprise (tooling spend only, no SDR headcount in the data)).

## Backtest (fit through the origin, compared with what happened)

- **SMB** (origin 2022-06-30, fit observed through month 28):

  | Month | Projected | Band | Realized (Kaplan-Meier) | Pooled ratio | Gap (pp) | Inside band |
  |---|---|---|---|---|---|---|
  | 36 | 60.1% | 53.4% to 66.5% | 58.8% | 58.8% | -1.3 | yes |
  | 42 | 55.4% | 47.7% to 62.7% | 54.5% | 55.5% | -0.9 | yes |
  | 48 | 51.1% | 42.6% to 59.1% | 49.9% | 50.3% | -1.2 | yes |
  | 54 | 47.1% | 38.1% to 55.7% | 45.4% | 47.3% | -1.6 | yes |
  | 60 | 43.4% | 34.1% to 52.5% | 42.8% | 44.8% | -0.6 | yes |

  - 36-month LTV on 1198 accounts: projected $6.5K vs realized $7.0K (-6.5%); retention-only +0.9%, MRR-only -7.2%.
  - 60-month LTV on 280 accounts: projected $9.6K vs realized $12.7K (-24.4%); retention-only -0.5%, MRR-only -24.1%.

- **Commercial** (origin 2022-06-30, fit observed through month 13):

  | Month | Projected | Band | Realized (Kaplan-Meier) | Pooled ratio | Gap (pp) | Inside band |
  |---|---|---|---|---|---|---|
  | 36 | 67.7% | 42.9% to 88.3% | 77.2% | 77.2% | +9.5 | yes |
  | 42 | 63.9% | 37.6% to 86.1% | 71.5% | 70.8% | +7.6 | yes |

  - 36-month LTV on 57 accounts: projected $70.6K vs realized $63.8K (+10.6%); retention-only -5.3%, MRR-only +17.1%.

- **Enterprise**: unavailable at origin 2022-06-30 (fewer than 30 accounts are at risk at the first transition).

## Drift assessment (proposed rule, one checkpoint)

- SMB: {"flag": false, "max_abs_gap_pp_months_48_60": 1.2, "limit_pp": 5.0, "marks_outside_band": []}
- Commercial: {"flag": null, "reason": "no Commercial mark at month 48 or later is observable with 30 accounts at risk"}
- Enterprise: {"flag": null, "backtestable": false, "accounts_at_risk_month_36": 19, "reason": "not backtestable until 30 accounts have reached month 36"}

## Checks

- [PASS] account_revenue_rows_start_at_signup_and_are_contiguous: 6246 accounts: 0 without revenue, 0 not starting at age 0, 0 with gaps
- [PASS] at_risk_and_active_counts_tie_to_retention_cohorts: max abs count difference 0 over 192 segment-ages
- [PASS] oldest_cohort_margin_adjusted_revenue_ties_to_fact_revenue_monthly: max relative difference 1.58e-15; Kaplan-Meier vs alive fraction max 3.33e-16; SMB: 280 accounts, $12,659.99 vs $12,659.99; Commercial: 10 accounts, $61,399.13 vs $61,399.13; Enterprise: 1 accounts, $1,608,097.35 vs $1,608,097.35
- [PASS] marketing_allocation_sums_back_to_spend: allocated $2,273,689.17 vs spend $2,273,689.17
- [PASS] new_accounts_by_channel_month_tie_to_fact_marketing_spend: 0 of 90 channel-months differ
- [PASS] won_new_business_logos_equal_entry_accounts_commercial_enterprise: max abs difference 0 (Commercial, Enterprise)
- [PASS] acquisition_rep_cost_ties_to_fact_rep_monthly_cost: module $32,323,839.98 vs SQL $32,323,839.98; AM roles excluded
- [PASS] am_cost_share_inputs_tie_to_the_facts: AM cost $5,931,484.70 vs SQL $5,931,484.70; Commercial and Enterprise revenue $88,955,075.65 vs SQL $88,955,075.65
- [PASS] ltv_node_stays_a_non_additive_overlay_with_no_children: registry additive=False, children=[], parent=consumption_payback, source_mart=None; tree marks it non-additive
- [PASS] gross_margin_constant_ties_to_the_dbt_var: dbt var 0.80, module 0.8, mart_efficiency reads the var: True, no 0.80 literal: True
- [PASS] horizon_discount_rate_and_margin_equal_the_metric_tree: tree states a 5-year horizon, 10% annual discount rate and ~80% margin; module 60 months, 0.1, 0.8
- [PASS] channel_retention_signal_not_overclaimed: log-rank p 0.124 (SMB self_serve vs inbound_marketing): no difference; LTV basis stated per channel row
- [PASS] backtest_fit_on_truncated_frames_equals_a_direct_reading_at_the_origin: origin 2022-06-30: max abs LTV difference $0.00 across the three segments
- [PASS] no_lookahead_reading_unchanged_by_post_2025-06-30_data: reading on marts with every post-cut fact corrupted is identical to the untouched reading
- [PASS] no_lookahead_reading_unchanged_by_post_2023-06-30_data: reading on marts with every post-cut fact corrupted is identical to the untouched reading
- [PASS] synthetic_known_answer_scenarios: 11 of 11 scenarios match their known answers
- [PASS] backtest_realized_ltv_equals_survival_times_mrr_identity: on accounts with the horizon fully observed, realized discounted margin per account equals the alive-fraction x mean-MRR sum (no censoring), for every backtest horizon
- [PASS] backtest_smb_retention_within_the_proposed_drift_rule: SMB realized retention at months 48 and 60 within 5pp of the projection and inside its band: max abs gap 1.20 pp
- [PASS] backtest_smb_36_month_ltv_error_within_limit: projected 36-month discounted margin per account $6.5K vs realized $7.0K (-6.5%; limit +/-25%); retention-only error +0.9%, MRR-only error -7.2%
- [INFO] backtest_smb_60_month_ltv_error_reported_without_a_limit: projected 60-month discounted margin per account $9.6K vs realized $12.7K (-24.4%, n = 280); the horizon the headline uses; the error is the MRR path (MRR-only -24.1%, retention-only -0.5%); no limit is set
- [INFO] backtest_commercial_realized_inside_band_directional: Commercial, fit through month 13 at the origin, 2 marks; max abs gap 9.49 pp; reported, gates nothing
- [INFO] backtest_enterprise_not_backtestable: Enterprise: 19 accounts have reached month 36 (needs 30); fewer than 30 accounts are at risk at the first transition

## Caveats

- A modeled lifetime view, not an observed value: the oldest accounts are 71 months old, and a large part of every segment's five-year value is projection (see observed_share).
- Per-account MRR rises with account age and with calendar time, and the two cannot be separated in this history, so the MRR path is the largest single uncertainty; the central path assumes no growth beyond what recent vintages have shown.
- Acquisition channel shows no detectable retention or revenue difference in this synthetic data (an absence of evidence, not proof); the channel split is a CAC split.
- The CAC spread by channel is a data-generation parameter, not an observed market price; SMB marketing-only LTV:CAC is very large by construction and is a floor on cost (no marketing headcount in the data), so read it as a direction, not a multiple.
- Marketing-only LTV:CAC is not decision-grade for Commercial or Enterprise: their reps are the acquisition cost.
- Pre-2023 vintages have no CAC (marketing spend starts 2023-01); they supply the retention tail and the MRR path, never an LTV:CAC.
- Commercial and Enterprise tails are thin (22 and 6 accounts at month 60): their LTVs are ranges, and Enterprise is directional only.
- Entry-segment LTV includes the MRR of accounts that migrated up; the account-management cost of serving and expanding them is not netted.
