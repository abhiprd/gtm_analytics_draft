# Acme Corp GTM Portfolio — Post-Wave-8 Improvement Plan

Source documents: `01-build-audit` (engineering/process review), `02-cro-readiness-gaps` (read as the CRO), `03-revops-integration-plan` (read as VP RevOps). A fourth document, `04-signal-to-action`, makes a separate case for buying external data and building an activation/decisioning layer — it's addressed at the end as **Track B**, not folded into the core plan, for reasons explained there.

## Why one plan instead of three lists

All three audit documents independently produced a priority ranking, and they don't fully agree — a CRO ranks by what gets asked in a meeting, RevOps ranks by operational leverage, the build audit ranks by ledger tier (how much new work a fix actually requires). Where they agree, that's the strongest possible signal. Where they disagree, this plan states the resolution and why.

**Where all three converge — this is not a close call:**
- Rep cost/comp data is the #1 item in *every single document* (01's P0, 02's ask #1, 03's next #1). One missing input kills 2 of 11 Layer-1 scorecard metrics (Magic Number, AM Efficiency) and blocks 8 downstream nodes. It is also the cheapest fix in this entire plan — one field, grounded against real comp bands, added to a Phase 1 generator that already knows how to do this.
- Trigger outcome capture is independently called the highest-leverage item in 03 ("the cheapest... in this document") and the sharpest process finding in 02 (an alert nobody owns, with `outcome = null` on all 1,558 rows) and a contributing fact in 01's reproducibility finding.

**Where they disagree, and how this plan resolves it:**
- 01 ranks orchestration/CI as P2 (after wiring fixes); 03 ranks it "Now" alongside the outcome-capture fix. **Resolution: orchestration moves up to Wave 9**, not because either document is wrong, but because 03's argument is structural — nothing built in later waves is trustworthy on a schedule until something produces it on a schedule, and every subsequent wave in this plan depends on that being true. Sequencing it late would mean re-validating every later fix by hand.
- 02 wants the executive-summary narrative in the very next release (it's the CRO's #3 ask, and the one section built for them that's empty); 03 puts it in "Then" (item 8, after the operational base). **Resolution: keep it late (Wave 11)**, per 03's argument — a narrative generator sitting on top of a scorecard that's still missing two metrics and running on stale manual triggers would need rework the moment Wave 9/10 land. Shipping it after the base is more honest to the CRO than shipping it twice.

## Wave 9 — Make the scorecard whole and stop the loop from leaking (days, not weeks)

Everything here is P0 in at least one source document and appears in at least two.

| Item | Closes | Effort | Source |
|---|---|---|---|
| **Rep cost/comp field** — OTE + fully-loaded cost on `users.csv`, exposed through `dim_reps`, grounded against real SaaS comp bands, seeded like every other distribution in this project | Magic Number + AM Efficiency (2 of 11 Layer-1 nodes, currently structurally NULL forever) + 8 blocked tree nodes. Ends the worse-than-blank state where a plan target exists against an actual that can't. | Days | 01 P0 · 02 ask#1 · 03 next#1 |
| **Fix the stale `pipeline_generated` marking** — it's `NOT_COMPUTABLE` in the variance engine while `marketing_attribution.py` already computes and validates it | The one Tier-A ledger item; also the cautionary case for Wave 12's cross-artifact audit | Hours | 01 finding 03 |
| **Trigger outcome capture** — a writer for the `outcome` column that already exists on `fact_playbook_triggers` | Makes all 1,558 historical triggers, and every one going forward, falsifiable. Without this, no rule can ever be tuned on evidence — don't touch threshold tuning before this ships. | Days | 03 C2 (their highest-leverage item) · 02 gap#6 (partial) |
| **Owner + SLA on triggers** — join to the rep/territory assignment that already exists in the data model, add an SLA clock and manager escalation | Turns an alert log into a task list. Also what makes 94%-from-one-rule defensible or not — an unowned queue can't be triaged either way. | Days | 03 C3 · 02 gap#6 |
| **One orchestration layer + freshness contract** — a single DAG replacing 19 independent `__main__` entrypoints, CI that fails when the metric-tree identity checks fail (the governance module already runs these checks, it has no enforcement point), a stated freshness SLA per artifact | The precondition for trusting anything below this line on a schedule, and the first fix a portfolio reviewer will notice is missing (01 calls it disqualifying for anything operational) | ~1 week | 01 P2, pulled forward · 03 C1 ("Now") |
| **Document all 11 generator batches in the README** (currently 3 of 11 are documented) | Cold-clone reproducibility — a credibility gap 01 says a reviewer hits in the first ten minutes | Hours | 01 finding 05 |

**Wave 9 gate:** the scorecard shows 11/11 live Layer-1 metrics with no plan-target-against-a-void state anywhere; a fresh clone can rebuild the dataset from a documented sequence; a trigger fired today can, in principle, be marked resolved. Nothing in Wave 10 starts before this is true — Wave 10's mart-exposure work is worthless if the pipeline producing those marts isn't trustworthy yet.

## Wave 10 — Close the wiring gaps (1–2 weeks)

Ten of the build audit's 21 catalogued gaps are Tier B: the raw data already has the field, it's just not exposed through a mart. This is the highest-volume, lowest-risk wave in the plan — no new modelling, no new validation regime, just joins and columns.

| Item | Closes | Source |
|---|---|---|
| Expose `loss_reason`, `discount_rate`, `list_price`, stage transitions through the marts layer | Loss-reason mix over time, competitive win rate (02 gap#4), discount-vs-list, deal-size trend | 01 P1 · 02 gap#4 |
| Expose workflow-chain under-utilization and overage realization (both already materialised upstream) | Two Layer-2 tree nodes that are defined in the metric tree but currently can't populate | 01 P1 · 04 (overage realization is also the node 04 flags as needed for real-time expansion triggers, but that part is Track B) |
| Fix `account_health_score`'s stale computability marking (Tier C — no new data, blocks 5 nodes) | Same failure class as `pipeline_generated`; check this against the actual current code the moment Wave 9's audit-culture fix lands, don't assume it's still broken | 01 P1 |
| **Pipeline coverage artifact** — by segment, against realized conversion, gap to quota in dollars. No new data required; open pipeline, stage, segment, and historical conversion all exist in the marts today. | The CRO's #2 gap, asked every Monday | 02 gap#2 · 03 next#4 |
| **Win/loss aggregate** — loss-reason mix and competitive win rate, aggregated over time/segment (not just per-deal) | 02 gap#4 — "can diagnose a single deal, cannot characterize a pattern" | 02 gap#4 · 03 next#5 |
| **Persistence flag on drill-downs** — reuse the drift-monitor's existing "2 consecutive breaches" pattern, point it at business metrics instead of just model calibration | Turns "this missed" into "this is the third consecutive month" — the CRO's stated line between weather and a decision | 02 gap#5 |
| **Weekly grain for the metrics that actually support it** — per `dashboard-design-conventions`' native-grain table (pipeline generated, MQL SLA, win-rate drivers, activity volume, ticket volume); Layer-1 stays monthly, no exceptions | Aligns the diagnostic layer with the cadence the business actually meets on | 03 note · dashboard-design-conventions §8 |
| **Segment migration promoted off the analyst tab** — "are we moving upmarket" surfaced as a headline view, not a drill-down. Presentation only, the computation is already built and validated. | 02 gap#7 — a standing board narrative currently buried | 02 gap#7 |

**One item in this wave isn't from the original three audits, and isn't wiring — flag it as heavier than the rest of this table:**

| Item | Closes | Source |
|---|---|---|
| **LTV by segment × acquisition channel** — new Layer-2 node under Consumption payback (metric tree, updated), new Phase 4 model (retention curve × margin × expansion trajectory, 5-year horizon, 10% discount rate — see `acme-corp-analytics-methods.md`) | Neither 01, 02, nor 03 caught this, but the build spec itself already anticipated it: Section 8 explicitly names "LTV:CAC and marginal-CAC economics" as absorbed into Magic Number/Consumption Payback rather than built standalone — this item is that absorption, finally done, not a new scope addition. MMM and marketing attribution currently optimize against short-term outcomes (win rate × initial deal size), which can systematically misallocate spend toward channels that convert cheaply but retain/expand poorly. LTV:CAC by channel is the correction, and it's a precondition for the `business-analyst` agent's own worked example (an MMM-driven budget-reallocation brief) being trustworthy. | Placement per build-spec Section 8's original design intent |

**Two things to check before scoping the build, not after:**
- Acquisition channel needs to persist as a stable account attribute through to the revenue/retention fact tables. Segment-level LTV works without this; the channel split — the actual point of building it — doesn't.
- `retention_cohorts.py` (Wave 6) already tested acquisition channel as a retention driver and found no comparable differentiation. Expect this model's channel signal to come mainly from CAC and segment-mix differences, not from differential retention curves — and expect the LTV:CAC ratio to inherit Consumption Payback's existing fully-loaded-CAC gap (it's marketing-spend-only until Wave 9's rep-cost fix lands), same as Magic Number and AM Efficiency.

**Wave 10 gate:** every Tier-B ledger item is closed; the CRO's five "still can't get" items from doc 02's cold-open are down to two (narrative + persistence, both deliberately deferred to Wave 11/10 respectively — check persistence lands here); LTV by channel is live and any attribution/MMM-based brief written after this wave states its LTV:CAC context rather than optimizing on conversion alone.

## Wave 11 — The last mile: delivery, narrative, and the CRM round-trip (1–2 weeks)

Everything below is genuinely easier than Waves 9–10 technically, but each item is deferred until now on purpose: shipping the narrative or the CRM sync against a scorecard that's still missing metrics or running on unowned triggers means redoing it once those land.

| Item | Closes | Source |
|---|---|---|
| **Executive summary narrative generation** — the seam is built (the structured readout already assembles everything a narrative step would consume); wire the deferred Claude API call | 02's #3 gap and the CRO's literal complaint: the one section written for them is the one that's empty | 02 gap#3 · 03 item#8 |
| **Push delivery** — Slack/email digest from the weekly readout, which already renders to Markdown/JSON | "A dashboard is a place you have to decide to visit"; every real GTM rhythm is push | 03 C4 |
| **CRM round-trip (reverse ETL)** — health score, risk tier, next-best-action written back to the CRM account record via Hightouch/Census | The only version of this work that reaches a rep, and the natural place outcome capture actually happens (pairs with Wave 9's C2) | 03 C5 |
| **Promote the semantic layer to the governed integration contract** — every downstream consumer (BI, bots, future syncs) goes through the metric registry, not around it | Prevents the standard failure mode (four teams, four definitions of NRR) as more consumers get added | 03 C6 |

**Note on convergence:** the CRM round-trip above is the *same deliverable* as Track B's Phase-1 "reverse ETL" (see below) — build it once here, and Track B inherits it for free if it's ever greenlit.

**Wave 11 gate:** a CRO or AM can act on this system without opening the dashboard — a Slack digest lands, a CRM field updates, a narrative sentence names the actual driver.

## Wave 12 — Validate the validations (ongoing, not a one-time wave)

01's P3, unchanged — this is process discipline, not a ship-and-done item.

- Backtest all 14 `PROPOSED, not yet confirmed` thresholds against a second period; promote or revise each. A threshold tested only against the data it was derived from is a guess with a decimal point.
- Run `drift-monitor` on an actual cadence (via Wave 9's new orchestration layer) instead of the current 5 ad-hoc checkpoint dates; feed or retire the 3 hooks with zero persisted readings.
- Run the cross-artifact analogue of the dashboard's independent QA pass. This is 01's sharpest "what worked" finding: the builder/critic split on the dashboard caught 8 real defects invisible in code review, and it's been applied to exactly one of six surfaces. Point the same discipline at the 20 analytics artifacts, none of which have ever been cross-audited by anything other than the agent that built them.

## Track B — External signal and activation platform (separate decision, not part of this plan)

`04-signal-to-action` makes a real argument, backed by a number the project generated itself (fit-score AUC ceiling of 0.557 — firmographics genuinely don't contain the answer). But it's a different kind of bet than Waves 9–12: it's new vendor spend, new data-privacy exposure (person-level enrichment), and a genuinely new capability (L0 identity, L1 external signal) rather than closing a gap in something already built. It also explicitly ends its own document with four open questions the author says aren't settled.

This plan doesn't fold it in, for one concrete reason: **04's own Phase 1 gate is "an account has a domain, has people, and a score we compute reaches a rep's screen" — and that last clause is the Wave 11 CRM round-trip.** Track B is not blocked on Waves 9–10 conceptually, but its first phase can't complete until Wave 11 ships anyway, so there's no version of this plan where it should start earlier than that. If greenlit, Track B's own Phase 1 (domain-as-key, person entity, reverse ETL, outcome capture) becomes cheap to start once Wave 9's outcome-capture and Wave 11's reverse-ETL work already exist — build once, serve both plans.

Recommendation: treat Track B as a Wave-13-or-later decision, revisited once Wave 11 ships, not a parallel effort now.

## What this plan doesn't try to solve

Consistent with 01's closing finding: this backlog is still an artifact list dressed as a plan. The better question for whoever runs Wave 13 planning is 01's own reframe — *"which decision does this artifact serve, and can it actually be computed end to end today?"* — asked as a gate on every future addition, not just a retrospective finding.
