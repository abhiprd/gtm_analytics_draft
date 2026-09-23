---
source: analytics/variance_diagnostic.py
---

# Variance-Diagnostic Engine

## What this is

The tool that explains *why* a top-line GTM number moved, not just that it moved. Each month, it checks all eleven of the metric tree's headline numbers against plan (or, for the one metric with no formal plan target, against its own recent trend) and, for any real miss, automatically traces the cause down to the specific driver responsible — for example, confirming that a revenue miss came from a drop in win rate specifically, rather than a smaller pipeline or smaller average deal size. It's built for whoever assembles or reads the weekly leadership readout, so every reported miss arrives with a specific, evidence-backed reason attached rather than a bare number.

## Why it exists

The metric tree is deliberately built so every top-line number is the exact mathematical result of the sub-drivers beneath it — the pieces really do multiply or add up to the parent figure, not just relate to it loosely. That structure only pays off if something actually uses it to explain a miss in real time, rather than leaving leadership with "revenue is down" and no next question answered. This engine is what turns the tree from a reference document into an active diagnostic — the reasoning step between "here are the eleven headline numbers" and "here's specifically what's wrong and where to look next" — and it's the mechanism the weekly executive readout's drill-down sections depend on.

## How it works

Each month, the engine compares every headline metric to its plan target, with one exception: the metric measuring how quickly a new account reaches first real value has no formal plan figure, so it's compared instead against its own trailing three-month average. When a metric's gap from plan (or from its own trend) is large enough to matter, the engine doesn't stop at the headline number — it looks at that metric's real sub-components, compares each of them against its own recent trend, and identifies whichever one has moved the furthest out of line, the same reasoning a sharp analyst would apply by hand, done consistently and automatically every time. Where that sub-driver itself breaks down into more granular detail, and the underlying data genuinely supports it, the engine pulls in the one or two most relevant pieces of supporting evidence beneath it. It never invents structure that isn't there — some drivers genuinely stop at one level of detail, and the engine reports that honestly rather than forcing a false sense of depth everywhere.

## Key decisions and why

- **A deterministic, rule-based approach was used instead of a fitted statistical model.** The relationship between a top-line metric and its sub-drivers is an exact mathematical identity — the pieces genuinely multiply or sum to the parent figure — so estimating that relationship statistically would introduce guesswork into arithmetic that already has one right answer. Directly calculating the tree's own logic is the accurate approach here, not a simplified stand-in for something more sophisticated.
- **The engine is built so it cannot mistake a sub-driver for a top-line number, or compare a driver against the wrong peer group.** Every metric's position in the framework — which level it sits at, and which other metrics it's a fair comparison against — is fixed by the underlying structure and read directly from it every time, rather than decided case by case as the engine runs. An independent review specifically tried to make the engine misfire in exactly this way, using deliberately constructed edge cases designed to trip it up, and could not.
- **Correctness is checked against known-answer test cases, not a statistical accuracy score.** Because this is a diagnostic tool rather than a predictive one, there's no equivalent of a forecasting model's accuracy percentage to report. Instead, it was checked against five hand-built scenarios, each with a single, unambiguous correct answer worked out in advance — including one scenario built specifically to try to defeat the layer-mislabeling guardrail above. All five resolved to the correct answer.
- **Where the underlying data can't support a finding, the engine says so explicitly rather than approximating around the gap.** A handful of drivers the framework calls for simply aren't measurable from data that exists today. Rather than substitute a rough proxy to fill the space, the engine reports the gap by name, so a "no driver identified" result can be trusted as an honest data limitation rather than mistaken for "nothing is wrong."
- **Two metrics can't be compared to plan at all, and the engine reports that as a known gap rather than fabricating a number.** Efficiency ratios that depend on rep cost and compensation data have no such data anywhere in the underlying system to compute an actual value against. The engine still reports the plan target for both, but leaves the actual and the variance explicitly blank rather than inventing a figure to complete the comparison.
- **The swing that decides whether a metric earns a closer look is carried forward from an early illustrative example, and is explicitly flagged as a starting point rather than a confirmed, final number.** It's adopted from a hand-built sample report that illustrates what this kind of readout looks like, and is intentionally left open for confirmation once the reporting cadence and real operating experience can settle what the right sensitivity actually is.
- **The plan figures for revenue retention and revenue expansion are derived from one shared calculation rather than set as two independently-chosen numbers, so the two targets are always mathematically consistent with each other.** A plan that could quietly contradict itself would make any variance measured against it untrustworthy before the comparison even starts.
- **Automatically flagging individual accounts against fixed rule-based triggers is deliberately left for a later phase of work, not built alongside this engine.** Building that automation on top of a threshold that hasn't yet been run against real, live results and proven reliable would risk automating the wrong signal; it's sequenced to follow only once this engine's own thresholds have been validated against real data.

## What drives the result

- **Plan targets** — one top-down target per headline metric per month, set independently of that same period's actual results, so the comparison isn't circular
- **Actual performance** across growth, efficiency, and durability, rolled up to the same company-wide view the plan targets are set at
- **The account health score's output**, reused as-is to identify at-risk accounts for the watchlist — not a second, separate risk model
- **The variance threshold** — a swing of roughly 8% in either direction from plan (or from trend, for the one metric without a plan figure) before a metric is flagged for a closer look
- **An eight-month trailing average** as the comparison baseline for identifying which specific sub-driver has moved furthest out of line once a metric is flagged

Coverage of the framework's sub-driver detail is honest rather than padded: a little over half of the sub-drivers the framework calls for are currently computable from existing data, and the framework's deepest level of detail — the specific evidence one step below that — isn't available anywhere in the data pipeline yet, for any branch. Where a branch's data doesn't exist, the engine reports that plainly rather than guessing.

## Current result

As of November 30, 2025 — the most recent month treated as a fully representative read (the final month of the underlying simulated history is deliberately excluded from normal interpretation, since it's cut off mid-pattern rather than reflecting a real steady state) — running the engine against the current numbers flags 7 of the 11 headline metrics as meaningfully off from plan or trend, each with a diagnosis attached wherever the underlying data supports one.

All five of the known-answer test scenarios, including the one built specifically to try to defeat the layer-mislabeling guardrail, resolved to the correct answer.

The engine was also tested against a real pattern deliberately built into the underlying data: one marketing channel's acquisition cost was made to climb steadily over a three-month stretch. Run across that window, the engine correctly flagged the resulting efficiency miss and pointed to the right underlying driver — rising acquisition cost in that specific channel, not a margin problem — in two of the three months; in the remaining month the two candidate drivers were close enough to each other that it named the wrong one.

## Known limitations

- **The framework's deepest level of supporting detail isn't computable from real data for any branch yet.** The engine is built to surface it wherever it exists, but none of that detail is currently available anywhere in the pipeline — closing that gap needs additional raw data collection, not a change to this engine.
- **Two metrics — the efficiency ratios that depend on rep cost and compensation data — can't be compared to plan at all**, because no source anywhere in the underlying system captures that cost data. This is reported as an explicit, known gap rather than filled with an estimated number.
- **Two of the eleven metrics — the revenue retention rates — currently show a plan-vs-actual gap that traces to a data-definition issue, not a real business miss.** The way "revenue contraction" is counted in the underlying data currently treats any small month-to-month dip the same as a meaningful, lasting pullback, which inflates the gap versus a plan built around durable, mature-book retention. A closely related figure with no such counting ambiguity — logo retention — lands within 2% of its plan target, which is the evidence that the retention-rate gap is a definitional issue on the measurement side rather than an actual performance problem.
- **This artifact isn't tracked for ongoing performance drift the way the predictive health score is.** Its correctness was checked once, at build time, against the known-answer scenarios and the real injected pattern described above; there's no equivalent of a monitored accuracy score to watch decay over time, since it isn't a model that can drift in that sense.
