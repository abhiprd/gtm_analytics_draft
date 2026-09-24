# Data quality / metric governance -- as of 2025-12-31

**Overall: 53 of 53 checks pass** (ALL PASS); synthetic self-check PASS (10 scenarios).

## 1. Metric-tree mathematical integrity
11 of 11 computable edges pass; 4 not computable (reasons below); 1 validated elsewhere.

| Edge | Formula | Status | Max abs diff | Rows checked |
|---|---|---|---|---|
| Growth pillar | `Starting + New logo + Expansion - Contraction - Churn (+/- migration, nets to zero)` | PASS | 0.00e+00 | 210 |
| Growth pillar (migration qualifier) | `Company-wide sum(migration_in) == sum(migration_out) per month` | PASS | 2.91e-11 | 72 |
| Win rate (Layer 2, under New logo) | `Closed won / (won + lost)` | PASS | 0.00e+00 | 188 |
| Magic number numerator ('Net new ARR... covered under Growth') | `(new_logo_mrr + expansion_mrr - contraction_mrr - churn_mrr) x 12` | PASS | 1.86e-09 | 210 |
| AM efficiency numerator ('Expansion consumption revenue... See Growth') | `expansion_mrr x 12` | PASS | 1.86e-09 | 210 |
| Consumption payback (Layer 1, Efficiency) | `CAC / utilized-Action margin` | PASS | 0.00e+00 | 107 |
| Onboarding/CS efficiency (Layer 1, Efficiency) | `Manual AM/CS touchpoints / volume of automated Actions delivered` | PASS | 0.00e+00 | 210 |
| NRR (Layer 1, Durability) | `(Starting - Contraction - Churn + Expansion) / Starting` | PASS | 0.00e+00 | 207 |
| GRR (Layer 1, Durability) | `(Starting - Contraction - Churn) / Starting` | PASS | 0.00e+00 | 207 |
| Logo retention (Layer 1, Durability) | `Retained accounts / Starting accounts` | PASS | 0.00e+00 | 414 |
| NRR/GRR drivers ('See Growth -- expansion, contraction, churn drivers') | `mart_durability's dollar_bridge == mart_growth_bridge's revenue_bridge, same segment/month` | PASS | 1.86e-09 | 210 |
| New logo consumption revenue (Layer 1, Growth) | `Pipeline generated x Win rate x Avg initial commitment` | NOT_COMPUTABLE | -- | -- |
| Pipeline generated (Layer 2, under New logo) | `Sum over channels (channel volume x channel-to-lead rate x lead-to-PQL rate)` | VALIDATED_ELSEWHERE | -- | -- |
| Expansion consumption revenue (Layer 1, Growth) | `Wallet share progression x Overage realization` | NOT_COMPUTABLE | -- | -- |
| Magic number (Layer 1, Efficiency) | `Net new ARR / prior-period S&M cost` | NOT_COMPUTABLE | -- | -- |
| AM efficiency (Layer 1, Efficiency) | `Expansion consumption revenue / AM cost` | NOT_COMPUTABLE | -- | -- |

**Not-computable / validated-elsewhere reasons:**
- **new_logo_equals_pipeline_x_winrate_x_commitment** (NOT_COMPUTABLE): No mart exposes 'Pipeline generated' at New Logo's own population -- mart_growth_bridge's win_rate/avg_initial_commitment are computed over closed SQO-stage opportunities, while Pipeline generated (per analytics/marketing_attribution.py) is computed over converting LEADS, a different population and a different unit (SMB in particular has no real win-rate concept at all -- one Opportunity record, always Closed Won). mart_growth_bridge's own header states the two New Logo lenses 'will NOT match exactly... a normal, real bookings-vs-revenue-recognition gap, not a bug.' Multiplying three marts-derived legs that don't share a population would manufacture a false tie-out, not a real one.
- **pipeline_generated_channel_formula** (VALIDATED_ELSEWHERE): Computable, but not re-derived here. analytics/marketing_attribution.py already computes this formula from marts (fact_leads, fact_campaign_engagement_events, dim_campaign) and independently validates it exactly in its own build-time check (reconcile_pipeline_generated_identity, listed there as pipeline_generated_rollup_reconciles_to_source; <=1e-9 tolerance, passing at both checkpoints). The formula's correctness depends on point-in-time lead-resolution-horizon logic (open/lapsed/converted state, derived per sub-channel) that is non-trivial and already owned by that module -- re-implementing it here would risk a second, silently-diverging copy rather than adding governance value. This edge is reported as validated, not skipped, with a pointer to where the check actually runs.
- **expansion_equals_wallet_share_x_overage** (NOT_COMPUTABLE): Wallet share progression (% of an account's total addressable workflow footprint running through Acme Corp) has no source anywhere in the raw data or the marts layer -- nothing estimates the non-Acme denominator. This is a genuine Phase 1 data gap (confirmed in analytics/variance_diagnostic.py's coverage table: 'Expansion consumption revenue | 0 of 2'), not a scope choice a Phase 4 workaround could close.
- **magic_number_ratio** (NOT_COMPUTABLE): No rep-cost/comp data exists anywhere in the raw sources, so mart_efficiency.magic_number_sm_cost and .magic_number are NULL by design (mart_efficiency's own header). This is the same gap analytics/variance_diagnostic.py and analytics/capacity_planning.py both name as structurally not-computable.
- **am_efficiency_ratio** (NOT_COMPUTABLE): No AM comp/cost data exists anywhere in the raw sources, so mart_efficiency.am_cost and .am_efficiency are NULL by design (mart_efficiency's own header). Same gap as magic_number above.

**Excluded by design (tree's own non-additive nodes):**
- **Brand & awareness**: Tree's own text: 'leading indicator, not summed into the pipeline math.' CLAUDE.md names this node explicitly as the one deliberate non-additive exception to the parent-equals-function-of-children invariant.
- **Marketing-sales handoff quality**: Tree's own text, parenthetical right after the node name: 'diagnostic overlay on the above three [Pipeline generated, Win rate, Avg initial commitment], not a fourth multiplicative factor.' A second explicitly non-additive node the tree itself carves out, alongside Brand & awareness -- CLAUDE.md's invariant text names only Brand & awareness as 'the one deliberate exception,' but the tree's own prose names two. Recorded here rather than silently reconciled, since resolving the wording gap between the two docs is a documentation call, not this checker's call to make unilaterally.

## 2. Marts-layer data quality
- Referential integrity: 9 / 9
- Completeness: 13 / 13
- Distributional sanity: 5 / 5
- Volume sufficiency: 7 / 7

## 3. Invariant governance
- **segment_terminology**: PASS
- **no_segment_downgrade**: PASS
- **currency_usd_only**: PASS
- **channel_segment_orthogonality**: PASS
- **trigger_reason_coverage**: PASS
- **win_probability_not_random**: PASS
- **churn_probability_not_random**: PASS
- **usage_growth_not_random**: PASS

## Synthetic injected-violation self-check
| Scenario | Expected | Actual | Match |
|---|---|---|---|
| metric_tree_growth_identity_clean_passes | PASS | PASS | yes |
| metric_tree_growth_identity_injected_break_fails | FAIL | FAIL | yes |
| metric_tree_win_rate_clean_passes | PASS | PASS | yes |
| metric_tree_win_rate_injected_break_fails | FAIL | FAIL | yes |
| segment_terminology_clean_passes | PASS | PASS | yes |
| segment_terminology_fabricated_tier_value_fails | FAIL | FAIL | yes |
| no_segment_downgrade_clean_passes | PASS | PASS | yes |
| no_segment_downgrade_fabricated_path_fails | FAIL | FAIL | yes |
| win_probability_real_driver_relationship_passes | PASS | PASS | yes |
| win_probability_independently_random_column_fails | FAIL | FAIL | yes |
