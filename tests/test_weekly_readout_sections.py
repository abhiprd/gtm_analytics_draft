"""The weekly readout's persistence line (per drill-down) and segment-mix section
(analytics/weekly_readout.py).

  * JSON-only tests read the two committed readouts
    (analytics/outputs/weekly_readout_2025-06-30.json and 2025-11-30.json): the
    contract, the rendering, the checks that catch a tampered payload, and the
    voice of the strings the dashboard prints verbatim.
  * Fresh-run tests need the dbt database: the committed sections equal a fresh
    run of the owning functions, the unavailable path at the truncated final
    month, and the full build-time validation.

Run: python3 -m pytest tests/test_weekly_readout_sections.py -v
"""
import copy
import json
import os
import re
import sys
from datetime import date

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from analytics import executive_summary as es  # noqa: E402
from analytics import segment_migration as sm  # noqa: E402
from analytics import variance_diagnostic as vd  # noqa: E402
from analytics import weekly_readout as wr  # noqa: E402

OUT = os.path.join(ROOT, "analytics", "outputs")
DB_PATH = os.path.join(ROOT, "data", "acme_gtm.duckdb")
DATES = ["2025-06-30", "2025-11-30"]
needs_db = pytest.mark.skipif(
    not os.path.exists(DB_PATH), reason="dbt-built database not present; run `cd dbt && dbt build`")


def _load(d):
    with open(os.path.join(OUT, "weekly_readout_%s.json" % d)) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def readouts():
    return {d: _load(d) for d in DATES}


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv(es.API_KEY_ENV, raising=False)


def _checks(readout):
    md = wr.render_markdown(readout)
    return md, {c["name"]: c for c in wr.verify_rendered_document(md, readout)}


# --------------------------------------------------------------------------
# Persistence on each drill-down
# --------------------------------------------------------------------------

PERSISTENCE_KEYS = {
    "status", "flagged", "threshold_months", "threshold_status", "streak_months", "driver_key",
    "driver_label", "driver_direction", "adverse_direction", "first_month_of_streak",
    "streak_detail", "streak_break", "reason", "basis", "caveat", "note", "status_display"}


class TestPersistenceContract:
    @pytest.mark.parametrize("d", DATES)
    def test_every_entry_carries_the_full_record(self, readouts, d):
        entries = readouts[d]["drilldowns"]["entries"]
        assert len(entries) == readouts[d]["drilldowns"]["count"] == 9
        for e in entries:
            p = e["persistence"]
            assert set(p) == PERSISTENCE_KEYS, e["layer1"]["metric_key"]
            assert p["driver_key"] == e["layer2_outlier"]["metric_key"]
            assert p["threshold_months"] == 2 and p["threshold_status"] == "Proposed, not yet confirmed"
            assert p["flagged"] == (p["status"] == "flagged")

    @pytest.mark.parametrize("d", DATES)
    def test_every_record_carries_the_repeat_marker_caveat(self, readouts, d):
        want = ("Repeat marker: the same driver as the adverse outlier in consecutive months; "
                "not evidence of a trend or cause.")
        for e in readouts[d]["drilldowns"]["entries"]:
            assert e["persistence"]["caveat"] == want
        md = wr.render_markdown(readouts[d])
        applicable = [e for e in readouts[d]["drilldowns"]["entries"]
                      if e["persistence"]["status"] != "not_applicable"]
        assert md.count("\n  - " + want) == len(applicable) > 0

    @pytest.mark.parametrize("d", DATES)
    def test_status_display_follows_the_status(self, readouts, d):
        for e in readouts[d]["drilldowns"]["entries"]:
            p = e["persistence"]
            expected = {
                "flagged": "Flagged: %s consecutive months" % p["streak_months"],
                "not_flagged": "Not flagged: streak %s of 2 months" % p["streak_months"],
                "not_applicable": "Not applicable"}[p["status"]]
            assert p["status_display"] == expected

    def test_the_june_flags_and_the_november_absence_of_flags(self, readouts):
        june = {e["layer1"]["metric_key"]: e["persistence"]
                for e in readouts["2025-06-30"]["drilldowns"]["entries"]}
        nov = {e["layer1"]["metric_key"]: e["persistence"]
               for e in readouts["2025-11-30"]["drilldowns"]["entries"]}
        assert {k for k, p in june.items() if p["flagged"]} == {
            "contraction_churned_revenue", "nrr", "grr"}
        assert june["contraction_churned_revenue"]["status_display"] == \
            "Flagged: 3 consecutive months"
        assert june["contraction_churned_revenue"]["first_month_of_streak"] == "2025-04-01"
        assert not any(p["flagged"] for p in nov.values())
        assert nov["expansion_consumption_revenue"]["reason"] == "single_candidate_read"

    @pytest.mark.parametrize("d", DATES)
    def test_a_flagged_record_has_a_detail_row_per_streak_month_newest_first(self, readouts, d):
        for e in readouts[d]["drilldowns"]["entries"]:
            p = e["persistence"]
            if p["status"] == "not_applicable":
                assert p["streak_detail"] == [] and p["first_month_of_streak"] is None
                continue
            months = [r["month"] for r in p["streak_detail"]]
            assert len(months) == p["streak_months"] == len(set(months))
            assert months == sorted(months, reverse=True)
            if months:
                assert p["first_month_of_streak"] == months[-1]
                assert months[0] == readouts[d]["header"]["evaluation_month"]
            if p["status"] != "not_applicable" and p["streak_break"] is not None:
                assert p["streak_break"]["month"] < (months[-1] if months else "9999")\
                    or not months

    @pytest.mark.parametrize("d", DATES)
    def test_the_markdown_carries_one_persistence_line_per_drilldown(self, readouts, d):
        md = wr.render_markdown(readouts[d])
        assert md.count("- **Persistence:**") == readouts[d]["drilldowns"]["count"]
        for e in readouts[d]["drilldowns"]["entries"]:
            assert wr._persistence_line(e["persistence"]) in md

    @pytest.mark.parametrize("d", DATES)
    def test_the_committed_markdown_is_the_current_rendering(self, readouts, d):
        with open(os.path.join(OUT, "weekly_readout_%s.md" % d)) as f:
            assert f.read() == wr.render_markdown(readouts[d])

    @pytest.mark.parametrize("d", DATES)
    def test_rendered_persistence_is_checked_against_the_payload(self, readouts, d):
        md, checks = _checks(readouts[d])
        assert checks["drilldown_persistence_rendered_per_payload"]["passed"]
        # a rendered line that no longer matches the payload is caught
        victim = readouts[d]["drilldowns"]["entries"][0]["persistence"]
        tampered = md.replace(wr._persistence_line(victim), "- **Persistence:** Not applicable.")
        bad = {c["name"]: c for c in wr.verify_rendered_document(tampered, readouts[d])}
        assert not bad["drilldown_persistence_rendered_per_payload"]["passed"]


class TestPersistenceTrace:
    def _engine(self, readout):
        out = {}
        for e in readout["drilldowns"]["entries"]:
            out[e["layer1"]["metric_key"]] = {k: v for k, v in e["persistence"].items()
                                              if k != "status_display"}
        return out

    @pytest.mark.parametrize("d", DATES)
    def test_the_committed_records_trace_to_themselves_and_are_coherent(self, readouts, d):
        ok, detail = wr._verify_persistence_against(readouts[d], self._engine(readouts[d]))
        assert ok, detail

    @pytest.mark.parametrize("mutate,needle", [
        (lambda p: p.__setitem__("streak_months", 9), "differs from the engine"),
        (lambda p: p.__setitem__("flagged", not p["flagged"]), "differs from the engine"),
        (lambda p: p.__setitem__("note", "edited"), "differs from the engine"),
        (lambda p: p.__setitem__("driver_key", "win_rate"), "tracks"),
    ])
    def test_any_edit_to_a_record_fails_the_trace(self, readouts, mutate, needle):
        r = copy.deepcopy(readouts["2025-06-30"])
        engine = self._engine(readouts["2025-06-30"])
        mutate(r["drilldowns"]["entries"][2]["persistence"])
        ok, detail = wr._verify_persistence_against(r, engine)
        assert not ok and needle in detail

    def test_a_missing_record_fails_the_trace(self, readouts):
        r = copy.deepcopy(readouts["2025-06-30"])
        r["drilldowns"]["entries"][0].pop("persistence")
        ok, detail = wr._verify_persistence_against(r, self._engine(readouts["2025-06-30"]))
        assert not ok and "no persistence record" in detail

    def test_the_coherence_rules_catch_an_inconsistent_record(self, readouts):
        r = copy.deepcopy(readouts["2025-06-30"])
        engine = self._engine(r)
        p = next(e["persistence"] for e in r["drilldowns"]["entries"]
                 if e["persistence"]["status"] == "flagged")
        p["streak_months"] = 1  # flagged below the threshold, on both sides of the comparison
        engine[next(e["layer1"]["metric_key"] for e in r["drilldowns"]["entries"]
                    if e["persistence"] is p)]["streak_months"] = 1
        ok, detail = wr._verify_persistence_against(r, engine)
        assert not ok and "flagged below the threshold" in detail

    def test_a_not_applicable_record_must_carry_a_reason_and_no_streak(self, readouts):
        r = copy.deepcopy(readouts["2025-06-30"])
        engine = self._engine(r)
        e = next(e for e in r["drilldowns"]["entries"]
                 if e["persistence"]["status"] == "not_applicable")
        e["persistence"]["reason"] = None
        engine[e["layer1"]["metric_key"]]["reason"] = None
        ok, detail = wr._verify_persistence_against(r, engine)
        assert not ok and "needs a reason" in detail

    def test_the_readout_computes_no_persistence_of_its_own(self):
        src = open(os.path.join(ROOT, "analytics", "weekly_readout.py")).read()
        assert "compute_persistence(" not in src
        assert "_persistence_status_display" in src  # formatting only
        with pytest.raises(ValueError, match="without a persistence record"):
            wr._persistence_record(None)


# --------------------------------------------------------------------------
# Segment mix
# --------------------------------------------------------------------------

MIX_KEYS = {"status", "evaluation_month", "basis", "caveats", "window", "total_ending_mrr",
            "segments", "upmarket_share", "migration", "reconciliation", "note", "headline",
            "total_ending_mrr_display"}


class TestSegmentMixContract:
    @pytest.mark.parametrize("d", DATES)
    def test_present_with_the_full_contract(self, readouts, d):
        m = readouts[d]["segment_mix"]
        assert m["status"] == "present" and set(m) == MIX_KEYS
        assert m["evaluation_month"] == readouts[d]["header"]["evaluation_month"]
        assert [s["segment"] for s in m["segments"]] == ["SMB", "Commercial", "Enterprise"]
        assert [(p["from_segment"], p["to_segment"]) for p in m["migration"]] == [
            ("SMB", "Commercial"), ("Commercial", "Enterprise")]
        assert len(m["caveats"]) == 6 and m["basis"]
        assert m["reconciliation"]["reconciles"] is True

    @pytest.mark.parametrize("d", DATES)
    def test_every_figure_has_a_display_string(self, readouts, d):
        m = readouts[d]["segment_mix"]
        for s in m["segments"]:
            for f in ("ending_mrr", "mrr_share", "share_change_vs_prior_month",
                      "share_change_vs_12m_ago"):
                assert s[f + "_display"], (s["segment"], f)
        for p in m["migration"]:
            for f in ("velocity_in_month", "velocity_trailing_12m", "velocity_trailing_12m_year_ago",
                      "velocity_change_vs_year_ago", "graduated_mrr_in_month",
                      "graduated_mrr_trailing_12m", "graduated_share_of_source_mrr_in_month",
                      "graduated_share_of_source_mrr_trailing_12m"):
                assert p[f + "_display"], (p["pair_label"], f)
        assert m["upmarket_share"]["mrr_share_display"]

    def test_the_november_headline_and_rates(self, readouts):
        m = readouts["2025-11-30"]["segment_mix"]
        assert m["headline"] == ("Commercial and Enterprise hold 87.9% of ending MRR "
                                 "(+5.2 pp against 12 months earlier).")
        by = {p["pair_label"]: p for p in m["migration"]}
        assert by["SMB to Commercial"]["events_in_month"] == 48
        assert by["SMB to Commercial"]["events_trailing_12m"] == 415
        assert by["SMB to Commercial"]["velocity_trailing_12m_display"] == "10.7%"
        assert by["Commercial to Enterprise"]["events_trailing_12m"] == 55
        assert m["window"]["last_month_in_marts"] == "2025-12-01"

    def test_the_june_headline(self, readouts):
        m = readouts["2025-06-30"]["segment_mix"]
        assert m["headline"] == ("Commercial and Enterprise hold 83.5% of ending MRR "
                                 "(+2.0 pp against 12 months earlier).")

    @pytest.mark.parametrize("d", DATES)
    def test_shares_sum_to_one_and_tie_to_the_ending_mrr(self, readouts, d):
        m = readouts[d]["segment_mix"]
        ok, detail = wr._segment_mix_ties(m)
        assert ok, detail
        assert sum(s["mrr_share"] for s in m["segments"]) == pytest.approx(1.0)
        assert m["upmarket_share"]["mrr_share"] == pytest.approx(
            sum(s["mrr_share"] for s in m["segments"] if s["segment"] != "SMB"))

    @pytest.mark.parametrize("d", DATES)
    def test_changes_are_differences_of_the_displayed_shares(self, readouts, d):
        for s in readouts[d]["segment_mix"]["segments"]:
            assert s["share_change_vs_prior_month"] == pytest.approx(
                s["mrr_share"] - s["mrr_share_prior_month"])
            assert s["share_change_vs_12m_ago"] == pytest.approx(
                s["mrr_share"] - s["mrr_share_12m_ago"])

    @pytest.mark.parametrize("d", DATES)
    def test_the_section_states_that_migration_is_upward_only(self, readouts, d):
        text = " ".join(readouts[d]["segment_mix"]["caveats"])
        assert "no downgrade path" in text and "rates" in text
        assert "final month of the data window" in text

    @pytest.mark.parametrize("d", DATES)
    def test_the_measured_caveats_state_the_flow_and_reclassification_limits(self, readouts, d):
        m = readouts[d]["segment_mix"]
        flow, mechanical = m["caveats"][4], m["caveats"][5]
        assert "flow set against an average base" in flow and "can exceed 100%" in flow
        assert "times the MRR of the average SMB account" in flow
        assert "of ending SMB MRR" in flow and "SMB MRR 12 months earlier" in flow
        assert "reclassified upward" in mechanical and "of company ending MRR" in mechanical
        assert "where MRR is booked more than who the company is selling to" in mechanical
        smb = next(p for p in m["migration"] if p["from_segment"] == "SMB")
        assert ("%.0f times" % smb["migrating_account_mrr_multiple_trailing_12m"]) in flow
        assert ("%.0f%% of ending SMB MRR" % (100 * smb["graduated_share_of_source_ending_mrr_trailing_12m"])) in flow
        assert ("%.1f%% of company ending MRR" % (
            100 * m["upmarket_share"]["smb_to_commercial_graduated_share_of_total_mrr_trailing_12m"])) in mechanical

    def test_the_november_figures_in_those_caveats(self, readouts):
        flow, mechanical = readouts["2025-11-30"]["segment_mix"]["caveats"][4:]
        assert "about 6 times" in flow and "$722K" in flow
        assert "60% of ending SMB MRR and 79% of SMB MRR 12 months earlier" in flow
        assert "7.3% of company ending MRR, more than the +5.2 pp change" in mechanical

    @pytest.mark.parametrize("d", DATES)
    def test_the_section_is_not_in_the_summary_evidence(self, readouts, d):
        assert "segment_mix" not in es.build_prompt_view(readouts[d])


class TestSegmentMixRendering:
    @pytest.mark.parametrize("d", DATES)
    def test_rendered_per_payload(self, readouts, d):
        md, checks = _checks(readouts[d])
        assert "## Segment mix" in md
        assert checks["segment_mix_section_rendered_per_status"]["passed"]
        assert "**%s**" % readouts[d]["segment_mix"]["headline"] in md
        for s in readouts[d]["segment_mix"]["segments"]:
            assert wr._segment_row_line(s) in md

    @pytest.mark.parametrize("d", DATES)
    def test_section_order_is_watchlist_then_segment_mix_then_provenance(self, readouts, d):
        md = wr.render_markdown(readouts[d])
        assert md.index("## Watchlist") < md.index("## Segment mix") < md.index("## Provenance")

    def test_a_wrong_rendered_value_a_dropped_row_and_a_dropped_caveat_are_caught(self, readouts):
        r = readouts["2025-11-30"]
        md, _ = _checks(r)
        seg = r["segment_mix"]["segments"][1]
        for tampered in (
                md.replace(wr._segment_row_line(seg),
                           wr._segment_row_line(seg).replace(seg["mrr_share_display"], "99.9%")),
                md.replace(wr._segment_row_line(r["segment_mix"]["segments"][0]) + "\n", ""),
                md.replace("- " + r["segment_mix"]["caveats"][0], "- "),
                md.replace("## Segment mix", "## Segments")):
            bad = {c["name"]: c for c in wr.verify_rendered_document(tampered, r)}
            assert not bad["segment_mix_section_rendered_per_status"]["passed"]

    def test_the_provenance_names_segment_migration_as_the_source(self, readouts):
        p = readouts["2025-11-30"]["provenance"]
        assert any(x["section"] == "segment_mix"
                   and x["artifact"] == "analytics/segment_migration.py" for x in p["sources"])
        assert "source of the segment-mix section only" in p["segment_migration_analysis"]
        assert "is not a source for any section" not in p["segment_migration_analysis"]


class TestSegmentMixTraceChecks:
    def test_status_problems_are_named(self, readouts):
        good = readouts["2025-11-30"]["segment_mix"]
        month = readouts["2025-11-30"]["header"]["evaluation_month"]
        assert wr._segment_mix_status_problem(good, month) is None
        assert "neither present nor unavailable" in wr._segment_mix_status_problem(
            dict(good, status="not_yet_built"), month)
        assert "section month" in wr._segment_mix_status_problem(good, "2025-10-01")
        bad = dict(good, reconciliation={"reconciles": False})
        assert "reconcile" in wr._segment_mix_status_problem(bad, month)
        unavailable = {"status": "unavailable", "evaluation_month": month}
        assert "specific reason" in wr._segment_mix_status_problem(unavailable, month)
        with_figures = dict(unavailable, reason="r", detail="d", segments=[])
        assert "no figures" in wr._segment_mix_status_problem(with_figures, month)
        assert wr._segment_mix_status_problem(dict(unavailable, reason="r", detail="d"), month) is None

    def test_ties_catch_shares_that_do_not_sum_or_tie(self, readouts):
        m = copy.deepcopy(readouts["2025-11-30"]["segment_mix"])
        m["segments"][0]["mrr_share"] += 0.01
        ok, detail = wr._segment_mix_ties(m)
        assert not ok and "do not sum to 1" in detail
        m = copy.deepcopy(readouts["2025-11-30"]["segment_mix"])
        m["upmarket_share"]["mrr_share"] = 0.5
        assert not wr._segment_mix_ties(m)[0]
        m = copy.deepcopy(readouts["2025-11-30"]["segment_mix"])
        m["total_ending_mrr"] *= 2
        assert not wr._segment_mix_ties(m)[0]

    def test_strip_presentation_removes_only_display_strings(self, readouts):
        m = readouts["2025-11-30"]["segment_mix"]
        stripped = wr._strip_presentation(m)
        assert "headline" not in stripped and "note" not in stripped
        assert "mrr_share_display" not in stripped["segments"][0]
        assert stripped["segments"][0]["mrr_share"] == m["segments"][0]["mrr_share"]
        assert stripped["basis"] == m["basis"] and stripped["caveats"] == m["caveats"]


# --------------------------------------------------------------------------
# Voice of the strings the dashboard prints verbatim
# --------------------------------------------------------------------------

_ALLOWED_CAPS = {"NRR", "GRR", "MRR", "ARR", "CAC", "TTFA", "AUC", "SMB", "CRO", "USD", "TTM"}
_HEDGES = re.compile(
    r"rather than silently|stated rather|stated explicitly|applied silently|silently|"
    r"fabricat|forced into|to force symmetry|must not present|design brief|genuinely|"
    r"reported rather|read the |is computed, but|not guessed", re.I)
_IMPERATIVE = re.compile(r"(?:^|\. )(Read|Use|Note|Treat|Do not|Don't)\b")
_CODE = re.compile(r"\b(?:mart|fact|dim|int|stg)_\w+|\b[a-z]+_[a-z0-9_]+\b|\.py\b|\(\)")


def _strings(r):
    out = []
    for e in r["drilldowns"]["entries"]:
        k = e["layer1"]["metric_key"]
        p = e["persistence"]
        out.append(("persistence.%s.note" % k, p["note"]))
        out.append(("persistence.%s.display" % k, p["status_display"]))
        out.append(("persistence.%s.basis" % k, p["basis"]))
        out.append(("persistence.%s.caveat" % k, p["caveat"]))
    m = r["segment_mix"]
    out += [("mix.basis", m["basis"]), ("mix.note", m["note"]), ("mix.headline", m["headline"]),
            ("mix.window", m["window"]["partial_month_handling"])]
    out.extend(("mix.caveat%d" % i, c) for i, c in enumerate(m["caveats"]))
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
    def test_notes_are_one_or_two_short_sentences(self, readouts, d):
        for e in readouts[d]["drilldowns"]["entries"]:
            assert len(e["persistence"]["note"]) <= 330, e["layer1"]["metric_key"]

def _assert_equal_up_to_float_noise(got, exp, path="root", rel=1e-9):
    """Structural equality where floats match at a relative tolerance and all other
    values match exactly."""
    if isinstance(exp, dict):
        assert isinstance(got, dict) and set(got) == set(exp), f"{path}: keys differ"
        for k in exp:
            _assert_equal_up_to_float_noise(got[k], exp[k], f"{path}.{k}", rel)
    elif isinstance(exp, (list, tuple)):
        assert isinstance(got, (list, tuple)) and len(got) == len(exp), f"{path}: length differs"
        for i, (g, e) in enumerate(zip(got, exp)):
            _assert_equal_up_to_float_noise(g, e, f"{path}[{i}]", rel)
    elif isinstance(exp, float) and isinstance(got, (int, float)) and not isinstance(got, bool):
        assert got == pytest.approx(exp, rel=rel, abs=1e-12), f"{path}: {got!r} != {exp!r}"
    else:
        assert got == exp, f"{path}: {got!r} != {exp!r}"


# --------------------------------------------------------------------------
# Fresh runs against the dbt database
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def built():
    diag = vd.run_diagnostic(date(2025, 11, 30))
    return diag, wr.assemble_readout(date(2025, 11, 30), diagnostic=diag)


@needs_db
class TestFreshRuns:
    def test_a_fresh_assembly_passes_the_new_trace_checks(self, built):
        diag, readout = built
        checks = {c["name"]: c for c in wr.verify_source_trace(readout, diag, date(2025, 11, 30))}
        for name in ("drilldown_persistence_matches_engine_output",
                     "drilldown_persistence_traces_exactly_to_a_fresh_engine_run",
                     "segment_mix_section_is_built_and_declares_its_status",
                     "segment_mix_traces_exactly_to_a_fresh_run",
                     "segment_mix_shares_tie_to_ending_mrr"):
            assert checks[name]["passed"], checks[name]
        assert "required_sections_present" in checks and checks["required_sections_present"]["passed"]

    def test_the_fresh_run_check_is_skipped_without_an_as_of_date(self, built):
        diag, readout = built
        names = {c["name"] for c in wr.verify_source_trace(readout, diag)}
        assert "drilldown_persistence_traces_exactly_to_a_fresh_engine_run" not in names
        assert "drilldown_persistence_matches_engine_output" in names

    def test_the_committed_sections_equal_a_fresh_run(self, readouts, built):
        # The committed JSON may have been written on a different platform than the one
        # running the tests; floating-point sums can differ in the last digit across
        # platforms, so floats compare at a relative tolerance of 1e-9 and everything
        # else compares exactly.
        _, fresh = built
        nov = readouts["2025-11-30"]
        _assert_equal_up_to_float_noise(wr._strip_presentation(nov["segment_mix"]),
                                        wr._strip_presentation(fresh["segment_mix"]))
        for got, exp in zip(nov["drilldowns"]["entries"], fresh["drilldowns"]["entries"]):
            _assert_equal_up_to_float_noise(got["persistence"], exp["persistence"])

    def test_a_tampered_persistence_record_fails_the_fresh_run_trace(self, built):
        diag, readout = built
        bad = copy.deepcopy(readout)
        bad["drilldowns"]["entries"][0]["persistence"]["streak_months"] = 8
        checks = {c["name"]: c for c in wr.verify_source_trace(bad, diag, date(2025, 11, 30))}
        assert not checks["drilldown_persistence_matches_engine_output"]["passed"]
        assert not checks["drilldown_persistence_traces_exactly_to_a_fresh_engine_run"]["passed"]

    def test_a_tampered_segment_mix_fails_the_fresh_run_trace(self, built):
        diag, readout = built
        bad = copy.deepcopy(readout)
        bad["segment_mix"]["segments"][2]["ending_mrr"] += 0.01
        checks = {c["name"]: c for c in wr.verify_source_trace(bad, diag, date(2025, 11, 30))}
        assert not checks["segment_mix_traces_exactly_to_a_fresh_run"]["passed"]

    def test_the_truncated_final_month_makes_the_section_unavailable_with_a_reason(self):
        sec = wr._segment_mix_section(pd.Timestamp("2025-12-01"))
        assert sec["status"] == "unavailable"
        assert sec["reason"] == "evaluation_month_is_truncated_final_month"
        assert sec["detail"] and sec["headline"] is None
        assert not any(k in sec for k in ("segments", "migration", "upmarket_share"))

    def test_an_unavailable_section_renders_its_reason_and_no_figures(self, readouts):
        r = copy.deepcopy(readouts["2025-11-30"])
        r["segment_mix"] = wr._segment_mix_section(pd.Timestamp("2025-12-01"))
        r["segment_mix"]["evaluation_month"] = r["header"]["evaluation_month"]
        md, checks = _checks(r)
        assert "**Status: unavailable (evaluation_month_is_truncated_final_month).**" in md
        assert "| Segment | Ending MRR |" not in md
        assert checks["segment_mix_section_rendered_per_status"]["passed"]
        assert wr._segment_mix_status_problem(r["segment_mix"], r["header"]["evaluation_month"]) is None

    def test_the_full_build_time_validation_passes_and_logs(self, tmp_path, monkeypatch):
        logged = {}
        monkeypatch.setattr(wr, "log_performance",
                            lambda model, as_of, name, value: logged.__setitem__(name, value))
        out = wr.run_build_time_validation(date(2025, 6, 30), write=False, log=True,
                                           out_dir=str(tmp_path))
        assert out["checks_passed"] == out["checks_total"] == 33
        names = {c["name"] for c in out["trace_checks"] + out["render_checks"]}
        assert {"drilldown_persistence_rendered_per_payload",
                "segment_mix_section_rendered_per_status"} <= names
        assert logged["sections_not_yet_built"] == 0.0
        assert out["readout"]["executive_summary"]["status"] == "not_generated"

    def test_the_required_sections_include_the_segment_mix(self):
        assert "segment_mix" in wr._REQUIRED_SECTIONS
