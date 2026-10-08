"""Pipeline-coverage display rules (dashboard/lib/coverage_view.py): status chip, quota-met
null ratio, gap sign wording, next-quarter states, unavailable reasons, dollar escaping and the
two committed reports. Numbers are compared with a relative tolerance of 1e-9 and an absolute
floor of 1e-9 so the checks are platform independent."""
import ast
import copy
import glob
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard.lib import coverage_view as V  # noqa: E402

OUT = os.path.join(REPO, "analytics", "outputs")
DATES = ("2025-08-15", "2025-11-14")
APPROX = dict(rel=1e-9, abs=1e-9)

RULE = {"covered_min_coverage_vs_required": 1.0, "thin_min_coverage_vs_required": 0.75,
        "status": "proposed, not yet confirmed"}


def reading(date):
    with open(os.path.join(OUT, f"pipeline_coverage_{date}.json")) as f:
        return json.load(f)["reading"]


def seg(reading_, name):
    return next(s for s in reading_["segments"] if s["segment"] == name)


def fake_seg(**over):
    base = dict(
        segment="Commercial", owner_role="ISR", status="present", coverage_status="thin",
        open_pipeline_after_quarter_deals=0, coverage_vs_required=0.8, conversion_implied_gap_usd=1000.0,
        display={"status_text": "Thin", "remaining_quota": "$1.0K", "quota": "$2.0K", "won_to_date": "$1.0K",
                 "attainment_to_date": "50.0%", "quota_basis": "basis", "open_pipeline": "$3.0K across 2 deals",
                 "coverage_vs_required": "0.80x", "pipeline_coverage_ratio": "3.00x",
                 "required_pipeline_multiple": "3.75x", "realized_conversion": "26.7% over 40 closed deals since 2024-01-01",
                 "conversion_implied_expected_close": "$0.0K", "conversion_implied_gap": "$1.0K short",
                 "pipeline_after_quarter_end": "$0 across 0 deals expected to close after quarter end, not counted"})
    base.update(over)
    return base


class TestStatusChip:
    @pytest.mark.parametrize("status,expected", [
        ("covered", "Proposed band: Covered, 1.00x of required or more"),
        ("thin", "Proposed band: Thin, 0.75x to below 1.00x of required"),
        ("shortfall", "Proposed band: Shortfall, below 0.75x of required"),
        ("quota_met", "Proposed band: Quota met, no quota left to book"),
    ])
    def test_band_text_comes_from_the_status_rule(self, status, expected):
        s = fake_seg(coverage_status=status, display={"status_text": V.STATUS_WORD[status]})
        assert V.status_chip(s, RULE) == expected

    def test_band_thresholds_are_the_artifacts_not_hardcoded(self):
        rule = dict(RULE, thin_min_coverage_vs_required=0.6)
        s = fake_seg(coverage_status="shortfall", display={"status_text": "Shortfall"})
        assert V.status_chip(s, rule) == "Proposed band: Shortfall, below 0.60x of required"

    def test_chip_without_a_rule_names_the_status_only(self):
        s = fake_seg(coverage_status="thin", display={"status_text": "Thin"})
        assert V.status_chip(s, None) == "Proposed band: Thin"

    def test_unavailable_segment_has_no_chip(self):
        assert V.status_chip(fake_seg(status="unavailable", coverage_status="unavailable"), RULE) is None

    def test_chip_never_reads_as_a_verdict(self):
        for status in V.BAND_STATUSES:
            chip = V.status_chip(fake_seg(coverage_status=status, display={"status_text": V.STATUS_WORD[status]}), RULE)
            assert chip.startswith("Proposed band: ")


class TestQuotaMet:
    def test_coverage_value_reads_quota_met_not_a_ratio(self):
        s = fake_seg(coverage_status="quota_met", coverage_vs_required=None, pipeline_coverage_ratio=None)
        assert V.coverage_value(s) == ("Quota met", "sm")

    def test_card_has_no_zero_ratio(self):
        s = fake_seg(coverage_status="quota_met", coverage_vs_required=None,
                     display=dict(fake_seg()["display"], coverage_vs_required="n/a", pipeline_coverage_ratio="n/a"))
        cards = V.segment_cards(s, "2025-Q4", "2025-11-14")
        text = json.dumps(cards)
        assert "0.00x" not in text and cards[2]["value_display"] == "Quota met"
        assert "No quota left to book" in cards[2]["footer"][0]

    def test_a_present_ratio_reads_x_of_required(self):
        assert V.coverage_value(fake_seg()) == ("0.80x of required", None)


class TestGapWording:
    def test_display_string_is_used_verbatim(self):
        assert V.gap_wording(fake_seg()) == "$1.0K short"
        assert V.gap_wording(fake_seg(display={"conversion_implied_gap": "$1.27M ahead"})) == "$1.27M ahead"

    def test_field_fallback_keeps_the_sign_convention(self):
        assert V.gap_wording(fake_seg(display={}, conversion_implied_gap_usd=181747.85)) == "$181.7K short"
        assert V.gap_wording(fake_seg(display={}, conversion_implied_gap_usd=-1274121.44)) == "$1.27M ahead"
        assert V.gap_wording(fake_seg(display={}, conversion_implied_gap_usd=None)) == "n/a"

    @pytest.mark.parametrize("date", DATES)
    def test_wording_matches_the_sign_of_the_field(self, date):
        for s in reading(date)["segments"]:
            word = V.gap_wording(s).split()[-1]
            assert word == ("short" if s["conversion_implied_gap_usd"] > 0 else "ahead")


class TestCards:
    def test_four_cards_each_with_a_basis_footer(self):
        cards = V.segment_cards(fake_seg(), "2025-Q4", "2025-11-14")
        assert [c["label"] for c in cards] == ["Remaining quota", "Open new-business pipeline",
                                               "Coverage vs required", "Conversion-implied gap"]
        for c in cards:
            assert any(line.startswith("Basis: ") for line in c["footer"])

    def test_no_card_carries_a_status_color_input(self):
        for c in V.segment_cards(fake_seg(), "2025-Q4", "2025-11-14"):
            assert not {"is_ahead", "favorable_direction", "variance_display"} & set(c)

    def test_after_quarter_pipeline_shows_only_when_there_are_deals(self):
        none = V.segment_cards(fake_seg(), "2025-Q3", "2025-08-15")[1]["footer"]
        assert not any("after quarter end" in line for line in none)
        some = V.segment_cards(fake_seg(open_pipeline_after_quarter_deals=31,
                                        display=dict(fake_seg()["display"], pipeline_after_quarter_end="$8.13M across 31 deals expected to close after quarter end, not counted")),
                               "2025-Q3", "2025-08-15")[1]["footer"]
        assert any("$8.13M across 31 deals" in line for line in some)

    def test_dates_in_footers_do_not_wrap(self):
        footer = V.segment_cards(fake_seg(), "2025-Q4", "2025-11-14")[2]["footer"]
        assert not any("2024-01-01" in line for line in footer) and any("2024‑01‑01" in line for line in footer)

    @pytest.mark.parametrize("date", DATES)
    def test_cards_use_the_artifacts_display_strings(self, date):
        r = reading(date)
        for s in r["segments"]:
            cards = V.segment_cards(s, r["period"], r["as_of_date"])
            assert cards[0]["value_display"] == s["display"]["remaining_quota"]
            assert cards[1]["value_display"] == s["display"]["open_pipeline"]
            assert cards[3]["value_display"] == s["display"]["conversion_implied_gap"]


class TestPocView:
    def test_present_view_states_n_and_is_labelled_indicative(self):
        block = V.poc_view_block(seg(reading("2025-11-14"), "Enterprise")["poc_view"])
        assert block["chip"] == "Indicative, not a forecast"
        text = " ".join(block["lines"])
        assert "59 closed deals, 26 won (42.1%)" in text and "78 closed deals, 7 won (9.5%)" in text

    def test_unavailable_view_has_no_figures(self):
        block = V.poc_view_block({"status": "unavailable", "reason": "too few closed deals", "label": "indicative, not a forecast"})
        assert block["lines"] == ["Too few closed deals"]

    def test_absent_view_renders_nothing(self):
        assert V.poc_view_block(None) is None
        assert seg(reading("2025-11-14"), "Commercial")["poc_view"] is None


class TestUnavailableReasons:
    WINDOW = {"last_opportunity_close": "2025-12-28"}

    @pytest.mark.parametrize("code,needle", [
        ("no_quota", "no quota to cover"),
        ("before_conversion_window", "precedes January 2023"),
        ("insufficient_closed_deals", "Only 11 closed deals between 2023-01-01 and 2023-01-13"),
        ("no_wins_in_window", "No deal was won"),
        ("after_data_window", "(2025-12-28)"),
    ])
    def test_each_reason_code_has_plain_language(self, code, needle):
        s = fake_seg(status="unavailable", reason_code=code, conversion_closed_deals=11,
                     conversion_window_start="2023-01-01", conversion_window_end="2023-01-13")
        msg = V.unavailable_message(s, self.WINDOW)
        assert msg.startswith("Commercial: coverage reading unavailable.") and needle in msg

    def test_unknown_code_falls_back_to_the_artifacts_reason(self):
        s = fake_seg(status="unavailable", reason_code="something_new", reason="a new reason")
        assert V.unavailable_message(s).endswith("A new reason")

    def test_no_reason_code_text_or_figures_leak(self):
        for code in ("no_quota", "before_conversion_window", "insufficient_closed_deals", "no_wins_in_window",
                     "after_data_window"):
            msg = V.unavailable_message(fake_seg(status="unavailable", reason_code=code), self.WINDOW)
            assert "_" not in msg and "0.00x" not in msg and "$" not in msg


class TestNextQuarter:
    def test_unavailable_at_the_data_window_end_is_a_blank_not_a_zero(self):
        r = reading("2025-11-14")
        v = V.next_quarter_view(r["next_quarter"], r["data_window"])
        assert v["kind"] == "unavailable" and v["lines"] == []
        assert "blank" in v["message"] and "2025-12-28" in v["message"] and "not zero coverage" in v["message"]
        assert v["needed"] and "0.00x" not in json.dumps(v)

    def test_reader_text_carries_no_reason_code_or_simulation_wording(self):
        r = reading("2025-11-14")
        v = V.next_quarter_view(r["next_quarter"], r["data_window"])
        text = json.dumps(v)
        assert "beyond_data_window" not in text and "simulated" not in text

    def test_present_block_commercial_none_yet_enterprise_has_figures(self):
        r = reading("2025-08-15")
        v = V.next_quarter_view(r["next_quarter"], r["data_window"])
        assert v["kind"] == "present" and v["period"] == "2025-Q4"
        lines = dict(v["lines"])
        assert lines["Commercial"].startswith("none yet") and "0.00x" not in lines["Commercial"]
        assert lines["Enterprise"].startswith("$8.13M across 31 deals closing next quarter")
        assert lines["Commercial"].endswith("no verdict") and lines["Enterprise"].endswith("no verdict")
        assert v["note"].startswith("Indicative only")

    def test_absent_block_shows_nothing(self):
        assert V.next_quarter_view(None)["kind"] == "absent"


class TestReconciliation:
    @pytest.mark.parametrize("date", DATES)
    def test_rows_and_tie_text(self, date):
        r = reading(date)
        v = V.reconciliation_view(r["reconciliation"])
        assert v["available"] and v["tie_text"] == "Open pipeline ties exactly to the forecast's new-business pipeline."
        assert [row[0] for row in v["rows"]] == ["Commercial", "Enterprise"]
        for row in v["rows"]:
            assert len(row) == len(V.RECON_HEADERS)
            assert "above the forecast lens" in row[5] or "below the forecast lens" in row[5]

    def test_2025_11_14_differences_match_the_report(self):
        r = reading("2025-11-14")
        v = V.reconciliation_view(r["reconciliation"])
        assert v["rows"][0][5] == "$21.4K above the forecast lens (13.1%)"
        assert v["rows"][1][5] == "$150.7K above the forecast lens (13.4%)"
        by = {b["segment"]: b for b in r["reconciliation"]["by_segment"]}
        assert by["Commercial"]["difference_usd"] == pytest.approx(
            by["Commercial"]["coverage_reading_conversion_implied_expected_close_usd"]
            - by["Commercial"]["forecast_manager_lens_new_business_weighted_usd"], **APPROX | {"abs": 0.011})

    def test_all_type_pipeline_is_the_artifacts_figure(self):
        v = V.reconciliation_view(reading("2025-11-14")["reconciliation"])
        assert v["rows"][0][6] == "$2.06M across 113 deals" and v["rows"][1][6] == "$9.19M across 33 deals"

    def test_a_negative_difference_reads_below(self):
        assert V._difference_text(-19900.0, -0.0216) == "$19.9K below the forecast lens (2.2%)"

    def test_unavailable_reconciliation_has_no_rows(self):
        v = V.reconciliation_view({"status": "unavailable", "reason": "x"})
        assert v["available"] is False and v["rows"] == []

    def test_a_non_tying_reconciliation_says_so(self):
        rec = copy.deepcopy(reading("2025-11-14")["reconciliation"])
        rec["ties_on_open_pipeline"] = False
        assert "does not tie" in V.reconciliation_view(rec)["tie_text"]


class TestNotes:
    def test_kinds_are_the_allowed_labels(self):
        for date in DATES:
            items = V.notes_for(reading(date), None)
            assert items and {k for k, _ in items} <= {"Assumption", "Scope", "Data gap"}

    def test_caveat_classification(self):
        assert V.classify_caveat("The data window ends in late December 2025: x") == "Data gap"
        assert V.classify_caveat("Quota is never pro-rated for a mid-quarter hire") == "Assumption"
        assert V.classify_caveat("Commercial and Enterprise new business only") == "Scope"

    def test_every_artifact_caveat_is_kept_as_written(self):
        r = reading("2025-11-14")
        texts = [t for _, t in V.notes_for(r, None)]
        for c in r["caveats"]:
            assert c in texts

    def test_backtest_lines_quote_the_report(self):
        with open(os.path.join(OUT, "pipeline_coverage_2025-11-14.json")) as f:
            summary = json.load(f)["backtest_summary"]
        text = " ".join(t for _, t in V.backtest_notes(summary))
        assert "21 segment-quarters" in text and "29.6%" in text and "47.7%" in text and "50.5%" in text
        assert "22 segment-quarters" in V.band_evidence_note(summary)
        kind, floor = V.commercial_floor_note(summary)
        assert kind == "Data gap" and "15% below actual bookings" in floor and "23% of Commercial bookings" in floor

    def test_missing_backtest_adds_no_figures(self):
        assert V.backtest_notes(None) == []
        assert "small number of segment-quarters" in V.band_evidence_note(None)

    def test_bands_are_labelled_proposed(self):
        items = V.notes_for(reading("2025-11-14"), None)
        assert any(k == "Assumption" and "proposed, not confirmed" in t for k, t in items)

    def test_failure_state_still_carries_the_reading_label(self):
        items = V.notes_for(None)
        assert items and "not a forecast" in items[0][1]


class TestHeaderAndEscaping:
    def test_status_text_names_the_unvalidated_artifact(self):
        assert V.artifact_status_text("In progress", False) == "In progress, not yet independently validated"
        assert V.artifact_status_text("Built and validated", True) == "Built and validated"

    def test_info_items(self):
        items = dict(V.info_items(reading("2025-11-14"), "In progress"))
        assert items["Quarter"] == "2025-Q4, 47 days left" and items["Evaluation date"].startswith("2025-11-14")

    def test_scope_line_states_new_business_only(self):
        line = V.scope_line(reading("2025-11-14"))
        assert "new business only" in line and "ISR- and AE-owned" in line and "2025-Q4" in line

    def test_dollar_signs_survive_markdown_escaping(self):
        from dashboard.lib import labels
        summary = seg(reading("2025-11-14"), "Commercial")["display"]["summary"]
        esc = labels.escape_markdown(summary)
        assert esc.count("\\$") == summary.count("$") >= 2

    def test_page_wraps_every_alert_in_escape_md(self):
        path = os.path.join(REPO, "dashboard", "lib", "coverage_render.py")
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "st"
                    and node.func.attr in {"info", "warning", "error", "success"} and node.args):
                arg = node.args[0]
                assert isinstance(arg, ast.Constant) or (
                    isinstance(arg, ast.Call) and getattr(arg.func, "attr", "") == "escape_md")

    def test_no_reader_text_carries_hedging_or_identifiers(self):
        r = reading("2025-11-14")
        texts = [V.scope_line(r), V.ERROR_NOTICE] + [t for _, t in V.notes_for(r, None)]
        for t in texts:
            for bad in ("quietly", "to be safe", "we ", "I ", "pipeline_coverage"):
                assert bad not in t


class TestCommittedReports:
    @pytest.mark.parametrize("date", DATES)
    def test_every_segment_renders_without_error(self, date):
        r = reading(date)
        assert r["label"] == "coverage reading, not a forecast"
        for s in r["segments"]:
            assert s["status"] == "present"
            assert V.status_chip(s, r["status_rule"]).startswith("Proposed band: ")
            assert len(V.segment_cards(s, r["period"], r["as_of_date"])) == 4
            assert V.keep_dates_whole("x 2025-01-02") == "x 2025‑01‑02"
        assert V.reconciliation_view(r["reconciliation"])["available"]

    def test_statuses_at_the_two_checkpoints(self):
        a, b = reading("2025-08-15"), reading("2025-11-14")
        assert [s["coverage_status"] for s in a["segments"]] == ["thin", "thin"]
        assert [s["coverage_status"] for s in b["segments"]] == ["shortfall", "quota_met"]
        assert seg(b, "Enterprise")["pipeline_coverage_ratio"] is None

    @pytest.mark.parametrize("date", DATES)
    def test_coverage_identities_hold_in_the_reports(self, date):
        for s in reading(date)["segments"]:
            if s["coverage_status"] == "quota_met":
                continue
            assert s["coverage_vs_required"] * s["remaining_quota_usd"] == pytest.approx(
                s["open_pipeline_usd"] * s["realized_conversion"], rel=1e-6, abs=1e-6)
            assert s["conversion_implied_gap_usd"] == pytest.approx(
                s["remaining_quota_usd"] - s["conversion_implied_expected_close_usd"], rel=1e-9, abs=0.011)

    def test_every_committed_report_loads(self):
        paths = glob.glob(os.path.join(OUT, "pipeline_coverage_*.json"))
        assert len(paths) >= 2
        for p in paths:
            r = json.load(open(p))["reading"]
            for s in r["segments"]:
                if s["status"] == "present":
                    V.segment_cards(s, r["period"], r["as_of_date"])
                else:
                    assert V.unavailable_message(s, r["data_window"])


def committed_summary(date="2025-11-14"):
    with open(os.path.join(OUT, f"pipeline_coverage_{date}.json")) as f:
        return json.load(f)["backtest_summary"]


class TestBacktestNoteIsFair:
    """The backtest note states every comparator the report carries, the conclusion the
    report's own flags support, and never quotes a subset silently."""

    def text(self, summary):
        return " ".join(t for _, t in V.backtest_notes(summary))

    @pytest.mark.parametrize("date", DATES)
    def test_every_comparator_pooled_and_by_segment(self, date):
        sm = committed_summary(date)
        text = self.text(sm)
        for key in ("mape_coverage_implied", "mape_naive_won_to_date", "mape_naive_trailing_4q_mean",
                    "mape_naive_constant_rate_025", "mape_naive_pace"):
            assert f"{sm['pooled'][key] * 100:.1f}%" in text
            for seg_ in ("Commercial", "Enterprise"):
                assert f"{sm['by_segment'][seg_][key] * 100:.1f}%" in text
        assert "incomplete" not in text

    def test_2025_11_14_figures(self):
        text = self.text(committed_summary())
        for figure in ("29.6%", "47.7%", "50.5%", "26.1%", "32.8%", "19.9%", "40.3%", "15.0%", "38.3%", "39.8%"):
            assert figure in text

    def test_conclusion_says_the_constant_rate_scores_as_well_or_better(self):
        text = self.text(committed_summary())
        assert "beats won to date alone and the prior four-quarter mean" in text
        assert "scores as well or better, so the reading's value is the coverage and gap framing" in text
        assert "not extra accuracy" in text
        assert "Enterprise does not beat the pace comparator" in text

    def test_figures_are_driven_by_the_report_not_hard_coded(self):
        sm = copy.deepcopy(committed_summary())
        sm["pooled"]["mape_naive_constant_rate_025"] = 0.1234
        sm["by_segment"]["Enterprise"]["mape_coverage_implied"] = 0.5678
        text = self.text(sm)
        assert "12.3%" in text and "56.8%" in text and "26.1%" not in text and "40.3%" not in text

    def test_a_report_that_beats_the_constant_rate_says_so(self):
        sm = copy.deepcopy(committed_summary())
        sm["pooled"]["beats_constant_rate_baseline"] = True
        text = self.text(sm)
        assert "also beats the fixed constant-rate comparator" in text and "as well or better" not in text

    def test_missing_comparators_are_omitted_and_flagged_incomplete(self):
        sm = copy.deepcopy(committed_summary())
        for key in ("mape_naive_constant_rate_025", "mape_naive_pace"):
            del sm["pooled"][key]
            for row in sm["by_segment"].values():
                del row[key]
        sm["pooled"].pop("beats_constant_rate_baseline")
        text = self.text(sm)
        assert "26.1%" not in text and "32.8%" not in text
        assert "47.7%" in text and "50.5%" in text
        assert "The comparison is incomplete: constant rate, pace not in this report." in text
        assert "scores as well or better" not in text

    def test_every_line_fits_the_notes_display_limit(self):
        # theme.NOTE_LINE_LIMIT is 200: longer text moves behind a Details toggle, which would
        # hide the conclusion.
        for date in DATES:
            for _, line in V.backtest_notes(committed_summary(date)):
                assert len(line) <= 200, line

    def test_no_backtest_means_no_note(self):
        assert V.backtest_notes(None) == [] and V.backtest_notes({}) == []

    def test_hindsight_free_scoping_is_quoted_when_present(self):
        text = self.text(committed_summary())
        assert "27.9% pooled error against 29.6%" in text and "70.1%" in text


class TestCommercialFloorIsOneLine:
    def commercial_floor_lines(self, items):
        return [t for _, t in items if "Commercial" in t and ("floor" in t or "not yet visible" in t
                                                              or "cannot see pipeline" in t)]

    def test_one_line_with_backtest(self):
        items = V.notes_for(reading("2025-11-14"), committed_summary())
        lines = self.commercial_floor_lines(items)
        assert len(lines) == 1 and "about 15% below" in lines[0] and "23%" in lines[0]

    def test_one_artifact_caveat_without_backtest(self):
        items = V.notes_for(reading("2025-11-14"), None)
        assert len(self.commercial_floor_lines(items)) == 1


class TestSummaryAndQualifier:
    def test_summary_reads_as_coverage_not_a_point_forecast(self):
        s = seg(reading("2025-11-14"), "Commercial")
        text = V.segment_summary(s)
        assert "would close about $184.9K, $181.7K less than the quota still to book" in text
        assert "expected to close" not in text and "1.98x coverage" in text and "25.5% win rate" in text

    def test_quota_met_keeps_the_artifacts_summary(self):
        s = seg(reading("2025-11-14"), "Enterprise")
        assert V.segment_summary(s) == s["display"]["summary"]

    def test_gap_sentence_ahead_reads_more_than(self):
        s = fake_seg(display=dict(fake_seg()["display"], conversion_implied_gap="$5.0K ahead",
                                  conversion_implied_expected_close="$9.0K"))
        assert V.gap_sentence(s) == ("At the recent win rate the open pipeline would close about $9.0K, "
                                     "$5.0K more than the quota still to book.")

    def test_qualifier_commercial_floor_and_error(self):
        q = V.segment_qualifier("Commercial", committed_summary())
        assert "Average error in the mid-quarter backtest: 20% for Commercial." in q
        assert "about 15% below actual bookings" in q and "23%" in q and "floor" in q

    def test_qualifier_enterprise_has_error_and_no_floor_claim(self):
        q = V.segment_qualifier("Enterprise", committed_summary())
        assert q == "Average error in the mid-quarter backtest: 40% for Enterprise."

    def test_no_qualifier_without_a_backtest(self):
        assert V.segment_qualifier("Commercial", None) is None


class TestEvaluationPoint:
    def test_mid_quarter_date_has_no_note(self):
        assert V.evaluation_point_note("2025-11-14", "2025-11-14") is None

    def test_other_dates_are_flagged(self):
        note = V.evaluation_point_note("2025-11-28", "2025-11-14")
        assert note.startswith("Outside the mid-quarter backtest window: this date is not validated.")
        assert "2025-11-14" in note

    def test_unknown_checkpoint_shows_nothing(self):
        assert V.evaluation_point_note("2025-11-28", None) is None


class TestCardWordingAndEdgeStates:
    def test_gap_card_uses_coverage_language(self):
        s = seg(reading("2025-11-14"), "Commercial")
        gap = V.segment_cards(s, "2025-Q4", "2025-11-14")[3]
        assert gap["footer"][0] == ("At the recent win rate the open pipeline would close about $184.9K, "
                                    "$181.7K less than the quota still to book.")
        assert "Expected close" not in json.dumps(gap)

    def test_quota_met_card_clarifies_the_surplus(self):
        s = seg(reading("2025-11-14"), "Enterprise")
        gap = V.segment_cards(s, "2025-Q4", "2025-11-14")[3]
        assert gap["value_display"] == "$1.27M ahead"
        assert ("Expected surplus over the quota still to book (none remaining); $2.67M won against $2.30M quota."
                in gap["footer"])

    def test_real_zero_pipeline_says_so_in_plain_words(self):
        s = fake_seg(open_pipeline_deals=0, display=dict(fake_seg()["display"], open_pipeline="$0 across 0 deals"))
        card = V.segment_cards(s, "2025-Q4", "2025-12-26")[1]
        assert card["value_display"] == "None open"
        assert card["footer"][0] == "No open new-business pipeline for this quarter"

    def test_zero_pipeline_summary_has_no_zero_close_claim(self):
        s = fake_seg(open_pipeline_deals=0, display=dict(
            fake_seg()["display"], open_pipeline="$0 across 0 deals", remaining_quota="$969.6K",
            required_pipeline_multiple="9.31x", realized_conversion="10.7% over 68 closed deals since 2023-01-01",
            status_text="Shortfall"))
        text = V.segment_summary(s)
        assert text.startswith("Commercial: Shortfall. No open new-business pipeline against $969.6K still to book")
        assert "would close" not in text and "10.7% win rate" in text

    def test_basis_states_the_window_actually_used(self):
        s = seg(reading("2025-11-14"), "Commercial")
        foot = V.segment_cards(s, "2025-Q4", "2025-11-14")[2]["footer"][-1]
        assert "trailing 365" not in foot
        assert V.keep_dates_whole("2024-11-15 to 2025-11-14") in foot
        early = fake_seg(conversion_window_start="2023-01-01", conversion_window_end="2023-06-30")
        assert V.keep_dates_whole("2023-01-01 to 2023-06-30") in V.segment_cards(early, "2023-Q2", "2023-06-30")[2]["footer"][-1]
        fallback = V.segment_cards(fake_seg(), "p", "d")[2]["footer"][-1]
        assert V.keep_dates_whole("since the later of 2023-01-01 and 365 days before the date") in fallback


class TestPocCaveats:
    def test_not_backtested_and_n_on_face(self):
        block = V.poc_view_block(seg(reading("2025-11-14"), "Enterprise")["poc_view"])
        assert "Not backtested; thin sample" in block["chips"]
        assert block["lines"][0] == "Not backtested; thin sample: 59 passed and 78 failed closed deals."
        assert block["window_start"] == "2024-11-15"

    def test_unavailable_reason_has_no_process_wording(self):
        block = V.poc_view_block({"status": "unavailable", "label": "x",
                                  "reason": "no open deal carries a point-in-time POC state at this date"})
        assert "point-in-time" not in block["lines"][0] and "POC outcome" in block["lines"][0]


class TestHiddenSegments:
    def reading_with_hidden_commercial(self):
        r = copy.deepcopy(reading("2025-08-15"))
        r["segments"][0].update(status="unavailable", coverage_status="unavailable", reason_code="no_quota")
        return r

    def test_hidden_segments_lists_unavailable_ones(self):
        r = self.reading_with_hidden_commercial()
        assert V.hidden_segments(r) == ["Commercial"]
        assert V.hidden_segments(reading("2025-08-15")) == []

    def test_next_quarter_line_is_replaced_not_shown(self):
        r = self.reading_with_hidden_commercial()
        v = V.next_quarter_view(r["next_quarter"], r["data_window"], V.hidden_segments(r))
        lines = dict(v["lines"])
        assert lines["Commercial"] == "not shown: coverage unavailable for Commercial"
        assert "$639.0K" not in json.dumps(v["lines"][0])
        assert lines["Enterprise"].startswith("$8.13M across 31 deals")

    def test_reconciliation_drops_the_row_and_says_why(self):
        r = self.reading_with_hidden_commercial()
        v = V.reconciliation_view(r["reconciliation"], V.hidden_segments(r))
        assert [row[0] for row in v["rows"]] == ["Enterprise"]
        assert v["hidden_notes"] == ["Not shown: coverage unavailable for Commercial."]
        assert "$910.3K" not in json.dumps(v["rows"])


class TestSplitUnitValue:
    from dashboard.lib import formatting as F

    @pytest.mark.parametrize("text,expected", [
        ("$1.27M ahead", ("$1.27M", "ahead")),
        ("$47.6K short", ("$47.6K", "short")),
        ("$181.7K short", ("$181.7K", "short")),
        ("$5.0K short", ("$5.0K", "short")),
        ("$725.9K across 34 deals", ("$725.9K", "across 34 deals")),
        ("0.50x of required", ("0.50x", "of required")),
    ])
    def test_splits(self, text, expected):
        assert self.F.split_unit_value(text) == expected

    @pytest.mark.parametrize("text", ["$0", "Quota met", "None open", "$2.67M", "<b>x</b> short", ""])
    def test_no_split(self, text):
        assert self.F.split_unit_value(text) is None


class TestCopyVoice:
    def test_phrase_map_removes_process_wording(self):
        from dashboard.lib import labels
        t = labels.apply_phrase_map(
            "The two are reconciled in the reconciliation block and never merged. "
            "A backtest scenario scoping by created date plus the trailing median cycle instead, which uses no "
            "hindsight, is reported in the methods document. Deals expected to close after the quarter end are x.")
        assert "reconciliation block" not in t and "methods document" not in t and "Deals expected" in t
        assert "needs the forecast" not in labels.apply_phrase_map(
            "needs the forecast's point-in-time POC state, which is unavailable at this date")

    def test_no_note_carries_process_wording(self):
        items = V.notes_for(reading("2025-11-14"), committed_summary())
        from dashboard.lib import labels
        for _, t in items:
            shown = labels.apply_phrase_map(t)
            for bad in ("reconciliation block", "methods document", "coverage-implied", "point-in-time POC state"):
                assert bad not in shown

    def test_lens_wording_note(self):
        items = V.notes_for(reading("2025-11-14"), None)
        assert any("override reason" in t and "pipeline coverage" in t for _, t in items)

    def test_one_day_left(self):
        r = dict(reading("2025-11-14"), days_to_quarter_end=1)
        assert dict(V.info_items(r, "x"))["Quarter"] == "2025-Q4, 1 day left"
        r["days_to_quarter_end"] = 2
        assert dict(V.info_items(r, "x"))["Quarter"] == "2025-Q4, 2 days left"

    def test_dates_in_notes_do_not_wrap(self):
        items = V.notes_for(reading("2025-11-14"), None)
        text = " ".join(t for _, t in items)
        assert "2025-12-28" not in text and "2025‑12‑28" in text

    def test_every_alert_in_the_renderer_keeps_dates_whole(self):
        src = open(os.path.join(REPO, "dashboard", "lib", "coverage_render.py")).read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "info" and node.args
                    and not isinstance(node.args[0], ast.Constant)):
                assert "_keep" in ast.unparse(node.args[0])
