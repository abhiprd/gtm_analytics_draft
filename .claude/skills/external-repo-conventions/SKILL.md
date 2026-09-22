---
name: external-repo-conventions
description: Use before every commit, and before any change to a doc under docs/, for the Acme Corp GTM portfolio repo. This repo is meant to be shared publicly as a portfolio piece — commit messages, the changelog, and every production doc must read as a deliberate engineering artifact, with no trace of the iterative design conversation that actually produced it.
---

# External-facing repo conventions

## The one rule everything else follows from

Nothing in the public-facing repo should reveal that this was built through back-and-forth conversation with revisions, reversals, and changed minds. Not because that process is something to hide in general — it's normal engineering — but because a portfolio repo reads as evidence of deliberate design skill, and a visible trail of "renamed X because it was confusing" or "added Y after realizing Z was missing" reads as indecision rather than iteration, even when the opposite is true. Every commit, and every production doc, describes **what the system is and does**, not **how the author arrived at it**.

**Exception: tool attribution is not conversation narration.** The standard `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` git trailer is fine on every commit Claude authors or co-authors — it's a plain attribution line, not a reference to what was discussed or decided. The rule below still bans narrating the conversation itself (what was asked, discussed, or changed as a result of feedback); it does not ban this one trailer.

## Commit messages

Format: Conventional Commits — `type(scope): summary`, body only if the change needs more than one line of explanation.

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `data`, `chore`. Scope is the area touched (`schema`, `metric-tree`, `dbt`, `semantic-layer`, `deck`, etc.).

**Never write, in any commit message:**
- "per request," "as discussed," "user asked," "based on feedback," any personal name (the repo owner's or anyone else's) — the `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer is the sole exception, per above
- Anything that frames the commit as a correction of a prior mistake in the *design* (e.g., "fix: correct the segment concept that was confusing people") — if the underlying decision changed, describe the resulting system, not the fact that a decision changed: `refactor(schema): rename tier field to segment for clarity with standard GTM terminology` reads as a deliberate technical choice; `fix: rename tier to segment since it was confusing` reads as walking something back.
- Hedged or exploratory language ("try," "attempt," "maybe," "WIP" beyond a genuinely in-progress branch)

**Good examples:**
- `feat(schema): add account_segment_history with four-value trigger_reason`
- `refactor(metric-tree): split combined NRR/GRR node into two independent Layer-1 metrics`
- `data(generators): add deliberate incident injection for proxy-metric decay detection`

## CHANGELOG.md — this is where history actually lives

All revision history goes here, in [Keep a Changelog](https://keepachangelog.com) format — versioned or `Unreleased` sections, with `Added` / `Changed` / `Fixed` / `Removed` subheadings. Same rule as commits: neutral, technical, no process language.

- `Added AM efficiency metric to the Efficiency pillar` — not "Added AM efficiency metric to address a gap identified during review"
- `Renamed tier to segment throughout the schema and documentation` — not "Renamed tier to segment per feedback that it was ambiguous"

## Production docs never carry revision residue

`docs/acme-corp-*.md` and `CLAUDE.md` describe the **current** state only. Never write "(previously called tier)," "NEW:," "this used to be X," or any inline note about what changed. If a doc needs an edit to reflect a decision, edit it in place so it reads as if it was always this way — the changelog is the only place "before/after" exists.

## Before every commit, self-check the message and diff for these red flags

`user`, `asked`, `requested`, `discussion`, `feedback`, `decided`, `per your`, `as you said`, `previously`, `used to`, any personal name, or any first/second-person pronoun referring to a conversation. Any hit means rewrite before committing, not after. The `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer is not a hit — it's expected on every Claude-authored commit and the self-check should skip it.

## If process-revealing commits already exist

Check `git log --oneline` before writing a single new commit. If the existing history is small and/or already reveals the design conversation, don't try to sanitize each commit individually — reset to a single clean initial commit (`git checkout --orphan clean-main`, re-add everything, one commit: `chore: initial commit — Acme Corp GTM analytics portfolio scaffold`) and force-push once, before anyone else has cloned it. This is far lower-risk than editing history commit-by-commit and missing one.
