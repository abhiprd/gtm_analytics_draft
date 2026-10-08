---
source: analytics/ltv_by_segment.py
---

# LTV by Segment

## What this is

A five-year estimate of what a newly acquired customer is worth, by the segment it enters as — SMB, Commercial or Enterprise — set against what it cost to acquire. It is built for finance, the account-management leads and the CRO, who need to know whether a segment pays back its acquisition spend and how much of that answer is observed versus projected.

It sits underneath one line of the metric tree, "LTV by segment × acquisition channel", which the tree defines as an overlay on Consumption payback and not as a building block of any other metric. Payback asks how fast the acquisition cost is recovered; this asks what the account is worth over its modeled life. It adds to nothing and nothing adds to it.

## Why it exists

Payback is a single-window ratio: it cannot see that two segments with the same payback can have very different lives. Lifetime value extends the same question over five years — how many accounts are still customers each month, what each surviving customer pays, at the 80% margin the company already assumes, discounted at 10% a year — and sets it against what the acquisition cost.

It also checks a question the marketing models cannot: whether an acquisition channel is worth more than its cost suggests because its customers stay longer or spend more. Between SMB's two channels it finds no detectable difference in retention (statistical test p = 0.17, with a 3.9-point gap in month-60 survival; Commercial p = 0.09) or in revenue per surviving account (p between 0.20 and 0.83 at months 6, 12, 24 and 36). That is an absence of evidence on synthetic data, not proof of no effect, and Enterprise is untested (too few lost accounts for the test to mean anything). So the channel difference in lifetime value to cost is a cost difference.

## How it works

For each segment, taken at the segment an account had on the day it signed up (an account that later moves up a segment stays in the segment that acquired it), the tool:

1. Follows every account forward month by month to see how many are still customers at each age, using all signup years together and every account's real observation window. Where fewer than 30 accounts remain under observation it stops reading the data and extends the curve at the recent monthly loss rate, with a plausible range around it.
2. Takes the average monthly revenue of a surviving account at each age. Revenue per surviving account rises with age and also with the calendar year, and the two cannot be told apart in this history, so the central path uses accounts that signed up in the last three years and then holds the level flat once the sample thins. Two alternatives (older signup years' own path; their growth carried forward) bracket it.
3. Multiplies survival by revenue by 80% margin, discounts each month back to signup at 10% a year, and adds up the first 60 months.
4. Works out the cost to acquire: marketing spend allocated to the segment by its share of each channel's new accounts, and, for Commercial and Enterprise, the sales reps' cost per won account (Inside Sales for Commercial, Account Executives and Sales Engineers for Enterprise; account managers excluded because they serve existing customers). Both are shown side by side, with the ratio of lifetime value to each.

## Key decisions and why

- **The answer is by entry segment, with ranges for the two thin segments.** SMB has 1,784 lost accounts to learn from, Commercial 44 and Enterprise 5. SMB gets a central figure with a narrow range; Commercial gets a range to be read as a range; Enterprise is directional only.
- **The channel split is shown for SMB only, and it is a cost split.** No difference in how long self-service and inbound-marketing customers stay, or in what they pay, is detectable (retention p = 0.17; revenue p = 0.20 to 0.83 by age), so the same lifetime value is divided by very different acquisition costs; this is an absence of evidence on synthetic data, not proof of no effect. Commercial and Enterprise channel cuts are withheld because a handful of lost accounts cannot support them.
- **Revenue is assumed to stop growing once the evidence thins.** That is a deliberately conservative convention, and for SMB the backtest shows it: revenue per surviving SMB account kept rising after the cutoff, so the SMB projection came in 6% to 32% below what actually happened. That finding is SMB's alone: Commercial's 36-month backtest was within 0.3% at one origin and 10.6% above realized at the other (57 accounts), and Enterprise has no backtest, so for those two segments the direction of the error is not known.
- **Marketing-only and sales-loaded cost are both shown, and only the second counts for Commercial and Enterprise.** For those segments the sales reps are the acquisition cost, so a ratio against marketing spend alone (hundreds of times over) is displayed only to show it is not usable.
- **Lifetime value includes revenue earned after an account moves up a segment.** For SMB that is about 60% of the five-year value and for Commercial about 72%, carried by about one account in ten (722 of 7,222 SMB and 38 of 365 Commercial). Account-management cost is not netted, but it is small: about 5.5% of segment revenue, which would take Commercial from 7.0 times to about 6.5, nowhere near the 1.9 times seen counting only revenue earned inside the segment. The gap between those two figures is about how much of the few accounts' upside is credited to the segment that acquired them, so the tool reports both.
- **Compounding the durability metric's gross revenue retention was rejected.** That metric counts month-to-month usage dips and would compound to about half the accounts a year, against customer retention of about 83% to 99%.
- **No look-ahead.** Everything is read as of a month end, and the tool was tested by corrupting every fact after the date and confirming the reading did not move.

## What drives the result

- **How long customers stay.** SMB keeps about 42% of accounts at month 60; Commercial and Enterprise lose customers mainly at contract renewals (Commercial at each annual renewal, Enterprise first at month 25).
- **What a surviving customer pays, and how it grows.** This is the largest uncertainty: a small share of accounts moves up a segment and pays five to thirty times as much, so a few accounts decide the average.
- **The cost to acquire.** For SMB the spread is set by channel: about $62 self-service and about $1,589 inbound marketing. For Commercial and Enterprise it is the sales team's cost per won account (about $31K and $338K).

## Current result

At December 2025 a new SMB account is worth about **$15.8K** of discounted margin over five years (range $14.7K to $20.3K) against $454 of marketing cost, a ratio of about 35 times that is best read as "far above any threshold": the cost excludes marketing and customer-success headcount, and the cost spread by channel is a data-generation setting. Self-service reads about 256 times and inbound marketing about 10 times, entirely from cost. A new Commercial account is worth about **$223K** (range $126K to $270K) against $31.8K including sales cost, a ratio of **7.0 times (range 4.0 to 8.5)**; counting only revenue earned while it is still a Commercial account the ratio is 1.9 times, and that gap — whether the account moves up — is the important finding for Commercial. A new Enterprise account is worth about **$1.14M** (range $1.03M to $1.52M) against $339K including sales cost, about **3.4 times (3.0 to 4.5)**, directional only on five lost accounts.

Roughly half of each segment's five-year value is projection beyond what the data directly shows (43% for SMB, 52% for Commercial, 49% for Enterprise).

All of the tool's structural checks pass at both checkpoints: its customer counts match the cohort tool's exactly, the oldest accounts' modeled revenue matches the revenue records to rounding error, the cost figures tie to the spend and rep-cost records, and eleven planted-answer scenarios come out as worked, each against an expected value computed by separate arithmetic in the scenario code (the test suite breaks the discount exponent, the first month, the margin and the survival-to-revenue alignment in turn and confirms the scenarios catch each). They include one that shows what the tool cannot see, a loss rate that changes beyond the observed window. In the backtest (fit on data to December 2022, compared with what then happened), SMB retention was projected within 1.9 percentage points at every checkpoint from month 36 to month 60 and always inside the stated range. SMB revenue per account was 11% below what was realized over 36 months and 32% below over 60 months (6.5% and 24% at the earlier origin), all from revenue growth rather than customer loss. The 5-point retention limit and 25% limit on the 36-month figure were set after seeing the size of those errors, only the 36-month figure is held to a limit (the 60-month figure, which the headline uses, would not meet it), and the two checkpoints are overlapping looks at mostly the same accounts, so a second consecutive check adds little independent confirmation. The monitored backtest also lags the fit by three years, and the drift rule has never been exercised.

## Known limitations

- **It is a modeled view.** The oldest accounts are 71 months old; the second half of every segment's five-year value rests on a projection.
- **The revenue assumption is the largest uncertainty.** For SMB the central path is conservative: realized revenue per account exceeded the projection in all four SMB backtest comparisons. For Commercial the backtest was mixed and for Enterprise there is none. The rule that stops the revenue path from being swung by a handful of accounts was added after the SMB figure was seen to move between checkpoints, so the stability of the two checkpoints is partly built in.
- **Commercial and Enterprise rest on very little.** Twenty-two Commercial and six Enterprise accounts have reached month 60. Enterprise cannot be backtested until 30 accounts have reached month 36 (23 now).
- **The cost to acquire is a floor and, by channel, a data-generation setting.** Marketing headcount and sales-development cost are absent from the data. The spend allocation by share of new accounts cannot show that a large account costs more through the same channel.
- **Customers that move up are counted fully**, with account-management cost not netted (it is about 5.5% of segment revenue and does not drive the gap between the two ratios).
- **A change in loss rate beyond the observed window cannot be seen**, and the reported range covers sampling error, not that.
- **Cost is averaged over 2023–2025 while retention and revenue come from all signup years;** accounts that signed up before 2023 have no acquisition cost at all.
- **The definitions, the 5-point and 25% backtest limits and the drift rule are proposals**, supported by two checkpoints.
