# Acme Corp GTM Analytics Portfolio — Build Spec

**Purpose:** Portfolio project demonstrating GTM analytics + data engineering + AI-context-layer design, built against a fictional company ("Acme Corp") with a three-segment, touch-differentiated GTM motion and a genuinely consumption-based revenue model (usage metered on "Actions" executed). Built for implementation in Claude Code, phase by phase.

**Companion artifact:** `acme-corp-gtm-metric-tree.md` is the single source of truth for all metric definitions (Growth/Efficiency/Durability, 3 layers deep). This spec defines the company, the motion, and the technical build that the tree gets computed from.

---

## 1. Company Model

**Product:** Closed-source workflow orchestration SaaS. Free trial/freemium self-serve entry; usage-based pricing metered on "Actions" (workflow steps executed).

**Segments**

| Segment | Touch model | ACV range | Cycle length | Coverage model |
|---|---|---|---|---|
| SMB | No-touch (PLG) | $0–$15K | Instant–7 days | Fully automated — no rep |
| Commercial | Low-touch | $15K–$75K | 14–45 days | ISR (new business) + Commercial AM (retention/expansion), pooled book ~200 accounts/rep |
| Enterprise | High-touch | $75K–$750K+ | 60–180 days | AE + SE (new business) + Enterprise AM (retention/expansion), named accounts ~20/rep |

**Revenue mix:** Enterprise ~65–70% of ARR despite being the smallest account count. SMB's ROI case rests substantially on how much of it graduates into paying segments, not on standalone profitability.

**Segment entry (at account creation, independent of acquisition channel):** Firmographic-fit scoring runs at signup or lead creation regardless of how the account arrived. Strong Enterprise-fit signal → Enterprise at entry, even if self-served (an AE is looped in in parallel — a PLG-assisted enterprise motion). Commercial-fit signal → Commercial at entry, ISR follow-up. No strong signal (personal email domain, unmatched company) → defaults to SMB. Outbound SDR is Enterprise-only, targets named lists, and is not an entry path for the other segments. Channel (self-serve, inbound marketing, SDR, graduated) describes *how* an account was acquired; segment describes *what it is* — the two are orthogonal.

**Segment migration (post-entry, for what firmographics couldn't catch at signup):**
- SMB → Commercial: usage/spend crosses ~$1,250/mo for 2 consecutive months, **or** later firmographic re-scoring reveals Commercial fit
- Commercial → Enterprise: usage/spend crosses ~$6,250/mo, **or** firmographic re-scoring reveals Enterprise fit
- No skip-level *migration* (an existing SMB account can't leapfrog Commercial into Enterprise via usage growth) — this restriction applies only to migration, not to entry, since entry has no prior segment to skip from
- `account_segment_history` carries an initial row at account creation (not just at migration), with `trigger_reason` distinguishing four values: `initial_firmographic`, `initial_default`, `usage_threshold`, `firmographic_rescore`

**Pricing/contract mechanics:**
- SMB: metered, month-to-month, no contract, card-on-file
- Commercial: annual contract, committed usage minimum + monthly overage billing
- Enterprise: multi-year, graduated usage commitments, true-up at renewal

---

## 2. GTM Motion Mechanics

**Demand gen channels:** organic/content, paid, community/events — all marketing-owned, feeding all three segments. Outbound SDR is sales-owned, Enterprise-only.

**Funnel by segment:**
- **SMB:** Signup → Trial Active → PQL signal (optional) → Converted or Churned. Gets exactly one `Opportunity` record, created at conversion, immediately Closed Won, no rep owner (`owner_role` = system), amount = initial ACV, no cycle time. No Closed Lost record for non-converting trials — that's a trial-expiry/churn event living in usage data, not a sales loss; SMB has no win-rate concept to true up.
- **Commercial:** Lead/Signup → MQL/PQL → SAL → SQO → Proposal/Negotiation → Closed. No POC stage — the self-serve trial already does the technical-validation job a POC would do.
- **Enterprise:** Lead/Signup/SDR-sourced/graduated → MQL/PQL → SAL → SQO → POC → Proposal/Negotiation (incl. security/procurement) → Closed.

**Roles:** ISR (Commercial new business), AE + SE (Enterprise new business), Commercial AM (Commercial retention/expansion, pooled book), Enterprise AM (Enterprise retention/expansion, named accounts, pairs with an AE when an account's growth justifies renegotiating the contract). SMB has no human role at all, acquisition or retention — no-touch means no-touch on both sides.

**Handoff:** ISR/AE own the account through Closed Won, then hand off to AM for the account's lifetime. Segment migration also migrates AM ownership (Commercial AM → Enterprise AM), typically opening a renewal/expansion opportunity to formalize the bigger contract.

**`fact_opportunities` fields (one pipeline table, filterable, not parallel structures):**
- `opportunity_type`: `new_business` / `renewal` / `expansion`
- `owner_role`: `ISR` / `AE` / `AM` / `system` (SMB)
- `loss_reason`: `competitive` / `no_decision` / `price` / `other`

**Retention/expansion mechanics:**
- Segment migration is excluded from the source segment's churn/contraction — reported separately as "graduated revenue." Otherwise SMB's revenue retention looks artificially bad every time it successfully feeds Commercial/Enterprise. Logo retention is unaffected by migration either way (the account persists, just at a different segment).
- SMB: churn = usage → $0 for N consecutive months, or explicit cancellation. Expansion = organic month-over-month usage growth (metered, no contract to renegotiate).
- Commercial/Enterprise: renewal (contract term end), expansion (usage exceeding the committed minimum → overage billing, continuous, not just at renewal), contraction (lower commitment at renewal), churn (non-renewal).
- Account health score inputs (real monthly time series, not a single score): usage trend (account-relative baseline, not a flat trailing-month comparison — customers span industries with different usage cycles), support ticket volume/severity, engagement/login frequency, AM sentiment notes.
- Retention flow: health score drops → churn-risk flag → AM outreach (activity record) → renewal/expansion opportunity opened ahead of term end → Closed Won (retained/expanded, possibly with segment migration) or Closed Lost (churned, `loss_reason` populated).

---

## 3. Architecture

```
Raw synthetic sources (Phase 1)
   CRM | Marketing automation | Sales engagement | Product/workflow telemetry | Billing
        │
        ▼
dbt: staging → intermediate → marts (Phase 2)
        │
        ▼
Semantic layer: metric registry (= acme-corp-gtm-metric-tree.md) + MCP server (Phase 3)
        │
   ┌────┴─────┐
   ▼          ▼
Variance-      CRO dashboard (Phase 5)
diagnostic     + weekly readout
engine         + embedded chat via same MCP tools
(Phase 4)
```

**Stack:** DuckDB · dbt-core (dbt-duckdb) · Python (generation, diagnostics) · MCP server (Python SDK) · web dashboard (Next.js or Streamlit) · Claude API for the readout's narrative generation and as the NL query interface via MCP.

---

## 4. Data Scope Assumptions

- 36 months monthly grain, quarterly seasonality
- Account counts: SMB ~5,000–8,000, Commercial ~800–1,200, Enterprise ~150–250
- Reps: SMB = 0; Commercial ISRs ~15–25 (book ~200 accounts), Commercial AMs sized to match; Enterprise AEs ~20–30 (book ~20 accounts), SEs ~1:3 AE ratio, Enterprise AMs sized to match
- Unramped reps at ~50% quota capacity for first 2 quarters, any segment/role
- Migration and entry thresholds per Section 1, with noise so neither is perfectly deterministic
- Flat ~80% gross margin assumed for Consumption Payback (not a simulated COGS ledger)
- All data seeded for reproducibility
- **Open tension, not yet resolved:** MMM/incrementality and proxy-metric decay detection both want a long time series to be credible; 36 months monthly is workable but thin for either. Not changing the horizon unilaterally — flagging so it's a deliberate call when those two artifacts get built, not a surprise when they produce a weak result.

---

## 5. Build Phases

### Phase 1 — Raw Source Simulation

Tables, by simulated source system, incorporating everything Sections 1–2 require:

- **CRM:** `accounts` (current segment, firmographic fields incl. region and industry), `contacts`, `opportunities` (`opportunity_type`, `owner_role`, `loss_reason`, `forecast_category`, `list_price` — needed to compute discount realization for pricing/packaging analytics, since we otherwise only have the final negotiated `amount`), `opportunity_stage_history`, `users` (reps: `rep_type` [ISR/AE/SE/AM-Commercial/AM-Enterprise], hire_date, book size), `quota_history` (rep, effective_date, amount — quota is time-varying, not static), `rep_status_history` (rep, status, effective_date — active/departed/on-leave, for headcount trending), `account_segment_history` (initial row at creation + migration rows, 4-value `trigger_reason`)
- **Marketing automation:** `leads`, `campaigns` (with holdout/control-group flags for specific periods — incrementality testing needs a deliberately-excluded group somewhere in the data), `campaign_engagement_events` — channel sub-attribution (organic/paid/community), not a flat channel field, captured at raw touch grain (every touch, not deduplicated to one) so multi-touch attribution is possible later; `marketing_spend_by_channel_month` (channel, month, spend, geo/segment — doesn't exist yet, and several metrics already in the tree assume it does)
- **Sales engagement:** `outbound_activities` (Enterprise only), `meetings_booked`, `fact_sales_activities` (rep, opportunity, activity_type, outcome, timestamp, `competitive_signal` flag — for deal-level diagnostics — individual-activity grain, not pre-aggregated; this is what makes "are meetings correlated with wins" answerable at all)
- **Product/workflow telemetry:** `usage_monthly` (Actions consumed, active workflows), `product_logins` (login/session events — the account health score's engagement-frequency input, deliberately independent of Actions volume so a fully-automated, high-usage account can still show a low login rate), `signups`, `fact_workflow_chain_events` (per-Action-step granularity — upstream/trigger vs. downstream/completion — to detect partial-chain abandonment), `content_engagement` (docs/quickstart interaction, for the Activation branch), `community_membership` (flagged separately for prospects vs. existing accounts — the Expansion branch needs the existing-account population, distinct from New Logo's prospect population)
- **Billing:** `subscriptions`, `mrr_by_account_month`, committed-vs-utilized Action volume per account per month (the input Consumption Payback needs to exclude subsidized, non-consuming accounts)
- **CS-ops:** `support_tickets` (volume, severity, resolution time, CSAT), `am_activity` (touchpoints, QBRs — Enterprise only, check-ins — Commercial), feeding the account health score
- **Forecasting:** `fact_forecast_submissions` (opportunity, snapshot_date, rep_forecast_category, manager_forecast_category — a weekly snapshot, not a single mutable field, since the gap between rep and manager categorization is itself a signal); `cro_forecast_adjustments` (period, segment, adjustment_amount, reason, timestamp — a logged, reasoned override, never silent)
- **FP&A/RevOps:** `gtm_plan_targets` (layer1_metric, month, plan_value, pillar — one row per Layer-1 metric per month, blended/company-wide grain, matching exactly what the Layer-1 scorecard displays). Ten of the tree's eleven Layer-1 nodes carry a plan value; Activation is excluded by design — the readout reports it against a trailing baseline ("2.4d last month"), not a plan figure, so a plan row for it would be unused. Set on an annual planning cycle, grounded in the QA plan's benchmark reference table and this simulation's own business-scale constants, deliberately independent of any other generator's realized output — a plan that read the actuals it's meant to be compared against would make "variance from plan" circular. This is what the Phase 4 variance-diagnostic engine's "compute variance from plan" requirement (Section 5) compares each Layer-1 metric against.
- **Scoring/testing infrastructure:** `lead_scoring_history` (lead, scored_at, model_version, predicted_segment, score components — stored separately from the eventual observed outcome, so a scoring model can be validated against what actually happened); `experiments_registry` (test, hypothesis, treatment/control definition, target + guardrail metrics, result) with assignment flags on the accounts/leads actually in each test
- **Market intelligence:** `market_universe` (prospect company records including non-customers — employee-count band, industry, region, `is_customer` flag linking to `accounts` when true, `icp_fit_score` computed with the same logic as `lead_scoring_history` but applied to the whole universe, not just inbound leads). Every real customer account should also have a corresponding `market_universe` row marked `is_customer = true`, so penetration is a clean ratio rather than an estimate. This single table is what makes TAM/ICP sizing and territory whitespace/allocation genuinely computed rather than hand-mocked — needs enough volume (tens of thousands of rows) to make TAM/SAM math meaningful.
- **Operational log:** `fact_playbook_triggers` (rule_id, account, timestamp, resulting action, outcome — needed to eventually backtest whether the triggers are worth keeping, not just to fire them); `data_quality_checks` (check_name, table, run_date, pass/fail, anomaly detected — the minimum needed to actually demonstrate a governance system operating, not just describe one)

Realism rules: seasonality; segment-specific funnel drop-off (SMB has almost no funnel, Enterprise has heavy POC drop-off); log-normal ACV within each segment's range; usage growth curves that cross migration thresholds for a believable subset of accounts; intentional messiness (nulls, duplicate contacts, occasional backdated stage changes). Everything above is captured at raw event grain and aggregated in dbt, not pre-aggregated in the generator — several artifacts (rep productivity, proxy-metric decay detection, MMM) lose the resolution they need if this is skipped.

### Phase 2 — dbt Data Model

- `stg_*` / `int_*`: standard clean-and-dedupe layer, plus deriving time-in-segment from `account_segment_history` and time-in-stage from `opportunity_stage_history`
- Dimensions: `dim_accounts` (segment + firmographics incl. region/industry), `dim_contacts`, `dim_reps` (`rep_type`, segment, book size — joined against `quota_history` and `rep_status_history` for point-in-time capacity queries), `dim_date`, `dim_campaign`
- Facts: `fact_engagement`, `fact_outbound_activity`, `fact_sales_activities`, `fact_opportunities`, `fact_opportunity_stage_history`, `fact_usage_monthly`, `fact_revenue_monthly`, `fact_account_segment_history`, `fact_workflow_chain_events`, `fact_content_engagement`, `fact_community_membership`, `fact_support_tickets`, `fact_am_activity`, `fact_product_logins`, `fact_marketing_spend`, `fact_forecast_submissions`, `fact_lead_scoring_history`, `fact_playbook_triggers`
- `dim_market_universe` (joins to `dim_accounts` where `is_customer = true`) plus `mart_tam_whitespace` (penetration and whitespace by territory/region/segment, feeding both TAM/ICP sizing and territory coverage)
- Marts aligned to the metric tree's own structure, not an ad hoc list: `mart_growth_bridge` (New Logo / Activation / Expansion / Contraction+Churn), `mart_efficiency` (Magic Number / Consumption Payback / Onboarding-CS Efficiency / AM Efficiency), `mart_durability` (NRR / GRR / Logo Retention), `mart_segment_migration`
- dbt tests: uniqueness/not-null on keys, accepted-values on segment/stage/`opportunity_type`/`loss_reason`/`trigger_reason`, relationships between facts and dims

### Phase 3 — Semantic / Context Layer (MCP)

The metric registry is generated directly from `acme-corp-gtm-metric-tree.md`'s structure (3 pillars → Layer 1 → Layer 2 → Layer 3), not maintained separately. MCP tools: `list_metrics()`, `get_metric_definition(name)`, `query_metric(metric, dimensions[], filters{}, grain, date_range)`. Segment is a default allowed dimension on every segment-scoped metric; channel and `opportunity_type` are allowed dimensions wherever the tree specifies them. Whitelisted metrics only — reject/clarify anything not in the registry, and return the metric's definition alongside every query result.

### Phase 4 — Variance-Diagnostic Engine

The deliverable is the engine that powers the weekly readout's drill-downs, not a fixed report set:

- For any Layer-1 metric, compute variance from plan
- Where variance exceeds a defined threshold (e.g. ±8%), identify which Layer-2 child is the actual outlier among its siblings (not just repeat the Layer-1 miss)
- Where that Layer-2 node has Layer-3 children, surface the 1–2 most relevant leaves as supporting evidence — respecting each branch's real depth (some branches are only 2 layers deep; never fabricate a Layer 3 to force symmetry)
- Watchlist selection: composite health-score threshold breach, ranked by ARR at risk
- Playbook triggers: binary threshold rules (e.g. "14+ days of ingestion-without-completion," "POC pass rate below 60%," "30 days post-close under 50% committed-Action utilization") — thresholds stored as configurable rules, not hardcoded into a narrative prompt, with a log of which triggers fired and what action resulted

### Phase 5 — CRO / Leadership Interface

Proven-out structure (see the sample readout in `acme-corp-claude-design-brief.md` for the exact content shape):

- Header: reporting period, audience
- Executive summary: narrative that names a specific Layer-2/3 cause for any real miss, not just "metric X is down" — pull qualitative context (AM notes, exit-interview-style reasons) into the narrative where available, and call out two-sided causes (what helped, what offset) when a metric moved from opposing forces
- Layer 1 scorecard: all 11 nodes, every week, unconditionally — value, vs. plan, status
- Drill-downs: variable, generated only for Layer-1 nodes whose Phase 4 engine found a real Layer-2 outlier — never padded to a fixed count
- Automated playbook triggers: whatever fired this week, unranked (binary, not prioritized)
- Forecast and watchlist sections, same variance/threshold logic as above

---

## 6. Sequencing & Scope Guardrail

Phases 1–3 are the technical backbone and the actual differentiator — go deep here. Phase 4's variance-diagnostic logic (the drill-down selection rule) is the piece that makes Phase 5 honest rather than decorative; don't under-scope it. Phase 5: a clean digest view + forecast view + segment-efficiency view + one working chat demo is enough; resist building a full BI platform.

## 7. Design Decisions and Open Questions

**Established:** entry logic is firmographic-driven and channel-independent; migration `trigger_reason` has 4 values, not 2; AM (not ISR/AE) owns retention/expansion; `opportunity_type`/`owner_role`/`loss_reason` are real fields; account health score inputs are genuine time series; marketing's footprint is distributed across New Logo/Activation/Expansion with population-distinct metrics, not duplicated.

**Still open:**
- Dashboard framework: Next.js vs. Streamlit
- Exact variance threshold for triggering a drill-down (used ±8% in the sample readout — confirm or adjust)
- Whether to model a full COGS ledger instead of the flat ~80% gross margin assumption

---

## 8. Analytics Artifact Portfolio

The full set of analytics artifacts this portfolio is designed to eventually include, beyond the metric tree itself. Each is either **built** (real Phase 1 data supports it directly) or **simulated** (ships as a hand-constructed illustrative example, no generated data pipeline behind it — same treatment as the sample weekly readout).

**Built, fully data-backed:**
1. Metric tree
2. Forecast (sales bottoms-up + ML/regression + CRO overlay)
3. Capacity planning (absorbs quota setting & attainment analysis — is the quota mathematically achievable given capacity, not just headcount count)
4. Account health score / churn-risk model
5. Segment/segmentation migration analysis
6. Marketing attribution & channel mix analysis
7. Variance-diagnostic engine
8. Semantic layer / AI context layer *(infrastructure)*
9. Weekly executive readout
10. Automated playbook triggers
11. Lead/segmentation scoring — model validation & drift detection
12. MMM / incrementality-based measurement
13. Testing/experimentation methodology & platform *(infrastructure)*
14. Rep productivity & coaching diagnostics
15. Proxy-metric health / analytics investment prioritization *(infrastructure/governance)*
16. Pricing / packaging analytics
17. Deal-level diagnostics (the evolution of Pipeline Scanner — per-opportunity risk detection, not just aggregate variance)
18. Data quality / metric governance *(infrastructure/governance)*
19. Scenario planning / sensitivity analysis (propagates a changed assumption through the tree's existing equations — distinct from forecast, which predicts, not simulates a hypothetical)
20. Retention / expansion cohort analytics (descriptive, population-level view by acquisition vintage — distinct from #4, which is predictive and account-level)
21. Territory / account coverage & routing, including whitespace and TAM-allocation
22. TAM / ICP / opportunity-sizing model

Both #21's whitespace piece and #22 run off a single new data source (see Phase 1) rather than being hand-mocked — generating a fake non-customer market universe costs little more than generating another account table, and it's the only way either artifact is genuinely computed rather than illustrated.

**Explicitly absorbed, not standalone:** quota setting (→ Capacity Planning, #3); LTV:CAC and marginal-CAC economics (→ enhancement to the Efficiency pillar's existing Magic Number / Consumption Payback nodes, not a new artifact); customer journey / time-to-value (→ already covered by the Growth pillar's Activation branch and the Growth→Durability arc — a new artifact only if the ask becomes feature-level adoption sequencing specifically).

**Build priority order.** Not an arbitrary ranking — grouped into waves by genuine dependency, since several artifacts within a wave can be built in parallel and pretending otherwise would be dishonest. Wave 0 is Phase 1 + Phase 2 themselves — nothing below exists as a *built* thing until then.

- **Wave 1 (core measurement loop, really one build effort):** Metric tree → Account health score → Segment migration → Variance-diagnostic engine → Weekly executive readout. The readout is the forcing function that proves the first four work against real generated data.
- **Wave 2 (the rest of the weekly operating cadence):** Forecast, Capacity planning, Marketing attribution & channel mix.
- **Wave 3 (infrastructure before more gets built on ungoverned data):** Data quality / metric governance, Semantic layer / AI context layer.
- **Wave 4 (deal/rep depth, builds on Wave 1–2, not required for the core loop):** Deal-level diagnostics, Rep productivity & coaching diagnostics, Automated playbook triggers (needs Wave 1's thresholds validated against real data first).
- **Wave 5 (strategic/market-facing, runs off `market_universe`, not part of weekly cadence):** Territory / coverage & routing, TAM/ICP, Pricing/packaging analytics.
- **Wave 6 (advanced methods needing Wave 2's baseline and the tree's equations fully live):** MMM/incrementality, Scenario planning, Retention/expansion cohort analytics.
- **Wave 7 (last by necessity — not computable meaningfully until real history accumulates):** Lead-scoring model validation & drift detection, Testing/experimentation platform, Proxy-metric health / analytics investment prioritization.

---

