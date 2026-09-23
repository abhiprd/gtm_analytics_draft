---
source: dbt/models/marts/marts/mart_segment_migration.sql, analytics/segment_migration.py
---

# Segment Migration Analysis

## What this is

A record of every account that has outgrown its starting segment — moved from SMB into Commercial, or from Commercial into Enterprise — and what that movement looked like: how often it happens, why, how long it typically takes, and how much revenue moves with it. It's built for GTM leadership and the teams who own segment strategy (RevOps, Account Management) to see segment graduation as its own growth story, separate from new-logo wins or ordinary expansion.

## Why it exists

The Growth pillar's math nets segment migration out to zero on purpose — an account moving up a segment isn't new revenue or lost revenue, it's the same revenue relabeled. But that only works cleanly if migration is genuinely tracked as its own category rather than folded into the sending segment's retention numbers, where it would make a healthy, growing account look like a loss. This is especially true for SMB, whose business case rests substantially on how many of its accounts graduate into paying segments rather than on SMB standing alone. This analysis exists to make that graduation story visible and trustworthy: confirming accounts really do move up through both the usage-driven path and a separate re-classification path, not just one of them, and quantifying how much revenue that movement represents.

## How it works

The analysis looks across the full history of every account that has ever moved from SMB to Commercial or from Commercial to Enterprise and summarizes that history several ways: how many moves happened recently and at what rate relative to the size of the segment they moved out of; whether each move happened because the account's own usage organically grew past the segment's spend line, or because a closer look at the account's business profile revealed it belonged in a bigger segment all along; how long, typically, an account stayed in its prior segment before moving up; and how much monthly recurring revenue moved with each account into its new segment. None of this is a prediction about which accounts will move next — it's a direct summary of moves that have already happened, checked against other parts of the portfolio to make sure the revenue figures agree exactly.

## Key decisions and why

- **This is built as a descriptive summary of what has already happened, not a model that predicts which accounts will move next.** Segment migration in this business follows a known, largely rule-based path — an account's usage or spend crossing a defined line for two consecutive months, plus a separate manual re-classification process — so a predictive model would mostly be re-discovering that existing rule rather than adding genuine insight. Measuring and validating the pattern directly is the more honest use of the effort.
- **Revenue that moves with a graduating account is tracked and reported separately from ordinary churn and contraction.** An account outgrowing SMB into Commercial is a sign of business health, not attrition — counting that revenue against the segment it left would make a successful graduation look identical to a lost customer, which understates exactly the outcome SMB is supposed to produce.
- **The two ways an account can migrate are tracked and reported as separate categories rather than combined into one count.** An account can move up because its own usage organically grew past the threshold, or because someone later re-examined its business profile and reclassified it. Reporting these separately confirms that both real pathways are actually firing in the business, not just the more obvious usage-driven one.
- **Recent momentum and long-run pattern are measured over two different windows on purpose.** How many accounts are migrating and how fast is measured over a rolling recent period, so it reflects current momentum. Why they're migrating and how long they typically wait beforehand is measured against the full history to date, because any single recent period doesn't yet contain enough migration events on its own to read those patterns reliably.
- **Every revenue figure this analysis produces is checked against an independently built version of the same number elsewhere in the portfolio, rather than trusted on its own.** The growth-accounting side of the portfolio computes migration revenue separately, from the same underlying records but through a different calculation path. Two independent calculations landing on the same number is much stronger evidence of correctness than one calculation checked only against itself.

## What drives the result

- **Which segment an account moved from and to** — SMB into Commercial, or Commercial into Enterprise (no account skips a segment on the way up)
- **Why the move happened** — either the account's usage or spend held above roughly $1,250 a month (into Commercial) or roughly $6,250 a month (into Enterprise) for two consecutive months, or a later, closer look at the account's business profile revealed it belonged in the bigger segment regardless of usage
- **When it happened, and how long the account had been in its prior segment beforehand**
- **How much monthly recurring revenue reclassified into the new segment** along with the account

## Current result

As of December 2025, 809 accounts have migrated up a segment over the company's history: 722 from SMB into Commercial, and 87 from Commercial into Enterprise.

Just under a third of all migrations — 30.3% — happened because a closer look at the account's business profile revealed it belonged in a bigger segment, rather than because its usage crossed the spend line on its own. That re-classification path shows up meaningfully in both directions: 28.9% of SMB-to-Commercial moves and 41.4% of Commercial-to-Enterprise moves. This confirms both ways an account can graduate are genuinely active in the business, not just the more visible usage-driven one.

Typical accounts spend a meaningful stretch of time in their starting segment before moving up: a median of about 297 days (roughly ten months) in SMB before graduating to Commercial, and about 212 days (roughly seven months) in Commercial before graduating to Enterprise.

## Known limitations

This analysis covers the revenue and event side of segment migration — how often it happens, why, and how much revenue moves — but not the account-team side. Segment migration is also supposed to hand an account's relationship-management ownership over to the bigger segment's team (for example, from a Commercial account manager to an Enterprise one), typically opening a renewal or expansion conversation in the process. Whether that ownership handoff is actually happening isn't confirmed one way or the other here, because none of the data this analysis draws from currently tracks it.
