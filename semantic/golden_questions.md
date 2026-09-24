# Semantic layer — golden NL question set

Regression check for natural-language routing over the MCP semantic layer
(`semantic/server.py`). Each question was run for real against the live
server (`semantic/.venv/bin/python`, tools invoked through
`mcp.server.mcpserver`'s actual `call_tool` path, not the raw Python
functions) on 2026-09-23 against `data/acme_gtm.duckdb` +
`semantic/metric_registry.json` v1 (`source_tree_sha256` `c360c7a2a8f8...`).

For each question: the expected tool call (what a Claude router should
produce from `list_metrics()` + `get_metric_definition()` alone, without
hidden project knowledge), the actual call made here, and the actual
result. Re-run this file's calls whenever the registry is regenerated
(`semantic/build_registry.py`) to catch routing regressions.

How to re-run one row: open `semantic/.venv/bin/python`, `sys.path.insert(0,
'semantic')`, `import server`, then `await server.mcp.call_tool(tool_name,
args)` inside `asyncio.run(...)`.

---

## 1. "What was NRR for Enterprise last quarter?"

- **Expected call**: `query_metric(metric="nrr", filters={"segment": "Enterprise"}, grain="quarter", date_range={"start": "2025-10-01", "end": "2025-12-31"})`
- **Actual call**: same.
- **Result**: `{"period": "2025-10-01", "value": 1.0257}` — resolves correctly on the first call, no clarification needed. `nrr`'s registry name is the literal acronym "NRR" and the tree's own formula/scope_note ("by segment") is unambiguous about the `segment` dimension.
- **Verdict**: PASS.

## 2. "How's Enterprise win rate trending?"

- **Expected call**: `query_metric(metric="win_rate", filters={"segment": "Enterprise"}, grain="quarter")` (no date_range — "trending" implies the full series).
- **Actual call**: same.
- **Result**: 6-quarter series, 2024-07 through 2025-10, values 0.21 → 0.10 → 0.21 → 0.26 → 0.32 (real recovery trend visible in the data).
- **Verdict**: PASS. `win_rate`'s formula note ("new-business only, by segment") and its gap_note about SMB always being 1.0 give a router enough signal to interpret the Enterprise-only cut correctly without asking the user anything further.

## 3. "What's driving the GRR miss this month?"

- **Expected call pattern**: two rounds, both discoverable from the registry alone — (1) `query_metric(metric="grr", grain="month", date_range=<recent 6mo>)` to see the trend/miss, then (2) `get_metric_definition("grr")` shows child `see_growth_contraction_churn_drivers`, whose own `gap_note` says verbatim *"query contraction_churned_consumption_revenue and its children instead"* — so (3) `query_metric(metric="contraction_churned_consumption_revenue", grain="month", date_range=<same window>)`.
- **Actual calls**: both run for 2025-07 through 2025-12.
- **Result**: GRR trend 0.930 → 0.965 → 0.986 → 0.965 → 0.948 → **0.881** (Dec miss), paired with contraction+churn dollars 484K → 249K → 106K → 304K → 502K → **1.18M** (Dec spike) — the decomposition call directly explains the miss.
- **Verdict**: PASS, but flagged as a genuinely **two-round** question (see item 5 of the task brief) — not a clarification failure, since both calls are chained via explicit registry cross-references (the `gap_note` literally names the next metric to query), not guesswork or a request back to the user. Still worth knowing this metric can never be answered in one `query_metric()` call.

## 4. "How's Brand & Awareness trending?"

- **Expected call**: `query_metric(metric="brand_awareness", grain="quarter")` → should hit the non-additive guardrail.
- **Actual call**: same.
- **Result**: `error: non_additive_metric`, message quotes the tree's own note ("leading indicator, not summed into the pipeline math") and separately notes it also has no mart data.
- **Verdict**: PASS. `list_metrics()` already flags `"additive": false` on this node before a router would even attempt `query_metric()`, so a well-built router can pre-empt the rejection — but the rejection path itself is also correct if attempted directly.

## 5. "What's our CAC by channel?"

- **Expected call**: `query_metric(metric="cac_by_channel", dimensions=["channel"])`.
- **Actual call**: same.
- **Result**: `error: dimension_not_queryable` — `channel` is in `allowed_dimensions` (the tree literally names "CAC by channel (unblended)") but not in `queryable_dimensions` (`mart_efficiency` only exposes `blended_cac`, already blended across channels).
- **Verdict**: PASS as a guardrail. This is the intended "allowed-but-not-data-backed dimension" test case, and the message is specific enough for a router to retry sensibly, e.g. re-querying with no `dimensions` argument (segment-level blended CAC) instead of giving up or fabricating a channel cut.

## 6. "What's logo retention for Tier 1 accounts?"

- **Expected call**: `query_metric(metric="logo_retention", filters={"segment": "Tier 1"})` — deliberately using forbidden "tier" terminology (CLAUDE.md's non-negotiable invariant: segment is SMB/Commercial/Enterprise, never "tier").
- **Actual call**: same.
- **Result**: `error: invalid_segment_value`, message explicitly says "never 'tier'".
- **Verdict**: PASS. The guardrail correctly refuses to guess a segment mapping for "Tier 1" rather than silently coercing it.

## 7. "What's our pipeline generated by marketing this quarter?"

- **Expected call**: `query_metric(metric="pipeline_generated", grain="quarter")` → data-gap leaf, should reject.
- **Actual call**: same.
- **Result**: `error: metric_not_queryable`, `suggested_alternative: "new_logo_consumption_revenue"` (its computable parent).
- **Verdict**: PASS. The `suggested_alternative` is exactly right — `pipeline_generated` is one of three multiplicative factors of `new_logo_consumption_revenue`, so redirecting to the parent is the correct fallback.

## 8. "What's our NPS score?"

- **Expected call**: out-of-registry probe. `get_metric_definition("NPS score")`.
- **Actual call**: same.
- **Result**: `error: unknown_metric`, `did_you_mean: []` — **no suggestions at all**, even though "AM sentiment notes" / "account_health_score" (which the tree lists NPS-adjacent signals under) exist in the registry.
- **Verdict**: FLAG (minor). `difflib.get_close_matches(cutoff=0.5)` produces zero matches for short/semantically-related-but-textually-dissimilar queries. Not a correctness bug — the server correctly refuses rather than guessing — but the fuzzy-match fallback gives a router no foothold here. A real Claude router would likely still recover by calling `list_metrics()` and reading full definitions, but the `did_you_mean` mechanism itself is not reliable for acronym/synonym gaps. See also #9.

## 9. "What's net revenue retention for Enterprise?" (spelled-out synonym for NRR)

- **Expected call**: a router with GTM domain knowledge should recognize "net revenue retention" = NRR and call `get_metric_definition("NRR")` or `"nrr"` directly.
- **Actual test**: called `get_metric_definition("net revenue retention")` literally (simulating a router that passes the user's phrase through unmodified rather than resolving to the registry name first).
- **Result**: `error: unknown_metric`, `did_you_mean: ["Logo retention", "logo_retention", "Overage realization"]` — **NRR is not suggested at all**; the top suggestion is the wrong metric (`logo_retention`), because `difflib`'s character-level similarity favors the shared substring "retention" over the acronym "NRR", which shares almost no characters with "retention".
- **Verdict**: FLAG (real gap, not hypothetical). Same pattern confirmed for "gross revenue retention" → suggests `logo_retention`, not `grr`; and bare "CAC" → zero suggestions despite `cac_by_channel` existing. **Recommendation for the builder**: add a small alias table (NRR → "net revenue retention", GRR → "gross revenue retention", CAC → "customer acquisition cost", etc.) to `_resolve_metric`/`_suggestions`, or accept this as a known limitation that a competent LLM router mitigates by reading `list_metrics()` output rather than trusting `did_you_mean`. Does not block shipping (query_metric never silently substitutes the wrong metric — worst case is a correct rejection with a misleading suggestion), but is worth a follow-up ticket.

## 10. "Marketing-sales handoff quality" — is it additive?

- **Expected call**: `query_metric(metric="marketing_sales_handoff_quality")` → should hit the non-additive guardrail, same family as Brand & Awareness.
- **Actual call**: same.
- **Result**: `error: non_additive_metric` (confirmed also `metric_not_queryable`-eligible independently — it has no mart data either, and the message notes both).
- **Verdict**: PASS as implemented. See the main report for the design-decision discussion (tree text: "diagnostic overlay on the above three, not a fourth multiplicative factor" vs. CLAUDE.md's framing of Brand & Awareness as "the one deliberate exception").

---

## Summary

- 8 of 10 questions resolved correctly in the expected number of rounds with no ambiguity.
- 1 question (#3, GRR miss) legitimately needs two chained `query_metric()` calls — acceptable, and the chain is fully discoverable from registry cross-references, not hidden knowledge.
- 2 questions (#8, #9) expose a real but minor weakness in the `did_you_mean` fuzzy-suggestion mechanism for acronym/spelled-out-synonym metric names (NRR, GRR, CAC). Does not cause a wrong answer to be returned — `unknown_metric`/`metric_not_queryable` are always correctly rejected — but the suggestion text itself can point at the wrong metric. Flagged for the builder as a follow-up, not a shipping blocker.
