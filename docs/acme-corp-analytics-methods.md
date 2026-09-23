# Acme Corp — Analytics methods

The Phase 4 equivalent of `acme-corp-gtm-metric-tree.md`: the source of truth for how each analytics artifact is built, what it's validated against, and when its performance has degraded enough to warrant review. Filled in as each artifact is actually built, per the build spec's priority order — not written speculatively ahead of the work.

An entry with no methodology yet is marked TBD, not omitted — the artifact's existence and its place in the priority order are already fixed by the build spec even before its method is chosen.

---

## Point-in-time discipline (applies to every entry below)

Every model in this doc must be computable as of any historical date using only data that existed up to that date — no leakage from the future. This is what makes backtesting and drift detection possible at all; see `analytics-engineering-conventions` for the coding rule this implies.

Historical performance is stored as a monthly time series, not sparse hand-picked checkpoints — `fact_model_performance_history` (model_name, as_of_date, metric_name, metric_value), an append-only log rather than a cross-cutting business mart. Any specific comparison ("today vs. a year ago") is a query against this series, not a separately-run one-off computation.

## Proxy-metric decoupling — general rule, applies to any Layer-3-to-Layer-2 relationship in the tree

A leaf is decoupling from its parent when the trailing 6-month correlation between them drops more than 30% relative to its trailing 12-month baseline, **while the leaf's own raw value has not declined**. That second condition is what distinguishes real decoupling (more meetings, not more wins) from a leaf simply falling off on its own (fewer meetings, naturally fewer wins) — the latter isn't decoupling, it's just decline, and the existing variance-diagnostic engine already handles it.

## Drift review trigger — general rule

Flag for review on **2 consecutive monthly checkpoints** below a stated threshold, never a single reading. One bad month is noise; two is a pattern. This applies uniformly — a specific entry below states its threshold, not a different consecutive-breach rule.

---

## Account health score / churn-risk model

- **Built**: `dbt/models/marts/marts/mart_account_health.sql` (grain: one row per account_id per month; joins `fact_usage_monthly`, `fact_support_tickets`, `fact_product_logins`, `fact_am_activity`, `fact_subscriptions`, `dim_accounts` so the model reads a single mart) + `analytics/health_score.py` (logistic regression, scikit-learn, `class_weight='balanced'`, seeded via `_RANDOM_SEED = 42`).
- **Model choice and why**: logistic regression, not a more complex classifier (random forest, gradient boosting, a neural network) — three reasons, all tied to this artifact's actual requirements rather than a default pick. (1) Every coefficient is directly attributable to one input feature, which is what makes the relative-importance breakdown and full coefficient table below possible without a secondary explainability technique (SHAP, permutation importance) standing between the model and its own explanation — this artifact needs to be independently auditable, not just accurate. (2) At this dataset's scale (~7,700 accounts, 15 model inputs after encoding), a linear model is a well-justified baseline; a higher-capacity model risks fitting noise rather than signal without a proportionally larger or richer dataset to justify the added complexity. (3) The score's actual downstream use is a ranking (quantile-based risk tiers, not a raw probability read literally — see the calibration note below), and a linear model's ranking behavior is more predictable and easier to sanity-check (e.g., confirming more support tickets always pushes risk in one direction) than an ensemble's. Achieving the QA plan's 0.65–0.80 AUC target with this simpler model is itself evidence the added complexity of a more powerful model class isn't needed to hit the stated bar — not a compromise made to keep things simple.
- **Inputs**: usage trend (account-relative baseline — trailing-3-month mean actions_consumed ÷ the account's own cumulative-to-date mean, not a flat trailing-month comparison), support ticket volume/severity (trailing 3 months), engagement/login frequency (reweighted per the QA plan — multiplied by 1.0 within an account's first 90 days of tenure, by 0.33 after, before being fed to the model as `login_frequency_weighted`), AM sentiment notes (trailing 3-month average `sentiment_score`, null for SMB — no-touch, no AM).
- **Why these four inputs**: usage trend, support ticket volume/severity, engagement/login frequency, and AM sentiment are the account health score's inputs by design, not by feature selection — `docs/acme-corp-gtm-metric-tree.md`'s Account health score leaf and `docs/acme-corp-gtm-portfolio-build-spec.md`'s retention/expansion mechanics both fix these four as the score's inputs at company-model-design time, before this model existed. `analytics/health_score.py` decides how much relative weight each of the four carries in the fitted decision boundary (see Relative importance in the Statistical validation package below); it does not select which signals to include from a wider candidate pool.
- **Label / point-in-time design**: one scored snapshot per account. Churners are scored `_SCORING_LEAD_MONTHS = 5` months before their actual churn month (label=1); survivors get a seeded-random scoring month drawn from their own history, at least 5 months before `as_of_date` (label=0) — a fixed "recent" snapshot for every survivor was tried first and rejected: it clustered every negative example on one calendar month, which degenerated any date-based train/test split. Held out via a class-stratified random split (`sklearn.model_selection.train_test_split`, seeded), not a temporal split — churn events concentrate earlier in the 36-month window (recent-cohort accounts haven't reached their churn point yet, ordinary right-censoring), so a late-date holdout ends up with only a handful of positives and an unstable AUC estimate. Point-in-time discipline holds regardless of split strategy: every row's features are computed only from that account's own data up to its own scoring_date, so shuffling rows across train/test cannot leak future information into any feature.
- **Target**: 0.65–0.80 AUC predicting eventual churn (QA plan grounding target). **Achieved: 0.7613 holdout AUC** (as_of_date 2025-12-31, n_train=5,277, n_test=1,760), logged to `fact_model_performance_history` via `analytics/model_performance.py`.
- **Calibration note (load-bearing, not incidental)**: `generators/config.py`'s `DECLINE_MONTHS_BEFORE_CHURN = 4` is how many months before churn the generator's deterministic usage/ticket/sentiment decline window starts. Scoring at or inside that boundary (`_SCORING_LEAD_MONTHS <= 4`) lets the model see the designed collapse directly and produced an inflated, unrealistic 0.93–0.99 AUC during build — pattern-matching the generator's own construction, not a genuine early-warning signal. `_SCORING_LEAD_MONTHS = 5` (one month before the decline window starts) is what actually exercises an early-warning problem and is what the 0.65–0.80 target describes.
- **Drift threshold**: AUC below 0.65 for 2 consecutive monthly checkpoints → flagged for review
- **Test E validation (QA plan)**: "High-automation, low-login, high-Actions accounts exist and are NOT predominantly mis-flagged as at-risk" — confirmed. Cohort defined per-segment as top-quartile trailing Actions AND bottom-quartile trailing logins (557 accounts as of 2025-12-31). `risk_tier` is quantile-based over the scored active population (top 20% = High) rather than a fixed probability cutoff — `class_weight='balanced'` shifts predicted probabilities up systematically, so a fixed 0.5 cutoff mis-flagged ~72–91% of accounts as High regardless of cohort. Under quantile tiering: population High-risk rate 20.0%, automated-but-healthy cohort High-risk rate 19.7% — at parity with, not elevated above, the general population.
- **Statistical validation package** (as_of_date 2025-12-31, computed on the same 1,760-row held-out split the holdout AUC above is computed on):
  - **Relative importance**: each of the twelve numeric model features is mapped to its one conceptual input (`_CONCEPTUAL_INPUT_GROUPS` in `analytics/health_score.py`), coefficient magnitudes are summed within each of the four groups, and the four group sums are normalized to 100%. `tenure_days`, `is_within_first_90_days`, and one-hot `segment` are excluded from this breakdown entirely (not folded into any group, not given a fifth bucket): they are real model features but not one of the four conceptual inputs this breakdown answers for, and `segment`'s dummy encoding is not on the same scale as the standardized numeric features, so including it would not be a like-for-like comparison. **Result: AM sentiment 34.7%, usage trend 32.0%, ticket volume/severity 27.2%, login frequency 6.0%.** Two caveats travel with this figure: (1) the AM sentiment group's weight is carried almost entirely by whether an account has any AM activity at all in the trailing window (`has_am_activity_3mo`, coefficient −0.322), not by the sentiment score's own polarity (`am_sentiment_avg_3mo`'s coefficient is −0.001, essentially zero) — this partly reflects which accounts have AM coverage at all (SMB has none) rather than sentiment content specifically. (2) `login_count_avg_3mo` and `login_frequency_weighted` are two representations of one underlying login signal (the second is a tenure-reweighted transform of the first), so the login-frequency group's percentage reflects the model's combined reliance on login behavior rather than two independently-contributing signals. Coefficient magnitude on jointly-standardized features is a defensible relative-importance heuristic for a linear model, reflecting the model's own reliance on a signal within its fitted decision boundary — not an independently-estimated, real-world causal effect size.
  - **Coefficient table** (standardized scale — `StandardScaler` applied to all 12 numeric inputs before fitting, so these are relative-magnitude comparisons, not raw-unit effects; sorted by absolute magnitude):

    | Feature | Coefficient |
    |---|---|
    | is_within_first_90_days | −0.8412 |
    | segment_Enterprise | −0.5432 |
    | tenure_days | 0.4309 |
    | usage_trend_ratio | −0.3534 |
    | has_am_activity_3mo | −0.3219 |
    | segment_SMB | 0.1295 |
    | ticket_count_3mo | −0.0928 |
    | high_severity_ticket_count_3mo | 0.0853 |
    | avg_ticket_severity_3mo | −0.0819 |
    | am_touchpoint_count_3mo | −0.0609 |
    | login_frequency_weighted | 0.0601 |
    | has_tickets_3mo | 0.0408 |
    | segment_Commercial | 0.0323 |
    | login_count_avg_3mo | 0.0065 |
    | am_sentiment_avg_3mo | −0.0009 |
  - **Confusion matrix, High-risk tier, at the production operating threshold** (top 20% of scored probability = High — same `high_risk_quantile=0.80` `score_accounts()` uses, cutoff probability 0.6678 on this held-out split): precision 0.4261, recall 0.4132, F1 0.4196, from TP=150, FP=202, TN=1195, FN=213.
  - **Calibration note**: mean predicted probability on the held-out set is 0.4431 against an actual base rate of 0.2063 — a calibration gap of +0.2369. Raw `churn_probability` is **not calibrated** to true likelihood (expected: `class_weight='balanced'` shifts probabilities up systematically). `churn_probability` is a valid ranking signal, which is what the quantile-based `risk_tier` relies on; it is not a calibrated probability estimate and must not be read as one.
  - **Sample sizes**: n_train=5,277 (positive=1,088), n_test=1,760 (positive=363) — same split the holdout AUC is computed on.
  - **No R²/RMSE section** — this is a classification model (`LogisticRegression`), not a regression model; deliberate, not an omission.
- **Known limitation**: not yet validated against the QA plan's injected incidents specifically — this build logged one build-time holdout checkpoint only (single as_of_date). Confirming the model's AUC visibly dips at each injected-incident month (and wiring up the recurring monthly backtest the drift threshold above depends on) is drift-monitor's job, still open.

## Segment/lead scoring model

- **Inputs**: TBD — firmographic features at signup, per build spec Section 1's entry-scoring logic
- **Target**: TBD
- **Drift threshold**: TBD

## Forecast (sales bottoms-up / ML / CRO overlay reconciliation)

- **Inputs**: TBD
- **Target**: TBD
- **Drift threshold**: TBD

## Variance-diagnostic engine

- Not itself a predictive model — no AUC/accuracy target applies. Its correctness is structural (does it correctly identify the true outlier Layer-2 child), validated by `analytics-model-validator`, not by drift monitoring.

## Capacity planning

- **Inputs**: TBD
- **Target**: TBD
- **Drift threshold**: TBD
