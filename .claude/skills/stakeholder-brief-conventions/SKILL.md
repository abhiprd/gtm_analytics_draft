---
name: stakeholder-brief-conventions
description: Read before writing any stakeholder-facing decision brief for the Acme Corp GTM portfolio — a document whose job is to turn an existing analytics artifact into something a specific person acts on (an investment call, a build priority, a process fix). Distinct from dashboard-design-conventions, which governs the live Streamlit app; this governs one-shot narrative documents like the CRO/RevOps/build-audit briefs. Load this before drafting one, not after.
---

# Stakeholder brief conventions

This project has already produced four documents that got this right — a build audit, a CRO-readiness assessment, a RevOps integration plan, and a strategic case for external data. They share a pattern that isn't accidental, and this file exists to make that pattern repeatable rather than something that has to be reinvented by feel each time. Read those four as reference implementations alongside this file.

## 0. The test a brief has to pass before it ships

**"What does the reader do differently after reading this?"** If you can't answer that in one sentence, it's not a stakeholder brief yet — it's a status update, and this repo already has places for those (`docs/acme-corp-analytics-methods.md`'s own entries, `docs/asset-briefs/`, `dashboard/project_status.json`), not here.

This rules out two common failure modes:
- **A tour of the system.** Describing what was built, however accurately, is not a decision. "We built an MMM model" is a status update. "Reallocate $180K of paid spend from Channel X to Channel Y based on this MMM's marginal-return curve, and here's the confidence interval" is a brief.
- **A wish list with no owner.** A gap that nobody specific is positioned to close isn't ready to be someone's brief yet — see Section 2.

## 1. Write it in the reader's seat, not about the reader

The strongest technique the four reference documents share: **02 and 03 are written in first person, as the stakeholder** ("I have sixty seconds on Monday morning..."; "My test for any analytics investment is simple..."). This isn't a style flourish — it forces the actual discipline of the exercise. You cannot write "I have sixty seconds and a board meeting Thursday" without first deciding exactly what that person needs in sixty seconds, which is a much harder and more useful question than "what does this system compute."

Doc 01 (the build audit) and 04 (the strategic case) are written in a reviewer/advocate voice instead of first-person-as-stakeholder — appropriate there because their reader is closer to the builder (an engineering audience, or a peer decision-maker weighing a proposal) rather than someone consuming a finished capability. Use first-person-as-stakeholder whenever the brief's reader is a business stakeholder consuming output; use the reviewer/advocate voice when the reader is evaluating a build or a proposal on its merits.

Before writing a word, answer explicitly (this becomes the brief's header):
- **Who is this for** — one named role, not "leadership" or "the team." (CRO, VP RevOps, CFO, board, CMO — never a group.)
- **What decision are they actually making** — a budget reallocation, a build priority call, a go/no-go, a headcount ask. If you can't name the decision, you don't have a brief yet, you have a topic.
- **What's their actual cadence with this** — a weekly Monday review, a quarterly board meeting, an ad hoc call. This determines the brief's framing (see Section 3's "asked" cadence tags) and whether it should exist as a recurring artifact or a one-time memo.

## 2. The audience → decision-owner map

Use this as a first pass, not a substitute for checking who actually owns the decision in a given case — the map exists so the same kind of finding doesn't get routed to the wrong desk by default.

| Decision type | Owner | What they need stated explicitly |
|---|---|---|
| Marketing/channel spend reallocation (MMM, attribution) | CMO or CRO if marketing rolls up to them | Dollar magnitude, which channels move which direction, confidence interval, cost of doing nothing |
| Sales capacity / headcount | CRO, sometimes jointly with CFO | Quota-vs-capacity gap in reps, ramp-adjusted, cost per rep vs. expected return |
| Pipeline sufficiency / demand generation | CRO or VP Marketing | Coverage ratio vs. historical conversion, by segment, gap to quota in dollars |
| Platform/build investment (engineering priority) | Whoever owns the roadmap — often VP RevOps or Eng lead, not the CRO | Effort estimate, what it unlocks, what breaks if deferred |
| Retention/expansion process fix (AM staffing, playbook tuning) | VP CS/AM or VP RevOps | ARR at risk, current intervention rate, cost of the fix vs. ARR protected |
| External data/vendor spend | Whoever owns the budget line — often RevOps or Marketing Ops, with CRO sign-off above a threshold | Cost, what it's expected to move (cite the internal validation ceiling if one exists, the way 04 did with its 0.557 AUC number), a probation/evaluation gate before renewal |
| Board/investor narrative | CEO or CRO, brief written for them to relay upward | The 2–3 numbers a board actually asks about, framed against plan, not against the system's internal complexity |

If a brief doesn't fit a row above, name the decision-owner explicitly anyway — don't skip this step because the mapping is ambiguous.

## 3. Structure

Follow this shape; the four reference documents all use it with only cosmetic variation.

1. **Eyebrow line** — context and audience in one line ("Read as the Chief Revenue Officer · Acme Corp").
2. **H1 title** — short, names the subject, not "Q3 Report."
3. **Lede** — 2–4 sentences, the thesis stated in full, in the reader's voice if using that mode. This is the one paragraph someone reads if they read nothing else — it must contain the actual verdict, not a preview of one.
4. **A cold numbers strip or a works/doesn't-work split** immediately after the lede — orient the reader with hard figures or a two-column reality check before any narrative argument starts.
5. **Numbered sections**, each with a one-line head. Don't exceed ~9 sections; if you need more, the brief is trying to be two documents.
6. **Ranked findings within a section** — each finding gets a rank number, a claim stated as a title (a question or an assertion, not a topic label), a cadence tag if relevant ("Asked every board meeting"), the pain in plain language, and a **"what closes it"** sub-block citing the specific, concrete fix.
7. **A build-order or action section**, phased, each phase effort-labeled and ending in a **gate**: an observable, checkable condition that proves the phase is actually done — not "was worked on," but "an account has a domain, has people, and a score reaches a rep's screen."
8. **Open questions**, if genuine ones exist — state your own lean, but don't disguise an undecided call as settled. A brief that manufactures false certainty to look more finished is worse than one that names what it doesn't know.
9. **A closing honest-assessment callout** — name what's genuinely good before the reader leaves, specifically the hard parts that are easy to take for granted (data discipline, validation rigor, refusal to fabricate). Every reference document does this; it's not padding, it's the thing that keeps a critical brief from reading as a indictment when the underlying work is actually strong.
10. **Footer citation** — exactly what this was assessed against (a commit, a PR, an `as_of_date`, a specific script). A brief that makes claims about a system's state needs the same grounding discipline the system itself is held to.

## 4. Evidence discipline — never state a number without its source

Every claim in a brief must trace to something a reader could go verify. The reference documents never say "the data shows X" — they say `mart_efficiency` casts the field to `null as double`, or cite the exact AUC (0.542) against the exact ceiling (0.557) with the exact sample size (n=40,207). Do the same:

- Cite the specific mart, model, script, or field, not "the analytics layer."
- Cite the specific figure, not a rounded impression — if the real number is 1,558, don't write "over 1,500."
- If an artifact isn't confirmed built-and-validated — check `docs/acme-corp-analytics-methods.md`'s own entry (a filled Target/Achieved pair vs. a `TBD` or `PROPOSED, not yet confirmed` line), the build spec's built/simulated marker, or `dashboard/project_status.json` for a dashboard-facing claim — **do not build a brief's central claim on it.** Cite the honest state instead ("this model is proposed, not confirmed") the same way the build audit did with its 14-of-15-thresholds finding, rather than treating a proposed threshold as settled fact.
- When a number carries real uncertainty (a confidence interval, a bootstrap result, a "ceiling" derived from a different calculation), state it — 01's fit-score section is the model for this: the honest ceiling (0.557) is what makes the finding a business case rather than a modelling complaint.

## 5. Color and visual identity for a brief

Briefs use the same base palette as the rest of the portfolio (see `dashboard-design-conventions` Sections 2.2–2.3) but with one addition: **each brief picks a single accent color tied to whichever pillar or theme the document's primary lens belongs to**, and uses it consistently for its eyebrow text, header rule, section-number monospace tags, and rank numerals.

| Brief's primary lens | Accent |
|---|---|
| Growth / build-and-engineering review | Navy `#1E2761` |
| Efficiency / systems and RevOps integration | Teal `#1C7293` |
| Durability / retention and CRO-facing readiness | Terracotta `#B85042` |
| A cross-cutting strategic proposal outside the three pillars | A distinct signal color not otherwise used (the reference strategic doc uses amber `#B45309`) — reserve this for genuinely new-category proposals, not routine reports, so it keeps its meaning as "this is a bigger decision than the usual brief" |

This is a different color role than Palette B's red/green/amber status semantics in `dashboard-design-conventions` — a brief's accent color identifies *which lens the whole document takes*, not the favorable/unfavorable status of any individual metric. Don't reuse status red/green as a brief's accent color; it will misread as a value judgment on the whole document before anyone reads a word.

Typography and base styling (Source Serif 4 headers, Inter body, light/dark `:root` variable pairs) follow `dashboard-design-conventions` Section 5.4 exactly — these are the same fonts for the same licensing reason, and a reader who's seen a dashboard page and then a brief should recognize them as the same system.

## 6. What a brief is not

- **Not a replacement for the project's own status records.** Status ("where are we") lives in `docs/acme-corp-analytics-methods.md`, `docs/asset-briefs/`, and `dashboard/project_status.json` — not here. A brief assumes the reader already knows or doesn't need to know full build status — it exists to get them to a decision, not to audit the repo for them.
- **Not a place to introduce a new number.** A brief translates and frames existing, already-computed output. If the number doesn't exist yet, the brief's job is to say so and name what would produce it — not to estimate it to fill the gap.
- **Not audience-agnostic.** The same underlying system produced 02 and 03, and they ask almost entirely different questions because they're for different decision-owners. Never write one brief and mentally relabel it for a second audience — write it again, from that reader's actual seat.
