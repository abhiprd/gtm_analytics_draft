---
source: analytics/deal_diagnostics.py
---

# Deal-Level Risk Diagnostics

## What this is

A live, per-deal early-warning system for every open Commercial and Enterprise new-business opportunity, built for sales leadership and managers who need to know which specific deals in the pipeline right now need attention — not next week's portfolio summary, but today's individual deal list. It flags concrete, nameable warning signs on each deal and, separately, gives every open deal a single risk-ranking number so the whole open pipeline can be triaged at a glance.

## Why it exists

Win rate is one of the three levers that determines how much new revenue actually lands, and win rate is won or lost deal by deal, in real time, not settled all at once when the quarter closes. The portfolio's other diagnostic tools work at a different altitude: one explains aggregate misses against plan across the whole metric tree, and another tracks the health of accounts that have already signed. Neither looks inside a single live deal while there's still time to act on it. This tool fills that gap — surfacing the deals most likely to slip before they actually do, so a manager can intervene while an intervention still matters.

## How it works

Every open deal is read against six specific, plain-English warning signs: has it gone quiet (no contact in about a week after enough time has passed for that to be meaningful), is it still resting on a single point of contact at the account, is a competitor actively showing up in the conversation, has it been stuck in its current stage far longer than deals like it normally take, has a manager recently pulled back on a rep's confident call, and — for Enterprise deals specifically — did a technical proof-of-concept fail. Each of these is a simple, transparent rule anyone can check by hand. Separately, a trained model looks at the same underlying signals in their full, continuous form — not just whether a threshold was crossed, but by how much — and combines them into a single risk score representing how likely the deal is to be eventually lost. The two views are kept side by side rather than merged into one verdict: a deal can carry a high risk score without tripping any named flag, or trip a flag while still scoring as relatively low-risk overall, and a manager is meant to look at both rather than have one silently override the other.

## Key decisions and why

- **The six warning flags and the composite risk score are reported side by side, never combined into one verdict.** A named flag tells a manager exactly *what* looks wrong and can be acted on directly; the risk score gives a rankable sense of *how* at-risk a deal is overall, even when nothing about it is crisp enough to name. Collapsing the two into a single number would hide exactly the distinction a manager needs to decide how to respond.
- **A simpler, fully transparent scoring method was deliberately used instead of a more complex alternative that can look impressive in testing but needs an extra calibration step before its output can be trusted as a genuine probability.** This score is read directly as "how likely is this deal to be lost," so a transparent method whose output holds up at face value — and whose every input's influence can be traced — was chosen over one that would need a second layer of tooling standing between the model and the number a manager actually reads.
- **Before any predictive model was built on deal activity, the design confirmed the model wasn't just going to read back an outcome the underlying data had already effectively decided.** Deal activity in this data is realistically shaped by how a deal eventually turns out — a deal that closed tends to show a busier, better-engaged history than one that didn't — the same realistic pattern that shows up in how proof-of-concept results are recorded elsewhere in this portfolio. Testing activity-only signals in isolation confirmed they carry a real but modest signal, in the same range as other legitimate early-warning tools in this portfolio and nowhere near the suspiciously perfect accuracy that would indicate the model was just re-deriving a foregone conclusion. That check is what justified building a real predictive model on engagement data rather than treating it as unusable.
- **The training data samples closed deals at a random point across their entire lifespan — from just-opened to nearly-closed — rather than only near the end.** The tool's actual job is scoring an open deal at whatever point it happens to be in its life right now, so the historical deals it learns from have to span that same range for the comparison to be fair. A model trained only on deals near their close would learn what a deal looks like right before it's decided, which is the easy case, not the useful one.
- **The score is tuned to stay an honestly calibrated probability rather than being artificially boosted to catch more at-risk deals.** A manager reading "this deal is 71% likely to be lost" should be able to take that number close to at face value; a version tuned to flag more deals would inflate that number systematically and make it useless as an actual probability.
- **A deal only lands in the highest-risk watchlist tier if it scores among the riskiest quarter of the current open pipeline, rather than crossing a fixed, one-size-fits-all cutoff.** This keeps the watchlist meaningful as the size and mix of open pipeline changes, instead of flagging almost every deal in a slow quarter or almost none in a strong one.
- **The competitive-pressure flag is read specifically as a warning about deals at risk of a competitive loss, not as a general risk signal.** Deals with heavy competitive chatter aren't meaningfully more likely to be lost overall — some level of competitive presence shows up on won deals too — but among the deals that are eventually lost, this flag is a sharp predictor of which ones were lost specifically to a named competitor. Presenting it as a generic risk flag without that distinction would overstate what it actually shows.
- **The stage-stall flag is kept even though it shows the weakest connection to outcome of the six.** A deal that has sat in its current stage far longer than normal for its kind is still operationally worth a manager's attention regardless of how strongly that pattern predicts the final result in the data — the flag's value is in prompting a conversation, not in being the single strongest predictor.

## What drives the result

- **How the deal is engaged** — how many people at the account are involved, how recently the deal was last touched, how often scheduled meetings actually happen, and how much competitor mention has shown up recently
- **Deal mechanics** — how long the deal has been open, what stage it's currently in, how far along its stage progression is, and how long it has sat in its current stage relative to what's normal for its kind
- **Proof-of-concept outcome, Enterprise only** — whether a technical proof-of-concept has concluded and whether it passed or failed
- **Forecast trajectory** — whether a rep's confident call on the deal was recently pulled back by their manager
- **Rep context** — how long the rep handling the deal has been in the role, since a newer rep's deals behave somewhat differently

How long a deal has been open turns out to be the single strongest input into the risk score, but it's closely tied to engagement: older open deals tend to be the ones that have gone quiet, so this is best read as one combined "is this deal still moving" signal rather than two fully independent effects carrying equal weight on their own.

## Current result

As of November 30, 2025, with 43 Commercial and Enterprise deals open in the pipeline, the model correctly identifies which of two deals — one that eventually closes and one that eventually falls through — is the riskier one in roughly 7 out of 10 random comparisons, when tested against outcomes it never saw during training. That accuracy held up at a second, earlier checkpoint (mid-2025) too, so it isn't a one-off result tied to a single snapshot in time. When the score does flag a deal as high-risk (the riskiest quarter of the open pipeline), it is right the large majority of the time — but it only catches a modest share of the deals that ultimately fall through, so a deal that isn't flagged should not be read as safe; it simply hasn't tripped this particular tool's threshold. The score is also genuinely calibrated: a deal the model calls "70% likely to be lost" behaves, on average, close to that in practice, rather than needing translation before it's trusted as a real probability.

## Known limitations

- **The stage-stall flag shows the smallest connection to actual outcome of the six flags** and is kept for the operational value of prompting a check-in, not because it strongly predicts which deals are actually lost.
- **The competitive-pressure flag is a signal about competitive losses specifically, not general deal risk**, and should be read that way — a flagged deal isn't meaningfully more likely to be lost overall, only more likely, if it is lost, to be lost to a named competitor.
- **The forecast-downgrade flag's connection to outcome is more modest here than the equivalent finding in the standalone quarterly forecast tool**, because this tool watches deals across their entire open life, not just the final stretch before a quarter closes — the underlying signal is the same one, just measured over a wider and naturally noisier window.
- **Most currently open deals can't yet be traced back to a named account.** The great majority of open deals at the most recent checkpoint have no account link in the underlying data — a pre-existing gap in how this pipeline is currently generated that several other tools in this portfolio already carry. It doesn't affect which deals get flagged or how they're scored, since scoring happens at the deal level regardless, but it does limit routing a flagged deal to the right account owner by account rather than by the individual deal alone.
- **Every deal is treated the same regardless of dollar size.** A small Commercial deal and a large Enterprise deal get identical treatment in the flag and scoring logic; a version of this tool that weights the watchlist by dollars at risk is a natural next step, not something built here yet.
- **This tool is not yet wired into the weekly leadership readout.** It currently runs and can be queried on its own; folding a deal-level watchlist section into the recurring weekly readout is future work.

## Technical validation

The following reproduces the model's full statistical record for a reader who wants to verify these claims directly. The six named risk flags are deterministic threshold rules, not a fitted model, and carry no coefficient, AUC, or confusion matrix of their own — they are instead validated against 14 hand-constructed known-answer test scenarios (14 of 14 pass) plus real-data selectivity checks confirming each flag fires on a genuine, non-trivial share of open deals. Everything below applies to the fitted composite risk-score model only.

**Target, set in advance:** pooled out-of-time held-out AUC between 0.60 and 0.85; calibration gap within ±0.05 of the actual base rate.

**Achieved, at two independent checkpoints:**

| Measure | 2025-11-30 | 2025-06-30 | Target | Met (both) |
|---|---|---|---|---|
| Out-of-time held-out AUC | 0.6965 | 0.7158 | 0.60–0.85 | Yes |
| Stratified-random-split AUC (secondary) | 0.7314 | 0.7167 | — | — |
| Calibration gap | +0.0132 (mean predicted 0.7127 vs. base rate 0.6995) | −0.0352 (0.6985 vs. 0.7337) | ≤ ±0.05 | Yes |
| n_train / n_holdout | 1,217 / 406 | 1,014 / 338 | — | — |
| n_train positive (loss) / n_holdout positive | 869 / 284 | 720 / 248 | — | — |

**Coefficient table** (canonical checkpoint, 2025-11-30; standardized / one-hot-encoded scale — every numeric input is scaled to comparable units before fitting, so these reflect relative influence, not raw-unit effects; sorted by absolute magnitude; label = 1 for eventual loss, so a positive coefficient raises predicted loss risk):

| Feature | Coefficient |
|---|---|
| deal_age_days | 2.6302 |
| n_touches | −1.4018 |
| n_contacts | −1.2113 |
| current_stage_POC | 0.5309 |
| current_stage_SAL | −0.4975 |
| comp_count_60d | 0.3097 |
| stage_progress | −0.2459 |
| deal_age_ratio | −0.2297 |
| days_since_last_touch | 0.2072 |
| segment_Enterprise | 0.1995 |
| meeting_held_rate | −0.1995 |
| rep_tenure_days | 0.1949 |
| current_stage_Proposal/Negotiation | 0.1918 |
| has_entered_a_stage | 0.1755 |
| stage_stall_ratio | −0.1453 |
| rep_confident_manager_downgrade | 0.1392 |
| days_in_current_stage | 0.1305 |
| poc_revealed_pass | −0.1235 |
| touch_rate | 0.1137 |
| rep_is_ramping | 0.0598 |
| poc_revealed_fail | 0.0566 |
| segment_Commercial | −0.0544 |
| current_stage_pre_stage | −0.0406 |
| current_stage_SQO | −0.0394 |

Three caveats travel with this table. (1) `deal_age_days` dominates and is negatively correlated with engagement volume (older deals tend to be the ones that have gone quiet, per `n_touches`/`n_contacts`'s strongly negative coefficients) — the two are related reads of the same underlying "is this deal still moving" signal, not two independent effects of equal weight. (2) `poc_revealed_pass`/`poc_revealed_fail` are structurally zero for every non-Enterprise deal, so their magnitudes describe their effect *within* that stratum only. (3) `stage_progress` and the `current_stage` dummies are two representations of one underlying signal, so neither coefficient alone describes the model's reliance on stage position. Note `poc_revealed_fail`'s coefficient (0.0566) reads smaller here than the flag-level grounding (a revealed fail drops win rate from a 28.8% base to 9.3%, n=54) would suggest — most of that stratum's effect is carried jointly with `current_stage_POC` and `segment_Enterprise`, a collinearity effect worth naming rather than reading the standalone coefficient as the whole story.

**Confusion matrix at the production operating threshold** (top quartile of scored probability on the training population — a ranking/watchlist threshold, not a fixed 0.5 cutoff):

At 2025-11-30 (threshold 0.8443): TP=88, FP=18, TN=104, FN=196 — precision 0.8302, recall 0.3099, F1 0.4513.

At 2025-06-30 (threshold 0.8455): TP=68, FP=6, TN=84, FN=180 — precision 0.9189, recall 0.2742, F1 0.4224.

This is the intended shape for a flagged watchlist tier: high precision, low-to-moderate recall — a deal the score calls flagged is very likely a genuine eventual loss, and a deal it doesn't flag is not thereby written off (the six named flags and the full continuous risk score remain visible for every open deal regardless of this binary cut).

**Calibration note.** Calibration gap +0.0132 at 2025-11-30 and −0.0352 at 2025-06-30, both inside the ±0.05 target — this model is calibrated and intended to be read as a probability, no reweighting applied. Reliability by held-out quintile (2025-11-30):

| Predicted-probability bucket | n | Mean predicted | Actual rate |
|---|---|---|---|
| 0.006–0.573 | 82 | 0.4053 | 0.4634 |
| 0.573–0.717 | 81 | 0.6519 | 0.6543 |
| 0.717–0.790 | 81 | 0.7581 | 0.7037 |
| 0.790–0.863 | 81 | 0.8281 | 0.8148 |
| 0.863–1.000 | 81 | 0.9237 | 0.8642 |

Monotone and close to the diagonal across all five buckets — no systematic over- or under-confidence at either end.

**Sample sizes**: fitted population 1,352–1,623 closed Commercial/Enterprise new-business opportunities depending on checkpoint, split 75/25 train/holdout, 24 columns after encoding (17 numeric + 2 categorical). Open, scored population at the canonical checkpoint: 43 deals (31 Commercial, 12 Enterprise).

**No R²/RMSE** — this is a classification model, not a regression model.
