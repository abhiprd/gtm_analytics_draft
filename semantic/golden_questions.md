# Semantic layer — golden NL question set

Regression check for natural-language routing over the MCP semantic layer
(`semantic/server.py`). Each question was run for real against the live
server (`semantic/.venv/bin/python`, tools invoked through
`mcp.server.mcpserver`'s actual `call_tool` path, not the raw Python
functions) on 2026-10-06; the documented outcomes (error codes and resolved calls) were re-checked on 2026-10-08 against `data/acme_gtm.duckdb` +
`semantic/metric_registry.json` v11 (`source_tree_sha256` `f24a0818dc7e...`, 70 nodes, 37 directly queryable).

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
- **Result**: a 24-quarter series. Enterprise has no closed deals in some early quarters (null) and only wins in 2020-07 through 2022-07 (1.0); from 2023-01 it reads 0.14, 0.06, 0.10, 0.22, 0.23, 0.38, then 0.21 (2024-07), 0.23, 0.10, 0.21, 0.26 and 0.32 (2025-10), a recovery trend visible in the data.
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

- **Expected call**: `query_metric(metric="pipeline_generated", grain="quarter")` → a node computed by `analytics/marketing_attribution.py` rather than served from a `mart_*` rollup, should reject.
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
- **Result**: `error: unknown_metric`, `did_you_mean: ["nrr"]`. The server's alias table (`_ALIASES`: net revenue retention → `nrr`, gross revenue retention → `grr`, customer acquisition cost → `cac_by_channel`, and, since v6, the short names of the v5 nodes) points the rejection at the right metric; the alias is a suggestion only, and the query is still not silently substituted.
- **Verdict**: PASS. At registry v1 this question suggested `logo_retention` (character-level `difflib` matching favours the shared word "retention" over the acronym); the alias table closed it.

## 10. "Marketing-sales handoff quality" — is it additive?

- **Expected call**: `query_metric(metric="marketing_sales_handoff_quality")` → should hit the non-additive guardrail, same family as Brand & Awareness.
- **Actual call**: same.
- **Result**: `error: non_additive_metric` (confirmed also `metric_not_queryable`-eligible independently — it has no mart data either, and the message notes both).
- **Verdict**: PASS as implemented. See the main report for the design-decision discussion (tree text: "diagnostic overlay on the above three, not a fourth multiplicative factor" vs. CLAUDE.md's framing of Brand & Awareness as "the one deliberate exception").

## 11. "What's the POC pass rate for Commercial?"

- **Expected call**: `query_metric(metric="poc_pass_rate", filters={"segment": "Commercial"})` → `poc_pass_rate` is Enterprise-only (Commercial has no POC stage), so the source mart has no POC outcomes for Commercial (its Commercial rows exist but the POC columns are empty).
- **Actual call**: same.
- **Result**: `error: segment_not_available`, message "'poc_pass_rate' has no POC data for segment 'Commercial': proof-of-concept outcomes exist only in the Enterprise motion, ... the metric is defined for ['Enterprise'] only." plus its gap note. Without this guardrail the query would return an empty result with a "no rows matched" warning.
- **Verdict**: PASS.

## 12. "How is the Enterprise POC pass rate trending?"

- **Expected call**: `query_metric(metric="poc_pass_rate", filters={"segment": "Enterprise"}, grain="year", date_range={"start": "2024-01-01", "end": "2025-11-30"})`.
- **Actual call**: same.
- **Result**: 2024 = 0.3974, 2025 (to November) = 0.4427, with a `partial` computability warning that monthly n is 10-15 and a quarter or year read is the stable one.
- **Verdict**: PASS.

## 13. "How much of Commercial and Enterprise MRR is overage?"

- **Expected call**: `query_metric(metric="overage_realization", grain="quarter", date_range={"start": "2025-01-01", "end": "2025-11-30"})`.
- **Actual call**: same.
- **Result**: overage MRR as a share of total MRR: 0.3955 (2025-Q1), 0.3751, 0.3633, 0.4166 (2025-Q4 to November). The metric's note states that the realization rate itself is identically 100%, so the dollar share is what is served.
- **Verdict**: PASS.

## 14. "What's stage-to-stage conversion?"

- **Expected call**: `query_metric(metric="stage_to_stage_conversion")` → a registered node with no queryable mapping.
- **Actual call**: same.
- **Result**: `error: metric_not_queryable`, `suggested_alternative: "win_rate"`, message states the conversion is 100% at every hop because every deal logs every stage.
- **Verdict**: PASS.

---

## 15. "What's the renewal win rate for Enterprise in 2025?"

- **Expected call**: `query_metric(metric="renewal_win_rate", filters={"segment": "Enterprise"}, grain="year", date_range={"start": "2025-01-01", "end": "2025-12-31"})`.
- **Actual call**: same.
- **Result**: `0.9333`. The warnings carry the node's note (Commercial renewals close from 2021-02, Enterprise from 2022-07).
- **Verdict**: PASS.

## 16. "How have Commercial discounts moved since 2020?"

- **Expected call**: `query_metric(metric="discount_rate_vs_list", filters={"segment": "Commercial"}, grain="year")`.
- **Actual call**: same, with `date_range` 2020-01-01 to 2025-12-31.
- **Result**: 0.1363 (2020), 0.1214, 0.1130, 0.1284, 0.1234, 0.1212 (2025). The `partial` caveat (the discount is an identity up to rounding, not an independent pricing check) is in `warnings`.
- **Verdict**: PASS.

## 17. "What share of Enterprise losses in 2025 were competitive?"

- **Expected call**: `query_metric(metric="loss_reason_mix", filters={"segment": "Enterprise"}, grain="year", date_range={"start": "2025-01-01", "end": "2025-12-31"})`.
- **Actual call**: same.
- **Result**: `0.3364`, with the warning that the node serves the competitive share of a three-way mix only.
- **Verdict**: PASS.

## 18. "What share of accounts under-use their workflow chain, by segment, in 2025?"

- **Expected call**: `query_metric(metric="workflow_chain_under_utilization", dimensions=["segment"], grain="year", date_range={"start": "2025-01-01", "end": "2025-12-31"})`.
- **Actual call**: same.
- **Result**: SMB `0.0454`, Commercial `0.0245`, Enterprise `0.0031`; `partial` warning about the end-of-window fall-away.
- **Verdict**: PASS.

## 19. "What's ingestion-without-completion by segment in 2025?"

- **Expected call**: `query_metric(metric="ingestion_without_completion_rate", dimensions=["segment"], grain="all", date_range={"start": "2025-01-01", "end": "2025-12-31"})`.
- **Actual call**: same.
- **Result**: SMB `0.095`, Commercial `0.0911`, Enterprise `0.0858`. The note that the ratio is actions-weighted comes back in `warnings` as well as in the metric echo.
- **Verdict**: PASS.

## 20. "How heavy is the Enterprise support-ticket load in 2025?"

- **Expected call**: `query_metric(metric="support_ticket_volume_severity", filters={"segment": "Enterprise"}, grain="year", date_range={"start": "2025-01-01", "end": "2025-12-31"})`.
- **Actual call**: same.
- **Result**: `0.6599` severity-weighted tickets per active account-month.
- **Verdict**: PASS.

## 21. "How much of each segment's 2025 wins land at the band floor?"

- **Expected call**: `query_metric(metric="deal_size_trend_within_segment_band", dimensions=["segment"], grain="year", date_range={"start": "2025-01-01", "end": "2025-12-31"})`.
- **Actual call**: same.
- **Result**: Commercial `0.5896`, Enterprise `0.0`; no SMB row (the mart carries Commercial and Enterprise only).
- **Verdict**: PASS.

## 22. "What's overage for SMB?"

- **Expected call**: `query_metric(metric="overage_realization", filters={"segment": "SMB"})`.
- **Actual call**: same.
- **Result**: `error: segment_not_available` (SMB carries no commitment, so the source mart has no SMB rows).
- **Verdict**: PASS.

## 23. "What's the AM sentiment for SMB in 2025?"

- **Expected call**: `query_metric(metric="am_sentiment_notes", filters={"segment": "SMB"}, grain="year", date_range={"start": "2025-01-01", "end": "2025-12-31"})`.
- **Actual call**: same.
- **Result**: `3.7976`, with the `partial` warning that sentiment is absent for 96% of SMB account-months so an SMB cut is nearly empty.
- **Verdict**: PASS.

## 24. "What's the POC pass rate by segment in 2025?"

- **Expected call**: `query_metric(metric="poc_pass_rate", dimensions=["segment"], grain="year", date_range={"start": "2025-01-01", "end": "2025-12-31"})`.
- **Actual call**: same.
- **Result**: a single Enterprise row, `0.4266`; no Commercial row.
- **Verdict**: PASS.

## 25. "What's AM efficiency for SMB?"

- **Expected call**: `query_metric(metric="am_efficiency", filters={"segment": "SMB"})`.
- **Actual call**: same.
- **Result**: `error: segment_not_available` (SMB has no AM; `queryable_segments` is Commercial and Enterprise). Before v6 this returned a null series.
- **Verdict**: PASS.

## 26. "What's logo retention?" (guards the month-grain tenure/period bug)

- **Expected call**: `query_metric(metric="logo_retention")` at the default grain.
- **Actual call**: same.
- **Result**: a 72-month series, `1.0` in 2020-02 settling near `0.985` to `0.99` (the first month has no starting accounts, so its value is `null`). Every queryable node was also run at month, quarter, year and all grains, with no filter, a segment dimension and each segment filter (740 calls through the real MCP `call_tool` path): none raised.
- **Verdict**: PASS.

## 27. "Logo retention from 2025-02-30" (guards date validation)

- **Expected call**: `query_metric(metric="logo_retention", date_range={"start": "2025-02-30"})`.
- **Actual call**: same.
- **Result**: `error: invalid_request`, "date_range.start '2025-02-30' is not a real calendar date". The same error covers month 13, a start after the end, and keys other than `start`/`end`.
- **Verdict**: PASS.

## 28. "What's Activation time to first Action by segment?" (live series, partial node)

- **Expected call**: `query_metric(metric="activation", grain="year", dimensions=["segment"])`.
- **Actual call**: same.
- **Result**: the real series, returned as data and not an error: 0.0 for Commercial, Enterprise and SMB in every year 2020 to 2025 (`mart_growth_bridge.activation_ttfa_months_avg` is exactly 0 in all 206 segment-months that have a signup cohort; usage is monthly grain, so every first Action lands in its signup month). `warnings[0]` reads "Partially computable: Blended time to first Action is identically 0 in every month and every segment of the current data ... no variance can be computed. Partial, matching the variance-diagnostic engine, which reports Activation as Not computable." `get_metric_definition("activation")` shows `computability: partial`, `computable: true`, children `onboarding_completion_rate` (partial), `time_to_first_integration_first_successful_run` and `quickstart_docs_content_engagement_rate` (both not computable). Before v11 the node was `full` and the series came back with no caveat.
- **Verdict**: PASS. A router should read the zeros as "no variation in the data", not as "instant activation".

---

## Summary

- 26 of 28 questions resolved correctly in the expected number of rounds with no ambiguity (every question except #3, which needs two chained calls, and #8, which is a flagged weakness).
- 1 question (#3, GRR miss) legitimately needs two chained `query_metric()` calls — acceptable, and the chain is fully discoverable from registry cross-references, not hidden knowledge.
- Question 8 ("NPS score") returns no `did_you_mean` suggestion: the fuzzy-match fallback finds nothing for a metric with no textual overlap. Not a correctness issue (the server rejects rather than guesses), and a router recovers by reading `list_metrics()`.
