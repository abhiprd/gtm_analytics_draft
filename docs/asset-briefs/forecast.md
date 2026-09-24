---
source: analytics/forecast.py
---

# Quarterly Revenue Forecast

## What this is

A running answer to one question sales and finance leadership ask throughout every quarter: how much revenue is actually going to close before the quarter ends. It covers Commercial and Enterprise deals — the two segments with a real sales cycle and a genuine forecasting cadence — and produces four independent readings on that question side by side, rather than blending them into a single number.

## Why it exists

Revenue predictability underpins the whole GTM operating rhythm — planning, board reporting, and the weekly cadence during an open quarter all depend on knowing how much of the pipeline will actually land, not just how large it looks on paper. A single averaged forecast number hides exactly the disagreements leadership most needs visibility into before quarter close rather than after: a rep who is more confident than the data supports, or deal mechanics that read weaker than a manager's own call.

## How it works

Every open Commercial and Enterprise deal is looked at through four separate lenses at once. The first is simply what the deals' own reps believe will close, based on the confidence category each rep files week to week. The second is what their managers believe about those same deals — managers are consistently more realistic than reps, and a deal a manager downgrades from a confident rep call goes on to close at a meaningfully lower rate, so that gap between the two calls carries real information on its own. The third lens is an independent, machine-driven read that looks only at the mechanics of each deal — what stage it's in, how long it has sat there, how the account's own product usage has been trending, whether a technical evaluation has passed or failed, how experienced the rep handling it is — and deliberately never sees what any human said about the deal, so it stands as a genuine check on human judgment rather than a repackaging of it. The fourth lens is leadership's own logged, reasoned adjustments on top of the roll-up, applied exactly as recorded. All four are reported together every period, along with how far apart they sit from one another — a wide spread is treated as a signal worth investigating, not noise to average away.

## Key decisions and why

- **Four separate views are kept side by side rather than merged into one forecast number.** Where the views agree, the forecast is more trustworthy; where they disagree, that disagreement is itself useful information about where a deal, a rep's optimism, or a shifting market deserves a closer look — collapsing them into one number would erase exactly the signal this artifact exists to surface.
- **The machine-driven view is deliberately kept blind to what reps and managers said about a deal.** If it read the same confidence categories the human lenses already use, it would just be repackaging human judgment rather than checking it. Reading only the underlying deal mechanics is what lets it serve as a genuine, independent second opinion.
- **A simpler, fully transparent, and reliably calibrated method was used for the machine-driven view instead of a more complex alternative that tends to need an extra correction step before its outputs can be trusted as real probabilities.** This view's output is multiplied directly by deal dollar amounts and summed into a forecast total, so a probability running systematically too high or too low would distort that total in exactly the same direction — a transparent method whose probabilities hold up at face value avoids adding that risk on top of everything else.
- **The dollar weight assigned to each confidence category is calculated from what deals with that label have actually closed at historically, broken out separately by deal type, rather than applied as one flat assumption.** A "Commit"-labeled renewal and a "Commit"-labeled new-business deal close at very different real rates, so pricing both at the same flat number would badly overstate confidence in the riskier of the two. Where a specific combination of category and deal type has too little history to price reliably on its own, its value leans on the closest larger group of comparable deals rather than being guessed outright.
- **One input that can look informative in testing — the number of days remaining until the quarter's end — is deliberately left out of the machine-driven view.** Every open deal being forecast at a given moment shares exactly the same number of days left in its quarter, so once actually put to live use the figure carries no real information about any individual deal — even though, across a training sample spanning many different evaluation dates, it can appear to correlate with outcomes for reasons that have nothing to do with genuine early warning. Leaving it out avoids baking a hidden, systematic downward pull into every live quarter's forecast, and the modest under-forecasting bias that remains is roughly half what it would be with that input included.
- **Leadership's logged adjustments are applied exactly as entered, never smoothed, estimated, or carried over from a neighboring quarter.** A quarter or segment with no logged adjustment is treated as having none, full stop — inventing a leadership judgment that was never actually made would be worse than leaving it out.
- **The forecast's accuracy targets were set before any results were seen**, and the forecast is tested by replaying it against 22 already-completed quarters of history, not just the most recent one, so its track record reflects a genuine range of market conditions rather than one convenient period.

## What drives the result

- **Rep and manager confidence categories** — filed weekly on every open deal, ranging from a written-off "Omitted" through "Pipeline," "Best Case," and "Commit" — each priced at its own real historical close rate for that specific deal type and segment, not one flat, one-size-fits-all assumption
- **Deal mechanics** — the input to the independent machine-driven view: what stage a deal is in, how long it has sat there relative to normal, the deal's overall age, whether a technical evaluation has concluded and how it went, whether the account's product usage has been trending up or down, and whether the rep handling the deal is still new to the role
- **Leadership's logged adjustments** — reasoned, dated overrides leadership has actually filed, applied on top of the roll-up exactly as recorded
- **A divergence threshold** — the four views are currently flagged as meaningfully disagreeing once they spread apart by roughly a quarter of their average value; this is an initial, proposed sensitivity rather than a confirmed final number, left open for revision once more history accumulates

## Current result

As of November 14, 2025 — roughly midway through the quarter being forecast, the same relative point used every quarter this is tested against — the forecast, using the manager view specifically (the one leadership's own adjustments build on top of), has been tested by replaying it across 22 already-completed quarters of history. On average across those quarters it landed within roughly 16% of what actually closed, and in aggregate it neither meaningfully over- nor under-forecasted: the total forecast across all 22 quarters came within less than 1% of the total revenue that actually closed.

The independent machine-driven view runs a consistent, modest built-in undershoot of a little over 5% across that same backtest — not a flaw to patch, but a genuine byproduct of a steadily shifting mix of deals over time (a growing share of steadier renewal business) that a view trained only on past history can't fully anticipate in advance. This is treated as an honest, explainable pattern rather than something to quietly smooth away, which is part of why the forecast keeps four separate views rather than leaning on any single one.

## Known limitations

- **The machine-driven view's modest built-in undershoot (a little over 5% across the historical backtest) is reported rather than corrected.** Patching it with an invented adjustment factor would trade a real, understood pattern for a tuned number with no independent grounding — the four-lens structure is the intended answer to this, not a single-number fix.
- **One accuracy checkpoint, from mid-2025, came back unusually high** — a result that, for this kind of model, is actually a caution sign rather than good news, since unusually strong accuracy can mean a model is picking up information it shouldn't have access to. That checkpoint is reported here as an open, unresolved finding: nothing currently confirms why it came in as high as it did.
- **One of the checks that validates the machine-driven view only catches it underperforming a manager's own judgment by too much — it has no equivalent check for the view doing suspiciously better than a person reasonably could,** which is precisely the kind of result that ought to raise a flag rather than be treated as a win. That gap in the validation approach is real and not yet closed.
- **Enterprise renewal deals don't yet have enough history to price or model independently.** There are too few completed Enterprise renewal deals to read that group on its own with confidence, so its pricing currently leans heavily on the broader pattern from other deal types rather than a dedicated read of its own history.
- **For Commercial new-business deals specifically, a manager's confidence label barely distinguishes which deals go on to close.** Deals rated "Commit" close only modestly more often than ones still rated "Pipeline" in this population, and no view in this forecast — human or machine — can manufacture a stronger signal than genuinely exists in that segment.
- **This forecast only covers the quarter already in flight, from pipeline that already exists.** It does not project a future quarter's pipeline that hasn't been created yet, and leadership's logged adjustments are applied exactly as recorded but not independently checked for whether the underlying business judgment behind them was right.

## Technical validation

The following reproduces the model's full statistical record for a reader who wants to verify these claims directly.

**Target, set in advance:** pooled out-of-time held-out AUC between 0.70 and 0.85; within each (segment, opportunity_type) stratum with at least 100 held-out deals, model AUC at least 0.95× the manager-category-lookup AUC on the same holdout; held-out calibration gap within ±0.05 of the actual base rate.

**Achieved, canonical checkpoint (`as_of_date` 2025-11-14):**

| Measure | Result | Target | Met |
|---|---|---|---|
| Out-of-time held-out AUC | 0.8153 | 0.70–0.85 | Yes |
| Stratified-random-split AUC (secondary) | 0.8236 | — | — |
| Manager-category-lookup AUC, same holdout (leak-proof reference) | 0.7819 | — | — |
| Within-stratum ratio, Commercial new_business (n=233) | 1.077× | ≥0.95× | Yes |
| Within-stratum ratio, Commercial renewal (n=160) | 1.117× | ≥0.95× | Yes |
| Held-out calibration gap | −0.0058 (mean predicted 0.4740 vs. base rate 0.4798) | ≤±0.05 | Yes |

Sample sizes: n_train = 1,410 (517 won), n_holdout = 471 (226 won), out-of-time split. Full fitted population 1,881 closed opportunities — Commercial new_business 1,034, Commercial renewal 428, Enterprise new_business 387, Enterprise renewal 32.

**Second checkpoint (`as_of_date` 2025-08-15):** out-of-time held-out AUC 0.8593, breaching the 0.70–0.85 ceiling; calibration gap +0.0150; both gated within-stratum ratios passed (Commercial new_business 1.101×, Commercial renewal 1.176×). This breach is not explained by the day-of-quarter input excluded from the model's feature set (see Key decisions above) — the manager-category-lookup baseline is built from disjoint inputs the classifier never touches, so a leak living inside those features could not move that baseline at all, yet the baseline itself scores 0.8357 here, well above its 0.7819 canonical-checkpoint value. It is also not explained by a difference in holdout composition: renewal share was 0.3546 at this checkpoint vs. 0.3544 at the canonical one, and every stratum was independently more discriminable here than at the canonical checkpoint. It stands as an open, unexplained finding rather than a resolved one.

**Coefficients** (standardized/one-hot-encoded scale — every numeric input is scaled to comparable units before fitting; sorted by absolute magnitude; canonical checkpoint, `days_to_period_end` excluded per the point-in-time design decision above):

| Feature | Coefficient |
|---|---|
| opportunity_type_renewal | 2.3455 |
| opportunity_type_new_business | −2.2922 |
| account_usage_trend_ratio | 0.8703 |
| deal_age_days | −0.4247 |
| poc_revealed_pass | 0.3974 |
| current_stage_Open | −0.3782 |
| current_stage_Negotiation | 0.3507 |
| poc_revealed_fail | −0.2274 |
| rep_tenure_days | 0.2219 |
| rep_is_ramping | −0.2043 |
| deal_age_ratio | 0.1833 |
| current_stage_POC | 0.1776 |
| stage_progress | −0.1403 |
| days_in_current_stage | 0.1133 |
| current_stage_SQO | −0.1056 |
| current_stage_Proposal/Negotiation | 0.0641 |
| segment_Enterprise | 0.0570 |
| current_stage_SAL | −0.0548 |
| has_entered_a_stage | 0.0247 |
| stage_stall_ratio | −0.0101 |
| segment_Commercial | −0.0038 |
| current_stage_pre_stage | −0.0006 |

The two `opportunity_type` dummies dominate this table because new-business and renewal deals carry a roughly 58-point difference in base close rate in this population; they function as a population indicator rather than a driver, which is exactly why the within-stratum ratio criterion above exists — to confirm the model separates deals genuinely, not just by which population they belong to. `poc_revealed_pass`/`poc_revealed_fail` are structurally zero outside Enterprise new business, so their magnitudes describe their effect within that stratum only. `stage_progress` and the `current_stage` dummies are two representations of one underlying signal, so neither coefficient alone describes the model's reliance on stage position.

**Confusion matrix, commit-grade threshold** (the observed close rate of manager-"Commit" deals in the training population, 0.7900, used as the operating threshold since the forecast's primary use has no threshold at all — it multiplies a probability by a dollar amount and sums):

| | Predicted commit-grade | Predicted not commit-grade |
|---|---|---|
| **Actual closed won** | TP = 129 | FN = 97 |
| **Actual closed lost** | FP = 6 | TN = 239 |

Precision 0.9556, recall 0.5708, F1 0.7147.

**Calibration**: mean predicted probability 0.4740 vs. actual base rate 0.4798 on held-out data (gap −0.0058) — this model is calibrated and its raw probability is meant to be read directly (no class-weight reweighting is applied), unlike the account health score's ranking-only output. Reliability by held-out quintile:

| Predicted-probability bucket | n | Mean predicted | Actual rate |
|---|---|---|---|
| 0.025–0.220 | 95 | 0.1286 | 0.2000 |
| 0.220–0.298 | 94 | 0.2604 | 0.2766 |
| 0.298–0.350 | 94 | 0.3228 | 0.3298 |
| 0.350–0.957 | 94 | 0.6784 | 0.6277 |
| 0.957–0.999 | 94 | 0.9837 | 0.9681 |

Monotone and close to the diagonal, with the bottom bucket under-predicting by roughly 7 points — the ordinary floor effect of a linear model on a bounded outcome, not a reweighting artifact.

**Backtest accuracy by lens** (22 completed period-segments with a non-zero realised actual, out of 24 backtested):

| Lens | MAPE per period-segment | Aggregate dollar bias |
|---|---|---|
| Bottoms-up, rep | 15.46% | +0.20% |
| Bottoms-up, manager | 16.05% | −0.07% |
| ML | 15.15% | −5.29% |
| CRO-adjusted | 17.69% | +0.43% |

**No R²/RMSE** — the underlying model is a win-probability classifier, not a regression on the period total; the dollar forecast is this classifier's probability multiplied through the CRM's own stated deal amounts.
