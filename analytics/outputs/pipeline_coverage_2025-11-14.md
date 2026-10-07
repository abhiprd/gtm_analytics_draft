# Pipeline coverage -- evaluation date 2025-11-14 (2025-Q4)

*coverage reading, not a forecast.* 47 days to quarter end (2025-12-31).

## Commercial

Commercial: short. $725.9K open across 34 deals against $366.6K still to book is 1.98x coverage; 3.93x is needed at the recent 25.5% win rate, so the pipeline is 0.50x of required and, at that win rate, is expected to close $181.7K short of the quota still to book.

| Measure | Value |
|---|---|
| Quota | $648.5K (18 ISRs with an active day so far this quarter, stated quota not pro-rated; 1 still ramping ($29.9K of quota)) |
| Won to date | $281.9K (43.5% of quota) |
| Remaining quota | $366.6K |
| Open pipeline | $725.9K across 34 deals |
| Coverage ratio | 1.98x |
| Realized conversion | 25.5% over 442 closed deals since 2024-11-15 |
| Required multiple | 3.93x |
| Coverage vs required | 0.50x |
| Conversion-implied gap | $181.7K short |
| Status (proposed rule) | Shortfall |

## Enterprise

Enterprise: quota met for the quarter ($2.67M won against $2.30M); $5.42M still open across 20 deals.

| Measure | Value |
|---|---|
| Quota | $2.30M (21 AEs with an active day so far this quarter, stated quota not pro-rated; 0 still ramping ($0 of quota)) |
| Won to date | $2.67M (115.8% of quota) |
| Remaining quota | $0 |
| Open pipeline | $5.42M across 20 deals |
| Coverage ratio | n/a |
| Realized conversion | 23.5% over 137 closed deals since 2024-11-15 |
| Required multiple | 4.26x |
| Coverage vs required | n/a |
| Conversion-implied gap | $1.27M ahead |
| Status (proposed rule) | Quota met |

## Next quarter (2026-Q1)

Unavailable: 2026-Q1 starts after the last close recorded in the data (2025-12-28), so no pipeline can exist for it; this is the edge of the simulated window, not zero coverage.

## Reconciliation to the forecast (reported, never merged)

The coverage reading and the forecast agree on which deals are open; they differ in how the open dollars are priced (one realized conversion per segment versus a per-deal category weight). The forecast remains the only owner of what will close; the forecast's all-opportunity-type pipeline additionally includes renewals and expansions that quota does not cover, which is why it is not used as the coverage numerator.

| Segment | Coverage open pipeline | Forecast new-business open pipeline | Conversion-implied expected close | Forecast manager lens (new business) |
|---|---|---|---|---|
| Commercial | $725.9K | $725.9K | $184.9K | $163.5K |
| Enterprise | $5.42M | $5.42M | $1.27M | $1.12M |

## Checks

- [PASS] open_pipeline_ties_to_independent_sql: 24 segment-dates; max abs diff $0.00; 0 count mismatches
- [PASS] quota_ties_to_capacity_planning_panel: 22 segment-quarters; max abs diff $0.00; 0 rep-count mismatches
- [PASS] won_to_date_ties_to_capacity_planning_wins: 22 segment-quarters; max abs diff $0.00
- [PASS] quota_constant_within_quarter: 475 rep-quarters; 0 with quota varying inside the quarter
- [PASS] segment_owner_role_one_to_one: Commercial/ISR: 1217; Enterprise/AE: 452
- [PASS] pre_2023_closed_deals_are_all_won: 91 closed deals before 2023-01-01; 91 won
- [PASS] coverage_definitions_hold_as_identities: 24 readings; violations: []
- [PASS] conversion_window_never_reaches_before_2023: 24 readings; earliest window start 2023-01-01
- [PASS] open_pipeline_ties_to_forecast_new_business_rollup: live reading ties: True; backtest max abs diff $0.0
- [PASS] no_lookahead_reading_unchanged_by_post_2025-11-14_data: reading on marts with every post-evaluation fact corrupted is identical to the untouched reading
- [PASS] synthetic_known_answer_scenarios: 14 of 14 scenarios match their known answers
- [PASS] no_lookahead_reading_unchanged_by_post_2024-05-10_data: reading on marts with every post-evaluation fact corrupted is identical to the untouched reading
- [PASS] backtest_beats_both_naive_baselines: coverage-implied expected bookings versus actual quarter-end bookings: pooled MAPE 0.2964 against won-to-date alone 0.4772 and prior-four-quarter mean 0.5053
- [INFO] backtest_versus_constant_rate_and_pace_comparators: reported, not part of the proposed target and gating nothing: pooled MAPE 0.2964 against a fixed constant-rate comparator (won to date + 0.25 x open) 0.2607 and a pace comparator (won to date / fraction of the quarter elapsed) 0.3276; Enterprise 0.4034 against 0.383 / 0.3975

## Caveats

- Commercial and Enterprise new business only, owned by ISRs and AEs. Renewal and expansion opportunities are excluded because quota does not cover them; SMB is excluded because it has no pipeline and no quota.
- This is a coverage reading, not a forecast. It uses one realized conversion rate per segment; the forecast prices each open deal individually and stays the only owner of what will close. The two are reconciled in the reconciliation block and never merged.
- Open pipeline counts deals whose CRM close date falls in the quarter, the same stand-in for an expected-close date the forecast uses. The deal's eventual close date therefore decides which open deals count toward the quarter, an information advantage a live CRM expected-close field would not have. A backtest scenario scoping by created date plus the trailing median cycle instead, which uses no hindsight, is reported in the methods document. Deals expected to close after the quarter end are reported separately and not counted against this quarter's quota.
- Commercial deals are created and closed inside a quarter (14 to 45 day cycles), so a mid-quarter reading cannot see pipeline that has not been created yet and understates Commercial bookings by the amount that is. Enterprise cycles run 60 to 180 days, so the same effect is negligible there.
- Realized conversion is a dollar-weighted rate over the trailing 365 days, from January 2023 only. Stage-conditional win rates are flat in this data (every deal logs every stage), so no stage adjustment is applied; Enterprise rests on far fewer deals than Commercial and its rate moves more.
- Quota is the stated quarterly quota of every quota-bearing rep with an active day so far this quarter, never pro-rated for a mid-quarter hire or departure; a rep hired later in the quarter is not yet knowable and is not counted. Reps still ramping carry full stated quota.
- Quota is not a steady-state target before 2023 (attainment is structurally depressed in the build-out years), so readings are evaluated from 2023 onward.
- The data window ends in late December 2025: no deal closes after the last close date, so next-quarter coverage is structurally unavailable there, and is reported as unavailable, never as zero coverage.
