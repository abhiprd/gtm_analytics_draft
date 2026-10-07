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

from lib import answers as _answers
from lib import routing as _routing

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


def _build_vocabulary() -> dict:
    """The registry's own display names and keys, the semantic layer's
    documented aliases (server.py `_ALIASES`, the one alias table; the dashboard
    adds none of its own, see routing.SUPPLEMENTARY_ALIASES). Matching a
    question against these is an exact match against names the registry
    recognizes, so it stays inside `_resolve_metric`'s never-fuzzy rule."""
    return _routing.build_vocabulary(
        _semantic_server._METRICS,
        aliases=_semantic_server._ALIASES,
        valid_segments=_semantic_server._VALID_SEGMENTS,
    )


_VOCAB = _build_vocabulary()


def parse_question(text: str) -> dict:
    """Deterministic keyword routing over the whitelisted registry; see
    lib/routing.py for the rules. Not an LLM call. When nothing resolves,
    `suggestions` carries the semantic layer's own difflib candidates for
    the UI to offer, unresolved."""
    return _routing.route_question(text, _VOCAB, suggest=_semantic_server._suggestions)


def answer_question(text: str, partial_month: str = None) -> dict:
    """Route a question and assemble its answer: the metric's own result
    plus, for a non-leaf metric, one entry per immediate child, each from
    the same query_metric() call (lib/answers.py). `partial_month` is the truncated
    final month of the data window: the headline is the last complete period."""
    parsed = parse_question(text)
    return _answers.build_answer(parsed, query_metric, _semantic_server._METRICS, partial_month=partial_month)


def safe_answer_question(text: str, partial_month: str = None) -> dict:
    """answer_question() that never raises: a failure comes back as kind 'failed' with a
    plain-language notice and no exception text (lib/answers.py safe_answer)."""
    return _answers.safe_answer(answer_question, text, partial_month=partial_month)


def registry() -> dict:
    """The loaded registry (metrics, metric_order, pillars, stamp fields)
    the semantic layer itself serves. The tree panel is built from this,
    never from a hard-coded copy."""
    return _semantic_server._REGISTRY
