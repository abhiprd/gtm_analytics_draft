"""Answer assembly and tree structure for the Ask the Metric Tree page
(dashboard/lib/answers.py). A fake query function with query_metric()'s
signature stands in for the semantic layer, so these run under the default
interpreter; the real query path is covered by the dashboard smoke check
and the semantic-layer validator.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard.lib import answers as A  # noqa: E402
from dashboard.lib import routing  # noqa: E402

with open(os.path.join(REPO, "semantic", "metric_registry.json")) as _f:
    REGISTRY = json.load(_f)
METRICS = REGISTRY["metrics"]


def _server_aliases():
    """The semantic layer's own alias table (the literal `_ALIASES` in semantic/server.py),
    read with ast so these tests need neither the mcp package nor the dashboard venv."""
    import ast
    with open(os.path.join(REPO, "semantic", "server.py")) as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_ALIASES" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("_ALIASES not found in semantic/server.py")


VOCAB = routing.build_vocabulary(METRICS, aliases=_server_aliases())


def fake_query(metric, dimensions=None, filters=None, grain="month", date_range=None):
    """Mimics query_metric()'s response shapes for the cases the answer
    builder branches on."""
    node = METRICS[metric]
    base = {"metric": {"key": metric, "name": node["name"], "formula": node["formula"],
                       "formula_note": node["formula_note"]}}
    if not node["additive"]:
        return dict(base, error="non_additive_metric", message=f"{node['name']} is non-additive")
    if not node["computable"]:
        return dict(base, error="metric_not_queryable", message=f"{node['name']} gap: {node['gap_note']}")
    for d in dimensions or []:
        if d not in node["queryable_dimensions"]:
            return dict(base, error="dimension_not_queryable", message=f"{d} not queryable")
    seg = (filters or {}).get("segment")
    if seg and seg not in ("SMB", "Commercial", "Enterprise"):
        return dict(base, error="invalid_segment_value", message=f"'{seg}' is not a valid segment")
    rows = []
    for period in ("2025-09-01", "2025-10-01", "2025-11-01"):
        if "segment" in (dimensions or []):
            for s in ("SMB", "Commercial", "Enterprise"):
                # Varies by period so no fake series is constant (a constant series is a gap).
                rows.append({"period": period, "segment": s, "value": 0.1 + 0.01 * ("2025-09-01", "2025-10-01", "2025-11-01").index(period)})
        else:
            rows.append({"period": period, "value": 0.25 if period != "2025-11-01" else 0.3})
    return dict(base, data=rows, warnings=[], sql="select 1", query={})


def answer(q):
    return A.build_answer(routing.route_question(q, VOCAB), fake_query, METRICS)


class TestNonLeafAnswersIncludeImmediateChildren:
    def test_win_rate_answer_carries_its_value_and_all_four_layer3_children(self):
        a = answer("What is Win rate for Enterprise and what is driving it?")
        assert a["kind"] == "answer"
        assert a["own"]["state"] == "value" and a["own"]["layer"] == 2
        assert a["own"]["values"] == {"": 0.3} and a["own"]["period"] == "2025-11-01"
        assert [c["key"] for c in a["children"]] == METRICS["win_rate"]["children"]
        assert len(a["children"]) == 4
        assert all(c["layer"] == 3 for c in a["children"])

    def test_children_that_cannot_be_queried_are_listed_with_their_reason_and_no_value(self):
        a = answer("What is Win rate?")
        blocked = [c for c in a["children"] if c["state"] == "not_computable"]
        # stage-to-stage conversion is the one Win rate child with no series (degenerate by construction)
        assert [c["key"] for c in blocked] == ["stage_to_stage_conversion"]
        for c in blocked:
            assert c["message"]
            assert "values" not in c
        assert {c["key"] for c in a["children"] if c["state"] == "value"} == {
            "poc_pass_rate", "rep_capacity_ramp_mix", "loss_reason_mix"}

    def test_a_queryable_child_carries_a_value_aligned_to_the_parent_period(self):
        a = answer("What is New logo consumption revenue?")
        by_key = {c["key"]: c for c in a["children"]}
        assert by_key["win_rate"]["state"] == "value"
        assert by_key["win_rate"]["values"] == {"": 0.3} and by_key["win_rate"]["aligned"]
        assert by_key["pipeline_generated"]["state"] == "not_computable"
        # the non-additive overlays under New logo are listed, not dropped
        assert by_key["marketing_sales_handoff_quality"]["state"] == "overlay"
        assert by_key["brand_awareness"]["state"] == "overlay"
        assert len(a["children"]) == len(METRICS["new_logo_consumption_revenue"]["children"])

    def test_a_non_leaf_that_is_itself_not_queryable_still_lists_its_children(self):
        a = answer("What is Pipeline generated?")
        assert a["own"]["state"] == "not_computable"
        assert [c["key"] for c in a["children"]] == METRICS["pipeline_generated"]["children"]

    def test_a_non_additive_non_leaf_returns_the_guardrail_message_and_its_children(self):
        a = answer("What is Marketing–sales handoff quality?")
        assert a["own"]["state"] == "overlay" and "overlay" in a["own"]["message"]
        assert "**" not in a["own"]["message"]
        assert len(a["children"]) == 3

    def test_cross_reference_children_are_labelled_as_such(self):
        a = answer("What is NRR?")
        child = a["children"][0]
        assert child["key"] == "see_growth_expansion_contraction_churn_drivers"
        assert child["state"] == "cross_reference" and child["status"] == A.STATUS_CROSS_REFERENCE

    def test_a_leaf_metric_has_no_children_section(self):
        a = answer("What is Tenure-at-churn (early vs. late lifecycle)?")
        assert a["own"]["state"] == "value" and a["children"] == []

    def test_segment_split_is_carried_to_the_children(self):
        a = answer("New logo consumption revenue by segment")
        win = [c for c in a["children"] if c["key"] == "win_rate"][0]
        assert set(win["values"]) == {"SMB", "Commercial", "Enterprise"}

    def test_grain_is_carried_to_the_children(self):
        seen = []

        def spy(metric, **kw):
            seen.append((metric, kw.get("grain")))
            return fake_query(metric, **kw)
        A.build_answer(routing.route_question("yearly new logo consumption revenue", VOCAB), spy, METRICS)
        assert {g for _, g in seen} == {"year"}


class TestGuardrailAnswersAreShownNotReplaced:
    def test_ltv_returns_the_non_additive_message_and_no_data(self):
        a = answer("LTV:CAC by channel")
        assert a["own"]["key"] == "ltv_by_segment_acquisition_channel"
        assert a["own"]["state"] == "overlay"
        assert "data" not in a["own"]["result"]

    def test_cac_by_channel_returns_the_dimension_guardrail_and_no_blended_data(self):
        a = answer("CAC by channel")
        assert a["own"]["state"] == "rejected"
        assert a["own"]["result"]["error"] == "dimension_not_queryable"
        assert "data" not in a["own"]["result"]
        assert a["children"] == []

    def test_tier_1_returns_invalid_segment_value(self):
        a = answer("win rate for Tier 1")
        assert a["own"]["state"] == "rejected"
        assert a["own"]["result"]["error"] == "invalid_segment_value"
        assert a["children"] == []

    def test_unresolved_question(self):
        a = answer("what is the weather")
        assert a["kind"] == "unresolved"


class TestNodeStatusAndTree:
    def test_eleven_layer1_nodes_under_three_pillars_in_tree_order(self):
        by_pillar = A.layer1_by_pillar(REGISTRY)
        assert list(by_pillar) == ["Growth", "Efficiency", "Durability"]
        assert sum(len(v) for v in by_pillar.values()) == 11
        assert {p: len(v) for p, v in by_pillar.items()} == {"Growth": 4, "Efficiency": 4, "Durability": 3}

    def test_layer1_nodes_are_exactly_the_registry_layer_1(self):
        listed = {k for v in A.layer1_by_pillar(REGISTRY).values() for k in v}
        assert listed == {k for k, n in METRICS.items() if n["layer"] == 1}

    def test_win_rate_is_layer_2_under_new_logo(self):
        assert METRICS["win_rate"]["layer"] == 2
        assert METRICS["win_rate"]["parent"] == "new_logo_consumption_revenue"

    def test_children_layers_are_parent_plus_one(self):
        for key, n in METRICS.items():
            for c in n["children"]:
                assert METRICS[c]["layer"] == n["layer"] + 1, (key, c)

    @pytest.mark.parametrize("key,status", [
        ("win_rate", A.STATUS_QUERYABLE),
        ("marketing_sales_handoff_quality", A.STATUS_OVERLAY),
        ("ltv_by_segment_acquisition_channel", A.STATUS_OVERLAY),
        ("pipeline_generated", A.STATUS_NOT_COMPUTABLE),
        ("marketing_spend_allocation_by_channel", A.STATUS_PARTIAL),
        ("see_growth_contraction_churn_drivers", A.STATUS_CROSS_REFERENCE),
    ])
    def test_node_status_comes_from_the_registry_flags(self, key, status):
        assert A.node_status(METRICS[key]) == status

    def test_ready_questions(self):
        assert A.question_for_node(METRICS["win_rate"]) == "What is Win rate and what is driving it?"
        assert A.question_for_node(METRICS["poc_pass_rate"]) == "What is POC pass rate (Enterprise)?"


class TestValueFormatting:
    @pytest.mark.parametrize("unit,v,out", [
        ("usd", 45_200, "$45.2K"), ("usd", 1_250_000, "$1.25M"), ("usd", -3_000, "-$3.0K"),
        ("pct", 0.3, "30.0%"), ("months", 0.0634, "0.06 mo"), ("multiple", 2.514, "2.51x"),
        ("count", 12345.0, "12,345"), ("days", 410.2, "410 days"),
        ("per_million_actions", 4.2e-6, "4.20 per 1M Actions"), ("usd", None, "n/a"),
        ("pct", float("nan"), "n/a"),
    ])
    def test_format_value(self, unit, v, out):
        assert A.format_value(unit, v) == out

    def test_units_for_the_ambiguous_ratios(self):
        # magic number and AM efficiency are multiples; a "% " would misstate them
        assert A.unit_for(METRICS["magic_number"]) == "multiple"
        assert A.unit_for(METRICS["am_efficiency"]) == "multiple"
        assert A.unit_for(METRICS["consumption_payback"]) == "months"
        assert A.unit_for(METRICS["onboarding_cs_efficiency"]) == "per_million_actions"

    def test_every_queryable_registry_node_has_an_explicit_unit(self):
        missing = [k for k, n in METRICS.items()
                   if n["computable"] and k not in A._UNIT_BY_KEY]
        assert not missing, missing


# ---------------------------------------------------------------------------
# Truncated final month, degenerate series, registry notes, guardrail wording
# ---------------------------------------------------------------------------

def _series(periods, value=0.3, key_value=None):
    return {"data": [{"period": p, "value": (key_value or {}).get(p, value)} for p in periods],
            "warnings": [], "sql": "select 1", "query": {}}


class TestLastCompleteMonth:
    def test_month_headline_skips_the_partial_final_month(self):
        r = _series(["2025-10-01T00:00:00", "2025-11-01T00:00:00", "2025-12-01T00:00:00"])
        assert A.last_complete_period(r, "month", "2025-12-01") == "2025-11-01T00:00:00"

    def test_no_partial_month_known_keeps_the_latest(self):
        r = _series(["2025-10-01", "2025-11-01", "2025-12-01"])
        assert A.last_complete_period(r, "month", None) == "2025-12-01"

    def test_coarser_grains_exclude_the_period_that_contains_the_partial_month(self):
        q = _series(["2025-07-01", "2025-10-01"])
        y = _series(["2024-01-01", "2025-01-01"])
        assert A.last_complete_period(q, "quarter", "2025-12-01") == "2025-07-01"
        assert A.last_complete_period(y, "year", "2025-12-01") == "2024-01-01"

    def test_period_covers_month_rules(self):
        assert A.period_covers_month("2025-10-01", "quarter", "2025-12-01")
        assert not A.period_covers_month("2025-07-01", "quarter", "2025-12-01")
        assert A.period_covers_month("2025-01-01", "year", "2025-12-01")
        assert not A.period_covers_month("2025-12-01", "all", "2025-12-01")
        assert not A.period_covers_month(None, "month", "2025-12-01")

    def test_answer_headlines_the_last_complete_month_and_reports_the_partial_one(self):
        def q(metric, dimensions=None, filters=None, grain="month", date_range=None):
            res = fake_query(metric, dimensions, filters, grain)
            if "data" in res:
                res["data"].append({"period": "2025-12-01", "value": -9.0})
            return res
        a = A.build_answer(routing.route_question("What is Win rate for Enterprise?", VOCAB), q, METRICS,
                           partial_month="2025-12-01")
        own = a["own"]
        assert own["period"] == "2025-11-01" and own["values"] == {"": 0.3}
        assert own["newest_partial_period"] == "2025-12-01" and not own["headline_is_partial"]
        assert own["basis"] == "Basis: last complete month"

    def test_without_a_partial_month_the_newest_period_is_the_headline(self):
        a = answer("What is Win rate?")
        assert a["own"]["newest_partial_period"] is None


class TestPartialInTables:
    def test_table_rows_use_period_labels_units_and_flag_the_partial_month(self):
        rows = A.table_rows({"data": [{"period": "2025-11-01T00:00:00", "value": 1.0},
                                      {"period": "2025-12-01T00:00:00", "value": 0.5}]},
                            "pct", "month", "2025-12-01")
        assert rows[0]["Period"] == "2025-11" and rows[0]["Value"] == "100.0%" and rows[0]["Note"] == ""
        assert rows[1]["Note"] == "Partial month"


class TestDegenerateSeries:
    NODE = {"computable": True, "gap_note": "Blended TTFA is identically 0 in the current data."}

    def test_constant_series_with_a_registry_note_is_degenerate(self):
        assert A.result_is_degenerate(self.NODE, _series(["2025-10-01", "2025-11-01"], value=0.0))

    def test_a_varying_series_is_not(self):
        r = _series(["2025-10-01", "2025-11-01"], key_value={"2025-11-01": 0.1}, value=0.0)
        assert not A.result_is_degenerate(self.NODE, r)

    def test_a_constant_series_without_the_registry_note_is_not(self):
        node = {"computable": True, "gap_note": "A real 0 for SMB, which has no AM."}
        assert not A.result_is_degenerate(node, _series(["2025-10-01", "2025-11-01"], value=0.0))

    def test_node_status_flags_the_degenerate_node_in_the_tree(self):
        assert A.node_status(METRICS["activation"]) == A.STATUS_DEGENERATE
        assert A.node_status(METRICS["win_rate"]) == A.STATUS_QUERYABLE
        assert A.STATUS_LABEL[A.STATUS_DEGENERATE] and A.STATUS_GLYPH[A.STATUS_DEGENERATE]

    def test_activation_answer_has_no_value_cards(self):
        def q(metric, dimensions=None, filters=None, grain="month", date_range=None):
            res = fake_query(metric, dimensions, filters, grain)
            if "data" in res and metric == "activation":
                for row in res["data"]:
                    row["value"] = 0.0
            return res
        a = A.build_answer(routing.route_question("What is Activation?", VOCAB), q, METRICS)
        assert a["own"]["state"] == "degenerate" and "values" not in a["own"]
        assert a["own"]["message"]


class TestRegistryNotesReachTheAnswer:
    def test_gap_note_of_a_live_metric_is_in_the_answer_in_plain_words(self):
        a = answer("What is Win rate?")
        note = a["own"]["gap_note"]
        assert "SMB" in note and "win_rate" not in note and "Commercial/Enterprise" in note

    def test_a_metric_without_a_gap_note_carries_none(self):
        assert answer("What is NRR?")["own"]["gap_note"] == ""


class TestGuardrailMessagesAreClean:
    def test_rejection_has_a_label_and_no_codes(self):
        def q(metric, dimensions=None, filters=None, grain="month", date_range=None):
            return {"error": "dimension_not_queryable", "metric": {"key": metric},
                    "message": "The metric tree allows 'channel' on 'cac_by_channel', but no mart_* table "
                               "currently exposes that cut -- queryable_dimensions today: ['segment']. "
                               "gap_note: mart_efficiency exposes blended_cac."}
        a = A.build_answer(routing.route_question("CAC by channel", VOCAB), q, METRICS)
        own = a["own"]
        assert own["state"] == "rejected" and own["guardrail_label"] == "Split not available yet"
        text = own["message"] + " " + (own["message_tail"] or "")
        for raw in ("dimension_not_queryable", "gap_note", "mart_", "queryable_dimensions", "**"):
            assert raw not in text

    def test_overlay_message_is_composed_without_markdown_or_build_files(self):
        a = answer("What is LTV?")
        m = a["own"]["message"]
        assert "**" not in m and ".py" not in m and "_SOURCE_MART_MAP" not in m


class TestUnitsForEngineKeys:
    @pytest.mark.parametrize("key,v,expected", [
        ("sm_cost", 1471734.9, "$1.47M"),
        ("automated_action_volume", 196504227.0, "196,504,227"),
        ("avg_initial_commitment", 121963.53, "$122.0K"),
        ("nrr_expansion_rate", 0.07897, "7.9%"),
        ("pipeline_generated", 53.0, "53 leads converted"),
        ("win_rate", 0.425, "42.5%"),
    ])
    def test_values_are_formatted_with_units_never_scientific(self, key, v, expected):
        assert A.format_for_key(key, v) == expected

    def test_unknown_unit_falls_back_to_a_plain_number(self):
        assert "e" not in A.format_value("value", 1.965e8).lower()


def test_pillar_taglines_are_declarative_labels():
    for pillar in ("Growth", "Efficiency", "Durability"):
        assert "?" not in A.pillar_tagline(pillar, "is what we sold sticking")
        assert not A.pillar_tagline(pillar).lower().startswith("is ")


# ---------------------------------------------------------------------------
# Data-table Note column, formula join, structural constants, months precision
# ---------------------------------------------------------------------------

def test_table_note_column_is_blank_never_none():
    rows = A.table_rows({"data": [{"period": "2025-10-01", "value": 0.5},
                                  {"period": "2025-12-01", "value": 0.4}]}, "pct", "month", "2025-12-01")
    assert rows[0]["Note"] == "" and rows[1]["Note"] == "Partial month"
    assert all(r["Note"] is not None for r in rows)


def test_table_has_no_note_column_when_nothing_is_partial():
    rows = A.table_rows({"data": [{"period": "2025-10-01", "value": 0.5}]}, "pct", "month", "2025-12-01")
    assert "Note" not in rows[0]


@pytest.mark.parametrize("formula,note,expected", [
    ("Net new ARR ÷ prior-period S&M cost", "(numerator covered under Growth)",
     "Net new ARR ÷ prior-period S&M cost (numerator covered under Growth)"),
    ("Closed won ÷ (won + lost)", ", new-business only", "Closed won ÷ (won + lost), new-business only"),
    ("Formula", None, "Formula"),
])
def test_formula_note_join(formula, note, expected):
    assert A.join_formula(formula, note) == expected


class TestStructuralConstants:
    WIN = {"computable": True, "gap_note": "SMB always shows win_rate = 1.0 (every SMB opportunity ...)."}

    def test_smb_only_win_rate_is_degenerate(self):
        r = _series(["2025-10-01", "2025-11-01"], value=1.0)
        assert A.result_is_degenerate(self.WIN, r)

    def test_win_rate_node_is_not_flagged_degenerate_in_the_tree(self):
        assert A.node_status(METRICS["win_rate"]) == A.STATUS_QUERYABLE

    def test_split_answer_names_the_constant_segment(self):
        res = {"data": [{"period": p, "segment": "SMB", "value": 1.0} for p in ("2025-10-01", "2025-11-01")]
                       + [{"period": p, "segment": "Commercial", "value": v}
                          for p, v in (("2025-10-01", 0.3), ("2025-11-01", 0.4))]}
        assert A.constant_segments(self.WIN, res) == ["SMB"]
        assert A.constant_segments({"computable": True, "gap_note": "ordinary note"}, res) == []

    def test_smb_filter_answer_has_no_headline_value(self):
        def q(metric, dimensions=None, filters=None, grain="month", date_range=None):
            res = fake_query(metric, dimensions, filters, grain)
            if "data" in res and metric == "win_rate":
                for row in res["data"]:
                    row["value"] = 1.0
            return res
        a = A.build_answer(routing.route_question("What is win rate for SMB?", VOCAB), q, METRICS)
        assert a["own"]["state"] == "degenerate" and "values" not in a["own"]
        assert "100%" in a["own"]["message"]


# --------------------------------------------------------------------------
# Query-interface gaps, overlays, default views, unsupported splits, failures
# --------------------------------------------------------------------------

class TestQueryInterfaceGap:
    def test_pipeline_generated_says_it_is_shown_in_the_weekly_readout(self):
        a = answer("pipeline generated")
        own = a["own"]
        assert own["state"] == "not_computable" and own["query_gap"] is True
        assert own["message"] == "Not available through this query interface; shown in the weekly readout."
        assert "no data source mapped" not in own["message"].lower()
        assert own["detail"] and "marketing attribution" in own["detail"]

    def test_the_long_paragraph_is_not_repeated_under_each_child(self):
        a = answer("pipeline generated")
        for c in a["children"]:
            if c["query_gap"]:
                assert c["reason"] == "Not available through this query interface; shown in the weekly readout."
                assert c["status_label"] == "Not queryable here"

    def test_a_genuinely_uncomputable_node_gives_its_reason_without_the_old_prefix(self):
        a = answer("workflow migration rate")
        assert a["own"]["query_gap"] is False
        assert "no data source mapped" not in a["own"]["message"].lower()
        assert "business-process-level onboarding events" in a["own"]["message"]

    def test_detection_keys_on_the_registry_wording(self):
        from dashboard.lib import labels
        assert labels.is_query_interface_gap("Computed and validated by analytics/x.py from y")
        assert not labels.is_query_interface_gap("Needs a churn-risk flag event.")
        assert not labels.is_query_interface_gap(None)


class TestOverlayWording:
    def test_ltv_has_no_registered_source_phrase(self):
        m = answer("LTV")["own"]["message"]
        assert "No data source is registered" not in m and "overlay" in m.lower()

    def test_overlay_without_a_gap_note_says_it_has_no_series(self):
        from dashboard.lib import labels
        assert labels.overlay_sentence("X", None, False, None).endswith("It has no series of its own.")


class TestDefaultSegmentView:
    def test_win_rate_with_no_segment_defaults_to_commercial_and_enterprise(self):
        a = answer("What is win rate?")
        assert a["parsed"]["segment_subset"] == ["Commercial", "Enterprise"]
        assert "segment" in a["parsed"]["dimensions"] and a["parsed"]["default_view_note"]

    @pytest.mark.parametrize("q", ["win rate for Enterprise", "win rate by segment", "win rate for SMB and Enterprise"])
    def test_a_named_segment_or_split_is_left_alone(self, q):
        assert answer(q)["parsed"]["default_view_note"] is None

    def test_other_metrics_have_no_default(self):
        assert answer("What is NRR?")["parsed"]["default_view_note"] is None


class TestUnsupportedSplitNotice:
    def test_notice_text(self):
        assert A.split_notice(["loss reason"], "Win rate") == (
            "Split by loss reason is not available for Win rate. The figures below are not split.")
        assert A.split_notice(["region", "industry"], "NRR").startswith("Split by region or industry")

    def test_loss_reason_offers_the_loss_reason_node(self):
        sug = A.split_suggestions(["loss reason"], METRICS, "win_rate")
        assert [s["key"] for s in sug] == ["loss_reason_mix"]
        assert sug[0]["label"] == "Loss-reason mix (competitive share)"

    def test_unrelated_splits_offer_nothing_and_every_target_exists(self):
        assert A.split_suggestions(["region"], METRICS, "nrr") == []
        for target in A.RELATED_SPLIT_NODES.values():
            assert target in METRICS


class TestNeverCrashes:
    def test_a_failing_answer_becomes_a_plain_notice(self):
        def boom(q, **kw):
            raise RuntimeError("duckdb exploded at /Users/x/db.duckdb")
        out = A.safe_answer(boom, "logo retention")
        assert out["kind"] == "failed" and out["notice"] == A.FAILED_NOTICE
        assert "duckdb" not in json.dumps(out) and "Traceback" not in json.dumps(out)

    def test_a_working_answer_passes_through(self):
        assert A.safe_answer(lambda q, **kw: {"kind": "answer", "q": q}, "x") == {"kind": "answer", "q": "x"}


class TestQualifiedLabels:
    def test_axis_label_is_not_doubled(self):
        from dashboard.lib import labels
        out = labels.qualified_node_label("loss_reason_mix", "Loss-reason mix (competitive / no-decision / price)")
        assert out == "Loss-reason mix (competitive share)"

    def test_marketing_spend_and_ramp_mix_carry_a_qualifier(self):
        a = answer("What is win rate for Enterprise?")
        names = {c["key"]: c["display_name"] for c in a["children"]}
        assert names["rep_capacity_ramp_mix"] == "Rep capacity / ramp mix (share from ramping reps)"
        assert names["loss_reason_mix"] == "Loss-reason mix (competitive share)"
        from dashboard.lib import labels
        assert "total across channels" in labels.qualified_node_label(
            "marketing_spend_allocation_by_channel", "Marketing spend allocation by channel")

    def test_the_complement_node_says_what_it_measures(self):
        from dashboard.lib import labels
        out = labels.qualified_node_label("declining_share_of_full_chain_vs_partial_chain_runs",
                                          "Declining share of full-chain vs. partial-chain runs")
        assert "at or above 70% completion" in out

    def test_pipeline_generated_carries_a_count_unit(self):
        assert A.format_for_key("pipeline_generated", 69) == "69 leads converted"
