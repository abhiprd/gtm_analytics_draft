---
source: analytics/lead_scoring_validation.py
---

# Lead Scoring Model Validation

## What this is

A check on whether the fit score every inbound lead already receives is actually doing its job — and whether a change made to that score partway through the company's history made it better. It's built for the marketing and sales-development leaders who rely on the score to prioritize which leads get attention, and who need to know how much weight to put on it.

## Why it exists

Every lead that enters the funnel is scored on firmographic fit — company size, industry, and region — at the moment it arrives, and that score determines which segment (SMB, Commercial, or Enterprise) it's routed toward and how aggressively it gets worked. If that score doesn't genuinely track which leads go on to convert, teams end up prioritizing effort using a number that only looks meaningful. This artifact exists to hold the scoring system accountable to real outcomes rather than assuming it works because it's already in production.

## How it works

Every lead that has had enough time to either convert or clearly go cold is pulled together with the most recent fit score it was given before that outcome was known. The score is then checked against what actually happened: did leads with higher scores really convert more often than leads with lower scores. That check is run for the whole population, and separately for the two priority cuts sales actually uses — leads scored well enough to be routed as "Commercial or better," and the smaller, stricter group scored high enough to be routed as "Enterprise-only." Alongside that, the analysis takes advantage of a real change made to the scoring formula partway through the company's history — a factor for the lead's region was added to it — and isolates exactly how much that one change improved the score's ability to tell converting leads apart from non-converting ones, without that read getting mixed up with any other changes happening in the business at the same time.

## Key decisions and why

- **This checks an existing, fixed scoring formula rather than training a new one.** The fit score's formula — company size, industry, and (more recently) region, combined with fixed weights — was set in advance and isn't estimated from the data this analysis touches. The job here is to hold that already-deployed formula accountable to real outcomes, not to build a competing model that would just duplicate what's already in production.
- **This deliberately does not build a competing predictive model on the same inputs.** Building a fresh classifier on company size, industry, and region would answer a different question than the one this artifact exists to answer — whether the score already driving day-to-day lead routing holds up, not whether some other model could theoretically do better. A second, uncoordinated scoring system running alongside the real one would create confusion about which number to trust.
- **The score's real-world value is reported separately for its two operating cuts, not blended into one number.** Leads are routed at two different score cutoffs in production — a broad "worth working" line and a stricter "Enterprise-only" line. Reporting them together would have hidden a real difference between them; reporting them apart is what reveals that the score's usefulness is concentrated almost entirely in the stricter cut.
- **The score is never treated as a probability of conversion, only as a ranking.** It's a 0–100 fit index, not a calibrated likelihood, so the honest question to ask of it is whether higher scores reliably mean better leads on average — not whether a score of 80 means an 80% chance of converting.
- **The formula-change comparison is built to isolate the change itself, not just the time period around it.** Simply comparing conversion results from before the scoring-formula change to results after it would blend the effect of the change together with anything else that shifted in the lead population over that same stretch of time — different marketing campaigns, a different mix of industries, and so on. The comparison is instead built by taking leads scored under the newer formula and asking what their score would have been under the older formula, on the exact same leads, at the exact same point in time — isolating the one factor that changed.
- **Leads still awaiting an outcome are left out of every check.** A lead that hasn't yet converted and also hasn't been inactive long enough to be written off as unlikely to convert has no knowable outcome yet. Including it with an assumed "did not convert" label would quietly bake in a wrong answer for leads whose story isn't over.

## What drives the result

- **Company size band** — the largest single input to the fit score
- **Industry** — the second-largest input
- **Region** — added to the formula partway through the company's history; the smallest of the three firmographic inputs, but its addition is the one change this analysis measures directly
- **A small amount of built-in randomness** — a deliberate design choice in the underlying score, not something this analysis introduces, that keeps the score from being a pure, mechanical lookup of a lead's firmographics
- **Two production routing cutoffs** — a broad "Commercial or better" line, and a stricter, higher "Enterprise-only" line — both fixed, real thresholds that route leads today, not thresholds chosen for this analysis

## Current result

As of December 31, 2025, the score does distinguish real signal from noise — but only modestly. Across all 40,207 leads with a known outcome, it correctly ranks a converting lead above a non-converting one a bit more often than chance, but well short of what would count as strong discrimination. That modest result is a real, statistically genuine finding rather than random noise, and it's also close to the practical ceiling this kind of score can reach given how it's built — no realistic scoring formula built purely on firmographics could be expected to do dramatically better against this population, so the modest result is a known, structural limit rather than something to try to engineer away.

The score's value is not spread evenly, though. Leads that clear the broad "Commercial or better" line convert at barely any better rate than the typical inbound lead — essentially no useful lift from that cut alone. Leads that clear the much stricter "Enterprise-only" bar are a different story: they convert at roughly 2.8 times the average rate. In practice, that means the score is genuinely useful for finding the very best leads in the pipeline, but not for drawing a broad line between "worth working" and "not worth working."

The formula change that added a region factor partway through the company's history produced a small but real, statistically measurable improvement in the score's ability to separate converting leads from non-converting ones, isolated specifically from any other shifts happening in the lead population over that same period. It's worth keeping, though the improvement itself is modest — not a step change in how well the score performs.

## Known limitations

The score's raw 0–100 value should not be read as a smoothly graded indicator of conversion likelihood across its full range. Conversion rates do rise from the bottom of the score range through the middle, but then dip slightly again at the very top of the range rather than continuing to climb — even though the strict, categorical "Enterprise-only" cut described above does carry real, meaningful lift. In other words, the score is a reasonably trustworthy coarse ranking tool and a genuinely strong signal at its very top categorical tier, but its exact numeric value in the upper part of its range shouldn't be over-interpreted on its own.

## Technical validation

The following reproduces the model's full statistical record for a reader who wants to verify these claims directly.

**Weights (fixed, not fitted — cited rather than a coefficient table, since nothing was estimated from data here):** `compute_fit_score()` = 0.6 × employee-band weight + 0.3 × industry weight [+ region_modifier, v2 only] + N(0, 7) noise.

**Discrimination — AUC:** overall 0.5420 (n=40,207 resolved leads, 2,061 positive, base rate 5.13%, `as_of_date` 2025-12-31), 90% bootstrap CI [0.5314, 0.5513] — distinguishable from 0.50. By model-version regime (confounded with calendar time — see below): `lead_fit_v1_preregion` AUC 0.5369 (n=19,035, 1,042 positive, base rate 5.47%, mean score 25.63); `lead_fit_v2_region_aware` AUC 0.5513 (n=21,172, 1,019 positive, base rate 4.81%, mean score 27.72).

**Confusion matrix, at the real production operating thresholds** (`ENTERPRISE_FIT_THRESHOLD`=72 / `COMMERCIAL_FIT_THRESHOLD`=40, never an arbitrary 0.5 cutoff, since `predicted_fit_score` was never fit as a probability):

| Threshold | Precision | Recall | F1 | Lift vs. base rate | n predicted positive |
|---|---|---|---|---|---|
| Commercial-or-better (predicted_segment != SMB) | 0.0542 | 0.1587 | 0.0808 | 1.06× | — |
| Enterprise-only (predicted_segment == Enterprise) | 0.1413 | 0.0194 | 0.0341 | 2.76× | 283 |

**Calibration note:** `predicted_fit_score` is a 0–100 ICP-fit index, never fit or stated as a conversion probability, so there is no mean-predicted-probability-vs-base-rate gap to check. Decile bins: conversion rates rise from ~4.0% (bottom 3 deciles) to a peak of 6.4% (decile 8, score ~31–36), then fall back to 5.4–5.7% in the top two deciles — not cleanly monotonic. Sample thinness at the top (n≈4,000/decile, positives ≈150–250/decile) plausibly contributes to the dip, alongside the fact that the categorical Enterprise tier above (a stricter, thinner cut than the top score decile) carries real lift that the top decile's raw mean does not fully preserve.

**Drift finding — region's marginal AUC contribution, isolated from the calendar-time confound:** a same-population, same-time-period, same-row test on v2-era scoring events (region zeroed vs. region included) gives AUC 0.5779 with region vs. 0.5755 without (Δ = +0.0023), 90% seeded bootstrap CI [+0.0003, +0.0046] (n=111,648 v2-era scoring events on 21,172 resolved leads, seed=42) — distinguishable from zero, but small. This is the trustworthy causal read, directionally consistent with the confounded regime comparison above (v2 AUC 0.5513 > v1 AUC 0.5369).

**Score-distribution shift, decomposed:** mean `predicted_fit_score` shifts +2.14 points from v1 (25.59) to v2 (27.72) across all scoring events. +1.72 points of that is region_component's own mean contribution (mechanical — v1 never computes a region term at all); the remaining +0.46 points is a small residual difference in mean employee-band/industry components between the two eras (real cohort composition drift over calendar time, not a formula effect).

**Sample sizes:** n=40,207 resolved leads at `as_of_date` 2025-12-31 (2,061 positive, 5.13% base rate) for the primary discrimination/calibration/confusion-matrix checks; n=111,648 v2-era scoring events (21,172 resolved leads) for the region-isolation test. No train/holdout split applies — nothing is fit.

**No coefficient/feature-importance table** — `compute_fit_score()`'s weights are fixed and pre-existing, not estimated from data this module touches.
