"""Display-state logic for the Digest page's executive-summary slot.

Pure functions, no Streamlit import, so the rule "prose is shown only when
it has been validated" is unit-testable (tests/test_dashboard_exec_summary_view.py)
and lives in exactly one place. The dashboard only READS the readout JSON's
`executive_summary` slot (contract: analytics/executive_summary.py); it never
calls the API and never imports the anthropic SDK.

The one gate: prose is returned ONLY when
  status == "generated"  AND  validation.passed is True  AND
  every statement is a {text, cites} pair with non-empty text  AND
  the slot's input_hash equals the hash of the readout it sits in
  (the same stale-summary guard the pipeline applies when it writes the slot).
Anything else returns kind == "blank" with statements == [] -- a caller
cannot accidentally render prose from a blank state, because none is carried.
"""
import html
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from analytics import executive_summary as es  # noqa: E402  (stdlib-only at import time)

KIND_GENERATED = "generated"
KIND_BLANK = "blank"

# Plain-language wording for each reason code the narrative step can write
# (analytics/executive_summary.py REASON_*). Written for a CRO, not an
# engineer: what happened to the summary, not which function failed.
REASON_TEXT = {
    es.REASON_NO_KEY: (
        "The step that writes this summary needs an Anthropic API key, and none was "
        "available when this readout was built."),
    es.REASON_PENDING: (
        "This readout was assembled, but the summary step has not been run for this "
        "version of it."),
    es.REASON_STALE_NO_KEY: (
        "A summary was written for an earlier version of this readout. The data has "
        "changed since, and no API key was available to rewrite it, so the old text is "
        "withheld."),
    es.REASON_API_ERROR: (
        "The summary step could not reach the language model, so no summary was produced."),
    es.REASON_NO_SDK: (
        "The software library the summary step needs is not installed in the environment "
        "that built this readout."),
    es.REASON_VALIDATION: (
        "A draft was written, but its figures did not all check out against the readout "
        "after one retry, so it is withheld."),
}
# Display-only reasons the page itself can reach (never written to the JSON).
REASON_MALFORMED = "slot_not_publishable"
REASON_HASH_MISMATCH = "summary_out_of_date"
REASON_TEXT[REASON_MALFORMED] = (
    "The summary section of this readout is present but did not meet the publishing "
    "contract (it must be marked generated, pass its figure checks, and contain "
    "well-formed statements), so nothing is shown.")
REASON_TEXT[REASON_HASH_MISMATCH] = (
    "The summary on file was written for different readout data than the figures "
    "shown on this page, so it is withheld.")
# What the reader (or whoever runs the build) must supply for the summary to appear.
NEEDED_TEXT = {
    es.REASON_NO_KEY: "An Anthropic API key is required to generate the summary.",
    es.REASON_PENDING: "The summary step has to be run for this readout.",
    es.REASON_STALE_NO_KEY: "An Anthropic API key is required to regenerate the summary.",
    es.REASON_API_ERROR: "The language model service has to be reachable when the summary is generated.",
    es.REASON_NO_SDK: "The Anthropic software library has to be installed where the readout is built.",
    es.REASON_VALIDATION: "The draft has to pass its figure checks; it failed them after one retry.",
}
_FALLBACK_NEEDED = "The summary step has to be run successfully for this readout."
_FALLBACK_REASON = "No summary is available for this readout."

_CITE_PREFIX = {
    "scorecard": "Scorecard",
    "drilldown": "Drill-down",
    "watchlist": "Watchlist",
    "playbook_triggers": "Playbook triggers",
    "header": "Readout header",
}


def _blank(reason: Optional[str], slot: Optional[Dict[str, Any]], status: str) -> Dict[str, Any]:
    text = REASON_TEXT.get(reason or "", None)
    if text is None:
        text = _FALLBACK_REASON   # never a raw reason code on the page
    failed: List[str] = []
    if isinstance(slot, dict):
        val = slot.get("validation") or {}
        for c in (val.get("checks") or []):
            if isinstance(c, dict) and c.get("passed") is False and c.get("name"):
                failed.append(str(c["name"]))
    if status == es.STATUS_VALIDATION_FAILED:
        headline = "Summary withheld — it did not pass its figure checks"
    else:
        headline = "No executive summary for this readout"
    return {
        "kind": KIND_BLANK,
        "headline": headline,
        "reason_code": reason,
        "reason_text": text,
        "needed_text": NEEDED_TEXT.get(reason or "", _FALLBACK_NEEDED),
        "statements": [],          # invariant: a blank state never carries prose
        "failed_checks": failed,   # check NAMES only -- never the validator's quoted text
        "slot_note": (slot or {}).get("note") if isinstance(slot, dict) else None,
    }


def display_state(slot: Optional[Dict[str, Any]], readout: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Map a readout's `executive_summary` slot to what the page may show.

    `readout` (the full readout dict the slot came from) enables the
    input-hash staleness guard; when omitted the guard is skipped, so the
    page always passes it.
    """
    if not isinstance(slot, dict):
        return _blank("pending_generation", None, es.STATUS_NOT_GENERATED)

    status = slot.get("status")
    # Legacy placeholder shape from before the narrative step existed.
    if status == "deferred":
        return _blank("pending_generation", slot, es.STATUS_NOT_GENERATED)
    if status in (es.STATUS_NOT_GENERATED, es.STATUS_VALIDATION_FAILED):
        return _blank(slot.get("reason"), slot, status)
    if status != es.STATUS_GENERATED:
        return _blank(REASON_MALFORMED, slot, str(status))

    validation = slot.get("validation") or {}
    statements = slot.get("statements")
    well_formed = (
        validation.get("passed") is True
        and isinstance(statements, list) and len(statements) > 0
        and all(isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"].strip()
                and isinstance(s.get("cites"), list) for s in statements)
    )
    if not well_formed:
        return _blank(REASON_MALFORMED, slot, str(status))

    if readout is not None and slot.get("input_hash") != es.compute_input_hash(readout):
        return _blank(REASON_HASH_MISMATCH, slot, str(status))

    checks = [c for c in (validation.get("checks") or []) if isinstance(c, dict)]
    return {
        "kind": KIND_GENERATED,
        "statements": [{"text": s["text"].strip(), "cites": [str(c) for c in s["cites"]]}
                       for s in statements],
        "provenance": provenance_line(slot),
        "checks_passed": sum(1 for c in checks if c.get("passed") is True),
        "checks_total": len(checks),
        "checks": [{"name": str(c.get("name")), "passed": c.get("passed") is True,
                    "detail": str(c.get("detail") or "")} for c in checks],
        "model": slot.get("model"),
        "prompt_version": slot.get("prompt_version"),
    }


def provenance_line(slot: Dict[str, Any]) -> str:
    """One calm caption: who wrote it, when, and that it was checked."""
    model = slot.get("model") or "a language model"
    when = ""
    raw = slot.get("generated_at")
    if raw:
        try:
            when = f" on {datetime.fromisoformat(str(raw).replace('Z', '+00:00')).date().isoformat()}"
        except ValueError:
            when = ""
    return f"Written by {model}{when} · figures validated against the readout"


def format_cite(cite: str, labels: Optional[Dict[str, str]] = None) -> str:
    """Human label for a cite id such as 'scorecard:contraction_churned_revenue'.
    `labels` maps metric_key -> the readout's own display label when known."""
    prefix, _, key = str(cite).partition(":")
    head = _CITE_PREFIX.get(prefix, prefix.replace("_", " ").capitalize())
    if not key:
        return head
    name = (labels or {}).get(key) or key.replace("_", " ").capitalize()
    return f"{head} · {name}"


def safe_html(text: str) -> str:
    """Escape model/validated text for an unsafe_allow_html block. '$' is
    also neutralised: Streamlit's markdown would otherwise read two dollar
    amounts in one statement ('$502.4K ... $49.3K') as a LaTeX span."""
    return html.escape(text, quote=True).replace("$", "&#36;")
