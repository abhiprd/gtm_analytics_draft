---
source: analytics/pipeline_coverage.py
---

# Pipeline Coverage

## What this is

A weekly-use check on whether there is enough open new-business pipeline, at the win rate the team has actually been realizing, to book the quota still left in the quarter — read separately for Commercial and Enterprise, with the shortfall or surplus stated in dollars. It is built for the CRO and sales leadership, who ask this question every Monday: "do we have the pipeline to make the number?"

It is a **coverage reading, not a forecast**. The forecast tool is still the only place that says what will close; this one says whether the pipeline is big enough, and the two are compared side by side rather than blended.

## Why it exists

A raw pipeline total flatters. Three dollars of open pipeline against one dollar of quota left sounds comfortable, until the team's realized win rate says it takes about four. This tool turns that into one defensible number per segment — how many dollars of open pipeline are needed per dollar still to book, how many are there, and what the gap is — using only what was known on the day of the reading.

## How it works

For each segment (Commercial, worked by Inside Sales reps; Enterprise, worked by Account Executives) on a given date, the tool:

1. Totals the quarter's quota across the reps who have been active at some point so far this quarter, and subtracts what has already been won, leaving the quota still to book.
2. Totals the open new-business pipeline expected to close this quarter.
3. Measures the win rate the team has realized recently: the share of closed new-business dollars that were won over the trailing twelve months, never reaching back before January 2023 (no lost deals were recorded earlier, so older win rates are an artificial 100%).
4. Divides one by that win rate to get the pipeline needed per dollar, compares it with the pipeline actually there, and states the dollar gap the pipeline is expected to leave against the quota still to book.
5. Labels the result covered, thin, short, or quota met, using a simple rule: at or above the needed level is covered; between three quarters of it and the needed level is thin; below three quarters is short. The rule is a proposal, not yet confirmed.

Readings are taken at a fixed point in the quarter — the Friday nearest the middle — so one quarter can be compared with the next.

## Key decisions and why

- **New business only.** Quota covers new-business deals, so renewals and expansions are left out. The forecast tool's pipeline total includes them, which would make coverage look about 1.7 to 2.8 times better than it is; the tool carries both totals side by side so the difference is visible.
- **A realized win rate rather than a stage-by-stage model.** In this data every new-business deal passes through every stage whether it is won or lost, so stage says nothing about the outcome. The one signal that does separate winners from losers at a point in time is the Enterprise proof-of-concept result (passes win about two in five closed dollars, failures about one in ten); it is shown as a clearly labelled, indicative extra view and is not folded into the main figure.
- **Compared against the forecast tool, not merged with it.** Both agree on which deals are open, exactly. They differ only in how the open dollars are priced, and the differences are reported (the coverage reading came out 4% to 31% above the forecast's manager view at the two checkpoints).
- **Next-quarter coverage is shown only where it exists, and never as zero.** Where the data has no deals closing in the following quarter (at the November 2025 checkpoint, the data ends before it starts) the section says unavailable and why.
- **No look-ahead.** A deal that closes after the reading date carries no outcome at all in the calculation, and the tool was tested by corrupting every fact that happens after the reading date and confirming the reading did not move.

## What drives the result

- **The quota still to book** — the quarter's quota across active reps, not reduced for reps who joined or left mid-quarter, less what has been won.
- **The open pipeline** — new-business deals that are open on the reading date and expected to close this quarter.
- **The realized win rate** — the more of the open dollars that historically convert, the less pipeline is needed per dollar.
- **The timing of pipeline creation** — Commercial deals are created and closed within weeks, so a mid-quarter reading cannot see the pipeline that has not been created yet.

## Current result

At the mid-August 2025 reading, both segments were thin: Commercial had $910K of open pipeline against $322K still to book (2.8x coverage; 3.5x needed at a 28% win rate), expected to close about $64K short, and Enterprise had $2.96M against $661K still to book (4.5x coverage; 4.8x needed), about $48K short. At the mid-November reading, Commercial was short: $726K open against $367K still to book (2.0x coverage; 3.9x needed at a 25% win rate), expected to close about $182K short of the quota left; Enterprise had already booked $2.67M against a $2.30M quota, so its quota was met.

Over every quarter from 2023, taking each reading at mid-quarter and comparing the pipeline-implied bookings with what was actually booked by quarter end, the typical miss was about 30% (Commercial 20%, Enterprise 40%), against about 48% for assuming only what was already won and about 51% for repeating the prior four quarters' average — better than either, but a simple fixed 25% win rate applied to the same pipeline does slightly better still (about 26% overall), so this tool's value is the coverage and dollar-gap framing, the separate required pipeline per segment and the explicit "unavailable" answers, not a more accurate number than a rule of thumb. Two things are worth knowing about its errors. Commercial is read about 15% low in aggregate (it read high in 2 of 11 quarters), because nearly a quarter of Commercial bookings come from deals that did not yet exist at mid-quarter, partly offset by the win rate over-pricing the Commercial pipeline that is visible. Enterprise is accurate on average but lumpy, with a few large single-deal misses (in the first quarter of 2025 it expected $1.5M and booked $0.5M). Coverage does line up with how quarters ended — quarters read as covered mostly reached quota, quarters read as short never did, though on only a few dozen quarters — but much of that is simply that quota already won is part of both sides of the comparison.

All of the tool's internal accuracy checks pass: its open pipeline matches an independent query to the cent, its quota and wins match the capacity-planning tool's for every complete quarter since 2023, and 14 hand-worked scenarios (covered, thin, short, quota met with and without a win rate, no pipeline, no quota, deals created after the reading date, quarter boundaries and others) all come out as worked.

## Known limitations

- **It is a coverage reading, not a forecast.** It uses one win rate per segment rather than a view of each deal.
- **Commercial is a floor at mid-quarter.** Roughly 23% of Commercial bookings come from pipeline created after the reading, which the tool cannot see.
- **Enterprise rests on little evidence.** About 140 closed deals in the win-rate window, of which about 33 were won, and ten quarters in the backtest; its win rate and its errors move far more than Commercial's. The proof-of-concept view rests on very few wins in its failed group (7 at the November reading) and has not been backtested.
- **Pipeline is counted against the quarter its deal eventually closes in**, the same stand-in for an expected close date the forecast tool uses. That is more information than a live system would have; scoping by creation date plus the recent typical sales cycle instead, which uses no hindsight, gave an error no worse (about 28% overall), while counting every open deal gave about 70%.
- **Quota before 2023 is not a realistic target and no win rate exists before then**, so readings start in 2023.
- **Reps still ramping carry full stated quota**; the ramp discount belongs to the capacity-planning tool. The tool reports how much quota sits with unramped reps.
- **The data ends in late December 2025**, so next-quarter coverage is unavailable at the November checkpoint and the current quarter is unavailable on or after the last recorded close.
- **The covered/thin/short bands and the accuracy target are proposals**, supported by 22 segment-quarters.
