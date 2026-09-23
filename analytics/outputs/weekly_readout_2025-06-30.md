# Acme Corp - Weekly executive readout

**Reporting period:** June 1 - June 30, 2025 (monthly grain)
**Audience:** Chief Revenue Officer - GTM leadership team
**As of:** 2025-06-30  
**Drill-down threshold:** +/-8% variance (proposed, not yet confirmed)

_Monthly, not weekly. Every actuals mart in this project is segment x month and the variance-diagnostic engine evaluates the last complete month at or before as_of_date; a weekly period would either re-window the marts inside this artifact (a computation it does not do) or repeat one monthly figure under four weekly labels._

## Executive summary

> _Executive summary narrative: not yet generated._
>
> Narrative generation is a separate, deliberately deferred piece of work. Build spec Section 5 specifies an executive summary that names a specific Layer-2/Layer-3 cause for any real miss, generated via the Claude API (Section 3's stack). No LLM is called from analytics/weekly_readout.py and no template-based prose generator substitutes for one -- canned sentences would read as narrative while carrying none of the causal reasoning the section exists for. assemble_readout()'s full return value is the structured input that step is designed to consume.

## Layer 1 scorecard - all 11 nodes

_All eleven Layer-1 nodes are shown every period, unconditionally, per build spec Section 5 -- including the nodes whose actual is not computable from any mart. A reported gap is more useful than a hidden one._

### Layer 1 - Growth

| Metric | Value | vs. plan | Variance | Status |
|---|---|---|---|---|
| New logo consumption revenue | $15.6K | $17.2K plan | -9.0% | Behind |
| Activation (TTFA, blended) | 0.00 mo | 0.00 mo last month | n/a | Not computable |
| Expansion consumption revenue | $491.2K | $129.1K plan | +280.5% | Ahead |
| Contraction + churned revenue | $394.2K | $43.8K plan | +800.1% | Behind |

### Layer 1 - Efficiency

| Metric | Value | vs. plan | Variance | Status |
|---|---|---|---|---|
| Magic number (blended) | n/a | 0.78x plan (no computable actual) | n/a | Not computable |
| Consumption payback (blended) | 0.11 mo | 12.21 mo plan | -99.1% | Ahead |
| Onboarding/CS efficiency (blended) | 5.26e-06 touches/Action | 6.16e-06 touches/Action plan | -14.7% | Ahead |
| AM efficiency (blended) | n/a | 2.76x plan (no computable actual) | n/a | Not computable |

### Layer 1 - Durability

| Metric | Value | vs. plan | Variance | Status |
|---|---|---|---|---|
| NRR | 171.6% | 117.9% plan | +45.5% | Ahead |
| GRR | 50.8% | 92.8% plan | -45.2% | Behind |
| Logo retention | 85.2% | 84.8% plan | +0.4% | On track |

Dollar figures are monthly MRR movements (`mart_growth_bridge`); NRR, GRR and logo retention are trailing-12-month compounded rates (`mart_durability`), which is the unit `mart_gtm_plan` states them in.

### Scorecard notes

- **Activation (TTFA, blended)** (no_plan_by_design): Activation is the one Layer-1 node mart_gtm_plan deliberately carries no plan row for (its own header, and generators/gtm_plan.py). The design brief's sample readout reports it against a trailing baseline ('2.1 days vs. 2.4d last month'), not a plan figure. This engine therefore gives Activation its own trailing-baseline variance mechanism -- a different mechanism from the other ten metrics, stated explicitly rather than forced into the plan-diff shape. DEGENERATE IN THE CURRENT DATA: blended TTFA is identically 0 in every month of the 36-month window, because fact_usage_monthly is monthly grain and every account records its first Action in its own signup month (see mart_growth_bridge's own Activation comment). The baseline mechanism is implemented and exercised, but on this data it has a zero baseline and therefore no computable deviation -- which is why Activation reports 'Not computable' rather than 'On track'. A real TTFA signal needs a day-grain first-Action timestamp in Phase 1 plus a mart change, not a Phase 4 workaround.
- **Magic number (blended)** (not_computable): mart_gtm_plan carries a plan value (a top-down target does not need cost data the way a computed ratio does), but mart_efficiency leaves magic_number NULL by design. Variance from plan is therefore STRUCTURALLY NOT COMPUTABLE -- a genuine data gap, not a bug. An actual is never fabricated to close it.
- **Consumption payback (blended)** (caveated): Both sides exist and the variance IS computed, but the LEVELS are not on the same footing and the readout must not present the gap as a business finding. mart_gtm_plan's anchor is the QA plan's benchmark payback band (Commercial ~14-18mo, Enterprise ~9-13mo), which assumes a fully-loaded CAC. mart_efficiency's actual CAC comes from fact_marketing_spend only -- generators/config.py records that outbound_sdr's channel spend 'covers tooling/data enrichment only, NOT rep headcount cost', so the actual numerator systematically excludes sales headcount. The actual's denominator is also average utilised margin across the whole installed base rather than per NEW account. Both push the computed actual far below the benchmark band. The Layer-2 drill-down is unaffected: it ranks each leg against its own trailing baseline, which is immune to a constant level offset.
- **AM efficiency (blended)** (not_computable): Same structural gap as magic number: mart_gtm_plan carries a plan value, mart_efficiency leaves am_efficiency NULL because no AM comp data exists. Variance from plan is not computable and no actual is fabricated.
- **NRR** (caveated): Two adjustments, both stated rather than applied silently. (1) UNITS: mart_gtm_plan's nrr is an annual-equivalent decimal rate while mart_durability exposes a monthly rate -- this engine compounds the trailing 12 company-wide monthly rates before diffing, per mart_gtm_plan's own header instruction. (2) SCOPE OF THE CONTRACTION BUCKET. The plan side is internally consistent: generators/gtm_plan.py derives its monthly expansion and contraction+churn shares of base FROM the benchmark-blended nrr/grr anchors (1 - grr**(1/12), and nrr**(1/12) - 1 + that), so the plan's flow rows and its durability rows are two readings of one identity rather than two independent guesses. The remaining gap is on the ACTUALS side and is definitional, not performance. Over the twelve months to 2025-11 the marts carry gross contraction+churn at ~5.4% of starting revenue per month against gross expansion at ~10.8%, of which outright churn is only ~0.2%: int_revenue_movements buckets ANY month-on-month usage decline as contraction, so in a consumption business whose base grows ~88% a year both gross legs are large and largely offsetting, while a benchmark NRR/GRR band describes durable downsell in a mature base. That one difference drives both signs at once -- TTM GRR lands ~0.51 against a 0.93 plan while TTM NRR lands ~1.82 against a 1.17 plan. Logo retention, which has no gross-flow bucket, reconciles to plan within 2%, which is the evidence that the churn leg is sound and it is the contraction bucket's SCOPE that differs. Read the Layer-2 drill-down, which ranks each leg against its own trailing baseline and is immune to a definitional level offset.
- **GRR** (caveated): Same two adjustments as NRR -- see the NRR entry.

## This period's drill-downs (7)

_Variable length: one drill-down per Layer-1 node that actually breached the variance threshold this period, and none for any node that did not. Never padded to a fixed count, never truncated. The Layer-2 outlier in each entry is the engine's own ranking of that node's TRUE siblings against their own trailing baselines, and Layer-3 evidence appears only where the branch genuinely has a Layer 3 that a mart can compute._

### 1. New logo consumption revenue - $15.6K vs. $17.2K plan (-9.0%, plan_diff)

- **Layer 2 coverage:** 2 of 3 children of this node have a mart-computable actual.
- **Layer 2 outlier:** Win rate (layer 2, child of `new_logo_consumption_revenue`) - 0.425 this period vs. a 0.2563 trailing baseline (+65.8%), ranked by `relative_deviation`; computability: computable.

| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation | Computability |
|---|---|---|---|---|---|---|
| 1 | Win rate | 2 | 0.425 | 0.2563 | +65.8% | computable |
| 2 | Avg initial commitment | 2 | 5.503e+04 | 5.688e+04 | -3.3% | computable |

- **Layer 3:** the tree has Layer-3 children here (branch depth 3), but none is computable from any `mart_*` table this period.
- _Note:_ win_rate does have Layer-3 children in the tree, but none is computable from any mart_* table; see layer3_evidence's missing list for the reasons.

### 2. Expansion consumption revenue - $491.2K vs. $129.1K plan (+280.5%, plan_diff)

- **Layer 2 coverage:** 0 of 2 children of this node have a mart-computable actual - single-candidate read, not an outlier selection among siblings.
- **Layer 2 outlier:** none identifiable - no child of this node has a mart-computable actual with a usable trailing baseline. The Layer-1 variance stands on its own.

- **Layer 3:** not reached - Layer-3 evidence hangs off a Layer-2 outlier, and none was identifiable here. The branch runs 3 layers deep in the tree.
- _Note:_ No Layer-2 child of expansion_consumption_revenue has a mart-computable actual with a usable trailing baseline, so no outlier can be identified. The Layer-1 variance stands on its own; see sibling_coverage for which children are missing and why.

### 3. Contraction + churned revenue - $394.2K vs. $43.8K plan (+800.1%, plan_diff)

- **Layer 2 coverage:** 1 of 4 children of this node have a mart-computable actual - single-candidate read, not an outlier selection among siblings.
- **Layer 2 outlier:** Cyclical/planned usage dip vs. structural churn (layer 2, child of `contraction_churned_revenue`) - 0.0299 this period vs. a 0.02753 trailing baseline (+8.6%), ranked by `relative_deviation`; computability: partial.

| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation | Computability |
|---|---|---|---|---|---|---|
| 1 | Cyclical/planned usage dip vs. structural churn | 2 | 0.0299 | 0.02753 | +8.6% | partial |

- **Layer 3:** the tree has Layer-3 children here (branch depth 3), but none is computable from any `mart_*` table this period.
- _Note:_ Only 1 of 4 Layer-2 siblings under contraction_churned_revenue have a mart-computable actual, so this is a single-candidate read rather than a genuine outlier selection among siblings.
- _Note:_ cyclical_vs_structural_usage_dip does have Layer-3 children in the tree, but none is computable from any mart_* table; see layer3_evidence's missing list for the reasons.

### 4. Consumption payback (blended) - 0.11 mo vs. 12.21 mo plan (-99.1%, plan_diff)

- **Layer 2 coverage:** 2 of 2 children of this node have a mart-computable actual.
- **Layer 2 outlier:** CAC by channel (unblended) (layer 2, child of `consumption_payback`) - 544.6 this period vs. a 768.2 trailing baseline (-29.1%), ranked by `relative_deviation`; computability: partial.

| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation | Computability |
|---|---|---|---|---|---|---|
| 1 | CAC by channel (unblended) | 2 | 544.6 | 768.2 | -29.1% | partial |
| 2 | Utilized vs. committed Action volume | 2 | 2.211e+04 | 2.276e+04 | -2.9% | partial |

- **Layer 3:** none - this branch is genuinely 2 layers deep in the metric tree. No Layer 3 is fabricated to force symmetry.
- _Note:_ Both sides exist and the variance IS computed, but the LEVELS are not on the same footing and the readout must not present the gap as a business finding. mart_gtm_plan's anchor is the QA plan's benchmark payback band (Commercial ~14-18mo, Enterprise ~9-13mo), which assumes a fully-loaded CAC. mart_efficiency's actual CAC comes from fact_marketing_spend only -- generators/config.py records that outbound_sdr's channel spend 'covers tooling/data enrichment only, NOT rep headcount cost', so the actual numerator systematically excludes sales headcount. The actual's denominator is also average utilised margin across the whole installed base rather than per NEW account. Both push the computed actual far below the benchmark band. The Layer-2 drill-down is unaffected: it ranks each leg against its own trailing baseline, which is immune to a constant level offset.
- _Note:_ cac_by_channel has no Layer-3 children in the metric tree -- this branch is genuinely two layers deep. No Layer 3 is fabricated to force symmetry.

### 5. Onboarding/CS efficiency (blended) - 5.26e-06 touches/Action vs. 6.16e-06 touches/Action plan (-14.7%, plan_diff)

- **Layer 2 coverage:** 2 of 2 children of this node have a mart-computable actual.
- **Layer 2 outlier:** Automated Action volume delivered (layer 2, child of `onboarding_cs_efficiency`) - 1.359e+08 this period vs. a 1.154e+08 trailing baseline (+17.8%), ranked by `relative_deviation`; computability: computable.

| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation | Computability |
|---|---|---|---|---|---|---|
| 1 | Automated Action volume delivered | 2 | 1.359e+08 | 1.154e+08 | +17.8% | computable |
| 2 | AM touchpoint volume | 2 | 715 | 636.1 | +12.4% | computable |

- **Layer 3:** none - this branch is genuinely 2 layers deep in the metric tree. No Layer 3 is fabricated to force symmetry.
- _Note:_ automated_action_volume has no Layer-3 children in the metric tree -- this branch is genuinely two layers deep. No Layer 3 is fabricated to force symmetry.

### 6. NRR - 171.6% vs. 117.9% plan (+45.5%, plan_diff)

- **Layer 2 coverage:** 3 of 3 children of this node have a mart-computable actual.
- **Layer 2 outlier:** Expansion (share of starting revenue) (layer 2, child of `nrr`) - 0.07275 this period vs. a 0.1044 trailing baseline (-30.3%), ranked by `additive_share`; computability: computable.
  - This node is the tree's cross-reference to `expansion_consumption_revenue` under Growth, not an independent driver.

| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation | Computability |
|---|---|---|---|---|---|---|
| 1 | Expansion (share of starting revenue) | 2 | 0.07275 | 0.1044 | -30.3% | computable |
| 2 | Contraction (share of starting revenue) | 2 | 0.05692 | 0.0555 | +2.6% | computable |
| 3 | Churn (share of starting revenue) | 2 | 0.001462 | 0.001735 | -15.7% | computable |

- **Layer 3:** none - this branch is genuinely 2 layers deep in the metric tree. No Layer 3 is fabricated to force symmetry.
- _Note:_ Two adjustments, both stated rather than applied silently. (1) UNITS: mart_gtm_plan's nrr is an annual-equivalent decimal rate while mart_durability exposes a monthly rate -- this engine compounds the trailing 12 company-wide monthly rates before diffing, per mart_gtm_plan's own header instruction. (2) SCOPE OF THE CONTRACTION BUCKET. The plan side is internally consistent: generators/gtm_plan.py derives its monthly expansion and contraction+churn shares of base FROM the benchmark-blended nrr/grr anchors (1 - grr**(1/12), and nrr**(1/12) - 1 + that), so the plan's flow rows and its durability rows are two readings of one identity rather than two independent guesses. The remaining gap is on the ACTUALS side and is definitional, not performance. Over the twelve months to 2025-11 the marts carry gross contraction+churn at ~5.4% of starting revenue per month against gross expansion at ~10.8%, of which outright churn is only ~0.2%: int_revenue_movements buckets ANY month-on-month usage decline as contraction, so in a consumption business whose base grows ~88% a year both gross legs are large and largely offsetting, while a benchmark NRR/GRR band describes durable downsell in a mature base. That one difference drives both signs at once -- TTM GRR lands ~0.51 against a 0.93 plan while TTM NRR lands ~1.82 against a 1.17 plan. Logo retention, which has no gross-flow bucket, reconciles to plan within 2%, which is the evidence that the churn leg is sound and it is the contraction bucket's SCOPE that differs. Read the Layer-2 drill-down, which ranks each leg against its own trailing baseline and is immune to a definitional level offset.
- _Note:_ Grain note: nrr's Layer-1 figure is the trailing-12-month compounded rate (to match mart_gtm_plan's annual-equivalent units), while its Layer-2 drivers are read at monthly grain -- the grain at which a driver actually moves. A driver can therefore point the opposite way to the annualised parent in any single month; read the driver ranking as 'what moved this month', not as a decomposition of the twelve-month figure.
- _Note:_ nrr_expansion_rate has no Layer-3 children in the metric tree -- this branch is genuinely two layers deep. No Layer 3 is fabricated to force symmetry.

### 7. GRR - 50.8% vs. 92.8% plan (-45.2%, plan_diff)

- **Layer 2 coverage:** 2 of 2 children of this node have a mart-computable actual.
- **Layer 2 outlier:** Contraction (share of starting revenue) (layer 2, child of `grr`) - 0.05692 this period vs. a 0.0555 trailing baseline (+2.6%), ranked by `additive_share`; computability: computable.
  - This node is the tree's cross-reference to `contraction_churned_revenue` under Growth, not an independent driver.

| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation | Computability |
|---|---|---|---|---|---|---|
| 1 | Contraction (share of starting revenue) | 2 | 0.05692 | 0.0555 | +2.6% | computable |
| 2 | Churn (share of starting revenue) | 2 | 0.001462 | 0.001735 | -15.7% | computable |

- **Layer 3:** none - this branch is genuinely 2 layers deep in the metric tree. No Layer 3 is fabricated to force symmetry.
- _Note:_ Same two adjustments as NRR -- see the NRR entry.
- _Note:_ Grain note: grr's Layer-1 figure is the trailing-12-month compounded rate (to match mart_gtm_plan's annual-equivalent units), while its Layer-2 drivers are read at monthly grain -- the grain at which a driver actually moves. A driver can therefore point the opposite way to the annualised parent in any single month; read the driver ranking as 'what moved this month', not as a decomposition of the twelve-month figure.
- _Note:_ grr_contraction_rate has no Layer-3 children in the metric tree -- this branch is genuinely two layers deep. No Layer 3 is fabricated to force symmetry.

## Automated playbook triggers

**Status: not_yet_built.** Automated playbook triggers is a Wave 4 artifact, not yet built. Build spec Section 8 places it in Wave 4 with the stated dependency 'needs Wave 1's thresholds validated against real data first', which is only coherent if the triggers are built after this wave's thresholds exist and have been validated -- the same resolved scope decision recorded in analytics/variance_diagnostic.py and in the methods doc. The source table it will log to, fact_playbook_triggers, does not exist yet either. The section is carried here with this status so the readout's structure stays forward-compatible; no trigger is invented to fill it.

## Forecast

**Status: not_yet_built.** Forecast (sales bottoms-up + ML/regression + CRO overlay) is a Wave 2 artifact, not yet built -- build spec Section 8 places it in the wave after this one, and its entry in docs/acme-corp-analytics-methods.md is still TBD. The section is carried here with this status so the readout's structure stays forward-compatible; no forecast number is fabricated to fill it.

## Watchlist (25 accounts)

_Accounts whose composite health score breaches the risk threshold (risk_tier == 'High'), ranked by estimated ARR at risk, then by churn probability -- analytics/variance_diagnostic.py's build_watchlist(), which consumes analytics/health_score.py's scored output directly._

| # | Account | Segment | Risk tier | Churn probability | Health score | Est. ARR at risk |
|---|---|---|---|---|---|---|
| 1 | ACC-004101 | Commercial | High | 0.928 | 7.2 | $26.2K |
| 2 | ACC-000142 | Commercial | High | 0.918 | 8.2 | $26.2K |
| 3 | ACC-003491 | Commercial | High | 0.916 | 8.4 | $26.2K |
| 4 | ACC-000200 | Commercial | High | 0.913 | 8.7 | $26.2K |
| 5 | ACC-004718 | Commercial | High | 0.903 | 9.7 | $26.2K |
| 6 | ACC-000318 | Commercial | High | 0.900 | 10.0 | $26.2K |
| 7 | ACC-000269 | Commercial | High | 0.895 | 10.5 | $26.2K |
| 8 | ACC-000317 | Commercial | High | 0.858 | 14.2 | $26.2K |
| 9 | ACC-000430 | Commercial | High | 0.853 | 14.7 | $26.2K |
| 10 | ACC-000221 | Commercial | High | 0.844 | 15.6 | $26.2K |
| 11 | ACC-000959 | Commercial | High | 0.842 | 15.8 | $26.2K |
| 12 | ACC-006872 | Commercial | High | 0.830 | 17.0 | $26.2K |
| 13 | ACC-000321 | Commercial | High | 0.819 | 18.1 | $26.2K |
| 14 | ACC-000382 | Commercial | High | 0.814 | 18.6 | $26.2K |
| 15 | ACC-000230 | Commercial | High | 0.813 | 18.7 | $26.2K |
| 16 | ACC-000243 | Commercial | High | 0.813 | 18.7 | $26.2K |
| 17 | ACC-000150 | Commercial | High | 0.809 | 19.1 | $26.2K |
| 18 | ACC-000363 | Commercial | High | 0.808 | 19.2 | $26.2K |
| 19 | ACC-000215 | Commercial | High | 0.804 | 19.6 | $26.2K |
| 20 | ACC-000289 | Commercial | High | 0.794 | 20.6 | $26.2K |
| 21 | ACC-000298 | Commercial | High | 0.789 | 21.1 | $26.2K |
| 22 | ACC-000254 | Commercial | High | 0.788 | 21.2 | $26.2K |
| 23 | ACC-000320 | Commercial | High | 0.783 | 21.7 | $26.2K |
| 24 | ACC-003163 | Commercial | High | 0.782 | 21.8 | $26.2K |
| 25 | ACC-000292 | Commercial | High | 0.781 | 21.9 | $26.2K |

- est_arr_at_risk_usd is the account's SEGMENT-AVERAGE ARR for the evaluation month (mart_durability starting_mrr / starting_accounts x 12), not its own contracted ARR -- no mart_* table exposes ARR at account grain. It orders the watchlist correctly across segments and by risk within a segment, but it is an estimate and is named as one.
- risk_tier is quantile-based over the scored active population, so the watchlist's segment mix follows the tier definition rather than an ARR-ranking judgement.
- churn_probability is a ranking signal, not a calibrated probability: class_weight='balanced' shifts the health model's predicted probabilities up systematically (see the health score's calibration note in docs/acme-corp-analytics-methods.md). It must not be read as a literal likelihood of churn.

## Provenance

Assembled by `analytics/weekly_readout.py`. Computation performed during assembly: **none** - every figure above is read verbatim from the artifact that owns it and is re-checked against that artifact field by field.

| Section | Source artifact | Entry point |
|---|---|---|
| layer1_scorecard | `analytics/variance_diagnostic.py` | `run_diagnostic()['layer1_scorecard']` |
| drilldowns | `analytics/variance_diagnostic.py` | `run_diagnostic()['drilldowns']` |
| watchlist | `analytics/variance_diagnostic.py -> analytics/health_score.py` | `run_diagnostic()['watchlist'] (build_watchlist -> score_accounts)` |
| source_coverage | `analytics/variance_diagnostic.py` | `run_diagnostic()['coverage']` |
| data_window | `analytics/variance_diagnostic.py` | `run_diagnostic()['data_window']` |

- Metric definitions: docs/acme-corp-gtm-metric-tree.md (via variance_diagnostic._TREE)
- Variance threshold: +/-8%, proposed and not yet confirmed -- build spec Section 7 lists the drill-down threshold as an open question. This readout consumes the engine's threshold; it does not set or override one.
- Segment migration: analytics/segment_migration.py is Wave 1's third artifact and is not a source for any section of this readout. Its outputs (migration velocity, trigger-reason mix, graduated revenue) are population-level descriptive series that the build spec's readout structure has no section for -- graduated revenue is deliberately excluded from the source segment's churn/contraction, so it does not belong in the Growth scorecard rows either. Stated here rather than left as a silent omission.
