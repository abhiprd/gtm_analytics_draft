"""Question routing for the Ask the Metric Tree page (dashboard/lib/routing.py).

The router is a pure function over the semantic layer's own registry
(semantic/metric_registry.json) and alias table (the literal `_ALIASES`
in semantic/server.py, read with ast so these tests need neither the mcp
package nor the dashboard virtualenv). Each failure an independent
validator found in the earlier router has its own test; the routes that
already worked are pinned alongside them.
"""
import ast
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard.lib import answers, routing  # noqa: E402

with open(os.path.join(REPO, "semantic", "metric_registry.json")) as _f:
    REGISTRY = json.load(_f)
METRICS = REGISTRY["metrics"]


def _server_aliases():
    with open(os.path.join(REPO, "semantic", "server.py")) as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_ALIASES" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("_ALIASES not found in semantic/server.py")


VOCAB = routing.build_vocabulary(METRICS, aliases=_server_aliases())


def route(q):
    return routing.route_question(q, VOCAB)


# --------------------------------------------------------------------------
# Failure 1: a short alias beat a longer, more specific term
# --------------------------------------------------------------------------

class TestLongestMatch:
    def test_ltv_cac_by_channel_resolves_to_ltv_not_cac_by_channel(self):
        p = route("LTV:CAC by channel")
        assert p["resolved_metric"] == "ltv_by_segment_acquisition_channel"
        assert p["dimensions"] == ["channel"]

    @pytest.mark.parametrize("q", [
        "What is LTV?", "show me ltv", "customer lifetime value by segment",
        "LTV to CAC ratio", "ltv/cac", "LTV : CAC",
    ])
    def test_any_question_naming_ltv_resolves_to_the_ltv_node(self, q):
        assert route(q)["resolved_metric"] == "ltv_by_segment_acquisition_channel"

    @pytest.mark.parametrize("q", ["payback", "cac payback", "CAC payback period",
                                   "What is the payback?"])
    def test_payback_and_cac_payback_resolve_to_consumption_payback(self, q):
        assert route(q)["resolved_metric"] == "consumption_payback"

    def test_plain_cac_still_resolves_to_cac_by_channel(self):
        assert route("What is CAC?")["resolved_metric"] == "cac_by_channel"

    def test_a_longer_name_wins_over_the_shorter_name_inside_it(self):
        assert route("what is renewal win rate")["resolved_metric"] == "renewal_win_rate"
        assert route("what is win rate")["resolved_metric"] == "win_rate"

    def test_matching_is_on_whole_tokens(self):
        # 'cac' inside another word is not a mention of CAC
        assert route("what is the cache hit ratio")["resolved_metric"] is None

    def test_a_second_metric_is_reported_not_dropped(self):
        p = route("NRR and GRR by segment")
        assert p["resolved_metric"] == "nrr" and p["secondary_metrics"] == ["grr"]


# --------------------------------------------------------------------------
# Failure 2: a named channel dimension was silently dropped
# --------------------------------------------------------------------------

class TestChannelDimension:
    def test_cac_by_channel_passes_a_channel_dimension(self):
        p = route("CAC by channel")
        assert p["resolved_metric"] == "cac_by_channel"
        assert p["dimensions"] == ["channel"]

    @pytest.mark.parametrize("q,dims", [
        ("pipeline generated per channel", ["channel"]),
        ("win rate by opportunity type", ["opportunity_type"]),
        ("NRR across segments", ["segment"]),
        ("NRR segment breakdown", ["segment"]),
        ("CAC by segment and channel", ["segment", "channel"]),
        ("What is CAC", []),
    ])
    def test_dimension_phrases(self, q, dims):
        assert sorted(route(q)["dimensions"]) == sorted(dims)

    def test_by_segment_keeps_a_named_segment_as_a_filter(self):
        p = route("NRR by segment for Enterprise")
        assert p["dimensions"] == ["segment"] and p["filters"] == {"segment": "Enterprise"}


# --------------------------------------------------------------------------
# Failure 3: an unrecognized segment-like qualifier was silently dropped
# --------------------------------------------------------------------------

class TestSegmentQualifiers:
    @pytest.mark.parametrize("q,term", [
        ("win rate for Tier 1", "Tier 1"),
        ("win rate for tier2 accounts", "tier2"),
        ("NRR for Mid-Market", "Mid-Market"),
        ("NRR for mid market", "mid market"),
        ("GRR for Strategic accounts", "Strategic"),
    ])
    def test_unrecognized_qualifier_is_passed_through_for_the_guardrail(self, q, term):
        p = route(q)
        assert p["filters"] == {"segment": term}
        assert p["unrecognized_segment"] == term

    def test_unrecognized_qualifier_wins_over_a_valid_one(self):
        p = route("Enterprise and Tier 1 win rate")
        assert p["filters"] == {"segment": "Tier 1"}

    @pytest.mark.parametrize("q,seg", [
        ("win rate for enterprise", "Enterprise"), ("SMB NRR", "SMB"),
        ("commercial win rate", "Commercial"),
    ])
    def test_valid_segment_filters(self, q, seg):
        assert route(q)["filters"] == {"segment": seg}

    def test_several_valid_segments_become_a_split_with_a_display_subset(self):
        p = route("SMB vs Enterprise NRR")
        assert p["dimensions"] == ["segment"] and p["filters"] == {}
        assert p["segment_subset"] == ["SMB", "Enterprise"]

    def test_a_segment_word_inside_the_metric_name_is_not_a_filter(self):
        node = METRICS["poc_pass_rate"]
        assert "enterprise" in node["name"].lower()
        assert route(f"What is {node['name']}?")["filters"] == {}


# --------------------------------------------------------------------------
# Failure 4: dash / multiplication-sign variants
# --------------------------------------------------------------------------

class TestNormalization:
    @pytest.mark.parametrize("q", [
        "LTV by segment × acquisition channel",
        "LTV by segment x acquisition channel",
        "ltv by segment acquisition channel",
        "ltv_by_segment_acquisition_channel",
    ])
    def test_multiplication_sign_variants(self, q):
        assert route(q)["resolved_metric"] == "ltv_by_segment_acquisition_channel"

    @pytest.mark.parametrize("q", [
        "Marketing–sales handoff quality",   # en dash, as the tree file writes it
        "Marketing-sales handoff quality",
        "marketing sales handoff quality",
        "Marketing — sales handoff quality",
    ])
    def test_en_dash_and_hyphen_are_equivalent(self, q):
        assert route(q)["resolved_metric"] == "marketing_sales_handoff_quality"

    def test_case_and_punctuation_do_not_matter(self):
        assert route("WIN-RATE???")["resolved_metric"] == "win_rate"


# --------------------------------------------------------------------------
# Routes that already worked
# --------------------------------------------------------------------------

class TestPreviouslyPassingRoutes:
    def test_win_rate_for_enterprise_last_year(self):
        p = route("What was win rate for Enterprise last year?")
        assert p["resolved_metric"] == "win_rate"
        assert p["filters"] == {"segment": "Enterprise"} and p["grain"] == "year"

    def test_nrr_by_segment(self):
        p = route("Show me NRR by segment")
        assert p["resolved_metric"] == "nrr" and p["dimensions"] == ["segment"]

    @pytest.mark.parametrize("q,key", [
        ("net revenue retention", "nrr"), ("gross revenue retention", "grr"),
        ("customer acquisition cost", "cac_by_channel"),
        ("logo retention rate", "logo_retention"), ("magic number", "magic_number"),
        ("AM efficiency", "am_efficiency"), ("avg initial commitment", "avg_initial_commitment"),
        ("net_revenue_retention", "nrr"), ("grr", "grr"),
    ])
    def test_names_aliases_and_keys(self, q, key):
        assert route(q)["resolved_metric"] == key

    @pytest.mark.parametrize("q,grain", [
        ("monthly NRR", "month"), ("NRR quarterly", "quarter"),
        ("annual win rate", "year"), ("win rate", "month"),
    ])
    def test_grain_words(self, q, grain):
        assert route(q)["grain"] == grain

    def test_no_match_falls_through_to_suggestions(self):
        p = routing.route_question("what is the weather", VOCAB, suggest=lambda t: ["nrr"])
        assert p["resolved_metric"] is None and p["suggestions"] == ["nrr"]


# --------------------------------------------------------------------------
# The tree panel's questions route back to the node that produced them
# --------------------------------------------------------------------------

class TestTreePanelQuestions:
    def test_every_registry_node_s_ready_question_resolves_to_that_node(self):
        misses = []
        for key, node in METRICS.items():
            got = route(answers.question_for_node(node))["resolved_metric"]
            if got != key:
                misses.append((key, got))
        assert not misses, misses

    def test_a_node_s_ready_question_never_adds_a_filter_or_grain_by_accident(self):
        for key, node in METRICS.items():
            p = route(answers.question_for_node(node))
            assert p["filters"] == {}, (key, p["filters"])

    def test_alias_targets_must_exist_in_the_registry(self):
        with pytest.raises(KeyError):
            routing.build_vocabulary(METRICS, aliases={"zzz": "no_such_metric"})


# --------------------------------------------------------------------------
# Scope words, unsupported splits and the alias table
# --------------------------------------------------------------------------

class TestScopeWordOutranksBroaderName:
    @pytest.mark.parametrize("q", ["win rate for renewals", "win rate of renewals", "renewal win rate",
                                   "What is the win rate for renewals?", "Renewals win rate by segment"])
    def test_renewal_phrasings_resolve_to_renewal_win_rate(self, q):
        assert route(q)["resolved_metric"] == "renewal_win_rate"

    def test_plain_win_rate_is_unchanged(self):
        assert route("win rate for Enterprise")["resolved_metric"] == "win_rate"
        assert route("win rate by segment")["resolved_metric"] == "win_rate"

    def test_every_override_targets_a_registry_node(self):
        for rule in routing.SCOPE_OVERRIDES:
            assert rule["from_key"] in METRICS and rule["to_key"] in METRICS


class TestUnsupportedSplits:
    @pytest.mark.parametrize("q,expected", [
        ("win rate by loss reason", ["loss reason"]),
        ("win rate by rep", ["rep"]),
        ("NRR by region", ["region"]),
        ("NRR by industry", ["industry"]),
        ("NRR by region/industry", ["region", "industry"]),
        ("win rate per rep", ["rep"]),
        ("win rate for each rep", ["rep"]),
        ("win rate by segment and region", ["region"]),
        ("win rate by the region for enterprise", ["region"]),
    ])
    def test_a_split_without_a_dimension_is_reported_not_dropped(self, q, expected):
        assert route(q)["unsupported_splits"] == expected

    @pytest.mark.parametrize("q", [
        "win rate by segment", "NRR by segment", "CAC by channel", "LTV by segment × acquisition channel",
        "Marketing spend allocation by channel", "win rate by month", "win rate by quarter for Enterprise",
        "win rate by Q3", "by the end of Q3 what is NRR", "win rate across all segments", "win rate",
        "win rate by opportunity type",
    ])
    def test_recognized_dimensions_grain_words_and_time_phrases_are_not_splits(self, q):
        assert route(q)["unsupported_splits"] == []

    def test_a_segment_after_the_split_is_a_filter_not_a_split(self):
        p = route("win rate by region for enterprise")
        assert p["filters"] == {"segment": "Enterprise"} and p["unsupported_splits"] == ["region"]

    def test_nothing_resolved_reports_no_split(self):
        assert route("tell me about the cache hit ratio by region")["unsupported_splits"] == []

    def test_all_segments_is_a_segment_split(self):
        assert route("win rate across all segments")["dimensions"] == ["segment"]


class TestAliasesLiveOnTheServer:
    def test_the_dashboard_adds_no_alias_the_server_already_has(self):
        server = {routing.tokenize(k) and tuple(t for t, _, _ in routing.tokenize(k)) for k in _server_aliases()}
        for phrase in routing.SUPPLEMENTARY_ALIASES:
            assert tuple(t for t, _, _ in routing.tokenize(phrase)) not in server, phrase

    @pytest.mark.parametrize("q,key", [
        ("overage share of MRR", "overage_realization"),
        ("how many tickets", "support_ticket_volume_severity"),
        ("login frequency by segment", "engagement_login_frequency"),
        ("AM sentiment for SMB", "am_sentiment_notes"),
        ("discount vs list", "discount_rate_vs_list"),
        ("renewal rate", "renewal_win_rate"),
        ("ramp mix", "rep_capacity_ramp_mix"),
        ("ingestion without completion", "ingestion_without_completion_rate"),
        ("mid-chain abandonment", "mid_chain_workflow_abandonment"),
        ("workflow chain under-utilization", "workflow_chain_under_utilization"),
        ("LTV", "ltv_by_segment_acquisition_channel"), ("lifetime value", "ltv_by_segment_acquisition_channel"),
        ("LTV:CAC", "ltv_by_segment_acquisition_channel"), ("payback", "consumption_payback"),
        ("CAC payback", "consumption_payback"), ("logo retention", "logo_retention"),
        ("tenure at churn", "tenure_at_churn"),
    ])
    def test_phrasings_route(self, q, key):
        assert route(q)["resolved_metric"] == key
