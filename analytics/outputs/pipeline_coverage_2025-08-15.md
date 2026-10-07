# Pipeline coverage -- evaluation date 2025-08-15 (2025-Q3)

*coverage reading, not a forecast.* 46 days to quarter end (2025-09-30).

## Commercial

Commercial: thin. $910.3K open across 34 deals against $322.0K still to book is 2.83x coverage; 3.53x is needed at the recent 28.3% win rate, so the pipeline is 0.80x of required and, at that win rate, is expected to close $64.3K short of the quota still to book.

| Measure | Value |
|---|---|
| Quota | $683.3K (19 ISRs with an active day so far this quarter, stated quota not pro-rated; 1 still ramping ($29.4K of quota)) |
| Won to date | $361.3K (52.9% of quota) |
| Remaining quota | $322.0K |
| Open pipeline | $910.3K across 34 deals |
| Coverage ratio | 2.83x |
| Realized conversion | 28.3% over 411 closed deals since 2024-08-16 |
| Required multiple | 3.53x |
| Coverage vs required | 0.80x |
| Conversion-implied gap | $64.3K short |
| Status (proposed rule) | Thin |

## Enterprise

Enterprise: thin. $2.96M open across 13 deals against $661.0K still to book is 4.47x coverage; 4.82x is needed at the recent 20.7% win rate, so the pipeline is 0.93x of required and, at that win rate, is expected to close $47.6K short of the quota still to book.

| Measure | Value |
|---|---|
| Quota | $2.27M (21 AEs with an active day so far this quarter, stated quota not pro-rated; 0 still ramping ($0 of quota)) |
| Won to date | $1.60M (70.8% of quota) |
| Remaining quota | $661.0K |
| Open pipeline | $2.96M across 13 deals |
| Coverage ratio | 4.47x |
| Realized conversion | 20.7% over 147 closed deals since 2024-08-16 |
| Required multiple | 4.82x |
| Coverage vs required | 0.93x |
| Conversion-implied gap | $47.6K short |
| Status (proposed rule) | Thin |

## Next quarter (2025-Q4)

- Commercial: $0 across 0 deals against carried-forward quota $639.0K (none yet (no deal is open for next quarter)); indicative only: next quarter's quota is not set yet, so this quarter's stated quota of the reps active today is carried forward, and pipeline that has not been created yet (all of it, for Commercial's short cycles) is not visible.
- Enterprise: $8.13M across 31 deals against carried-forward quota $2.27M (3.59x); indicative only: next quarter's quota is not set yet, so this quarter's stated quota of the reps active today is carried forward, and pipeline that has not been created yet (all of it, for Commercial's short cycles) is not visible.

## Reconciliation to the forecast (reported, never merged)

The coverage reading and the forecast agree on which deals are open; they differ in how the open dollars are priced (one realized conversion per segment versus a per-deal category weight). The forecast remains the only owner of what will close; the forecast's all-opportunity-type pipeline additionally includes renewals and expansions that quota does not cover, which is why it is not used as the coverage numerator.

| Segment | Coverage open pipeline | Forecast new-business open pipeline | Conversion-implied expected close | Forecast manager lens (new business) |
|---|---|---|---|---|
| Commercial | $910.3K | $910.3K | $257.7K | $197.2K |
| Enterprise | $2.96M | $2.96M | $613.5K | $590.5K |

## Checks

- [PASS] open_pipeline_ties_to_independent_sql: 22 segment-dates; max abs diff $0.00; 0 count mismatches
- [PASS] quota_ties_to_capacity_planning_panel: 20 segment-quarters; max abs diff $0.00; 0 rep-count mismatches
- [PASS] won_to_date_ties_to_capacity_planning_wins: 20 segment-quarters; max abs diff $0.00
- [PASS] quota_constant_within_quarter: 431 rep-quarters; 0 with quota varying inside the quarter
- [PASS] segment_owner_role_one_to_one: Commercial/ISR: 1217; Enterprise/AE: 452
- [PASS] pre_2023_closed_deals_are_all_won: 91 closed deals before 2023-01-01; 91 won
- [PASS] coverage_definitions_hold_as_identities: 22 readings; violations: []
- [PASS] conversion_window_never_reaches_before_2023: 22 readings; earliest window start 2023-01-01
- [PASS] open_pipeline_ties_to_forecast_new_business_rollup: live reading ties: True; backtest max abs diff $0.0
- [PASS] no_lookahead_reading_unchanged_by_post_2025-08-15_data: reading on marts with every post-evaluation fact corrupted is identical to the untouched reading
- [PASS] synthetic_known_answer_scenarios: 14 of 14 scenarios match their known answers
- [PASS] no_lookahead_reading_unchanged_by_post_2024-05-10_data: reading on marts with every post-evaluation fact corrupted is identical to the untouched reading
- [PASS] backtest_beats_both_naive_baselines: coverage-implied expected bookings versus actual quarter-end bookings: pooled MAPE 0.3152 against won-to-date alone 0.4839 and prior-four-quarter mean 0.5376
- [INFO] backtest_versus_constant_rate_and_pace_comparators: reported, not part of the proposed target and gating nothing: pooled MAPE 0.3152 against a fixed constant-rate comparator (won to date + 0.25 x open) 0.2708 and a pace comparator (won to date / fraction of the quarter elapsed) 0.3329; Enterprise 0.4479 against 0.419 / 0.3917

## Caveats

- Commercial and Enterprise new business only, owned by ISRs and AEs. Renewal and expansion opportunities are excluded because quota does not cover them; SMB is excluded because it has no pipeline and no quota.
- This is a coverage reading, not a forecast. It uses one realized conversion rate per segment; the forecast prices each open deal individually and stays the only owner of what will close. The two are reconciled in the reconciliation block and never merged.
- Open pipeline counts deals whose CRM close date falls in the quarter, the same stand-in for an expected-close date the forecast uses. The deal's eventual close date therefore decides which open deals count toward the quarter, an information advantage a live CRM expected-close field would not have. A backtest scenario scoping by created date plus the trailing median cycle instead, which uses no hindsight, is reported in the methods document. Deals expected to close after the quarter end are reported separately and not counted against this quarter's quota.
- Commercial deals are created and closed inside a quarter (14 to 45 day cycles), so a mid-quarter reading cannot see pipeline that has not been created yet and understates Commercial bookings by the amount that is. Enterprise cycles run 60 to 180 days, so the same effect is negligible there.
- Realized conversion is a dollar-weighted rate over the trailing 365 days, from January 2023 only. Stage-conditional win rates are flat in this data (every deal logs every stage), so no stage adjustment is applied; Enterprise rests on far fewer deals than Commercial and its rate moves more.
- Quota is the stated quarterly quota of every quota-bearing rep with an active day so far this quarter, never pro-rated for a mid-quarter hire or departure; a rep hired later in the quarter is not yet knowable and is not counted. Reps still ramping carry full stated quota.
- Quota is not a steady-state target before 2023 (attainment is structurally depressed in the build-out years), so readings are evaluated from 2023 onward.
- The data window ends in late December 2025: no deal closes after the last close date, so next-quarter coverage is structurally unavailable there, and is reported as unavailable, never as zero coverage.
