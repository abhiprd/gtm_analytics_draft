# Proxy-metric health / analytics investment prioritization -- as of 2025-12-31

**Headline finding**: no genuine drift/decay claim is possible yet for anything in this project. Every model with any logged checkpoint has between 1 and 3 real checkpoints (23 models total) -- see 'Checkpoint depth by model' below. This artifact is a governance catalog and framework, not a time-series drift tool; it becomes more useful as `drift-monitor` actually runs on a recurring cadence.

This module's own correctness checks: 3 of 3 pass (ALL PASS).

## Correctness checks
- Hooks trace to real doc text: 32 of 32
- Cited data-gap node keys are live in variance_diagnostic.py's `_TREE`: 14 of 14
- Checkpoint counts reconcile against an independent CSV parse: PASS (23 models checked)
- Variance-engine computability markings agree with `marketing_attribution.py`'s validated coverage: PASS

## Checkpoint depth by model (as of 2025-12-31)
| Model | n_checkpoints | as_of_dates |
|---|---|---|
| account_health_score | 1 | 2025-12-31 |
| automated_playbook_triggers | 3 | 2025-06-30, 2025-11-30, 2025-12-31 |
| capacity_planning | 2 | 2025-06-30, 2025-12-31 |
| data_quality_governance | 2 | 2025-06-30, 2025-12-31 |
| deal_diagnostics | 2 | 2025-06-30, 2025-11-30 |
| executive_summary_narrative | 2 | 2025-06-30, 2025-11-30 |
| experimentation_platform | 2 | 2025-06-30, 2025-12-31 |
| forecast | 2 | 2025-08-15, 2025-11-14 |
| lead_scoring_model | 1 | 2025-12-31 |
| ltv_by_segment | 2 | 2025-06-30, 2025-12-31 |
| marketing_attribution | 2 | 2025-06-30, 2025-12-31 |
| mmm_incrementality | 2 | 2025-06-30, 2025-12-31 |
| pipeline_coverage | 2 | 2025-08-15, 2025-11-14 |
| pricing_packaging_analytics | 2 | 2025-06-30, 2025-11-30 |
| proxy_metric_health | 2 | 2025-06-30, 2025-12-31 |
| rep_productivity | 2 | 2025-06-30, 2025-12-31 |
| retention_expansion_cohort_analytics | 2 | 2025-06-30, 2025-12-31 |
| scenario_planning | 3 | 2025-06-30, 2025-11-30, 2025-12-31 |
| segment_migration_analysis | 1 | 2025-12-31 |
| tam_icp_opportunity_sizing | 2 | 2025-06-30, 2025-12-31 |
| territory_coverage_routing | 2 | 2025-06-30, 2025-12-31 |
| variance_diagnostic_engine | 2 | 2025-11-30, 2025-12-31 |
| weekly_executive_readout | 3 | 2025-06-30, 2025-11-30, 2025-12-31 |

## Drift-monitor hook catalog -- reading counts
28 hooks catalogued across 17 artifacts; 3 have zero persisted readings today.

| Hook | Artifact | Rule family | Persisted metric(s) | Reading count |
|---|---|---|---|---|
| health_score_auc | account_health_score | model_calibration_accuracy_drift | `auc_holdout` | 1 |
| segment_migration_firmographic_rescore_share | segment_migration_analysis | grounding_or_apparatus_integrity | `pct_firmographic_rescore_overall`, `pct_firmographic_rescore_smb_to_commercial`, `pct_firmographic_rescore_commercial_to_enterprise` | 1 |
| marketing_mix_shift_tvd | marketing_attribution | grounding_or_apparatus_integrity | `first_to_last_mix_shift_tvd` | 2 |
| marketing_channel_switch_share | marketing_attribution | grounding_or_apparatus_integrity | `channel_switch_share` | 2 |
| marketing_measured_incremental_share_pooled | marketing_attribution | grounding_or_apparatus_integrity | `measured_incremental_share_pooled` | 2 |
| forecast_ml_calibration_gap | forecast | model_calibration_accuracy_drift | `ml_calibration_gap` | 2 |
| forecast_ml_auc_ratio_vs_leak_proof_baseline | forecast | model_calibration_accuracy_drift | `ml_auc_ratio_vs_leak_proof_baseline` | 2 |
| capacity_empirical_ramp_ratio_pooled | capacity_planning | grounding_or_apparatus_integrity | `empirical_ramp_ratio_pooled` | 2 |
| capacity_ramped_baseline_attainment_pooled | capacity_planning | grounding_or_apparatus_integrity | `ramped_baseline_attainment_pooled` | 2 |
| dq_governance_metric_tree_edges_not_computable | data_quality_governance | grounding_or_apparatus_integrity | `metric_tree_edges_not_computable` | 2 |
| dq_governance_not_independently_random_spot_checks | data_quality_governance | grounding_or_apparatus_integrity | *(none logged)* | 0 |
| playbook_triggers_firing_counts | automated_playbook_triggers | firing_rate_or_reuse_integrity | `triggers_fired_ingestion_without_completion`, `triggers_fired_poc_pass_rate_below_threshold`, `triggers_fired_post_close_underutilization` | 3 |
| deal_diagnostics_flag_firing_counts | deal_diagnostics | firing_rate_or_reuse_integrity | *(none logged)* | 0 |
| deal_diagnostics_ml_auc | deal_diagnostics | model_calibration_accuracy_drift | `auc_holdout_out_of_time` | 2 |
| deal_diagnostics_calibration_gap | deal_diagnostics | model_calibration_accuracy_drift | `calibration_gap` | 2 |
| rep_productivity_cohort_recovery | rep_productivity | grounding_or_apparatus_integrity | *(none logged)* | 0 |
| rep_productivity_flag_firing_counts | rep_productivity | firing_rate_or_reuse_integrity | `reps_flagged_volume_constrained`, `reps_flagged_volume_and_quality_constrained`, `reps_flagged_engagement_quality_constrained`, `reps_flagged_ramp_explained_on_par`, `reps_flagged_on_par` | 2 |
| pricing_deal_size_drift | pricing_packaging_analytics | grounding_or_apparatus_integrity | `deal_size_pct_change_smb`, `deal_size_pct_change_commercial`, `deal_size_pct_change_enterprise` | 2 |
| pricing_packaging_calibration | pricing_packaging_analytics | grounding_or_apparatus_integrity | `packaging_median_utilization_commercial`, `packaging_median_utilization_enterprise` | 2 |
| tam_icp_non_vacuousness_floors | tam_icp_opportunity_sizing | grounding_or_apparatus_integrity | `tier_acv_separation_ratio_tier1_tier2`, `tier_acv_separation_ratio_tier2_tier3`, `entry_tier_explained_share`, `entry_tier_downgrade_anomaly_share` | 2 |
| territory_coverage_index_whitespace | territory_coverage_routing | grounding_or_apparatus_integrity | `coverage_index_whitespace_apac`, `coverage_index_whitespace_emea`, `coverage_index_whitespace_latam`, `coverage_index_whitespace_na_east`, `coverage_index_whitespace_na_west` | 2 |
| pipeline_coverage_mape_ratio_vs_naive_baseline | pipeline_coverage | model_calibration_accuracy_drift | `backtest_mape_ratio_vs_naive_baseline` | 2 |
| ltv_backtest_retention_gap_smb | ltv_by_segment | model_calibration_accuracy_drift | `backtest_retention_max_abs_gap_pp_smb`, `backtest_retention_realized_in_band_smb` | 2 |
| mmm_checks_passed | mmm_incrementality | grounding_or_apparatus_integrity | `checks_passed` | 2 |
| mmm_vif_log_spend_with_trend | mmm_incrementality | grounding_or_apparatus_integrity | `vif_log_spend_with_trend` | 2 |
| mmm_gap_vs_holdout | mmm_incrementality | grounding_or_apparatus_integrity | `gap_vs_holdout_paid`, `gap_vs_holdout_community` | 2 |
| retention_cohort_annualized_logo_retention_benchmark | retention_expansion_cohort_analytics | grounding_or_apparatus_integrity | `implied_annual_logo_retention_smb`, `implied_annual_logo_retention_commercial`, `implied_annual_logo_retention_enterprise` | 2 |
| scenario_planning_baseline_self_check | scenario_planning | firing_rate_or_reuse_integrity | `baseline_self_check_nodes_passed` | 3 |

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
1 artifact section(s) carry a threshold CONFIRMED by `analytics-model-validator`; 19 carry at least one threshold still PROPOSED, not yet confirmed.

| Artifact section | PROPOSED mentions | CONFIRMED mentions |
|---|---|---|
| Segment/segmentation migration analysis | 0 | 1 |
| Marketing attribution & channel mix | 1 | 0 |
| Segment/lead scoring model | 2 | 0 |
| Forecast (sales bottoms-up / ML / CRO overlay reconciliation) | 1 | 0 |
| Variance-diagnostic engine | 2 | 0 |
| Weekly executive readout | 1 | 0 |
| Executive summary narrative | 3 | 0 |
| Capacity planning | 1 | 0 |
| Pipeline coverage | 6 | 0 |
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
| LTV by segment × acquisition channel | 4 | 0 |
