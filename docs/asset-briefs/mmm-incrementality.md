---
source: analytics/mmm_incrementality.py
---

# Marketing Spend Incrementality Model

## What this is

A model that tries to answer a hard but important question for every marketing dollar spent: how much of a channel's results come from the marketing itself, versus the company simply growing anyway? It's built for marketing and revenue leadership deciding how to size and split channel budget, and it exists specifically to reach the one channel — organic content — that the company's existing, more trustworthy measurement approach structurally cannot reach.

## Why it exists

The existing marketing attribution and channel-mix analysis already answers this question with real confidence for two of the three marketing channels, paid and community, because those two have a genuine held-back comparison group: marketing was deliberately withheld from a portion of prospects for a period of time, and what happened to them was compared against everyone else. Organic content has no such comparison group — there is no practical way to switch organic search or content off for a chosen slice of prospects — so it has never had an incrementality read of any kind. This model exists to close that gap, extending a rough estimate to the one channel that would otherwise have none, using the same channel-grain spend and conversion numbers the existing attribution analysis already computes.

## How it works

The model looks at three years of monthly data for each channel — how much was spent and how many customers converted — and fits a curve describing how conversions respond as spend goes up or down, with smaller and smaller gains for each additional dollar as spend rises. Critically, the model also has to separately account for the fact that the company has simply been growing on its own over that same three-year window, largely independent of marketing spend. Without controlling for that underlying growth, the model would credit marketing for a great deal of growth it didn't actually cause. The resulting curve is then used to answer the same question the real controlled test answers for paid and community: how many fewer customers would have converted if spend had been cut down to the same low level the real test held its comparison group at.

## Key decisions and why

- **The model uses a single, simple diminishing-returns curve rather than a more elaborate model that would also try to capture marketing dollars continuing to work for a period after they're spent, and a sharper bend in the response curve at very high spend.** Both of those extra features are reasonable additions to this kind of model in general, but three years of monthly data per channel is not enough information to reliably tell those effects apart from ordinary month-to-month noise. Adding them here would likely produce an unstable, close-to-arbitrary split of credit rather than a more accurate one — the simpler curve is the more honest tool at this amount of data.
- **The model always accounts for the company's own underlying growth trend over the same period, in every version of the model it runs.** Leaving that out inflates marketing's apparent effect by a wide margin — a real, checkable finding in its own right, described in Current result below — so controlling for it is treated as mandatory, not optional.
- **The channel breakdown used — organic content, paid, and community/events — isn't a choice this model makes.** It's the same breakdown the company's own growth measurement already defines marketing's contribution as, and the same one the existing attribution analysis works with; this model operates inside that existing structure rather than inventing its own channel categories, and it uses this specific breakdown (rather than one blended "marketing" number) because it's the only one with a real controlled test to check the model against for two of the three channels.
- **The model is fit on the number of customers converting each month, not directly on the dollar value of deals booked each month; dollar figures are produced afterward by applying each channel's own typical deal size.** A given month's booked revenue is dominated by the size of a handful of large deals that happen to close that month, which has little to do with that month's marketing spend, while the number of new customers converting tracks spend far more directly. Fitting the model on booked revenue directly would mostly be fitting deal-size noise, not marketing's actual effect.
- **When comparing this model's answer to the real controlled test, the comparison point used is a steep but not total spend cut — matching the exact reduced-spend level the real test's comparison group actually received — rather than a cut all the way down to zero spend.** A curve fit on real spending levels has no honest basis to answer what happens at zero; using the same comparison level the real test uses keeps the two answers on the same question, and the comparison fair and meaningful.
- **The channel-level spend and conversion numbers this model runs on are reused directly from the existing attribution analysis rather than recalculated from raw records.** That analysis already computes and checks these numbers; building a second, independent calculation of the same underlying facts would risk two different answers with no way to know which one to trust.

## What drives the result

- **Monthly marketing spend by channel** — organic content, paid advertising, and community/events — over the three full years of data available (January 2023 through December 2025)
- **Monthly customer conversions attributed to each channel** over that same window, counted the same way the existing attribution analysis splits credit across a customer's full path of marketing touches
- **The company's own overall growth trend over the same window**, controlled for in every version of the model so it isn't mistaken for marketing's effect
- **The real controlled test's comparison spend level** (the same steep, deliberate cut the actual held-back test group received) as the basis for the "what would happen at reduced spend" comparison

## Current result

As of December 2025 (three full years of monthly data, January 2023 through December 2025):

The single most solid, checkable finding from this model isn't a channel-by-channel number — it's a caution. A naive read of the data, simply comparing spend and conversions over time without accounting for the company's own growth, would suggest marketing spend drove roughly 73% of the increase in conversions. Once the company's real underlying growth is properly controlled for, that estimate drops to roughly 22%. That's a large, real difference, and it's a useful warning against a common measurement mistake: crediting marketing for growth the business would have had anyway.

Beyond that caution, the honest answer is that this model cannot yet say with real confidence how much of any channel's results its spend is truly driving. At three years of monthly data, none of the three channels' estimated marketing effects clear the bar leadership teams normally use to call a result "statistically real" rather than a pattern that could plausibly be noise.

For the two channels that already have a real controlled test — paid and community — this model's own estimate comes in noticeably lower than what that real test measured directly: it understates paid's true incremental effect by roughly 25 percentage points, and community's by roughly 46 points. Where a real, measured answer already exists, it should be trusted over this model's estimate for those two channels. The most likely reason for the gap is that the growth trend this model has to control for is close enough to marketing spend's own pattern over time that some of spend's real effect likely gets absorbed into the growth control instead of credited to spend.

For organic content — the one channel with no real controlled test available at all — this model provides the only incrementality read that exists in this data. It suggests organic marketing plausibly has a real, worthwhile effect, but the range of plausible answers is wide enough to include almost no measurable effect as well as a substantial one. This is genuinely the model's single most useful contribution, and simultaneously its least certain number.

A repeat of this analysis using six fewer months of data produced a meaningfully different answer for the community channel specifically — not a confirmation of the same pattern on a smaller sample, but a different one. That's a sign the current channel-level estimates are still sensitive to exactly how much history is available, rather than settled.

## Known limitations

- **This model does not yet have enough months of history to give a statistically confident, channel-by-channel answer.** Two of the three channels' modeled marketing effects fail even a deliberately loose bar for "more than noise," and all three fail that same bar when the model is re-run on six fewer months of data — expected, given how thin three years of monthly data is for this kind of estimation.
- **This model cannot fully separate "the marketing caused it" from "the business was growing anyway" in this data.** The two move together closely enough that some of marketing's real effect likely gets folded into the growth control instead of credited to spend — the most probable explanation for why this model's estimates run below what the real controlled test measured for paid and community.
- **Organic's estimate has no outside check available in this data, and never will**, since there's no practical way to run a real controlled test on organic content the way there is on a paid budget or a community program. It should be read as a directionally useful but genuinely uncertain number, not a confident figure to plan a budget around.
- **The model doesn't yet capture marketing dollars continuing to work for a period after they're spent, or returns bending more sharply once spend gets very high in a channel** — both reasonable features of this kind of model in general, but not something the available three years of data can support estimating reliably. Adding them now would likely make the answer less stable, not more accurate.
- **The practical takeaway: these channel-level numbers are not yet solid enough to drive a real budget reallocation decision on their own.** This model needs more months of history to accumulate before its estimates should carry real planning weight. Until then, for the two channels where a real controlled test exists and disagrees with this model — paid and community — that real test should be the one relied on, not this model's estimate.

## Technical validation

The following reproduces the model's full statistical record for a reader who wants to verify these claims directly.

**Per-channel elasticity models — primary read, at `as_of_date` 2025-12-31 (n=36 months per channel)**

| Channel | n | R² | Elasticity (coefficient on log-spend) | SE | p | 95% CI | Trend coefficient | Nested F-test p |
|---|---|---|---|---|---|---|---|---|
| Organic | 36 | 0.585 | 0.4297 | 0.2387 | 0.0810 | [−0.056, 0.915] | 0.0168 | 0.0810 |
| Paid | 36 | 0.713 | 0.2206 | 0.1273 | 0.0924 | [−0.038, 0.480] | 0.0302 | 0.0924 |
| Community | 36 | 0.423 | 0.1923 | 0.2751 | 0.4894 | [−0.367, 0.752] | 0.0352 | 0.4894 |

At n=36 per channel, no channel's spend coefficient clears the conventional 5% significance level. Organic (p=0.081) and paid (p=0.092) are marginal at 10%; community's is not distinguishable from zero (p=0.489). Organic's 95% CI includes values near zero.

**Pooled robustness model** (secondary, common elasticity across all three channels, organic as reference level): n=108, R²=0.774, common elasticity 0.2246 (SE 0.1157, p=0.0550), vs. 0.7304 with no trend control. VIF on log-spend with the trend control included: 7.42.

**Residual diagnostics** (Breusch-Pagan heteroscedasticity test; lag-1 residual autocorrelation; Durbin-Watson): organic BP p=0.135, paid p=0.920, community p=0.151 — all homoscedastic at the 5% level. Lag-1 residual autocorrelation: organic −0.370, paid −0.272, community −0.302; Durbin-Watson 2.5–2.6 (mild negative autocorrelation, not the positive autocorrelation that would most concern a trending series). No HAC/Newey-West standard-error correction applied — at n=36 the correction itself would be poorly estimated.

**Out-of-sample validation**:
- LOOCV RMSE on conversions: organic 5.37 (25.8% of its own mean monthly conversions), paid 4.84 (26.4%), community 2.56 (37.1%). Full model beats a trend-only baseline for organic (+0.7% log-RMSE improvement) and paid (+1.7%) but not community (−0.6%).
- Forward holdout (Oct–Dec 2025 withheld, trained on the other 33 months): RMSE on conversions — organic 5.96, paid 5.26, community 4.23. Rests on 3 points per channel.
- Both back-transformed from log-scale predictions via Duan's smearing estimator.

**Cross-validation against the holdout read** (`compare_to_holdout()`, counterfactual = the holdout's own suppressed-spend level, 10% of normal budget, not spend = 0):

| Channel | MMM-implied incremental share | 95% CI | Holdout-measured incremental share (SE) | Gap (MMM − holdout) | Holdout within MMM's CI? |
|---|---|---|---|---|---|
| Paid | 0.398 | [−0.092, 0.669] | 0.648 (0.101) | −0.249 | Yes |
| Community | 0.358 | [−1.330, 0.823] | 0.816 (0.185) | −0.458 | Yes |
| Organic | 0.628 | [−0.137, 0.879] | not estimable | not applicable | — |

Incremental bookings translation (window totals at 2025-12-31): organic $3.33M implied incremental bookings, paid $2.92M, community $1.65M.

**Checkpoint instability** — 2025-06-30 (n=30 monthly obs/channel, n=90 pooled) vs. 2025-12-31:

| Channel | Elasticity 2025-12-31 | Elasticity 2025-06-30 | MMM-implied share 2025-12-31 | MMM-implied share 2025-06-30 | Holdout share (unchanged) | Gap 2025-12-31 | Gap 2025-06-30 |
|---|---|---|---|---|---|---|---|
| Organic | 0.430 | 0.402 | 0.628 | 0.604 | not estimable | — | — |
| Paid | 0.221 | 0.224 | 0.398 | 0.404 | 0.648 | −0.249 | −0.226 |
| Community | 0.192 | 0.915 | 0.358 | 0.878 | 0.816 | −0.458 | +0.063 |

Pooled VIF on log-spend rises from 7.42 (2025-12-31) to 13.24 (2025-06-30) with six fewer months of history. Zero of three channels clear the nested F-test's p<0.10 floor at the 2025-06-30 checkpoint (organic p=0.153, paid p=0.250, community p=0.261), against two of three at 2025-12-31.

**Build-time validation checks** (`spend_adds_value_{channel}`: nested F-test p<0.10 AND LOOCV beats trend-only baseline, both required):

| Check | Result (2025-12-31) | Result (2025-06-30) |
|---|---|---|
| spend_adds_value_organic | Pass — F p=0.0810, LOOCV +0.7% | Fail — F p=0.1533, LOOCV −0.8% |
| spend_adds_value_paid | Pass — F p=0.0924, LOOCV +1.7% | Fail — F p=0.2499, LOOCV −0.4% |
| spend_adds_value_community | Fail — F p=0.4894, LOOCV −0.6% | Fail — F p=0.2610, LOOCV +0.5% |

2 of 3 checks pass at 2025-12-31; 0 of 3 pass at 2025-06-30.

**Sample sizes**: 36 monthly observations per channel / 108 pooled at 2025-12-31 (30 / 90 at 2025-06-30); LOOCV uses 35 training points per fold (29 at 2025-06-30); the forward holdout uses 33 training months / 3 test months (27/3 at 2025-06-30).
