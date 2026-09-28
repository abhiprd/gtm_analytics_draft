---
source: analytics/territory_coverage.py
---

# Territory Coverage & Routing

## What this is

A check on whether new-business sales reps are actually placed where the market opportunity sits, territory by territory — not just how many reps exist in total. It's built for sales leadership and RevOps to answer a specific question: is a given territory under-staffed, over-staffed, or roughly proportionate to the size of the opportunity in front of it, and by how much?

## Why it exists

The business runs new-business coverage through reps working defined geographic patches — Inside Sales reps prospecting into Commercial accounts, Account Executives prospecting into Enterprise accounts. That model only works as designed if headcount in each territory actually tracks where the opportunity is; a territory with a large, high-fit prospect base and a thin roster is structurally handicapped in its ability to contribute new revenue, no matter how well the reps assigned to it perform. This tool exists to turn "does our territory staffing match the market" from an impression into a measured, defensible answer.

## How it works

For each of the five sales territories, the tool compares that territory's share of new-business reps against its share of the market opportunity — measured three separate ways, so the read isn't tied to one narrow definition of "opportunity." The first measure is the number of companies in the territory that fit the target customer profile but aren't customers yet. The second narrows that same population down to just the best-fit companies among them. The third looks at the territory's current customer count instead of unclaimed prospects, to check whether even the existing book of business is proportionately staffed. Each of the three produces a single index number: a territory holding exactly its proportional share of reps reads as 1.0; below 1.0 means the territory is under-staffed relative to that slice of opportunity; above 1.0 means it's over-staffed. The tool also runs a separate, purely arithmetic exercise showing what it would take, in headcount terms, to bring every territory to that 1.0 mark if the total rep count stayed fixed and reps could simply be reshuffled across territories.

## Key decisions and why

- **Three different measures of opportunity are used side by side, rather than settling on one.** Checking unclaimed prospects, the best-fit subset of those prospects, and the existing customer base separately confirms whether a staffing gap is narrowly a missed-prospecting problem or something broader about how a territory's whole book is resourced — a distinction worth seeing rather than assuming away.
- **Opportunity is measured in company counts, not dollar value.** A dollar-weighted version would require borrowing a revenue-per-account assumption that belongs to a separate sizing exercise elsewhere in the portfolio; using company counts instead keeps this read self-contained and avoids introducing a second, potentially inconsistent dollar figure into the conversation.
- **A direct comparison was used instead of a predictive model.** Territory is a current snapshot of who covers what, not a time series with enough history to train a model against, and the question leadership actually needs answered — is headcount proportionate to opportunity right now — is a straightforward ratio, not something worth approximating with a probability.
- **Reps and prospects are counted as of the same specific date, not as static totals**, for the two measures that genuinely change over time — reps are hired and depart, and companies keep signing up as new customers throughout the period. The unclaimed-prospect count is the one exception: it reflects the full history of company data available rather than a clean point-in-time cut, a gap that is measured directly (see Known limitations) and confirmed too small to change which territories read as most and least covered.
- **The finding was checked at two different points in time, six months apart, rather than accepted from a single snapshot.** Both checkpoints show the same territory reading as most under-resourced and the same one reading as most over-resourced, at essentially the same magnitude — evidence the finding reflects a genuine, persistent staffing pattern rather than a one-off artifact of when the numbers happened to be pulled.
- **The "what would it take to equalize" calculation holds total headcount fixed and treats reshuffling as the only lever**, rather than assuming new hiring. This keeps the exercise honest as a structural read of the current roster rather than a disguised hiring request.

## What drives the result

- **Which reps are counted** — only new-business roles: Inside Sales reps (selling into Commercial accounts) and Account Executives (selling into Enterprise accounts), the reps who actually open new territory-based accounts. Account managers, who handle existing customers rather than a geographic prospecting patch, aren't part of this measure.
- **Three yardsticks for "opportunity"** — the count of not-yet-customer companies that fit the target profile, that same group narrowed to just the strongest-fit companies, and the territory's current customer count.
- **The coverage index itself** — a territory's share of new-business reps divided by its share of whichever opportunity yardstick is being used; 1.0 is proportionate, below 1.0 is under-staffed, above 1.0 is over-staffed.
- **The rebalancing exercise** — holding total headcount fixed, what each territory's headcount would need to be for every territory to land exactly at a coverage index of 1.0.

## Current result

As of December 31, 2025 (confirmed again against a June 30, 2025 checkpoint, with the same pattern holding both times): APAC is the most under-resourced territory on every one of the three yardsticks — a coverage index of roughly 0.51 measured against unclaimed prospects, 0.61 against the best-fit subset of those prospects, and 0.52 against existing customer accounts. In practical terms, APAC carries only about half the reps its share of the opportunity would call for, and that shortfall shows up whether the opportunity is measured by unclaimed prospects or by the customer base already on the books — this isn't narrowly a missed-prospecting gap.

LATAM sits at the opposite end on all three yardsticks — a coverage index of roughly 1.55 against unclaimed prospects, 2.72 against the best-fit subset, and 1.68 against existing accounts, meaning it carries meaningfully more headcount than its share of the opportunity alone would justify. NA-East and NA-West both run modestly over their proportional share (coverage index around 1.2 and 1.16), while EMEA runs modestly under (around 0.72–0.82 across the three measures) — a real but far more moderate gap than APAC's.

The rebalancing exercise, holding total new-business headcount fixed at 39 reps, shows that bringing APAC's coverage index to exactly 1.0 would take about 3 additional reps (2.84, rounded up since a fractional rep can't be hired) — funded, on paper, by trimming roughly 3 reps from NA-East, 1.5 from NA-West, and 1 from LATAM. All of the tool's own internal accuracy checks pass, including a check confirming that the tool genuinely detects this staffing pattern in the data rather than assuming it.

## Known limitations

- **The unclaimed-prospect count isn't measured as of the same specific date as reps and existing accounts** — it reflects the full company-data history available rather than a clean point-in-time cut, which could slightly overstate how many companies are already customers as of an earlier checkpoint. That effect is measured directly at roughly 1.3% of the unclaimed-prospect pool at the earlier checkpoint tested — real, but far too small to change which territory reads as most or least covered.
- **Opportunity is measured in company counts, not dollar value.** A large, high-value prospect and a small, marginal one count the same in this read; a dollar-weighted version would need a revenue-per-account assumption from elsewhere in the portfolio and isn't built here.
- **The "what would it take to equalize" figure is a structural exercise, not a staffing recommendation.** It doesn't and can't account for the cost of moving or hiring reps, whether reps would actually be willing to relocate, the ramp-up time a newly placed rep needs before reaching full productivity, or the fact that LATAM's headcount is deliberately held above its strict proportional share to keep the territory functionally staffable at all. Taken literally, the exercise would pull headcount out of LATAM — but that would run directly against the reason LATAM carries the headcount it does, so the numbers should be read as a structural reference point, not acted on directly.
- **Inside Sales and Account Executive headcount are treated as one interchangeable pool** in the rebalancing math, since opportunity isn't currently broken out by Commercial fit versus Enterprise fit at the territory level. A sharper version — Commercial-fit opportunity against Inside Sales headcount, Enterprise-fit opportunity against Account Executive headcount, each separately — would sharpen the read further and is a natural next step, not built yet.
- **Account manager capacity for the existing customer book isn't measured here.** Account managers own a portfolio of specific accounts rather than a geographic territory, so that capacity question is already covered elsewhere in the portfolio and isn't duplicated in this tool.
- **A supplementary view of open new-business pipeline by territory is included for context but isn't comparable across time.** At the most recent checkpoint the simulated pipeline is fully closed out, so that view is empty there by construction and only populated at the earlier checkpoint — it's reported as descriptive detail only and doesn't feed the coverage-index finding above.
