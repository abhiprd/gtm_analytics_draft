"""Thin bridge onto the Phase 3 semantic layer (semantic/server.py).

The dashboard's "Ask the metric tree" page is a second client of the same
MCP tool functions Claude Desktop/Claude Code call over the MCP protocol
-- list_metrics(), get_metric_definition(), query_metric() -- imported and
called in-process rather than reimplemented. The @mcp.tool() decorator in
the mcp SDK returns the original function unchanged (it only registers the
tool for the MCP transport as a side effect), so calling these functions
directly here runs the exact same whitelist/guardrail/query logic a real
MCP client would trigger. This module never redefines a metric or a query
rule of its own -- see analytics-engineering-conventions on not building a
competing copy.

Requires the same Python >=3.10 + `mcp` package as semantic/.venv, which
is why dashboard/.venv is also built on Homebrew Python 3.12 rather than
the repo's default Python 3.9 -- see dashboard/README.md.
"""
import importlib.util
import os
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_SERVER_PATH = os.path.join(_REPO_ROOT, "semantic", "server.py")

_spec = importlib.util.spec_from_file_location("acme_semantic_server", _SERVER_PATH)
_semantic_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_semantic_server)

list_metrics = _semantic_server.list_metrics
get_metric_definition = _semantic_server.get_metric_definition
query_metric = _semantic_server.query_metric
resolve_metric_name = _semantic_server._resolve_metric
registry_stamp = _semantic_server._registry_stamp

_SEGMENT_WORDS = {"smb": "SMB", "commercial": "Commercial", "enterprise": "Enterprise"}
_GRAIN_WORDS = {
    "month": "month", "monthly": "month",
    "quarter": "quarter", "quarterly": "quarter",
    "year": "year", "yearly": "year", "annual": "year", "annually": "year",
}
_BY_SEGMENT_PHRASES = ("by segment", "per segment", "across segments", "segment breakdown")


def _known_metric_vocabulary() -> dict:
    """Every string the registry itself already treats as a name for a
    metric -- its display name (_NAME_INDEX, lowercased), its registry key
    with underscores turned to spaces, and its documented aliases
    (_ALIASES, e.g. 'nrr' -> 'nrr'). Scanning the question for one of
    these as a literal substring is an exact match against the whitelist,
    not a guess -- it stays inside _resolve_metric's own 'never fuzzy'
    guardrail rather than routing around it."""
    vocab = dict(_semantic_server._NAME_INDEX)
    vocab.update(_semantic_server._ALIASES)
    for key in _semantic_server._METRICS:
        vocab.setdefault(key.replace("_", " "), key)
    return vocab


_VOCAB = _known_metric_vocabulary()


def _find_metric_by_substring(lowered_text: str) -> Optional[str]:
    matches = [(name, key) for name, key in _VOCAB.items() if name in lowered_text]
    if not matches:
        return None
    # Longest matching name wins -- most specific, e.g. "logo retention
    # rate" over a shorter partial name that also happens to appear.
    matches.sort(key=lambda pair: len(pair[0]), reverse=True)
    return matches[0][1]


def parse_question(text: str) -> dict:
    """Deterministic, keyword-based NL routing over the whitelisted
    metric registry -- not an LLM call. Extracts a segment filter, a
    grain, and a 'by segment' dimension request from the raw question
    text, then resolves the metric itself by scanning for one of the
    registry's own known names/keys/aliases as a literal substring (see
    _find_metric_by_substring) so a real sentence like 'what was win rate
    for Enterprise last year?' still resolves, without ever silently
    accepting a fuzzy/partial match the registry itself wouldn't accept
    through _resolve_metric. If no known name is found, `suggestions`
    carries _resolve_metric's own difflib-based candidates (computed
    against the raw text) for the UI to offer, unresolved, rather than
    guessing on the caller's behalf."""
    lowered = text.lower()

    filters = {}
    for word, segment in _SEGMENT_WORDS.items():
        if word in lowered:
            filters["segment"] = segment
            break

    grain = "month"
    for word, g in _GRAIN_WORDS.items():
        if word in lowered:
            grain = g
            break

    dimensions = []
    if any(phrase in lowered for phrase in _BY_SEGMENT_PHRASES):
        dimensions = ["segment"]
        filters.pop("segment", None)

    metric_key = _find_metric_by_substring(lowered)
    suggestions = [] if metric_key else _semantic_server._suggestions(text)

    return {
        "raw_question": text,
        "resolved_metric": metric_key,
        "suggestions": suggestions,
        "dimensions": dimensions,
        "filters": filters,
        "grain": grain,
    }
