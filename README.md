# Acme Corp GTM Analytics Portfolio

An end-to-end GTM analytics stack for Acme Corp, a fictional consumption-based B2B SaaS company: simulated raw data → dbt data model → semantic layer → diagnostic analytics → a CRO-facing weekly readout. Built to demonstrate GTM analytics, data engineering, and AI-context-layer design as a single coherent system rather than a collection of disconnected notebooks.

Every number in this repo is generated, not sampled from a real company — but it's generated with real causal structure (win probability, churn probability, and usage growth are functions of their actual drivers, not independently random columns), so every diagnostic artifact built on top of it has something real to find.

## The company

Acme Corp sells workflow orchestration software, priced on metered usage ("Actions" executed). Three segments — SMB, Commercial, Enterprise — differentiated by touch model, deal size, and coverage, with accounts migrating upward as usage or firmographics cross defined thresholds (never downward: an account that fails to activate churns entirely rather than demoting). Channel (how an account was acquired) and segment (what it is) are orthogonal.

## Workflow: data → analytics → feedback

The system is a loop, not a pipeline. Diagnostic output doesn't just get read — it drives account-level action (AM outreach, playbook triggers), and the outcome of that action shows up in next period's raw data, closing the loop back into the same metric tree that flagged it.

```
┌─────────────────┐     ┌──────────────┐     ┌───────────────┐     ┌────────────────────┐     ┌──────────────┐
│  1. Raw source   │────▶│  2. dbt data │────▶│  3. Semantic   │────▶│  4. Diagnostic       │────▶│ 5. CRO       │
│     simulation   │     │     model    │     │     layer      │     │     analytics        │     │    readout   │
│                  │     │              │     │     (MCP)      │     │                      │     │              │
│  Event-grain     │     │ staging →    │     │ Metric tree,   │     │ Account health score,│     │ Weekly       │
│  CRM, billing,   │     │ intermediate │     │ registry-      │     │ segment migration,   │     │ scorecard +  │
│  usage, CS-ops,  │     │ → dims/facts │     │ backed query   │     │ variance-diagnostic  │     │ narrative    │
│  marketing spend │     │ → marts      │     │ tool           │     │ engine, forecast      │     │ drill-downs  │
└─────────────────┘     └──────────────┘     └───────────────┘     └──────────┬───────────┘     └──────┬───────┘
        ▲                                                                      │                        │
        │                                                                      ▼                        ▼
        │                                                          ┌────────────────────┐    ┌──────────────────┐
        └──────────────────────────────────────────────────────────┤ Playbook triggers /  │◀───┤ AM outreach,      │
                                   next period's                    │ churn-risk flags     │    │ renewal/expansion │
                                   raw data reflects                │ (threshold rules,    │    │ opportunity       │
                                   whether the                      │ logged fire + result)│    │ opened            │
                                   intervention worked               └──────────────────────┘    └──────────────────┘
```

Concretely, the loop that actually runs through the data model:

1. **Account health declines** — usage trend, support ticket volume/severity, and AM sentiment all move together in the months before a real churn (this is generated causally, not decorative noise; a naive classifier on these inputs lands at ~0.65–0.80 AUC, not ~0.5 or ~0.98).
2. **The variance-diagnostic engine** flags the account (or the segment-level metric it rolls up into) once its health score crosses a threshold, and drills from the Layer-1 metric that missed plan down to the actual Layer-2/3 driver — not just "revenue is down."
3. **A playbook trigger fires** off that same threshold (binary rule, e.g. "30 days post-close under 50% committed-Action utilization"), logged with what action resulted — not just fired silently.
4. **AM outreach happens** (`am_activity`), and a renewal or expansion opportunity opens ahead of term end.
5. **The opportunity closes** — Won (retained/expanded, possibly with a segment migration) or Lost (churned, `loss_reason` populated) — and that outcome lands back in the raw event data.
6. **Next week's readout** recomputes the same metric tree against the new data, so the drill-down either disappears (intervention worked) or persists/worsens (it didn't) — the same diagnostic loop runs again, informed by what actually happened.

## The metric tree

Every parent metric is the literal mathematical result of its children (sum, product, or ratio) — never a "related metrics" grouping. Two deliberate exceptions, both explicitly marked non-additive in the tree's own text: Brand & Awareness (a leading indicator, not summed into the pipeline math) and Marketing–sales handoff quality (a diagnostic overlay on New Logo's three multiplicative factors, not a fourth factor).

- **Growth** — `Starting + New Logo − Contraction − Churn + Expansion` (± segment migration, nets to zero). New Logo decomposes into Pipeline Generated × Win Rate × Avg Initial Commitment; Expansion into Wallet Share Progression × Overage Realization; Contraction/Churn into workflow under-utilization, account health score, and renewal win rate.
- **Efficiency** — is the touch model paying for itself. Magic Number, Consumption Payback (CAC ÷ utilized-Action margin), Onboarding/CS Efficiency, AM Efficiency.
- **Durability** — is what we sold sticking. NRR, GRR, Logo Retention.

Full formulas, owners, and layer depth: [`docs/acme-corp-gtm-metric-tree.md`](docs/acme-corp-gtm-metric-tree.md).

## Repo structure

| Path | Contents |
|---|---|
| `docs/` | Company model, GTM motion, schema, and metric-tree reference docs — the single source of truth for anything defined here |
| `generators/` | Phase 1 Python generators — one module per simulated source system (CRM, billing, usage, CS-ops, marketing) |
| `data/raw/` | Generator output (CSV), seeded for reproducibility |
| `dbt/` | Phase 2 dbt-duckdb project — staging → intermediate → dimensions/facts → marts |
| `tests/` | QA plan's pytest suite — referential integrity, distributional realism, correlational validity, volume sufficiency, edge-case existence |
| `semantic/` | Phase 3 MCP server + metric registry, generated from the tree file |
| `analytics/` | Phase 4 variance-diagnostic engine, health score, forecast, capacity planning |
| `dashboard/` | Phase 5 CRO-facing web app |

## Build status

Built phase by phase, each validated against real generated data before the next begins.

- [x] **Phase 1 — Raw source simulation**: raw tables across CRM, billing, usage, CS-ops, and marketing spend (including `campaigns`/`leads`/`campaign_engagement_events` and `fact_forecast_submissions`/`cro_forecast_adjustments`, added in Wave 2), causally wired and incident-injected.
- [x] **Phase 2 — dbt data model**: staging through the core marts (`mart_growth_bridge`, `mart_efficiency`, `mart_durability`, `mart_segment_migration`) plus TAM whitespace.
- [x] **Phase 3 — Semantic layer (MCP)**: metric registry generated from the tree file + MCP server (`list_metrics`, `get_metric_definition`, `query_metric`) under `semantic/`.
- [~] **Phase 4 — Analytics artifacts**: Wave 1 (metric tree, account health score, segment migration, variance-diagnostic engine, weekly executive readout), Wave 2 (forecast, capacity planning, marketing attribution & channel mix), and Wave 3's data quality / metric governance module are built and validated. Waves 4–7 (deal-level diagnostics, rep productivity, playbook triggers, territory/TAM, MMM, scenario planning, lead-scoring drift, experimentation platform) remain.
- [ ] **Phase 5 — CRO / leadership interface**

Known, deliberate gaps rather than silent placeholders: no rep-cost data exists yet, so Magic Number and AM Efficiency are null rather than fabricated; there's no territory dimension in the raw data yet, so TAM whitespace has none either.

## Stack

DuckDB · dbt-core (dbt-duckdb adapter) · Python · MCP Python SDK · Claude API for the readout's narrative generation

## Running it

```bash
# Phase 1 — generate raw data
python3 -m generators.run_foundation
python3 -m generators.run_batch2
python3 -m generators.run_batch3
python3 -m pytest tests/ -v

# Phase 2 — build and test the dbt project
cd dbt && dbt build
```
