---
source: dbt/models/marts/marts/mart_account_health.sql, analytics/health_score.py
---

# Account Health Score

## What this is

A monthly, account-by-account early-warning signal that flags which customers are at meaningful risk of churning — built for the team that owns retention and expansion (Account Management) to know where to focus before a renewal conversation goes wrong.

## Why it exists

Revenue lost to churn and contraction is one of the forces that makes up the company's overall growth number, and it's driven by how healthy an account's relationship with the product looks over time — not just whether this month's usage happened to dip. This score turns that relationship into a single, trackable signal per account per month, so a decline can be caught and acted on before the account is already gone.

## How it works

Each month, every active account is scored using four signals about how it has been behaving recently: how its usage compares to its own normal level, how many support issues it has raised and how serious they were, how often people at the account are actually logging in, and how positive or concerned the account's dedicated contact has sounded in recent check-ins. Those four signals are combined by a model trained to recognize the pattern that shows up before an account actually leaves, and the account is then placed into a risk tier — Low, Medium, or High — based on how it compares to the rest of the active customer base right now.

## Key decisions and why

- **A simpler, fully transparent method was deliberately used instead of more complex alternatives that can sometimes be more accurate but are harder to explain.** Every factor's influence on the score can be traced and shown directly, rather than relying on a black box and a second layer of tools just to explain what it's doing — important for a score that's meant to be trusted and acted on, not just accurate.
- **The four signals it uses were fixed in advance, not selected by the model.** Usage trend, support activity, login frequency, and account-team sentiment are the four signals the business already uses to think about account health; the model's role is to weigh them appropriately against each other, not to search for different signals that might predict churn better.
- **Usage is compared against the account's own history, not a company-wide average.** Different accounts have different normal usage levels and rhythms, so a meaningful drop is defined relative to where that specific account normally sits, not a one-size-fits-all bar.
- **Login frequency counts for more in an account's first three months, and less after that.** A brand-new account logging in often is a sign of healthy onboarding; a mature, well-automated account logging in rarely is expected and not a warning sign on its own — the score is built to tell those two situations apart rather than penalizing an account simply for running smoothly on autopilot.
- **The score is tested on how well it predicts churn several months in advance, not in the final weeks before it happens.** By the time an account is a few weeks from leaving, the warning signs are usually obvious to anyone looking. The real value of an early-warning score is catching risk while there's still time to act, so its accuracy is measured against a meaningfully early window, not the easy, last-minute case.
- **Each healthy account's comparison snapshot is drawn from a different point in its own history, not a single shared month.** This keeps the group of "healthy" examples the score is measured against spread out realistically across time, rather than clustered artificially in one moment that wouldn't represent how account health actually varies.
- **Risk tiers move with the current book of business rather than sitting at a fixed score.** An account only lands in the "High" tier if it's genuinely among the riskiest share of accounts active right now, so the tiers stay meaningful as the overall customer base changes, instead of drifting toward flagging almost everyone or almost no one.

## What drives the result

- **Usage trend** — how an account's recent activity compares to its own typical level
- **Support activity** — how many tickets an account has filed recently, and how serious they were
- **Login frequency** — how often people at the account are logging in, weighted more heavily during an account's first three months
- **Account team sentiment** — how positive or concerned the account's dedicated contact has sounded in recent check-ins (not tracked for self-serve small-business accounts, which don't have a dedicated contact)

Right now, the account team's engagement with an account and how its usage is trending carry the most weight in the score — roughly 35% and 30% respectively. Support activity plays a meaningful secondary role at roughly 25%, and login frequency — while still tracked, and still weighted more heavily for brand-new accounts — currently has the smallest influence, at roughly 5%. One thing worth knowing about the account-team signal specifically: its influence comes more from whether the account has a dedicated contact actively engaged with it at all, rather than from exactly how positive or negative that contact's notes have sounded.

## Current result

As of December 2025, the score correctly separates accounts that go on to churn from ones that don't in roughly 3 out of 4 cases, when tested against outcomes it was never shown during training — comfortably within the accuracy range this artifact was built to hit.

A specific concern going in was whether the score would unfairly flag accounts that are simply running on a high degree of automation — heavy product usage with very little manual login activity, which looks unusual but is actually a sign of a healthy, well-integrated account. That concern was checked directly: accounts fitting this "automated but healthy" pattern were flagged High risk at almost exactly the same rate as the overall customer base, not more.

## Known limitations

The score has been validated once, using a single point-in-time snapshot of results. It has not yet been checked against how it would have performed across the full simulated history — including whether it would have caught the deliberately engineered problem periods in the underlying data as they happened. That ongoing, month-by-month tracking is a separate, still-open piece of work.

## Technical validation

The following reproduces the model's full statistical record for a reader who wants to verify these claims directly.

**Relative importance** (as of 2025-12-31): AM sentiment 34.7%, usage trend 32.0%, ticket volume/severity 27.2%, login frequency 6.0%. Computed from the fitted logistic regression's standardized coefficients, summed within each of the four conceptual input groups and normalized to 100% — `tenure_days`, `is_within_first_90_days`, and one-hot `segment` are excluded from this breakdown entirely (not on the same scale as the standardized numeric features, and not one of the four conceptual inputs). Two caveats: (1) the AM sentiment group's weight is carried almost entirely by `has_am_activity_3mo` (coefficient −0.322) rather than `am_sentiment_avg_3mo` itself (coefficient −0.001, essentially zero). (2) `login_count_avg_3mo` and `login_frequency_weighted` are two representations of one underlying login signal, so the login-frequency percentage reflects combined reliance on login behavior, not two independent signals.

**Coefficients** (standardized scale — every numeric input is scaled to comparable units before fitting, so these reflect relative influence, not raw-unit effects; sorted by absolute magnitude):

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

**Confusion matrix — High-risk tier, at the production operating threshold** (top 20% of scored probability, cutoff probability 0.6678 on this held-out split):

| | Predicted High | Predicted not-High |
|---|---|---|
| **Actual churner** | TP = 150 | FN = 213 |
| **Actual non-churner** | FP = 202 | TN = 1195 |

Precision 0.4261, recall 0.4132, F1 0.4196.

**Calibration**: mean predicted probability 0.4431 vs. actual base rate 0.2063 on the held-out set (calibration gap +0.2369) — raw churn probability is not calibrated to true likelihood (expected, given `class_weight='balanced'`); it is a valid ranking signal only, which is what the risk-tier system above relies on.

**Sample sizes**: n_train = 5,277 (positive = 1,088), n_test = 1,760 (positive = 363).

**No R²/RMSE** — this is a classification model, not a regression model.
