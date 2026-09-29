# Testing / experimentation methodology & platform -- as of 2025-12-31

**Scope, stated plainly**: this project has exactly one real, catalogued, randomized experiment (`EXP-0001`) today. What's built here is the reusable evaluation framework, proven correct against that one known-correct case, and ready for the next registration via one new outcome adapter.

This module's own correctness checks: 3 of 3 pass (ALL PASS).

## 1. Reproduction check -- does the general framework get the known-correct answer?
Recomputed pooled incremental share: **0.681861** (published: 0.6819, abs diff 0.000039).
Recomputed pooled z-statistic: **4.4289** (published: 4.43, abs diff 0.0011).
Reproduces published result within rounding tolerance: **True**.
Cells: 5 of 6 fully resolved as of this checkpoint.

## 2. Sample-size / power context
Pooled fully-resolved arm sizes: 4751 treatment, 1168 control. Achieved power to detect the registry's designed effect size at these actual sizes: **0.9970**. Minimum detectable effect at 80% power (as an implied incremental share): **0.5147**. Adequately powered: **True**.

## 3. Guardrail-metric monitoring
2 of 2 guardrails pass.

| Guardrail | Observed | Threshold | Passes |
|---|---|---|---|
| resolved_control_cell_lead_volume | 1168 | >= 300 | True |
| control_arm_crossover_rate | 0.0105 | <= 0.05 (PROPOSED, not yet confirmed) | True |

## 4. Registry / methodology governance
1 of 1 registered experiment(s) have a complete, well-formed definition.

| experiment_id | is_complete | missing_fields | arm_counts |
|---|---|---|---|
| EXP-0001 | True | [] | {'treatment': 5026, 'control': 1239} |

## 5. Registry-completeness known-answer test
5 of 5 synthetic scenarios matched their expected outcome.

| Scenario | Expected pass | Actual pass | Matches |
|---|---|---|---|
| clean_synthetic_registration_passes | True | True | True |
| broken_synthetic_registration_flagged_incomplete | False | False | True |
| broken_flags_missing_control_definition | True | True | True |
| broken_flags_missing_guardrail_metrics | True | True | True |
| broken_flags_no_real_control_population | True | True | True |

## 6. Cell-level results (EXP-0001)
| channel | cell_quarter | n_treatment | k_treatment | rate_treatment | n_control | k_control | rate_control | incremental_share | z_stat | fully_resolved |
|---|---|---|---|---|---|---|---|---|---|---|
| community | 2023Q3 | 137 | 13 | 0.0949 | 20 | 0 | 0.0 | 1.0 | 1.4384506624112634 | True |
| community | 2024Q2 | 234 | 20 | 0.0855 | 41 | 1 | 0.024390243902439025 | 0.7146341463414634 | 1.3584310512507773 | True |
| community | 2025Q1 | 164 | 22 | 0.1341 | 45 | 2 | 0.044444444444444446 | 0.6686868686868688 | 1.671904499335653 | False |
| paid | 2023Q3 | 1095 | 34 | 0.0311 | 347 | 4 | 0.011527377521613832 | 0.6287506357009662 | 1.9784373851732189 | True |
| paid | 2024Q2 | 1692 | 55 | 0.0325 | 413 | 5 | 0.012106537530266344 | 0.6275588817961699 | 2.2335505461999126 | True |
| paid | 2025Q1 | 1593 | 57 | 0.0358 | 347 | 4 | 0.011527377521613832 | 0.6778401334748976 | 2.346019088722188 | True |
