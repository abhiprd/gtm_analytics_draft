"""Semantic layer server (semantic/server.py) and registry (semantic/metric_registry.json).

Guards the failures an independent validation of registry v5 found: a period
expression rewritten by string replacement broke tenure_at_churn at month grain,
date_range accepted impossible dates, a node with no AM rows listed SMB as
queryable, and the alias table did not cover the nodes added in v5.

The server's tool functions are plain Python; when the `mcp` package is not
importable (this suite runs under the root interpreter, the SDK needs Python
3.10+) a stand-in for MCPServer is injected so the same functions are exercised.
One test goes through the real MCP call path when the SDK is available.
"""
import asyncio
import importlib.util
import json
import os
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_PATH = os.path.join(REPO, "semantic", "server.py")
REGISTRY_PATH = os.path.join(REPO, "semantic", "metric_registry.json")
DB_PATH = os.path.join(REPO, "data", "acme_gtm.duckdb")

pytestmark = pytest.mark.skipif(not os.path.exists(DB_PATH), reason="data/acme_gtm.duckdb not built")

GRAINS = ("month", "quarter", "year", "all")
SEGMENTS = ("SMB", "Commercial", "Enterprise")

with open(REGISTRY_PATH) as _f:
    REGISTRY = json.load(_f)
METRICS = REGISTRY["metrics"]
QUERYABLE = [k for k in REGISTRY["metric_order"] if METRICS[k]["computable"]]


def _mcp_available() -> bool:
    try:
        import mcp.server.mcpserver  # noqa: F401
        return True
    except Exception:
        return False


MCP_REAL = _mcp_available()  # decided before any stand-in is injected


def _load_server():
    if not MCP_REAL:
        class _StubMCPServer:
            def __init__(self, *args, **kwargs):
                pass

            def tool(self, *args, **kwargs):
                return lambda fn: fn

            def run(self, *args, **kwargs):
                raise RuntimeError("stub")

        for name in ("mcp", "mcp.server", "mcp.server.mcpserver"):
            sys.modules.setdefault(name, types.ModuleType(name))
        sys.modules["mcp.server.mcpserver"].MCPServer = _StubMCPServer
    spec = importlib.util.spec_from_file_location("acme_semantic_server_under_test", SERVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


server = _load_server()


def q(metric, **kwargs):
    return server.query_metric(metric, **kwargs)


# --------------------------------------------------------------------------
# D1: every queryable node x every grain runs without raising
# --------------------------------------------------------------------------

class TestNodeGrainMatrix:
    def test_the_registry_has_queryable_nodes(self):
        assert len(QUERYABLE) >= 37

    @pytest.mark.parametrize("grain", GRAINS)
    @pytest.mark.parametrize("key", QUERYABLE)
    def test_no_node_raises_at_any_grain(self, key, grain):
        node = METRICS[key]
        if not node["additive"]:
            pytest.skip("non-additive nodes are rejected before any SQL")
        variants = [{}, {"dimensions": ["segment"]}]
        variants += [{"filters": {"segment": s}} for s in SEGMENTS]
        for kwargs in variants:
            result = q(key, grain=grain, **kwargs)
            segment = kwargs.get("filters", {}).get("segment")
            if segment and segment not in node["queryable_segments"]:
                assert result["error"] == "segment_not_available", (key, grain, kwargs, result)
            else:
                assert "error" not in result, (key, grain, kwargs, result.get("message"))
                assert isinstance(result["data"], list)
                if grain == "all":
                    assert all("period" not in row for row in result["data"])
                else:
                    assert all("period" in row for row in result["data"])

    @pytest.mark.parametrize("grain", GRAINS)
    def test_every_non_queryable_node_gives_a_structured_rejection(self, grain):
        for key, node in METRICS.items():
            if node["computable"]:
                continue
            result = q(key, grain=grain)
            assert result["error"] in ("metric_not_queryable", "non_additive_metric"), key


class TestTenureAtChurn:
    def test_month_grain_returns_values(self):
        r = q("tenure_at_churn", grain="month")
        assert "error" not in r and r["data"]
        assert all(row["value"] is not None for row in r["data"])
        assert r["data"][0]["period"].startswith("20")

    def test_sql_buckets_the_churn_month_for_every_grain(self):
        for grain in ("month", "quarter", "year"):
            sql = q("tenure_at_churn", grain=grain)["sql"]
            assert f"date_trunc('{grain}', churn_month)" in sql

    def test_string_literals_are_never_rewritten(self):
        for grain in ("month", "quarter", "year"):
            assert "'churn_month'" not in q("tenure_at_churn", grain=grain)["sql"]

    def test_segment_filter_and_dimension_still_apply(self):
        r = q("tenure_at_churn", grain="year", dimensions=["segment"])
        assert {row["segment"] for row in r["data"]} <= set(SEGMENTS)
        one = q("tenure_at_churn", grain="year", filters={"segment": "SMB"})
        assert "segment = ?" in one["sql"] and one["data"]

    def test_applies_the_queryable_segments_scope(self):
        node = server._METRICS["tenure_at_churn"]
        original = node["queryable_segments"]
        try:
            node["queryable_segments"] = ["Enterprise"]
            r = q("tenure_at_churn", grain="year", dimensions=["segment"])
            assert "segment in ('Enterprise')" in r["sql"]
            assert {row["segment"] for row in r["data"]} <= {"Enterprise"}
            rejected = q("tenure_at_churn", filters={"segment": "SMB"})
            assert rejected["error"] == "segment_not_available"
        finally:
            node["queryable_segments"] = original

    def test_logo_retention_default_grain_returns_a_value(self):
        r = q("logo_retention")
        assert "error" not in r
        assert any(row["value"] is not None for row in r["data"])


# --------------------------------------------------------------------------
# D2: date_range validation
# --------------------------------------------------------------------------

class TestDateRange:
    @pytest.mark.parametrize("bad", ["2025-02-30", "2025-13-45", "2025-00-10", "2023-02-29", "2025-1-5",
                                     "20250101", "2025/01/01", "not a date", ""])
    @pytest.mark.parametrize("end", ["start", "end"])
    def test_impossible_or_malformed_dates_are_invalid_request(self, bad, end):
        r = q("logo_retention", date_range={end: bad})
        assert r["error"] == "invalid_request", r
        assert "metric" in r and "registry_version" in r

    def test_non_string_date_is_invalid_request(self):
        assert q("logo_retention", date_range={"start": 20250101})["error"] == "invalid_request"

    def test_start_after_end_is_invalid_request(self):
        r = q("nrr", date_range={"start": "2025-06-01", "end": "2025-01-01"})
        assert r["error"] == "invalid_request" and "after" in r["message"]

    def test_unknown_keys_are_invalid_request(self):
        r = q("nrr", date_range={"from": "2025-01-01"})
        assert r["error"] == "invalid_request" and "from" in r["message"]
        r = q("nrr", date_range={"start": "2025-01-01", "to": "2025-02-01"})
        assert r["error"] == "invalid_request"

    def test_a_non_object_date_range_is_invalid_request(self):
        assert q("nrr", date_range=["2025-01-01"])["error"] == "invalid_request"

    def test_leap_day_and_equal_ends_are_accepted(self):
        assert "error" not in q("nrr", date_range={"start": "2024-02-29", "end": "2024-02-29"})
        assert "error" not in q("nrr", date_range={"start": "2025-03-01"})
        assert "error" not in q("nrr", date_range={"end": "2025-03-01"})

    def test_validation_applies_to_the_tenure_path_too(self):
        assert q("tenure_at_churn", date_range={"start": "2025-02-30"})["error"] == "invalid_request"

    def test_valid_range_still_filters(self):
        r = q("nrr", grain="month", date_range={"start": "2025-10-01", "end": "2025-12-31"})
        assert [row["period"][:7] for row in r["data"]] == ["2025-10", "2025-11", "2025-12"]


# --------------------------------------------------------------------------
# Segment scoping and notes
# --------------------------------------------------------------------------

class TestSegmentAvailability:
    def test_am_efficiency_excludes_smb(self):
        assert METRICS["am_efficiency"]["queryable_segments"] == ["Commercial", "Enterprise"]
        r = q("am_efficiency", filters={"segment": "SMB"})
        assert r["error"] == "segment_not_available"

    def test_am_efficiency_by_segment_returns_no_smb_row(self):
        r = q("am_efficiency", grain="year", dimensions=["segment"])
        assert {row["segment"] for row in r["data"]} == {"Commercial", "Enterprise"}

    def test_poc_pass_rate_message_describes_missing_poc_data(self):
        r = q("poc_pass_rate", filters={"segment": "Commercial"})
        assert r["error"] == "segment_not_available"
        assert "has no POC data for segment 'Commercial'" in r["message"]
        assert "carries ['Enterprise'] only" not in r["message"]
        assert "['Enterprise']" in r["message"]

    def test_poc_pass_rate_by_segment_is_a_single_enterprise_row(self):
        r = q("poc_pass_rate", grain="all", dimensions=["segment"])
        assert [row["segment"] for row in r["data"]] == ["Enterprise"]

    def test_generic_message_is_unchanged_for_a_mart_without_the_segment(self):
        r = q("overage_realization", filters={"segment": "SMB"})
        assert r["error"] == "segment_not_available"
        assert "has no rows for segment 'SMB'" in r["message"]

    def test_the_reason_template_is_only_on_poc(self):
        with_reason = [k for k, n in METRICS.items() if n.get("segment_unavailable_reason")]
        assert with_reason == ["poc_pass_rate"]


class TestWarnings:
    @pytest.mark.parametrize("key", ["win_rate", "ingestion_without_completion_rate", "renewal_win_rate"])
    def test_full_ratio_nodes_carry_their_note_in_warnings(self, key):
        node = METRICS[key]
        assert node["computability"] == "full" and node["query"]["aggregation"] == "ratio"
        r = q(key, grain="year")
        assert node["gap_note"] in r["warnings"]
        assert r["metric"]["gap_note"] == node["gap_note"]

    def test_partial_nodes_keep_the_partial_prefix(self):
        r = q("onboarding_completion_rate", grain="year")
        assert r["warnings"][0].startswith("Partially computable:")

    def test_a_node_with_no_note_has_no_note_warning(self):
        assert q("nrr", grain="year")["warnings"] == []


# --------------------------------------------------------------------------
# Registry notes
# --------------------------------------------------------------------------

class TestRegistryNotes:
    def test_onboarding_completion_rate_is_partial_like_the_engine(self):
        node = METRICS["onboarding_completion_rate"]
        assert node["computability"] == "partial"
        assert "1.0" in node["gap_note"] and "variance" in node["gap_note"]

    def test_renewal_note_gives_both_segment_start_dates(self):
        note = METRICS["renewal_win_rate"]["gap_note"]
        assert "2021-02" in note and "2022-07" in note

    def test_renewal_start_dates_match_the_mart(self):
        import duckdb
        con = duckdb.connect(DB_PATH, read_only=True)
        try:
            rows = dict(con.execute(
                "select segment, min(month) from main_marts.mart_deal_funnel "
                "where renewal_won_count + renewal_lost_count > 0 group by 1").fetchall())
        finally:
            con.close()
        assert str(rows["Commercial"])[:7] == "2021-02" and str(rows["Enterprise"])[:7] == "2022-07"

    def test_no_gap_note_is_a_build_todo(self):
        for key, node in METRICS.items():
            note = node["gap_note"] or ""
            assert "build_registry.py" not in note, key
            assert "has been identified for this leaf yet" not in note, key

    def test_ltv_note_says_why_it_is_not_queryable(self):
        note = METRICS["ltv_by_segment_acquisition_channel"]["gap_note"]
        assert "non-additive" in note and "Consumption payback" in note and "outside the mart engine" in note
        r = q("ltv_by_segment_acquisition_channel")
        assert r["error"] == "non_additive_metric"
        assert "build_registry" not in r["message"] and "_SOURCE_MART_MAP" not in r["message"]

    def test_account_specific_baseline_note_matches_the_engine_reason(self):
        note = METRICS["account_specific_baseline_deviation"]["gap_note"]
        assert "restates its parent" in note.lower()
        assert "no mart_* table exposes" not in note

    def test_the_long_cross_reference_key_has_a_written_note(self):
        key = next(k for k in METRICS if k.startswith("outbound_sdr_and_segment_graduation_volume"))
        note = METRICS[key]["gap_note"]
        assert not note.startswith("Cross-reference within the tree")
        assert "win_rate" in note


# --------------------------------------------------------------------------
# Aliases
# --------------------------------------------------------------------------

NEW_ALIASES = {
    "overage": "overage_realization", "overage share": "overage_realization",
    "overage mrr": "overage_realization",
    "ingestion without completion": "ingestion_without_completion_rate",
    "tickets": "support_ticket_volume_severity", "support tickets": "support_ticket_volume_severity",
    "ticket volume": "support_ticket_volume_severity",
    "logins": "engagement_login_frequency", "login frequency": "engagement_login_frequency",
    "am sentiment": "am_sentiment_notes", "account manager sentiment": "am_sentiment_notes",
    "discount": "discount_rate_vs_list", "discounting": "discount_rate_vs_list",
    "discount vs list": "discount_rate_vs_list",
    "renewals": "renewal_win_rate", "renewal rate": "renewal_win_rate",
    "ramp mix": "rep_capacity_ramp_mix", "ramping reps": "rep_capacity_ramp_mix",
    "mid-chain abandonment": "mid_chain_workflow_abandonment",
    "workflow chain under-utilization": "workflow_chain_under_utilization",
    "ltv": "ltv_by_segment_acquisition_channel", "lifetime value": "ltv_by_segment_acquisition_channel",
    "ltv:cac": "ltv_by_segment_acquisition_channel",
    "payback": "consumption_payback", "cac payback": "consumption_payback",
}


class TestAliases:
    def test_every_alias_targets_a_registered_metric(self):
        for alias, target in server._ALIASES.items():
            assert target in METRICS, (alias, target)

    @pytest.mark.parametrize("alias,target", sorted(NEW_ALIASES.items()))
    def test_new_aliases_suggest_their_node(self, alias, target):
        assert server._ALIASES[alias] == target
        assert server._suggestions(alias) == [target]

    @pytest.mark.parametrize("alias,target", [("Mid-Chain Abandonment", "mid_chain_workflow_abandonment"),
                                              ("LTV : CAC", "ltv_by_segment_acquisition_channel"),
                                              ("Workflow chain under utilization",
                                               "workflow_chain_under_utilization")])
    def test_lookup_ignores_case_and_punctuation(self, alias, target):
        assert server._suggestions(alias) == [target]

    @pytest.mark.parametrize("alias", ["overage", "tickets", "renewals", "discount", "payback"])
    def test_an_alias_is_a_suggestion_never_a_substitution(self, alias):
        d = server.get_metric_definition(alias)
        assert d["error"] == "unknown_metric"
        assert d["did_you_mean"] == [server._ALIASES[alias]]
        r = q(alias)
        assert r["error"] == "unknown_metric" and "data" not in r

    def test_existing_aliases_still_resolve(self):
        assert server._suggestions("net revenue retention") == ["nrr"]
        assert server._suggestions("customer acquisition cost") == ["cac_by_channel"]

    def test_fuzzy_matching_still_works_for_non_aliases(self):
        assert "win_rate" in server._suggestions("win rte")

    def test_build_rejects_an_alias_to_a_missing_metric(self):
        spec = importlib.util.spec_from_file_location(
            "acme_build_registry_under_test", os.path.join(REPO, "semantic", "build_registry.py"))
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        build._check_aliases(REGISTRY)
        broken = {"metrics": {k: v for k, v in METRICS.items() if k != "consumption_payback"}}
        with pytest.raises(ValueError):
            build._check_aliases(broken)


# --------------------------------------------------------------------------
# Real MCP call path (only where the SDK is installed)
# --------------------------------------------------------------------------

@pytest.mark.skipif(not MCP_REAL, reason="mcp SDK needs Python 3.10+ (semantic/.venv)")
class TestMcpCallPath:
    def _call(self, tool, args):
        result = asyncio.run(server.mcp.call_tool(tool, args))
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured
        return json.loads(result.content[0].text)

    def test_logo_retention_default_grain_through_call_tool(self):
        out = self._call("query_metric", {"metric": "logo_retention"})
        assert "error" not in out and out["data"]

    def test_tenure_at_churn_every_grain_through_call_tool(self):
        for grain in GRAINS:
            out = self._call("query_metric", {"metric": "tenure_at_churn", "grain": grain})
            assert "error" not in out and out["data"], grain

    def test_impossible_date_through_call_tool(self):
        out = self._call("query_metric", {"metric": "nrr", "date_range": {"start": "2025-02-30"}})
        assert out["error"] == "invalid_request"
