"""Reader-facing labels and text cleaning (dashboard/lib/labels.py)."""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard.lib import labels as L  # noqa: E402


@pytest.mark.parametrize("rule,label", [
    ("ingestion_without_completion", "Ingestion without completion"),
    ("poc_pass_rate_below_threshold", "POC pass rate below threshold"),
    ("post_close_underutilization", "Post-close under-utilization"),
])
def test_known_rules_have_labels(rule, label):
    assert L.rule_label(rule) == label


def test_unknown_rule_is_humanized_with_acronyms():
    assert L.rule_label("poc_new_rule") == "POC new rule"


def test_source_labels_hide_table_prefixes():
    out = L.source_label("fact_committed_vs_utilized_monthly + fact_opportunities")
    assert out == "Committed vs. utilized Actions (monthly) and Opportunities"
    assert "fact_" not in L.source_label("fact_something_new")


def test_evidence_columns_get_display_labels_and_ids_are_hidden():
    assert L.field_label("parent_key") == "Under" and L.field_label("label") == "Metric"
    assert "metric_key" in L.HIDDEN_FIELDS


class TestCleanRegistryText:
    def test_markdown_and_identifiers_are_removed(self):
        out = L.clean_registry_text("**non-additive** diagnostic overlay on mart_efficiency and fact_leads")
        assert "**" not in out and "mart_efficiency" not in out and "fact_leads" not in out

    def test_snake_case_words_become_words(self):
        assert "win rate" in L.clean_registry_text("SMB always shows win_rate = 1.0")

    def test_paths_and_functions_are_rewritten_not_quoted(self):
        out = L.clean_registry_text("Computed by analytics/marketing_attribution.py, so query_metric cannot serve it.")
        assert ".py" not in out and "query_metric" not in out and "marketing attribution" in out

    def test_constant_names_drop_the_sentence_but_keep_the_rest(self):
        out = L.clean_registry_text("Not registered in _SOURCE_MART_MAP -- nothing mapped. Company-wide only.")
        assert out == "Company-wide only."

    def test_segment_tuple_becomes_a_list(self):
        out = L.clean_registry_text("must be one of ('SMB', 'Commercial', 'Enterprise')")
        assert out == "Must be one of SMB, Commercial or Enterprise"

    def test_empty_text(self):
        assert L.clean_registry_text(None) == "" and L.clean_registry_text("") == ""

    def test_sentences_start_with_a_capital(self):
        out = L.clean_registry_text("Needs rep data. dim_reps carries quota but nothing exposes it.")
        assert "Reps data carries quota" in out


class TestGuardrails:
    def test_codes_have_readable_labels_and_unknown_codes_never_leak(self):
        assert L.guardrail_label("dimension_not_queryable") == "Split not available yet"
        assert L.guardrail_label("something_new") == "Request not supported"
        assert L.guardrail_label(None) == "Request not supported"

    def test_dimension_message_is_rewritten(self):
        msg = ("The metric tree allows 'channel' on 'cac_by_channel', but no mart_* table currently exposes "
               "that cut -- queryable_dimensions today: ['segment']. gap_note: mart_efficiency exposes blended_cac.")
        sentence, tail = L.guardrail_sentence("dimension_not_queryable", msg, "CAC by channel")
        assert sentence == ("The metric tree allows a channel split on CAC by channel, but no reporting table "
                            "exposes that split yet. Available split: segment.")
        assert tail and "gap_note" not in tail and "mart_" not in tail

    def test_tail_equal_to_the_displayed_gap_note_is_dropped(self):
        msg = ("The metric tree allows 'channel' on 'x', but no mart_* table currently exposes that cut -- "
               "queryable_dimensions today: ['segment']. gap_note: Something happened.")
        _, tail = L.guardrail_sentence("dimension_not_queryable", msg, "X", gap_note="Something happened.")
        assert tail is None

    def test_segment_rejection_is_a_clean_sentence(self):
        s, _ = L.guardrail_sentence("invalid_segment_value",
                                    "'Tier 1' is not a valid segment -- must be one of ('SMB', 'Commercial', 'Enterprise').", "Win rate")
        assert "(" not in s.split("one of")[1][:5] and "SMB, Commercial or Enterprise" in s

    def test_overlay_sentence_strips_markdown_and_build_machinery(self):
        out = L.overlay_sentence("LTV", "**non-additive** diagnostic overlay on payback", False,
                                 "Not registered in semantic/build_registry.py's _SOURCE_MART_MAP.")
        assert "**" not in out and "_SOURCE_MART_MAP" not in out and "It has no series of its own" in out


class TestFirstSentences:
    def test_short_text_is_not_split(self):
        assert L.first_sentences("One. Two.", 200) == ("One. Two.", "")

    def test_long_text_keeps_every_fact_in_the_remainder(self):
        text = "First sentence here. " + "Second sentence that is long enough. " * 8
        short, rest = L.first_sentences(text.strip(), 30)
        assert short == "First sentence here." and rest.startswith("Second")
        assert (short + " " + rest).replace("  ", " ") == text.strip()

    def test_an_overlong_first_sentence_is_cut_and_fully_kept(self):
        text = "word " * 80
        short, rest = L.first_sentences(text.strip(), 50)
        assert short.endswith("…") and len(short) <= 51 and rest == text.strip()


# ---------------------------------------------------------------------------
# Markdown escaping, the explicit phrase map, and the page-level alert-box rule
# ---------------------------------------------------------------------------
import ast  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402


class TestEscapeMarkdown:
    def test_two_dollar_amounts_cannot_open_a_latex_span(self):
        out = L.escape_markdown("$1.50M here, $1.40M in the readout")
        assert out.count("\\$") == 2 and "$" not in out.replace("\\$", "")

    def test_emphasis_characters_are_literal(self):
        assert L.escape_markdown("a_b *c* #d") == "a\\_b \\*c\\* \\#d"

    def test_forecast_comparison_text_survives_escaping_intact(self):
        from dashboard.lib import forecast_logic as F
        seg = dict(segment="Commercial", bottoms_up_rep=1.0, bottoms_up_manager=1.0, ml=1.0,
                   cro_adjusted=1500000.0, open_pipeline_amount=5.0)
        text = F.compare_to_readout([seg], [dict(seg, cro_adjusted=1400000.0)], "2025-11-30")[0]["text"]
        esc = L.escape_markdown(text)
        assert "$1.50M" in esc.replace("\\$", "$") and esc.count("\\$") == text.count("$")


def _safe_alert_arg(node) -> bool:
    """An argument to st.warning/info/error/success is safe when every interpolated or
    concatenated part is a literal or passes through escape_md (or is a variable named
    *_md, which the page computes from escape_md)."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.JoinedStr):
        return all(_safe_alert_arg(v) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return _safe_alert_arg(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _safe_alert_arg(node.left) and _safe_alert_arg(node.right)
    if isinstance(node, ast.Call):
        fn = node.func
        return (isinstance(fn, ast.Attribute) and fn.attr == "escape_md") or \
               (isinstance(fn, ast.Name) and fn.id == "escape_md")
    if isinstance(node, ast.Name):
        return node.id.endswith("_md")
    return False


def test_every_dynamic_alert_box_escapes_its_data():
    root = os.path.join(REPO, "dashboard")
    files = glob.glob(os.path.join(root, "pages", "*.py")) + [os.path.join(root, "home.py")]
    offenders = []
    for path in files:
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "st"
                    and node.func.attr in {"warning", "info", "error", "success"} and node.args):
                if not _safe_alert_arg(node.args[0]):
                    offenders.append(f"{os.path.basename(path)}:{node.lineno}")
    assert offenders == [], f"st.{{warning,info,error,success}} with unescaped data: {offenders}"


class TestPhraseMap:
    @pytest.mark.parametrize("raw,expected", [
        ("SMB always shows win_rate = 1.0 (every SMB opportunity is created already Closed Won -- build spec Section 2)",
         "SMB always shows a win rate of 100% (every SMB opportunity is created already Closed Won)"),
        ("Real, not fabricated, just degenerate on this data.", "The value is a property of the data."),
        ("A real data property, not a query bug.", "The value is a property of the data."),
        ("use grain=year for a stable read", "use the year grain for a stable read"),
        ("summed PRIOR-period S&M cost", "summed prior-period S&M cost"),
        ("(see the calibration note in docs/acme-corp-analytics-methods.md)",
         "(see the calibration note in the analytics methods document)"),
        ("(full_chain_completion_rate < 70%)", "(full-chain completion rate below 70%)"),
        ("spread > 25% of the mean", "spread above 25% of the mean"),
        ("The build spec's community_membership source was never generated.",
         "The community_membership source was never generated."),
    ])
    def test_exact_rewrites(self, raw, expected):
        assert L.apply_phrase_map(raw) == expected

    def test_unlisted_text_is_untouched(self):
        text = "Net new ARR over prior-period S&M cost."
        assert L.apply_phrase_map(text) == text and L.apply_phrase_map(None) == ""

    def test_renewal_scoping_sentence_keeps_its_facts(self):
        out = L.clean_registry_text(
            "Needs opportunity-level detail (stage history, loss_reason, list_price, or opportunity_type='renewal' "
            "scoping) that lives in fact_opportunities / fact_opportunity_stage_history -- fact_* tables outside a "
            "mart_* rollup for this cut.")
        assert "renewal-only scoping" in out and "stage history, loss reason, list price" in out
        assert "fact_" not in out and "mart_" not in out and "event tables" not in out

    def test_queryable_dimension_sentence(self):
        out = L.clean_registry_text(
            "the tree's own per-channel cut is not exposed by any mart_* table, so `channel` is listed in "
            "allowed_dimensions per the tree but is NOT in queryable_dimensions until a Phase 2 mart change exposes it.")
        assert out.endswith("until the data model exposes it.") and "NOT" not in out and "_" not in out

    def test_pointer_nodes_say_what_to_ask_instead(self):
        out = L.clean_registry_text(
            "Defined by reference in the tree ('See Growth -- expansion, contraction, churn drivers') -- query "
            "nrr_expansion/contraction/churn via expansion_consumption_revenue and "
            "contraction_churned_consumption_revenue instead.")
        assert "ask about Expansion consumption revenue and Contraction + churned consumption revenue instead" in out
        assert "query" not in out and "_" not in out

    def test_abbreviation_does_not_start_a_sentence_in_the_middle(self):
        out = L.clean_registry_text("Leads data records only convert vs. not, which is the lead-to-PQL rate.")
        assert "vs. not" in out

    def test_mart_column_reference_reads_as_words(self):
        out = L.clean_registry_text("The cost side exists (mart_efficiency.sm_cost) and mart_efficiency.rep_ramp_cost isolates ramp.")
        assert "mart_" not in out and "S&M cost" in out and "rep ramp cost" in out


FORBIDDEN_IN_REGISTRY_TEXT = ("build spec", "grain=", "PRIOR", "Real, not fabricated", "not a query bug",
                              "queryable_dimensions", "allowed_dimensions", ".py", "fact_", "dim_", "mart_",
                              "query_metric", "Phase 2 mart", "**")


def test_cleaned_live_registry_text_has_no_process_references():
    """Audit of the live registry through the display layer; a new upstream string that
    slips past the phrase map fails here and is the cue to extend it."""
    with open(os.path.join(REPO, "semantic", "metric_registry.json")) as f:
        metrics = json.load(f)["metrics"]
    offenders = []
    for key, node in metrics.items():
        for field in ("gap_note", "note"):
            cleaned = L.clean_registry_text(node.get(field))
            offenders += [f"{key}.{field}: {tok!r}" for tok in FORBIDDEN_IN_REGISTRY_TEXT if tok in cleaned]
    assert offenders == []


class TestSegmentNotAvailableMessages:
    def test_old_shape(self):
        msg = ("'am_efficiency' has no rows for segment 'SMB': its source mart (mart_efficiency) carries "
               "['Commercial', 'Enterprise'] only. gap_note: Commercial and Enterprise only.")
        sentence, tail = L.guardrail_sentence("segment_not_available", msg, "AM efficiency")
        assert sentence == "AM efficiency has no data for the SMB segment; it covers Commercial or Enterprise only."

    def test_poc_pass_rate_shape(self):
        msg = ("'poc_pass_rate' has no POC data for segment 'Commercial': proof-of-concept outcomes exist only in the "
               "Enterprise motion, so the source mart (mart_deal_funnel) has no POC outcomes for any other segment; "
               "the metric is defined for ['Enterprise'] only. gap_note: Enterprise only, as the tree specifies.")
        sentence, tail = L.guardrail_sentence("segment_not_available", msg, "POC pass rate (Enterprise)")
        assert sentence == ("POC pass rate (Enterprise) has no data for the Commercial segment; "
                            "it covers Enterprise only.")
        assert tail and tail.startswith("Enterprise only")
        assert L.guardrail_label("segment_not_available") == "Segment not available"
