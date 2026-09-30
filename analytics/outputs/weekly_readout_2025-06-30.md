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
| Magic number (blended) | 1.54x | 0.78x plan | +95.9% | Ahead |
| Consumption payback (blended) | 0.11 mo | 12.21 mo plan | -99.1% | Ahead |
| Onboarding/CS efficiency (blended) | 5.26e-06 touches/Action | 6.16e-06 touches/Action plan | -14.7% | Ahead |
| AM efficiency (blended) | 2.00x | 2.76x plan | -27.8% | Behind |

### Layer 1 - Durability

| Metric | Value | vs. plan | Variance | Status |
|---|---|---|---|---|
| NRR | 171.6% | 117.9% plan | +45.5% | Ahead |
| GRR | 50.8% | 92.8% plan | -45.2% | Behind |
| Logo retention | 85.2% | 84.8% plan | +0.4% | On track |

Dollar figures are monthly MRR movements (`mart_growth_bridge`); NRR, GRR and logo retention are trailing-12-month compounded rates (`mart_durability`), which is the unit `mart_gtm_plan` states them in.

### Scorecard notes

- **Activation (TTFA, blended)** (no_plan_by_design): Activation is the one Layer-1 node mart_gtm_plan deliberately carries no plan row for (its own header, and generators/gtm_plan.py). The design brief's sample readout reports it against a trailing baseline ('2.1 days vs. 2.4d last month'), not a plan figure. This engine therefore gives Activation its own trailing-baseline variance mechanism -- a different mechanism from the other ten metrics, stated explicitly rather than forced into the plan-diff shape. DEGENERATE IN THE CURRENT DATA: blended TTFA is identically 0 in every month of the 36-month window, because fact_usage_monthly is monthly grain and every account records its first Action in its own signup month (see mart_growth_bridge's own Activation comment). The baseline mechanism is implemented and exercised, but on this data it has a zero baseline and therefore no computable deviation -- which is why Activation reports 'Not computable' rather than 'On track'. A real TTFA signal needs a day-grain first-Action timestamp in Phase 1 plus a mart change, not a Phase 4 workaround.
- **Magic number (blended)** (caveated): Both sides exist and the variance IS computed, but the LEVELS are not on the same footing and the readout must not present the gap as a business finding on its own. (1) SCOPE OF S&M COST. mart_gtm_plan's anchor is the QA plan's benchmark Magic Number band (Commercial and Enterprise ~0.7-0.9), a figure for a fully scoped S&M line. The actual's S&M cost is the metric tree's three-part definition: rep fully-loaded cost (incl. ramp, with a management/ops allocation in the loading factor) plus marketing program spend. Marketing-team headcount, which the raw data does not carry, is outside it, so the denominator is a floor and the actual a ceiling against the benchmark. (2) BASIS. The actual is a trailing-twelve-month ratio of net new ARR (new logo + expansion - contraction - churn, so it includes usage-driven expansion) to the prior-month S&M cost over the same twelve months, blended over Commercial and Enterprise only (SMB carries no rep cost and is 'n/a' in the benchmark table), the same population the plan blend uses. (3) TREND. Net new ARR compounds with a revenue base growing ~88% a year while quota-carrying and AM headcount is close to flat, so the actual climbs through the window (roughly 0.9 to 2.5) against a plan that moves ~3% a year: the gap widens with scale rather than tracking any one month. Read the sign, the trend and the Layer-2 drill-down, not the level.
- **Consumption payback (blended)** (caveated): Both sides exist and the variance IS computed, but the LEVELS are not on the same footing and the readout must not present the gap as a business finding. mart_gtm_plan's anchor is the QA plan's benchmark payback band (Commercial ~14-18mo, Enterprise ~9-13mo), which assumes a fully-loaded CAC. mart_efficiency's actual CAC comes from fact_marketing_spend only -- generators/config.py records that outbound_sdr's channel spend 'covers tooling/data enrichment only, NOT rep headcount cost', so the actual numerator systematically excludes sales headcount. The actual's denominator is also average utilised margin across the whole installed base rather than per NEW account. Both push the computed actual far below the benchmark band. The Layer-2 drill-down is unaffected: it ranks each leg against its own trailing baseline, which is immune to a constant level offset.
- **AM efficiency (blended)** (caveated): Both sides exist and the variance IS computed; three differences in footing are stated rather than applied silently. (1) UNITS AND BASIS: the tree defines the ratio as Expansion consumption revenue / AM cost; both are read as monthly flows (monthly expansion MRR movement over the same month's AM cost), the basis generators/gtm_plan.py's anchor uses, and the actual is a trailing-twelve-month aggregate of them because a single month carries the raw data's Q4 seasonality. (2) POPULATION: the plan anchor's numerator is built on the company-wide revenue base (SMB included; see generators/gtm_plan.py's KNOWN DIVERGENCE note), while the actual is blended over Commercial and Enterprise, the only segments with an AM, so the actual sits below a like-for-like plan by roughly SMB's share of expansion. (3) SCOPE OF EXPANSION: int_revenue_movements buckets any month-on-month usage increase as expansion, the same gross-bucket definition that caveats NRR/GRR. The actual rises through the window (roughly 0.8 to 2.6) toward a plan that is nearly flat, so the negative gap narrows over time. Read the sign, the trend and the Layer-2 drill-down, not the level.
- **NRR** (caveated): Two adjustments, both stated rather than applied silently. (1) UNITS: mart_gtm_plan's nrr is an annual-equivalent decimal rate while mart_durability exposes a monthly rate -- this engine compounds the trailing 12 company-wide monthly rates before diffing, per mart_gtm_plan's own header instruction. (2) SCOPE OF THE CONTRACTION BUCKET. The plan side is internally consistent: generators/gtm_plan.py derives its monthly expansion and contraction+churn shares of base FROM the benchmark-blended nrr/grr anchors (1 - grr**(1/12), and nrr**(1/12) - 1 + that), so the plan's flow rows and its durability rows are two readings of one identity rather than two independent guesses. The remaining gap is on the ACTUALS side and is definitional, not performance. Over the twelve months to 2025-11 the marts carry gross contraction+churn at ~5.4% of starting revenue per month against gross expansion at ~10.8%, of which outright churn is only ~0.2%: int_revenue_movements buckets ANY month-on-month usage decline as contraction, so in a consumption business whose base grows ~88% a year both gross legs are large and largely offsetting, while a benchmark NRR/GRR band describes durable downsell in a mature base. That one difference drives both signs at once -- TTM GRR lands ~0.51 against a 0.93 plan while TTM NRR lands ~1.82 against a 1.17 plan. Logo retention, which has no gross-flow bucket, reconciles to plan within 2%, which is the evidence that the churn leg is sound and it is the contraction bucket's SCOPE that differs. Read the Layer-2 drill-down, which ranks each leg against its own trailing baseline and is immune to a definitional level offset.
- **GRR** (caveated): Same two adjustments as NRR -- see the NRR entry.

## This period's drill-downs (9)

_Variable length: one drill-down per Layer-1 node that actually breached the variance threshold this period, and none for any node that did not. Never padded to a fixed count, never truncated. The Layer-2 outlier in each entry is the engine's own ranking of that node's TRUE siblings against their own trailing baselines, and Layer-3 evidence appears only where the branch genuinely has a Layer 3 that a mart can compute._

### 1. New logo consumption revenue - $15.6K vs. $17.2K plan (-9.0%, plan_diff)

- **Layer 2 coverage:** 3 of 3 children of this node have a mart-computable actual.
- **Layer 2 outlier:** Win rate (layer 2, child of `new_logo_consumption_revenue`) - 0.425 this period vs. a 0.2563 trailing baseline (+65.8%), ranked by `relative_deviation`; computability: computable.

| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation | Computability |
|---|---|---|---|---|---|---|
| 1 | Win rate | 2 | 0.425 | 0.2563 | +65.8% | computable |
| 2 | Pipeline generated | 2 | 69 | 54.38 | +26.9% | computable |
| 3 | Avg initial commitment | 2 | 5.503e+04 | 5.688e+04 | -3.3% | computable |

- **Layer 3:** the tree has Layer-3 children here (branch depth 3), but none is computable from any `mart_*` table this period.
- _Note:_ Pipeline generated is read from analytics/marketing_attribution.py as a monthly flow: leads that converted to a PQL (this funnel's signup) in the month, by the lead's sourcing sub-channel (organic / paid / community), company-wide. It covers inbound-marketing-sourced accounts only, across all three segments (SMB included), and is indexed by conversion month rather than lead-creation month so the latest month is not right-censored. Win rate and Avg initial commitment are measured on rep-sold Commercial/Enterprise opportunities, a different population and unit, so this engine ranks Pipeline generated against its own trailing baseline like any sibling but does not multiply the three legs into a New logo figure (the governance module's New-logo product edge stays NOT_COMPUTABLE for the same reason).
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

### 4. Magic number (blended) - 1.54x vs. 0.78x plan (+95.9%, plan_diff)

- **Layer 2 coverage:** 1 of 1 children of this node have a mart-computable actual - single-candidate read, not an outlier selection among siblings.
- **Layer 2 outlier:** S&M cost (layer 2, child of `magic_number`) - 1.475e+06 this period vs. a 1.425e+06 trailing baseline (+3.5%), ranked by `relative_deviation`; computability: computable.

| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation | Computability |
|---|---|---|---|---|---|---|
| 1 | S&M cost | 2 | 1.475e+06 | 1.425e+06 | +3.5% | computable |

- **Layer 3 evidence:** Rep fully-loaded cost, incl. ramp (layer 3), Marketing spend allocation by channel (layer 3).

| Rank | Layer-3 leaf | Layer | Value | Trailing baseline | Deviation |
|---|---|---|---|---|---|
| 1 | Rep fully-loaded cost, incl. ramp | 3 | 1.45e+06 | 1.403e+06 | +3.4% |
| 2 | Marketing spend allocation by channel | 3 | 2.518e+04 | 2.24e+04 | +12.4% |
- _Note:_ Both sides exist and the variance IS computed, but the LEVELS are not on the same footing and the readout must not present the gap as a business finding on its own. (1) SCOPE OF S&M COST. mart_gtm_plan's anchor is the QA plan's benchmark Magic Number band (Commercial and Enterprise ~0.7-0.9), a figure for a fully scoped S&M line. The actual's S&M cost is the metric tree's three-part definition: rep fully-loaded cost (incl. ramp, with a management/ops allocation in the loading factor) plus marketing program spend. Marketing-team headcount, which the raw data does not carry, is outside it, so the denominator is a floor and the actual a ceiling against the benchmark. (2) BASIS. The actual is a trailing-twelve-month ratio of net new ARR (new logo + expansion - contraction - churn, so it includes usage-driven expansion) to the prior-month S&M cost over the same twelve months, blended over Commercial and Enterprise only (SMB carries no rep cost and is 'n/a' in the benchmark table), the same population the plan blend uses. (3) TREND. Net new ARR compounds with a revenue base growing ~88% a year while quota-carrying and AM headcount is close to flat, so the actual climbs through the window (roughly 0.9 to 2.5) against a plan that moves ~3% a year: the gap widens with scale rather than tracking any one month. Read the sign, the trend and the Layer-2 drill-down, not the level.
- _Note:_ Only 1 of 1 Layer-2 siblings under magic_number have a mart-computable actual, so this is a single-candidate read rather than a genuine outlier selection among siblings.

### 5. Consumption payback (blended) - 0.11 mo vs. 12.21 mo plan (-99.1%, plan_diff)

- **Layer 2 coverage:** 2 of 2 children of this node have a mart-computable actual.
- **Layer 2 outlier:** CAC by channel (unblended) (layer 2, child of `consumption_payback`) - 544.6 this period vs. a 768.2 trailing baseline (-29.1%), ranked by `relative_deviation`; computability: partial.

| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation | Computability |
|---|---|---|---|---|---|---|
| 1 | CAC by channel (unblended) | 2 | 544.6 | 768.2 | -29.1% | partial |
| 2 | Utilized vs. committed Action volume | 2 | 2.211e+04 | 2.276e+04 | -2.9% | partial |

- **Layer 3:** none - this branch is genuinely 2 layers deep in the metric tree. No Layer 3 is fabricated to force symmetry.
- _Note:_ Both sides exist and the variance IS computed, but the LEVELS are not on the same footing and the readout must not present the gap as a business finding. mart_gtm_plan's anchor is the QA plan's benchmark payback band (Commercial ~14-18mo, Enterprise ~9-13mo), which assumes a fully-loaded CAC. mart_efficiency's actual CAC comes from fact_marketing_spend only -- generators/config.py records that outbound_sdr's channel spend 'covers tooling/data enrichment only, NOT rep headcount cost', so the actual numerator systematically excludes sales headcount. The actual's denominator is also average utilised margin across the whole installed base rather than per NEW account. Both push the computed actual far below the benchmark band. The Layer-2 drill-down is unaffected: it ranks each leg against its own trailing baseline, which is immune to a constant level offset.
- _Note:_ cac_by_channel has no Layer-3 children in the metric tree -- this branch is genuinely two layers deep. No Layer 3 is fabricated to force symmetry.

### 6. Onboarding/CS efficiency (blended) - 5.26e-06 touches/Action vs. 6.16e-06 touches/Action plan (-14.7%, plan_diff)

- **Layer 2 coverage:** 2 of 2 children of this node have a mart-computable actual.
- **Layer 2 outlier:** Automated Action volume delivered (layer 2, child of `onboarding_cs_efficiency`) - 1.359e+08 this period vs. a 1.154e+08 trailing baseline (+17.8%), ranked by `relative_deviation`; computability: computable.

| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation | Computability |
|---|---|---|---|---|---|---|
| 1 | Automated Action volume delivered | 2 | 1.359e+08 | 1.154e+08 | +17.8% | computable |
| 2 | AM touchpoint volume | 2 | 715 | 636.1 | +12.4% | computable |

- **Layer 3:** none - this branch is genuinely 2 layers deep in the metric tree. No Layer 3 is fabricated to force symmetry.
- _Note:_ automated_action_volume has no Layer-3 children in the metric tree -- this branch is genuinely two layers deep. No Layer 3 is fabricated to force symmetry.

### 7. AM efficiency (blended) - 2.00x vs. 2.76x plan (-27.8%, plan_diff)

- **Layer 2 coverage:** 1 of 2 children of this node have a mart-computable actual - single-candidate read, not an outlier selection among siblings.
- **Layer 2 outlier:** AM cost by segment (layer 2, child of `am_efficiency`) - 2.209e+05 this period vs. a 2.048e+05 trailing baseline (+7.9%), ranked by `relative_deviation`; computability: computable.

| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation | Computability |
|---|---|---|---|---|---|---|
| 1 | AM cost by segment | 2 | 2.209e+05 | 2.048e+05 | +7.9% | computable |

- **Layer 3:** none - this branch is genuinely 2 layers deep in the metric tree. No Layer 3 is fabricated to force symmetry.
- _Note:_ Both sides exist and the variance IS computed; three differences in footing are stated rather than applied silently. (1) UNITS AND BASIS: the tree defines the ratio as Expansion consumption revenue / AM cost; both are read as monthly flows (monthly expansion MRR movement over the same month's AM cost), the basis generators/gtm_plan.py's anchor uses, and the actual is a trailing-twelve-month aggregate of them because a single month carries the raw data's Q4 seasonality. (2) POPULATION: the plan anchor's numerator is built on the company-wide revenue base (SMB included; see generators/gtm_plan.py's KNOWN DIVERGENCE note), while the actual is blended over Commercial and Enterprise, the only segments with an AM, so the actual sits below a like-for-like plan by roughly SMB's share of expansion. (3) SCOPE OF EXPANSION: int_revenue_movements buckets any month-on-month usage increase as expansion, the same gross-bucket definition that caveats NRR/GRR. The actual rises through the window (roughly 0.8 to 2.6) toward a plan that is nearly flat, so the negative gap narrows over time. Read the sign, the trend and the Layer-2 drill-down, not the level.
- _Note:_ Only 1 of 2 Layer-2 siblings under am_efficiency have a mart-computable actual, so this is a single-candidate read rather than a genuine outlier selection among siblings.
- _Note:_ am_cost_by_segment has no Layer-3 children in the metric tree -- this branch is genuinely two layers deep. No Layer 3 is fabricated to force symmetry.

### 8. NRR - 171.6% vs. 117.9% plan (+45.5%, plan_diff)

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

### 9. GRR - 50.8% vs. 92.8% plan (-45.2%, plan_diff)

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

## Automated playbook triggers (1404)

_Whatever fired this period, unranked (binary, not prioritized) -- build spec Section 5's own phrasing for this section. Each row is one binary threshold rule (see 'rules' above for each rule's stored, configurable threshold) firing for one account, computed fresh from main_marts fact tables at as_of_date. outcome is read from the operational log (fact_playbook_triggers / data/playbook_triggers.csv) and shown only where it was already knowable at as_of_date: a trigger reads pending until its rule's observation window has elapsed (analytics/playbook_triggers.py OUTCOME_CRITERIA, PROPOSED). Owner, SLA and the open task list live in the same log (open_trigger_tasks())._

| Rule | Account | Timestamp | Resulting action | Outcome |
|---|---|---|---|---|
| ingestion_without_completion | ACC-000020 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000022 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000030 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000041 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000113 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000125 | 2022-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000128 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000134 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000139 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000144 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000146 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000162 | 2021-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000186 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000189 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000212 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000234 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000256 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000267 | 2021-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000268 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000272 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000280 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000290 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000329 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000338 | 2021-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000357 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000391 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000399 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000402 | 2022-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000410 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000411 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000424 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000440 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000446 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000475 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000484 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000503 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000520 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000522 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000527 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000536 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000537 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000540 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000541 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000547 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000549 | 2020-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000551 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000561 | 2020-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000574 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000581 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000582 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000585 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000588 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000593 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000594 | 2023-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000595 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000598 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000602 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000608 | 2020-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000620 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000625 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000628 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000655 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000656 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000658 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000680 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000686 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000690 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000701 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000705 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000713 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000717 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000718 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000727 | 2021-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000741 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000751 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000753 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000757 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000758 | 2023-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000759 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000766 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000771 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000777 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000782 | 2020-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000789 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000795 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000797 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000798 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000799 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000805 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000814 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000818 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000824 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000836 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000846 | 2022-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000848 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000849 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000855 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000860 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000881 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000882 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000886 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000891 | 2022-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000893 | 2023-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000894 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000896 | 2022-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000902 | 2021-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000905 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000906 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000910 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000914 | 2020-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000917 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000921 | 2020-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000938 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000945 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000966 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000968 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-000985 | 2021-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000988 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000989 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000992 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-000997 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001010 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001013 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001020 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001027 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001034 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001036 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001040 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001048 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001052 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001081 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001082 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001089 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001103 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001106 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001123 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001128 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001129 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001146 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001151 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001172 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001173 | 2023-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001180 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001192 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001193 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001202 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001204 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001209 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001221 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001224 | 2022-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001227 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001230 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001236 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001237 | 2020-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001269 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001270 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001272 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001274 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001277 | 2023-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001290 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001305 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001309 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001312 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001321 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001323 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001324 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001330 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001331 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001341 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001342 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001347 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001362 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001363 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001367 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001397 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001402 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001408 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001410 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001413 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001419 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001424 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001427 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001428 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001433 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001441 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001442 | 2020-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001443 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001444 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001449 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001458 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001467 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001468 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001477 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001485 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001494 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001516 | 2021-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001523 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001535 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001539 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001548 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001550 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001557 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001566 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001570 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001572 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001574 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001576 | 2021-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001581 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001592 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001600 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001601 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001624 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001626 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001627 | 2020-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001631 | 2021-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001636 | 2021-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001638 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001649 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001650 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001663 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001680 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001694 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001695 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001716 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001720 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001723 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001729 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001732 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001734 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001737 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001749 | 2022-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001759 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001766 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001768 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001770 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001777 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001784 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001787 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001792 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001808 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001816 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001821 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001825 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001826 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001830 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001831 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001835 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001837 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001842 | 2023-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001843 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001847 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001851 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001855 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001863 | 2021-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001872 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001874 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001886 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001891 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001894 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001902 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001907 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001910 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001925 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001926 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001928 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001938 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001943 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001952 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001955 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001956 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001958 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001961 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001965 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001968 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001969 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-001980 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-001989 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002009 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002011 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002014 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002019 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002022 | 2023-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002030 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002032 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002034 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002035 | 2022-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002036 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002043 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002046 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002051 | 2020-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002057 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002063 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002066 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002069 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002080 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002082 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002084 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002097 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002098 | 2020-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002101 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002102 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002106 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002107 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002108 | 2021-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002113 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002123 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002133 | 2020-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002134 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002141 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002155 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002161 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002167 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002169 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002173 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002175 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002199 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002211 | 2023-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002214 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002218 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002219 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002225 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002232 | 2022-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002242 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002243 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002253 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002255 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002260 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002273 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002285 | 2022-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002288 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002296 | 2022-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002303 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002309 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002311 | 2021-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002312 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002324 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002328 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002332 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002333 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002340 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002343 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002354 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002355 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002357 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002360 | 2021-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002363 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002367 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002370 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002373 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002378 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002383 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002396 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002402 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002403 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002406 | 2021-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002410 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002415 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002418 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002427 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002436 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002442 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002447 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002458 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002462 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002464 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002471 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002487 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002493 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002495 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002505 | 2021-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002515 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002525 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002528 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002536 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002544 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002549 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002550 | 2021-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002560 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002569 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002594 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002598 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002599 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002613 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002625 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002627 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002628 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002630 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002642 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002647 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002652 | 2022-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002655 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002674 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002675 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002680 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002684 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002688 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002698 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002701 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002702 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002708 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002712 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002714 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002716 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002723 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002724 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002735 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002738 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002742 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002744 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002762 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002770 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002777 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002780 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002787 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002789 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002793 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002797 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002805 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002809 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002811 | 2023-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002813 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002823 | 2021-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002830 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002838 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002839 | 2021-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002846 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002847 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002848 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002852 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002856 | 2020-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002865 | 2020-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002872 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002887 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002890 | 2022-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002893 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002896 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002901 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002902 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002906 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002909 | 2020-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002911 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002912 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002920 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002931 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002941 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002944 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002954 | 2022-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002957 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-002967 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002972 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002973 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002975 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-002981 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003005 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003009 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003035 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003038 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003039 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003061 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003063 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003073 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003081 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003082 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003092 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003097 | 2021-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003098 | 2021-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003106 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003113 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003122 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003124 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003127 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003130 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003132 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003135 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003137 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003138 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003139 | 2020-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003144 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003146 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003149 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003153 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003155 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003158 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003168 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003176 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003182 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003185 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003196 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003199 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003201 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003213 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003215 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003219 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003222 | 2022-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003223 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003227 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003230 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003233 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003243 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003253 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003270 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003271 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003273 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003276 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003285 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003291 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003296 | 2020-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003303 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003310 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003312 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003331 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003337 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003346 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003349 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003358 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003359 | 2023-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003360 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003364 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003366 | 2021-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003384 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003391 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003393 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003409 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003410 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003420 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003423 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003425 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003426 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003433 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003436 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003438 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003439 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003442 | 2021-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003451 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003453 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003455 | 2020-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003459 | 2023-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003463 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003465 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003466 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003476 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003480 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003486 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003497 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003500 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003501 | 2020-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003503 | 2022-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003506 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003510 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003518 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003528 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003529 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003540 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003543 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003565 | 2021-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003569 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003576 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003579 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003584 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003602 | 2021-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003610 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003614 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003618 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003619 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003620 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003626 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003628 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003630 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003631 | 2020-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003632 | 2021-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003637 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003638 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003640 | 2022-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003641 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003646 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003648 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003651 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003656 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003663 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003666 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003669 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003671 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003673 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003675 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003683 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003685 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003688 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003694 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003701 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003709 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003726 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003735 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003742 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003743 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003746 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003756 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003758 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003759 | 2023-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003763 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003767 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003770 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003775 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003779 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003781 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003784 | 2021-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003785 | 2021-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003791 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003795 | 2020-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003800 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003802 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003804 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003806 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003807 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003814 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003832 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003837 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003839 | 2021-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003847 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003849 | 2020-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003857 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003861 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003867 | 2023-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003868 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003879 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003888 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003890 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003891 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003892 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003905 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003906 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003917 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003919 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003929 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003932 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003938 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003940 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003945 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003967 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003969 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003976 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003981 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003983 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-003985 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-003992 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004000 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004001 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004003 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004009 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004011 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004012 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004018 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004029 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004036 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004053 | 2021-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004058 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004061 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004064 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004070 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004074 | 2021-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004076 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004081 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004084 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004085 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004086 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004106 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004107 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004109 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004114 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004122 | 2020-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004123 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004126 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004127 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004131 | 2022-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004142 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004145 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004152 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004154 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004164 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004165 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004168 | 2020-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004175 | 2020-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004176 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004177 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004183 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004184 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004186 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004190 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004200 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004205 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004223 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004224 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004226 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004231 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004241 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004242 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004263 | 2020-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004277 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004281 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004286 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004287 | 2021-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004288 | 2023-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004299 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004301 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004307 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004330 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004336 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004346 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004355 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004356 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004357 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004360 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004370 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004376 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004377 | 2020-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004379 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004380 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004417 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004419 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004429 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004432 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004434 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004447 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004451 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004459 | 2022-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004488 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004501 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004502 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004510 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004521 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004522 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004525 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004529 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004537 | 2020-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004540 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004544 | 2021-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004548 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004552 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004556 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004563 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004565 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004568 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004570 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004577 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004578 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004600 | 2020-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004602 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004606 | 2020-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004607 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004608 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004609 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004623 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004626 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004631 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004640 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004643 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004651 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004653 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004654 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004658 | 2020-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004660 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004665 | 2021-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004667 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004672 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004673 | 2021-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004674 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004681 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004684 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004687 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004705 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004717 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004721 | 2021-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004729 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004750 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004759 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004760 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004764 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004765 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004766 | 2022-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004767 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004772 | 2021-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004785 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004789 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004796 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004801 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004802 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004803 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004810 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004820 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004822 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004824 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004835 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004839 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004842 | 2021-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004844 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004845 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004859 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004869 | 2021-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004870 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004872 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004877 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004883 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004902 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004909 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004911 | 2023-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004925 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004928 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004930 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004932 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004934 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004937 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004938 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004944 | 2020-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004946 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004951 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004953 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004954 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004961 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004965 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004968 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004972 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004979 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-004981 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004994 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-004999 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005000 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005004 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005007 | 2021-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005011 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005021 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005025 | 2021-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005026 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005029 | 2021-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005031 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005033 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005034 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005043 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005046 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005047 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005053 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005057 | 2021-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005059 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005070 | 2022-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005077 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005081 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005088 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005096 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005097 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005099 | 2022-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005101 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005105 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005113 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005115 | 2023-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005121 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005136 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005138 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005142 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005147 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005151 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005155 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005161 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005176 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005184 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005189 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005211 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005214 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005216 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005218 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005219 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005220 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005223 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005228 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005230 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005231 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005240 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005241 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005268 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005273 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005281 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005284 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005290 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005303 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005304 | 2022-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005305 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005310 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005319 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005325 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005329 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005342 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005345 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005353 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005354 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005356 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005357 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005373 | 2022-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005375 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005385 | 2020-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005391 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005392 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005398 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005406 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005407 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005412 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005418 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005422 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005423 | 2021-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005425 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005433 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005437 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005457 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005459 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005471 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005475 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005482 | 2022-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005488 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005490 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005500 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005502 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005505 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005507 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005509 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005515 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005522 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005523 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005527 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005528 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005536 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005538 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005540 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005541 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005543 | 2022-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005544 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005546 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005550 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005551 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005559 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005563 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005570 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005586 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005592 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005597 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005609 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005614 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005618 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005630 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005635 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005646 | 2020-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005665 | 2021-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005666 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005670 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005673 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005683 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005687 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005688 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005691 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005696 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005703 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005705 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005722 | 2021-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005730 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005756 | 2023-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005759 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005760 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005765 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005776 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005779 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005780 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005783 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005786 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005796 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005801 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005811 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005821 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005825 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005832 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005834 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005839 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005843 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005847 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005859 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005865 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005872 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005873 | 2021-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005882 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005884 | 2021-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005896 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005900 | 2022-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005909 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005911 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005913 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005921 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005923 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005924 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005933 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005939 | 2021-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005940 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005945 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005946 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005947 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005961 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005962 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005963 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005964 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005968 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005975 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005976 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-005978 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005983 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005990 | 2022-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-005998 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006002 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006010 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006014 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006015 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006016 | 2021-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006018 | 2022-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006029 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006030 | 2020-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006032 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006042 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006045 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006046 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006047 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006052 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006060 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006061 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006065 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006071 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006075 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006093 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006095 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006100 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006102 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006104 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006109 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006115 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006129 | 2023-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006138 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006143 | 2023-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006148 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006150 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006176 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006186 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006191 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006205 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006210 | 2020-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006211 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006218 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006221 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006228 | 2023-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006238 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006245 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006253 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006256 | 2021-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006258 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006260 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006266 | 2022-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006272 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006274 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006277 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006281 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006287 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006297 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006316 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006329 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006332 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006335 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006337 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006341 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006342 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006349 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006350 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006356 | 2021-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006372 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006383 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006388 | 2021-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006393 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006395 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006398 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006399 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006402 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006407 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006411 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006412 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006420 | 2021-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006432 | 2021-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006437 | 2022-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006445 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006449 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006452 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006463 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006465 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006466 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006476 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006479 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006480 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006483 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006493 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006502 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006520 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006525 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006527 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006539 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006548 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006558 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006560 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006562 | 2020-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006564 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006574 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006576 | 2020-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006580 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006586 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006588 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006596 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006603 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006605 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006607 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006613 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006617 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006619 | 2020-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006630 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006631 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006636 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006638 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006641 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006644 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006653 | 2021-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006656 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006658 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006666 | 2021-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006681 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006687 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006691 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006697 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006700 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006702 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006705 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006711 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006723 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006727 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006732 | 2020-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006739 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006741 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006746 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006764 | 2021-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006770 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006776 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006778 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006781 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006785 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006786 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006812 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006832 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006835 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006839 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006848 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006849 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006851 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006852 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006863 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006865 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006866 | 2021-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006867 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006873 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006879 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006880 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006881 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006884 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006894 | 2023-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006900 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006907 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006909 | 2023-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006921 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006938 | 2021-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006944 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006947 | 2021-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006949 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006954 | 2021-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006960 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006965 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006969 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006970 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006972 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006974 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006975 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-006976 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006991 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006992 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006993 | 2024-02-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006994 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-006997 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007002 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007003 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007010 | 2021-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007011 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007012 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007014 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007018 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007022 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007024 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007025 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007035 | 2022-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007038 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007040 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007041 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007046 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007049 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007051 | 2024-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007073 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007075 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007083 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007088 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007089 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007097 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007098 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007114 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007130 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007133 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007137 | 2023-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007139 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007143 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007146 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007152 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007154 | 2021-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007162 | 2024-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007164 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007168 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007182 | 2021-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007186 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007195 | 2020-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007203 | 2023-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007205 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007206 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007216 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007218 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007223 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007224 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007228 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007240 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007245 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007248 | 2020-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007253 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007258 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007260 | 2021-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007265 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007270 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007275 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007290 | 2021-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007294 | 2020-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007307 | 2022-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007315 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007322 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007328 | 2024-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007335 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007337 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007338 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007353 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007360 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007365 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007367 | 2022-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007370 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007378 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007379 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007398 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007399 | 2024-03-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007402 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007403 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007410 | 2022-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007414 | 2020-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007422 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007428 | 2022-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007430 | 2023-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007440 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007442 | 2022-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007443 | 2023-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007454 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007478 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007479 | 2024-04-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007481 | 2025-04-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007489 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007491 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007495 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007505 | 2025-02-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007511 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007513 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007519 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007522 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007528 | 2021-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007532 | 2023-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007552 | 2025-01-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007554 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007566 | 2020-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007572 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007580 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007590 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007591 | 2023-08-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007602 | 2025-06-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007611 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007615 | 2022-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007617 | 2022-05-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007618 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007621 | 2024-06-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007623 | 2025-03-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007624 | 2021-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007628 | 2023-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007631 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007637 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007651 | 2024-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007653 | 2021-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007654 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007655 | 2024-12-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007658 | 2023-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007668 | 2024-11-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007675 | 2024-09-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007682 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007683 | 2022-01-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007686 | 2025-05-01 | Escalate to CS for workflow-chain diagnostic outreach | pending |
| ingestion_without_completion | ACC-007688 | 2023-07-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007690 | 2021-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| ingestion_without_completion | ACC-007696 | 2024-10-01 | Escalate to CS for workflow-chain diagnostic outreach | unresolved |
| poc_pass_rate_below_threshold | ACC-000108 | 2025-06-27 | Escalate to Sales Engineering leadership for POC process review | pending |
| post_close_underutilization | ACC-000106 | 2020-08-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000080 | 2020-10-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000020 | 2020-12-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000033 | 2021-01-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000073 | 2020-11-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000010 | 2021-01-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000017 | 2021-04-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000100 | 2021-04-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000111 | 2021-04-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000099 | 2021-04-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000022 | 2021-07-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000001 | 2021-07-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000067 | 2021-10-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000009 | 2021-10-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000039 | 2022-03-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000011 | 2022-03-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000042 | 2022-06-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000038 | 2022-07-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000078 | 2022-07-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000041 | 2022-09-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000105 | 2022-08-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000058 | 2022-10-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000055 | 2023-03-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000079 | 2023-03-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000012 | 2023-04-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000019 | 2023-03-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000107 | 2023-04-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000061 | 2023-06-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000057 | 2023-05-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000031 | 2023-09-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000096 | 2023-09-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000030 | 2023-10-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000092 | 2023-11-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000062 | 2023-09-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000083 | 2023-12-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000051 | 2023-12-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000040 | 2023-12-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000077 | 2023-11-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000095 | 2024-02-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000005 | 2023-12-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000089 | 2024-03-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000008 | 2024-04-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000094 | 2024-02-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000050 | 2024-04-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000088 | 2024-02-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000090 | 2024-05-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000003 | 2024-02-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000025 | 2024-05-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000023 | 2024-05-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000048 | 2024-05-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000064 | 2024-06-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000059 | 2024-05-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000081 | 2024-05-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000021 | 2024-06-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000000 | 2024-04-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000037 | 2024-06-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000035 | 2024-05-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000066 | 2024-08-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000074 | 2024-05-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000101 | 2024-05-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000015 | 2024-06-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000104 | 2024-06-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000069 | 2024-07-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000085 | 2024-09-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000026 | 2024-08-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000024 | 2024-08-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000007 | 2024-09-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000091 | 2024-10-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000047 | 2024-11-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000109 | 2024-10-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000029 | 2024-11-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000110 | 2024-10-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000027 | 2024-12-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000065 | 2024-12-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000082 | 2024-12-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000013 | 2025-02-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000018 | 2024-12-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000006 | 2025-01-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000032 | 2025-02-01 | Trigger AM proactive onboarding check-in | resolved |
| post_close_underutilization | ACC-000076 | 2025-04-01 | Trigger AM proactive onboarding check-in | pending |
| post_close_underutilization | ACC-000063 | 2025-05-01 | Trigger AM proactive onboarding check-in | pending |
| post_close_underutilization | ACC-000086 | 2025-05-01 | Trigger AM proactive onboarding check-in | pending |
| post_close_underutilization | ACC-000075 | 2025-05-01 | Trigger AM proactive onboarding check-in | pending |
| post_close_underutilization | ACC-000045 | 2025-05-01 | Trigger AM proactive onboarding check-in | pending |

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
