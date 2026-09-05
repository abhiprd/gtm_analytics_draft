---
name: sync-portfolio-docs
description: Use whenever a change is made to the metric tree, company model, schema, or artifact list for the Acme Corp GTM portfolio. The four reference docs (build spec, metric tree, design brief, QA plan) and the slide deck cross-reference each other and have gone stale independently multiple times during design. This skill is the checklist for propagating a change everywhere it needs to go in one pass, instead of discovering the staleness later.
---

# Keeping the Acme Corp portfolio docs in sync

## When this applies

Any of: a metric's formula, owner, or layer position changes · a segment/company-model rule changes · a new field or table is added to the schema · an artifact is added, removed, or rescoped · a terminology change (this has happened once already — tier → segment).

## Checklist — go through all five, not just the one you're thinking of

1. **`docs/acme-corp-gtm-metric-tree.md`** — the metric definition itself, if that's what changed
2. **`docs/acme-corp-gtm-portfolio-build-spec.md`** — company model / schema / artifact list / Phase 1–5 sections. Also check Section 8's artifact count and build-priority tiers if an artifact was added, removed, or rescoped.
3. **`docs/acme-corp-claude-design-brief.md`** — duplicates tree and readout content as verbatim text for handoff purposes; it does not just reference the other files, so it goes stale silently if skipped
4. **`docs/acme-corp-phase1-data-qa-plan.md`** — check whether the change adds a new invariant, edge case, or test case
5. **The slide deck** (edit the generator script → rebuild → validate → render → visually QA before overwriting the `.pptx`) — if the change touches anything the deck displays: metric names, formulas, segment counts, card counts

## Known failure modes from this project's own history — don't repeat these

- A file gets renamed but an old copy resurfaces or lingers alongside it — always list the output directory after a rename to confirm the old file is actually gone; don't assume the rename succeeded.
- A term gets globally replaced but a different, legitimate use of the same word gets swept up incorrectly (e.g., "tiered pricing," a graduated-pricing-levels concept, vs. "tier" meaning the segment concept). Grep every instance with surrounding context before a blanket find-and-replace — never blind-replace a common word.
- A count stated in prose (e.g., "10 nodes" vs. "11 nodes," "6 additions" vs. "7") appears in more than one place, and only some of them get updated when the count changes. Grep for the old number specifically after any addition or removal — don't rely on remembering everywhere it was mentioned.
