"""Display-state rules for the Digest page's executive-summary slot
(dashboard/lib/exec_summary_view.py). The module is Streamlit-free, so these
run under the system interpreter. The 'generated' slots here are built from
the hand-authored golden statement sets in tests/test_executive_summary.py --
TEST FIXTURES, never written to analytics/outputs.
"""
import copy
import json
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

from analytics import executive_summary as es  # noqa: E402
from dashboard.lib import exec_summary_view as v  # noqa: E402
from test_executive_summary import GOLDEN  # noqa: E402

OUT = os.path.join(REPO, "analytics", "outputs")
DATES = ["2025-06-30", "2025-11-30"]


def _readout(d):
    with open(os.path.join(OUT, f"weekly_readout_{d}.json")) as f:
        return json.load(f)


def _generated(readout, d, **over):
    rep = es.validate_statements(readout, GOLDEN[d])
    slot = {"status": "generated",
            "statements": [{"text": s["text"], "cites": s["cites"]} for s in GOLDEN[d]],
            "model": "claude-fake", "generated_at": "2026-09-30T12:00:00+00:00",
            "input_hash": es.compute_input_hash(readout), "prompt_version": es.PROMPT_VERSION,
            "validation": {"passed": True, "checks": rep["checks"]}}
    slot.update(over)
    return slot


@pytest.mark.parametrize("d", DATES)
def test_committed_readouts_render_the_honest_blank_state(d):
    r = _readout(d)
    state = v.display_state(r["executive_summary"], r)
    assert state["kind"] == v.KIND_BLANK
    assert state["statements"] == []
    assert state["reason_code"] == "no_api_key"
    assert "API key" in state["reason_text"]


@pytest.mark.parametrize("d", DATES)
def test_validated_golden_slot_renders_prose(d):
    r = _readout(d)
    state = v.display_state(_generated(r, d), r)
    assert state["kind"] == v.KIND_GENERATED
    assert [s["text"] for s in state["statements"]] == [s["text"].strip() for s in GOLDEN[d]]
    assert state["checks_passed"] == state["checks_total"] > 0
    assert "figures validated against the readout" in state["provenance"]
    assert "2026-09-30" in state["provenance"] and "claude-fake" in state["provenance"]


@pytest.mark.parametrize("reason", [es.REASON_NO_KEY, es.REASON_PENDING, es.REASON_STALE_NO_KEY,
                                    es.REASON_API_ERROR, es.REASON_NO_SDK])
def test_every_not_generated_reason_has_plain_text_and_no_prose(reason):
    slot = {"status": "not_generated", "statements": [], "reason": reason,
            "note": "engineer note", "validation": {"passed": None, "checks": []}}
    state = v.display_state(slot, _readout("2025-11-30"))
    assert state["kind"] == v.KIND_BLANK and state["statements"] == []
    assert state["reason_text"] == v.REASON_TEXT[reason]
    assert "{" not in state["reason_text"] and "Traceback" not in state["reason_text"]
    assert reason not in state["reason_text"]  # plain language, not the raw code


def test_validation_failed_is_blank_lists_check_names_only():
    slot = {"status": "validation_failed", "statements": [],
            "reason": es.REASON_VALIDATION, "note": "n",
            "validation": {"passed": False, "checks": [
                {"name": "figures_grounded", "passed": False,
                 "detail": "statement 0: $999 is not in the readout"},
                {"name": "schema_valid", "passed": True, "detail": "ok"}],
                "errors": ["statement 0 says $999"]}}
    state = v.display_state(slot, _readout("2025-11-30"))
    assert state["kind"] == v.KIND_BLANK and state["statements"] == []
    assert state["failed_checks"] == ["figures_grounded"]
    assert "$999" not in json.dumps(state["failed_checks"] + [state["reason_text"]])
    assert "withheld" in state["headline"]


def test_unknown_reason_falls_back_without_dumping_the_slot():
    state = v.display_state({"status": "not_generated", "reason": "brand_new_reason",
                             "statements": []}, None)
    assert state["kind"] == v.KIND_BLANK
    assert "brand_new_reason" not in json.dumps({k: v for k, v in state.items() if k != "reason_code"})
    assert "reason code" not in state["reason_text"].lower()
    assert state["needed_text"]


@pytest.mark.parametrize("reason", ["no_api_key", "pending_generation", "stale_summary_no_api_key",
                                    "api_error", "anthropic_sdk_not_installed", "validation_failed"])
def test_every_known_reason_states_what_is_needed(reason):
    state = v.display_state({"status": "not_generated", "reason": reason}, None)
    assert state["needed_text"] and "_" not in state["needed_text"]


def test_no_api_key_needs_an_api_key_in_plain_words():
    state = v.display_state({"status": "not_generated", "reason": "no_api_key"}, None)
    assert "API key" in state["needed_text"]


@pytest.mark.parametrize("bad", [
    {"validation": {"passed": False, "checks": []}},   # generated but not validated
    {"validation": {"passed": None, "checks": []}},
    {"validation": {}},
    {"statements": []},
    {"statements": [{"text": "  ", "cites": ["header"]}]},
    {"statements": [{"text": "ok", "cites": "header"}]},
    {"statements": ["just a string"]},
    {"statements": None},
])
def test_generated_status_alone_is_never_enough(bad):
    d = "2025-11-30"
    r = _readout(d)
    state = v.display_state(_generated(r, d, **bad), r)
    assert state["kind"] == v.KIND_BLANK and state["statements"] == []
    assert state["reason_code"] == v.REASON_MALFORMED


def test_stale_input_hash_is_withheld():
    d = "2025-11-30"
    r = _readout(d)
    slot = _generated(r, d)
    changed = copy.deepcopy(r)
    changed["header"]["variance_threshold"] = 0.5
    state = v.display_state(slot, changed)
    assert state["kind"] == v.KIND_BLANK and state["statements"] == []
    assert state["reason_code"] == v.REASON_HASH_MISMATCH


@pytest.mark.parametrize("slot", [None, "text", [], {}, {"status": "deferred", "note": "x"},
                                  {"status": "something_else"}])
def test_missing_or_legacy_or_unknown_slots_are_blank(slot):
    state = v.display_state(slot, None)
    assert state["kind"] == v.KIND_BLANK and state["statements"] == []


def test_format_cite_uses_readout_labels_and_falls_back():
    labels = {"magic_number": "Magic number (blended)"}
    assert v.format_cite("scorecard:magic_number", labels) == "Scorecard · Magic number (blended)"
    assert v.format_cite("drilldown:new_logo", None) == "Drill-down · New logo"
    assert v.format_cite("watchlist") == "Watchlist"
    assert v.format_cite("watchlist:ACC-1") == "Watchlist · Acc-1"


def test_safe_html_escapes_markup_and_dollar_math():
    out = v.safe_html("<b>$502.4K</b> vs $49.3K & more")
    assert "<" not in out and "$" not in out and "&amp;" in out


def test_digest_page_never_dumps_the_raw_slot_or_imports_the_sdk():
    src = open(os.path.join(REPO, "dashboard", "pages", "1_Digest.py")).read()
    assert "st.write(exec_summary)" not in src
    assert not re.search(r"^\s*(import|from)\s+anthropic", src, re.M)
    lib = open(os.path.join(REPO, "dashboard", "lib", "exec_summary_view.py")).read()
    assert not re.search(r"^\s*(import|from)\s+(anthropic|streamlit)", lib, re.M)
