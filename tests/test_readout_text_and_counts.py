"""Weekly readout: the Not-computable node count, the voice of the
artifact-sourced strings the dashboard shows verbatim, the cross-reference
labelling of NRR/GRR drivers, and the period-aware forecast notes.

Voice rules (docs: dashboard design conventions, Section 11): production BI
copy -- no assistant-voice hedging, no ALL-CAPS emphasis, no imperatives, no raw
code identifiers, one short line per list item with the long form in a
separate `detail` key.
"""
import copy
import json
import os
import re
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics import forecast as fc  # noqa: E402
from analytics import variance_diagnostic as vd  # noqa: E402
from analytics import weekly_readout as wr  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "analytics", "outputs")
DATES = ["2025-06-30", "2025-11-30"]


def _load(d):
    with open(os.path.join(OUT, "weekly_readout_%s.json" % d)) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def readouts():
    return {d: _load(d) for d in DATES}


# --------------------------------------------------------------------------
# Not-computable count
# --------------------------------------------------------------------------

class TestNotComputableCount:
    @pytest.mark.parametrize("d", DATES)
    def test_committed_count_equals_the_rows_the_scorecard_shows_as_not_computable(
            self, readouts, d):
        sec = readouts[d]["layer1_scorecard"]
        shown = [r["metric_key"] for r in sec["rows"] if r["status"] == "Not computable"]
        assert shown == ["activation"]
        assert sec["nodes_not_computable"] == 1 and sec["nodes_not_computable_keys"] == shown
        assert "Not computable" in sec["not_computable_rule"]
        # the mechanism is trailing_baseline, not not_computable: the count must follow status
        act = next(r for r in sec["rows"] if r["metric_key"] == "activation")
        assert act["mechanism"] == "trailing_baseline" and act["actual"] == 0.0

    @pytest.mark.parametrize("d", DATES)
    def test_the_rendered_document_states_the_same_count(self, readouts, d):
        md = wr.render_markdown(readouts[d])
        assert "**Nodes:** 11 tracked, %d breaching the variance threshold, 1 Not computable " \
               "(Activation (TTFA, blended))." % readouts[d]["layer1_scorecard"][
                   "nodes_breaching_threshold"] in md
        checks = {c["name"]: c for c in wr.verify_rendered_document(md, readouts[d])}
        assert checks["scorecard_rendered_values_match_structured_payload"]["passed"]
        stripped = md.replace("1 Not computable", "0 Not computable")
        checks = {c["name"]: c for c in wr.verify_rendered_document(stripped, readouts[d])}
        assert not checks["scorecard_rendered_values_match_structured_payload"]["passed"]


@pytest.fixture(scope="module")
def built():
    diag = vd.run_diagnostic(date(2025, 11, 30))
    return diag, wr.assemble_readout(date(2025, 11, 30), diagnostic=diag)


class TestNotComputableTraceCheck:
    def test_a_fresh_assembly_passes_the_check(self, built):
        diag, readout = built
        checks = {c["name"]: c for c in wr.verify_source_trace(readout, diag)}
        assert checks["not_computable_count_matches_scorecard_status"]["passed"]
        assert readout["layer1_scorecard"]["nodes_not_computable"] == 1

    @pytest.mark.parametrize("mutate", [
        lambda s: s.__setitem__("nodes_not_computable", 0),
        lambda s: s.__setitem__("nodes_not_computable_keys", []),
        lambda s: s.__setitem__("nodes_not_computable", 2),
    ])
    def test_a_count_that_disagrees_with_the_rows_fails_the_check(self, built, mutate):
        diag, readout = built
        bad = copy.deepcopy(readout)
        mutate(bad["layer1_scorecard"])
        checks = {c["name"]: c for c in wr.verify_source_trace(bad, diag)}
        assert not checks["not_computable_count_matches_scorecard_status"]["passed"]

    def test_the_mechanism_based_count_would_have_disagreed(self, built):
        """The previous rule counted mechanism == not_computable, which is 0 here."""
        _, readout = built
        assert sum(1 for r in readout["layer1_scorecard"]["rows"]
                   if r["mechanism"] == "not_computable") == 0


# --------------------------------------------------------------------------
# Voice of the strings the dashboard prints verbatim
# --------------------------------------------------------------------------

_ALLOWED_CAPS = {"NRR", "GRR", "MRR", "ARR", "CAC", "TTFA", "AUC", "SMB", "CRO", "USD", "TTM",
                 "CRM", "POC", "SDR", "MQL", "SAL", "PQL", "QA"}
_HEDGES = re.compile(
    r"rather than silently|stated rather|stated explicitly|applied silently|silently|"
    r"fabricat|forced into|to force symmetry|must not present|design brief|genuinely|"
    r"reported rather|read the |is computed, but|not guessed", re.I)
_IMPERATIVE = re.compile(r"(?:^|\. )(Read|Use|Note|Treat|Do not|Don't)\b")
_CODE = re.compile(r"\b(?:mart|fact|dim|int|stg)_\w+|\b[a-z]+_[a-z0-9_]+\b|\.py\b|\(\)")


def _strings(r):
    out = []
    for row in r["layer1_scorecard"]["rows"]:
        for f in ("gap_note", "plan_comparability_note"):
            if row.get(f):
                out.append(("row.%s.%s" % (row["metric_key"], f), row[f]))
    out.append(("scorecard.note", r["layer1_scorecard"]["note"]))
    out.append(("scorecard.rule", r["layer1_scorecard"]["not_computable_rule"]))
    out.append(("drilldowns.note", r["drilldowns"]["note"]))
    for e in r["drilldowns"]["entries"]:
        k = e["layer1"]["metric_key"]
        for i, n in enumerate(e["notes"]):
            out.append(("drilldown.%s.note%d" % (k, i), n))
        for m in e["sibling_coverage"]["missing_siblings"]:
            out.append(("drilldown.%s.missing.%s" % (k, m["metric_key"]), m["gap_note"]))
    out.append(("header.grain", r["header"]["reporting_period_grain_note"]))
    f = r["forecast"]
    for k in ("note", "data_window_note", "divergence_threshold_status"):
        out.append(("forecast." + k, f[k]))
    out.append(("forecast.selection", f["selection"]["rule"]))
    out.append(("forecast.plan", f["plan_comparison"]["reason"]))
    out.extend(("forecast.caveat%d" % i, c) for i, c in enumerate(f["caveats"]))
    out.append(("watchlist.rule", r["watchlist"]["selection_rule"]))
    out.extend(("watchlist.caveat%d" % i, c) for i, c in enumerate(r["watchlist"]["caveats"]))
    return out


class TestVoice:
    @pytest.mark.parametrize("d", DATES)
    def test_no_assistant_voice_caps_emphasis_imperatives_or_code_identifiers(self, readouts, d):
        problems = []
        for name, text in _strings(readouts[d]):
            for m in re.finditer(r"\b[A-Z]{4,}\b", text):
                if m.group(0) not in _ALLOWED_CAPS:
                    problems.append((name, "caps", m.group(0)))
            for rx, kind in ((_HEDGES, "hedge"), (_IMPERATIVE, "imperative"), (_CODE, "code")):
                m = rx.search(text)
                if m:
                    problems.append((name, kind, m.group(0)))
        assert not problems, problems

    @pytest.mark.parametrize("d", DATES)
    def test_list_item_notes_are_short_and_the_long_form_lives_in_detail(self, readouts, d):
        sc = readouts[d]["layer1_scorecard"]["rows"]
        for row in sc:
            if row["plan_comparability_note"]:
                assert len(row["plan_comparability_note"]) <= 260, row["metric_key"]
        caveated = [r for r in sc if r["plan_comparability"] == "caveated"]
        assert len(caveated) == 5
        for row in caveated:
            assert row["plan_comparability_detail"], row["metric_key"]
            assert row["plan_comparability_note"].startswith("Caveated:")
        activation = next(r for r in sc if r["metric_key"] == "activation")
        assert "trailing 3-month baseline" in activation["plan_comparability_note"]
        assert "day-grain first-Action timestamp" in activation["plan_comparability_detail"]
        for e in readouts[d]["drilldowns"]["entries"]:
            for n in e["notes"]:
                assert len(n) <= 330, (e["layer1"]["metric_key"], n)
            for item in e["notes_detail"]:
                assert item["note"] in e["notes"] and len(item["detail"]) > len(item["note"])

    @pytest.mark.parametrize("d", DATES)
    def test_no_disclosed_fact_was_dropped_from_the_long_forms(self, readouts, d):
        rows = {r["metric_key"]: r for r in readouts[d]["layer1_scorecard"]["rows"]}
        magic = rows["magic_number"]["plan_comparability_detail"]
        for fact in ("marketing-team headcount", "trailing-12-month ratio", "about 0.9 to 2.5",
                     "about 88% a year", "SMB carries no rep cost"):
            assert fact in magic.replace("Marketing-team", "marketing-team"), fact
        pay = rows["consumption_payback"]["plan_comparability_detail"]
        for fact in ("fully loaded CAC", "tooling and data enrichment", "installed base",
                     "9-13 months"):
            assert fact in pay, fact
        am = rows["am_efficiency"]["plan_comparability_detail"]
        for fact in ("Q4 seasonality", "SMB's share of expansion", "about 0.8 to 2.6"):
            assert fact in am, fact
        nrr = rows["nrr"]["plan_comparability_detail"]
        for fact in ("annual-equivalent", "5.4%", "10.8%", "0.51", "1.82", "within 2%"):
            assert fact in nrr, fact
        assert rows["grr"]["plan_comparability_detail"].startswith("Same two adjustments as NRR")

    def test_every_short_note_is_in_the_drilldown_it_belongs_to(self, readouts):
        d = "2025-11-30"
        entries = {e["layer1"]["metric_key"]: e for e in readouts[d]["drilldowns"]["entries"]}
        rows = {r["metric_key"]: r for r in readouts[d]["layer1_scorecard"]["rows"]}
        for k in ("magic_number", "consumption_payback", "am_efficiency", "nrr", "grr"):
            assert rows[k]["plan_comparability_note"] in entries[k]["notes"], k
        assert vd.PIPELINE_GENERATED_SCOPE_NOTE in entries["new_logo_consumption_revenue"]["notes"]
        assert any(i["detail"] == vd.PIPELINE_GENERATED_SCOPE_DETAIL
                   for i in entries["new_logo_consumption_revenue"]["notes_detail"])
        single = [n for n in entries["contraction_churned_revenue"]["notes"]
                  if n.startswith("Single-candidate read")]
        assert single and "no sibling comparison" in single[0]


# --------------------------------------------------------------------------
# NRR / GRR drivers are cross-references to the Growth drivers
# --------------------------------------------------------------------------

class TestCrossReferenceLabelling:
    def test_engine_nodes_under_nrr_and_grr_are_labelled_as_growth_cross_references(self):
        for key in ("nrr_expansion_rate", "nrr_contraction_rate", "nrr_churn_rate",
                    "grr_contraction_rate", "grr_churn_rate"):
            node = vd.get_node(key)
            assert node.label.startswith("See Growth: "), key
            assert node.cross_reference_to in ("expansion_consumption_revenue",
                                               "contraction_churned_revenue")
            assert node.layer == 2

    @pytest.mark.parametrize("d", DATES)
    def test_the_payload_names_the_growth_node_each_driver_mirrors(self, readouts, d):
        for e in readouts[d]["drilldowns"]["entries"]:
            if e["layer1"]["metric_key"] not in ("nrr", "grr"):
                continue
            l2 = e["layer2_outlier"]
            assert l2["label"].startswith("See Growth: ")
            assert l2["cross_reference_label"] == vd.get_node(l2["cross_reference_to"]).label
            for r in e["sibling_ranking"]:
                assert r["cross_reference_label"] == vd.get_node(r["cross_reference_to"]).label
            tree = [n for n in e["notes"] if n.startswith("Tree definition")]
            assert tree and "'See Growth" in tree[0] and "single reference" in tree[0]

    def test_other_drilldowns_carry_no_cross_reference(self, readouts):
        for e in readouts["2025-11-30"]["drilldowns"]["entries"]:
            if e["layer1"]["metric_key"] not in ("nrr", "grr"):
                assert not e["layer2_outlier"] or not e["layer2_outlier"]["cross_reference_to"]

    def test_the_tree_file_is_unchanged_in_meaning(self):
        tree = open(os.path.join(os.path.dirname(OUT), "..", "docs",
                                 "acme-corp-gtm-metric-tree.md")).read()
        assert "See Growth — expansion, contraction, churn drivers" in tree
        assert "See Growth — contraction, churn drivers" in tree


# --------------------------------------------------------------------------
# Period-aware forecast notes and the ML target position
# --------------------------------------------------------------------------

class TestForecastNotes:
    def test_the_data_window_note_applies_only_to_the_quarter_it_describes(self, readouts):
        june = readouts["2025-06-30"]["forecast"]["data_window_note"]
        nov = readouts["2025-11-30"]["forecast"]["data_window_note"]
        assert "2025-Q2" in june and "does not apply" in june and "2025-Q4" not in june
        assert "2025-Q4" in nov and "every open deal scopes into the current quarter" in nov
        assert fc._data_window_note(date(2025, 6, 27)) == june
        assert fc._data_window_note(date(2025, 11, 28)) == nov

    @pytest.mark.parametrize("d", DATES)
    def test_the_selection_rule_states_the_one_post_call_field_that_is_read(self, readouts, d):
        rule = readouts[d]["forecast"]["selection"]["rule"]
        assert "close date" in rule and "no outcome after the call is read" in rule
        assert "Nothing after the period end is read" not in rule

    def test_the_ml_target_position_is_stated_with_its_direction(self, readouts):
        june = readouts["2025-06-30"]["forecast"]["ml_lens"]
        nov = readouts["2025-11-30"]["forecast"]["ml_lens"]
        assert june["auc_target_position"] == "above" and june["auc_holdout"] > 0.85
        assert nov["auc_target_position"] == "within"
        md_june = wr.render_markdown(readouts["2025-06-30"])
        md_nov = wr.render_markdown(readouts["2025-11-30"])
        assert "(above the 0.70-0.85 target range)" in md_june
        assert "(within the target range)" in md_nov

    def test_the_rebuild_variation_caveat_is_carried(self, readouts):
        for d in DATES:
            caveats = readouts[d]["forecast"]["caveats"]
            assert any("vary slightly across database rebuilds" in c and "0.53%" in c
                       for c in caveats)
