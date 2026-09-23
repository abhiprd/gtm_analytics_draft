---
source: analytics/weekly_readout.py
---

# Weekly Executive Readout

## What this is

The single document a Chief Revenue Officer and the GTM leadership team would actually sit down and read: one page, per reporting period, that shows how the business is doing against plan across all eleven top-level GTM health measures, explains why any that missed actually missed, and flags which accounts are most at risk of walking away. It's built for GTM leadership as the regular operating-cadence read, not a one-off analysis.

## Why it exists

Building a metric tree, a health score, a migration analysis, and a diagnostic engine only pays off if leadership actually sees the results in one place, on a regular cadence, in a form built to be read rather than queried. This is that artifact — the capstone that proves the rest of the core measurement loop genuinely works together against real data, not just individually. It's the intended final stop for a leader who wants the state of the business without having to open four different tools to get it.

## How it works

Each period, the readout pulls together everything the other three artifacts have already produced — the eleven headline scorecard figures, the causal explanations behind any real miss, and the list of at-risk accounts — and lays it out in one consistent document: a scorecard up top, a section that digs into whatever actually went wrong that period, and a watchlist of the accounts most worth a leader's attention. It doesn't calculate a single new figure itself; every number it shows was already produced and checked by the artifact responsible for it, and the readout's only job is to assemble, format, and present those numbers faithfully, the same way a chief of staff assembles a board packet from other people's already-approved slides rather than redoing the analysis.

## Key decisions and why

- **The readout is built to add nothing of its own to the numbers it shows.** Every figure is read directly from the artifact that owns and has already validated it, rather than recalculated or adjusted along the way — this was independently confirmed by spot-checking several figures end to end and finding them identical, bit for bit, back to their source. A document meant to be trusted at a glance can't be the place where a number quietly drifts from the analysis behind it.
- **The scorecard always shows all eleven top-level measures, every period, with no exceptions** — including the two where there's currently no way to compute an actual cost figure, and one that behaves in a structurally unusual way in this dataset. Each of those is shown honestly, with its own gap explained, rather than dropped from the page to make the document look tidier than the business actually is.
- **The section that explains what went wrong is only ever as long as it needs to be.** It shows one entry for every measure that actually missed its target that period and nothing more — never padded out to look thorough, never trimmed to look better, including periods where nothing missed at all and the section says so plainly rather than disappearing.
- **The at-risk account list is drawn straight from the account health score rather than built as a second, separate risk judgment.** Maintaining two different opinions about which accounts are risky would leave leadership guessing which one to trust; reusing the same validated source keeps the whole document internally consistent.
- **The narrative paragraph that would normally explain "what happened and why" in plain prose is deliberately left out of this build, rather than faked with a templated stand-in.** A generated paragraph that reads like an explanation but doesn't actually reason through the cause would be worse than no paragraph at all. What's built instead is everything that paragraph would need to draw on — the fully assembled scorecard, drill-downs, and watchlist — left ready for that piece to be added as its own, separate step. Two other sections, automated playbook triggers and a forecast, are held to the same honest-placeholder standard: both are later work, and both say so directly in the document rather than being silently missing.

## What drives the result

- **The Layer-1 scorecard** — all eleven top-level GTM health measures, shown every period without exception
- **The variance-diagnostic engine's drill-downs** — a deeper explanation for each measure that actually missed its target that period, reused exactly as that engine produced it
- **The account health score's watchlist output** — the accounts flagged as most at risk, ranked by how much revenue is estimated to be on the line
- **Two sections marked plainly as not yet built** — an automated set of account-level triggers and a forward-looking forecast, both scheduled for later work

## Current result

As of the November 2025 reporting period, the readout renders correctly on every check it's held to: all eleven top-level measures present every time, a drill-down section that lines up exactly with the count of measures that actually missed target that period (seven, in this period), and a watchlist pulled straight from the health score's own output. A second period was checked the same way and produced a consistent shape, and a deliberately impossible-to-trigger test period confirmed the drill-down section correctly renders as "nothing missed" rather than an empty gap when that's the honest result. Twenty separate checks were run against the document — covering both the underlying data behind it and the actual rendered page — including checks added specifically to make sure a number printed on the page can never quietly drift from the number it was supposed to show. All twenty passed.

## Known limitations

Every gap this document shows is inherited from the artifacts that feed it, not introduced here, and each carries its own explanation forward rather than being smoothed over. The most consequential one to know about going in concerns the at-risk account watchlist: because there's currently no way to know an individual account's actual contract value — only the average for its segment — ranking accounts by estimated revenue at risk skews the list toward whichever segment has the largest typical contract size. In the current period, that means the watchlist at its default length shows only Commercial accounts. No Enterprise accounts are at risk this period, and SMB — which actually has by far the largest number of at-risk accounts — doesn't appear until the list is made longer, purely as a side effect of how the estimate is built rather than because those accounts matter less. This is a known, explained consequence of a stand-in revenue figure, not a defect, and it resolves once real account-level revenue data exists to rank against.

Two smaller notes for completeness: the executive summary paragraph and the automated playbook-trigger and forecast sections are honest placeholders rather than finished content, each labeled as such in the document itself; and there is currently no policy for keeping a historical archive of past readouts versus overwriting each period's document with the next — that's an open question that doesn't need settling until the document runs on a regular cadence.
