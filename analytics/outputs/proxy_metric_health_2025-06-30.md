# Proxy-metric health / analytics investment prioritization -- as of 2025-06-30

**Headline finding**: no genuine drift/decay claim is possible yet for anything in this project. Every model with any logged checkpoint has between 1 and 1 real checkpoints (16 models total) -- see 'Checkpoint depth by model' below. This artifact is a governance catalog and framework, not a time-series drift tool; it becomes more useful as `drift-monitor` actually runs on a recurring cadence.

This module's own correctness checks: 3 of 3 pass (ALL PASS).

## Correctness checks
- Hooks trace to real doc text: 30 of 30
- Cited data-gap node keys are live in variance_diagnostic.py's `_TREE`: 14 of 14
- Checkpoint counts reconcile against an independent CSV parse: PASS (16 models checked)
- Variance-engine computability markings agree with `marketing_attribution.py`'s validated coverage: PASS

## Checkpoint depth by model (as of 2025-06-30)
| Model | n_checkpoints | as_of_dates |
|---|---|---|
| automated_playbook_triggers | 1 | 2025-06-30 |
| capacity_planning | 1 | 2025-06-30 |
| data_quality_governance | 1 | 2025-06-30 |
| deal_diagnostics | 1 | 2025-06-30 |
| executive_summary_narrative | 1 | 2025-06-30 |
| experimentation_platform | 1 | 2025-06-30 |
| marketing_attribution | 1 | 2025-06-30 |
| mmm_incrementality | 1 | 2025-06-30 |
| pricing_packaging_analytics | 1 | 2025-06-30 |
| proxy_metric_health | 1 | 2025-06-30 |
| rep_productivity | 1 | 2025-06-30 |
| retention_expansion_cohort_analytics | 1 | 2025-06-30 |
| scenario_planning | 1 | 2025-06-30 |
| tam_icp_opportunity_sizing | 1 | 2025-06-30 |
| territory_coverage_routing | 1 | 2025-06-30 |
| weekly_executive_readout | 1 | 2025-06-30 |

## Drift-monitor hook catalog -- reading counts
26 hooks catalogued across 15 artifacts; 7 have zero persisted readings today.

| Hook | Artifact | Rule family | Persisted metric(s) | Reading count |
|---|---|---|---|---|
| health_score_auc | account_health_score | model_calibration_accuracy_drift | `auc_holdout` | 0 |
| segment_migration_firmographic_rescore_share | segment_migration_analysis | grounding_or_apparatus_integrity | `pct_firmographic_rescore_overall`, `pct_firmographic_rescore_smb_to_commercial`, `pct_firmographic_rescore_commercial_to_enterprise` | 0 |
| marketing_mix_shift_tvd | marketing_attribution | grounding_or_apparatus_integrity | `first_to_last_mix_shift_tvd` | 1 |
| marketing_channel_switch_share | marketing_attribution | grounding_or_apparatus_integrity | `channel_switch_share` | 1 |
| marketing_measured_incremental_share_pooled | marketing_attribution | grounding_or_apparatus_integrity | `measured_incremental_share_pooled` | 1 |
| forecast_ml_calibration_gap | forecast | model_calibration_accuracy_drift | `ml_calibration_gap` | 0 |
| forecast_ml_auc_ratio_vs_leak_proof_baseline | forecast | model_calibration_accuracy_drift | `ml_auc_ratio_vs_leak_proof_baseline` | 0 |
| capacity_empirical_ramp_ratio_pooled | capacity_planning | grounding_or_apparatus_integrity | `empirical_ramp_ratio_pooled` | 1 |
| capacity_ramped_baseline_attainment_pooled | capacity_planning | grounding_or_apparatus_integrity | `ramped_baseline_attainment_pooled` | 1 |
| dq_governance_metric_tree_edges_not_computable | data_quality_governance | grounding_or_apparatus_integrity | `metric_tree_edges_not_computable` | 1 |
| dq_governance_not_independently_random_spot_checks | data_quality_governance | grounding_or_apparatus_integrity | *(none logged)* | 0 |
| playbook_triggers_firing_counts | automated_playbook_triggers | firing_rate_or_reuse_integrity | `triggers_fired_ingestion_without_completion`, `triggers_fired_poc_pass_rate_below_threshold`, `triggers_fired_post_close_underutilization` | 1 |
| deal_diagnostics_flag_firing_counts | deal_diagnostics | firing_rate_or_reuse_integrity | *(none logged)* | 0 |
| deal_diagnostics_ml_auc | deal_diagnostics | model_calibration_accuracy_drift | `auc_holdout_out_of_time` | 1 |
| deal_diagnostics_calibration_gap | deal_diagnostics | model_calibration_accuracy_drift | `calibration_gap` | 1 |
| rep_productivity_cohort_recovery | rep_productivity | grounding_or_apparatus_integrity | *(none logged)* | 0 |
| rep_productivity_flag_firing_counts | rep_productivity | firing_rate_or_reuse_integrity | `reps_flagged_volume_constrained`, `reps_flagged_volume_and_quality_constrained`, `reps_flagged_engagement_quality_constrained`, `reps_flagged_ramp_explained_on_par`, `reps_flagged_on_par` | 1 |
| pricing_deal_size_drift | pricing_packaging_analytics | grounding_or_apparatus_integrity | `deal_size_pct_change_smb`, `deal_size_pct_change_commercial`, `deal_size_pct_change_enterprise` | 1 |
| pricing_packaging_calibration | pricing_packaging_analytics | grounding_or_apparatus_integrity | `packaging_median_utilization_commercial`, `packaging_median_utilization_enterprise` | 1 |
| tam_icp_non_vacuousness_floors | tam_icp_opportunity_sizing | grounding_or_apparatus_integrity | `tier_acv_separation_ratio_tier1_tier2`, `tier_acv_separation_ratio_tier2_tier3`, `entry_tier_explained_share`, `entry_tier_downgrade_anomaly_share` | 1 |
| territory_coverage_index_whitespace | territory_coverage_routing | grounding_or_apparatus_integrity | `coverage_index_whitespace_apac`, `coverage_index_whitespace_emea`, `coverage_index_whitespace_latam`, `coverage_index_whitespace_na_east`, `coverage_index_whitespace_na_west` | 1 |
| mmm_checks_passed | mmm_incrementality | grounding_or_apparatus_integrity | `checks_passed` | 1 |
| mmm_vif_log_spend_with_trend | mmm_incrementality | grounding_or_apparatus_integrity | `vif_log_spend_with_trend` | 1 |
| mmm_gap_vs_holdout | mmm_incrementality | grounding_or_apparatus_integrity | `gap_vs_holdout_paid`, `gap_vs_holdout_community` | 1 |
| retention_cohort_annualized_logo_retention_benchmark | retention_expansion_cohort_analytics | grounding_or_apparatus_integrity | `implied_annual_logo_retention_smb`, `implied_annual_logo_retention_commercial`, `implied_annual_logo_retention_enterprise` | 1 |
| scenario_planning_baseline_self_check | scenario_planning | firing_rate_or_reuse_integrity | `baseline_self_check_nodes_passed` | 1 |

## Data-gap / investment-prioritization ranking
Ranked cheapest-to-close first, then by live count of downstream tree nodes blocked.

| Node | Layer | Tier | Blocks full Layer-1? | Nodes blocked |
|---|---|---|---|---|
| Cost per channel activity (`cost_per_channel_activity`) | 3 | B_phase2_mart_exposure_only | False | 1 |
| Account health score (`account_health_score`) | 2 | C_phase4_code_or_design_fix | False | 1 |
| Marketing-sales handoff quality (`marketing_sales_handoff_quality`) | 2 | D_genuine_new_phase1_data | False | 4 |
| Brand & awareness (`brand_awareness`) | 2 | D_genuine_new_phase1_data | False | 4 |
| Wallet share progression (`wallet_share_progression`) | 2 | D_genuine_new_phase1_data | False | 4 |
| Stage-to-stage conversion (`stage_to_stage_conversion`) | 3 | D_genuine_new_phase1_data | False | 1 |
| Churn reason category (loud vs. silent) (`churn_reason_category`) | 2 | D_genuine_new_phase1_data | False | 1 |
| Loud vs. silent churn mix (`loud_vs_silent_churn_mix`) | 3 | D_genuine_new_phase1_data | False | 1 |
| Time-to-respond on churn-risk flag (`time_to_respond_churn_risk_flag`) | 3 | D_genuine_new_phase1_data | False | 1 |
| Time-to-first-integration / first successful run (`time_to_first_integration`) | 2 | D_genuine_new_phase1_data | False | 1 |
| Quickstart/docs content engagement rate (`quickstart_docs_engagement_rate`) | 2 | D_genuine_new_phase1_data | False | 1 |
| Cohort comparison (same account type, same period last cycle) (`cohort_comparison`) | 3 | D_genuine_new_phase1_data | False | 1 |
| Expansion revenue drivers (`expansion_revenue_drivers`) | 2 | E_not_a_real_gap | False | 1 |
| Account-specific baseline deviation (`account_specific_baseline_deviation`) | 3 | E_not_a_real_gap | False | 1 |

## Validation-maturity summary (self-proposed vs. independently confirmed thresholds)
1 artifact section(s) carry a threshold CONFIRMED by `analytics-model-validator`; 17 carry at least one threshold still PROPOSED, not yet confirmed.

| Artifact section | PROPOSED mentions | CONFIRMED mentions |
|---|---|---|
| Segment/segmentation migration analysis | 0 | 1 |
| Marketing attribution & channel mix | 1 | 0 |
| Segment/lead scoring model | 2 | 0 |
| Forecast (sales bottoms-up / ML / CRO overlay reconciliation) | 1 | 0 |
| Variance-diagnostic engine | 1 | 0 |
| Weekly executive readout | 1 | 0 |
| Executive summary narrative | 3 | 0 |
| Capacity planning | 1 | 0 |
| Data quality / metric governance | 1 | 0 |
| Automated playbook triggers | 4 | 0 |
| Deal-level diagnostics | 1 | 0 |
| Rep productivity & coaching diagnostics | 1 | 0 |
| Pricing / packaging analytics | 2 | 0 |
| TAM / ICP / opportunity-sizing model | 1 | 0 |
| Territory / account coverage & routing | 1 | 0 |
| MMM / incrementality-based measurement | 1 | 0 |
| Retention / expansion cohort analytics | 1 | 0 |
| Testing / experimentation methodology & platform | 1 | 0 |
