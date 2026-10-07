"""Registry v5 additions on the dashboard side: every queryable node has a display unit,
the segment_not_available guardrail reads as a plain sentence (no raw code, table name or
bracketed list), overage realization reads as a share of MRR, and Layer-3 table labels
carry the slice they measure."""
import json
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard.lib import answers as A  # noqa: E402
from dashboard.lib import labels as L  # noqa: E402
from dashboard.lib import routing  # noqa: E402

with open(os.path.join(REPO, "semantic", "metric_registry.json")) as _f:
    REGISTRY = json.load(_f)
METRICS = REGISTRY["metrics"]
VOCAB = routing.build_vocabulary(METRICS, aliases={})

SEGMENT_MSG = ("'poc_pass_rate' has no rows for segment 'Commercial': its source mart (mart_deal_funnel) carries "
               "['Enterprise'] only. gap_note: Enterprise only, as the tree specifies: passed POCs over closed "
               "new-business opportunities with a POC outcome.")

# Queryable nodes whose scalar has no natural unit; they are shown as plain numbers on purpose.
PLAIN_NUMBER_OK = set()


def test_every_queryable_node_has_a_display_unit():
    missing = [k for k, n in METRICS.items()
               if n.get("computable") and not n.get("cross_reference") and n.get("additive")
               and A.unit_for(dict(n, key=k)) == "value" and k not in PLAIN_NUMBER_OK]
    assert missing == [], f"queryable nodes with no display unit: {missing}"


class TestUnits:
    def test_overage_realization_is_a_share_not_a_rate_of_100(self):
        assert A.format_for_key("overage_realization", 0.3818) == "38.2%"

    @pytest.mark.parametrize("key,value,shown", [
        ("poc_pass_rate", 0.2222, "22.2%"), ("rep_capacity_ramp_mix", 0.05, "5.0%"),
        ("loss_reason_mix", 0.3913, "39.1%"), ("discount_rate_vs_list", 0.208, "20.8%"),
        ("deal_size_trend_within_band", 0.35, "35.0%"), ("renewal_win_rate", 0.8556, "85.6%"),
        ("workflow_chain_under_utilization", 0.0414, "4.1%"),
        ("rep_fully_loaded_cost", 1450036.51, "$1.45M"),
        ("marketing_spend_allocation_by_channel", 25177.6, "$25.2K"),
        ("engagement_login_frequency", 4.028, "4.0 logins per account-month"),
        ("support_ticket_volume_severity", 0.267, "0.27 weighted tickets per account-month"),
        ("am_sentiment_notes", 3.7637, "3.76"),
    ])
    def test_new_node_values_carry_units(self, key, value, shown):
        assert A.format_for_key(key, value) == shown

    def test_no_scientific_notation_for_any_unit(self):
        for unit in ("usd", "pct", "months", "days", "multiple", "count", "per_million_actions", "value",
                     "weighted_tickets_per_account_month", "logins_per_account_month", "score"):
            for v in (4.9e-06, 1.5e9, -0.00012, 0):
                assert not re.search(r"\de[+-]?\d", A.format_value(unit, v)), (unit, v)


class TestSegmentNotAvailable:
    def test_label_is_plain(self):
        assert L.guardrail_label("segment_not_available") == "Segment not available"

    def test_sentence_names_the_segment_and_what_is_covered(self):
        sentence, tail = L.guardrail_sentence("segment_not_available", SEGMENT_MSG, "POC pass rate (Enterprise)")
        assert sentence == "POC pass rate (Enterprise) has no data for the Commercial segment; it covers Enterprise only."
        assert tail and tail.startswith("Enterprise only, as the tree specifies")

    def test_sentence_has_no_machinery(self):
        sentence, tail = L.guardrail_sentence("segment_not_available", SEGMENT_MSG, "POC pass rate")
        for text in (sentence, tail or ""):
            assert not re.search(r"mart_|gap_note|\[|\]|segment_not_available|'poc_pass_rate'", text)

    def test_dedupes_the_tail_when_it_equals_the_gap_note(self):
        gap = "Enterprise only, as the tree specifies: passed POCs over closed new-business opportunities with a POC outcome."
        _, tail = L.guardrail_sentence("segment_not_available", SEGMENT_MSG, "POC", gap_note=gap)
        assert tail is None

    def test_unparseable_message_still_reads_cleanly(self):
        sentence, _ = L.guardrail_sentence("segment_not_available", "something else entirely", "POC")
        assert "segment_not_available" not in sentence

    def test_answer_for_a_rejected_segment_is_a_neutral_rejection(self):
        def q(metric, dimensions=None, filters=None, grain="month", date_range=None):
            node = METRICS[metric]
            if metric == "poc_pass_rate" and (filters or {}).get("segment") == "Commercial":
                return {"error": "segment_not_available", "message": SEGMENT_MSG,
                        "metric": {"key": metric, "name": node["name"], "formula": None, "formula_note": None}}
            return {"data": [{"period": "2025-10-01", "value": 0.3}, {"period": "2025-11-01", "value": 0.4}],
                    "warnings": [], "metric": {"key": metric, "name": node["name"], "formula": None, "formula_note": None}}
        a = A.build_answer(routing.route_question("What is POC pass rate for Commercial?", VOCAB), q, METRICS)
        own = a["own"]
        assert own["state"] == "rejected" and own["guardrail_label"] == "Segment not available"
        assert "Commercial segment" in own["message"] and "mart_" not in own["message"]

    def test_a_rejected_child_row_reads_as_a_sentence(self):
        def q(metric, dimensions=None, filters=None, grain="month", date_range=None):
            node = METRICS[metric]
            meta = {"key": metric, "name": node["name"], "formula": None, "formula_note": None}
            if metric == "poc_pass_rate" and (filters or {}).get("segment") == "Commercial":
                return {"error": "segment_not_available", "message": SEGMENT_MSG, "metric": meta}
            if not node["computable"] or not node["additive"]:
                return {"error": "metric_not_queryable", "message": "gap", "metric": meta}
            return {"data": [{"period": "2025-10-01", "segment": "Commercial", "value": 0.3},
                             {"period": "2025-11-01", "segment": "Commercial", "value": 0.4}],
                    "warnings": [], "metric": meta}
        a = A.build_answer(routing.route_question("What is win rate for Commercial?", VOCAB), q, METRICS)
        poc = next(c for c in a["children"] if c["key"] == "poc_pass_rate")
        assert poc["state"] == "rejected"
        assert poc["message"] == poc["reason"]
        assert "mart_" not in poc["message"] and "gap_note" not in poc["message"] and "[" not in poc["message"]


class TestNodeQualifiers:
    def test_slice_is_added_once(self):
        assert L.qualified_node_label("loss_reason_mix", "Loss-reason mix") == "Loss-reason mix (competitive share)"
        assert L.qualified_node_label("loss_reason_mix", "Loss-reason mix (competitive share)") == "Loss-reason mix (competitive share)"

    def test_overage_realization_is_labelled_as_a_share_of_mrr(self):
        assert L.qualified_node_label("overage_realization", "Overage realization") == "Overage realization (overage share of MRR)"

    def test_other_nodes_pass_through_clean(self):
        assert L.qualified_node_label("poc_pass_rate", "POC pass rate (Enterprise)") == "POC pass rate (Enterprise)"
        assert L.qualified_node_label("nrr_expansion_rate", "See Growth: Expansion (share of starting revenue)") == "Expansion (share of starting revenue)"


class TestRegistryTextCleaning:
    def test_stage_to_stage_note_has_no_wildcard_residue(self):
        out = L.clean_registry_text(METRICS["stage_to_stage_conversion"]["gap_note"])
        assert "*" not in out and "avg days in )" not in out and "mart" not in out.lower()
        assert "(the average days in each stage)" in out

    def test_the_mart_carries_is_reworded(self):
        out = L.clean_registry_text(METRICS["loss_reason_mix"]["gap_note"])
        assert "the mart" not in out and "reporting table carries" in out


def test_phrase_map_strips_the_cross_reference_prefix_in_notes():
    out = L.apply_phrase_map("GRR drill-down: See Growth: Contraction (share of starting revenue) has no Layer-3 children.")
    assert out == "GRR drill-down: Contraction (share of starting revenue) has no Layer-3 children."
