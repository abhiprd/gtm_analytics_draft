"""Deterministic question routing for the Ask the Metric Tree page.

Pure Python, no Streamlit and no import of semantic/server.py, so the
routing rules are unit-testable under the repo's default interpreter
(tests/test_dashboard_routing.py). lib/semantic_bridge.py builds the
vocabulary from the semantic layer's own registry and alias table and
passes it in; nothing here defines a metric.

Matching is keyword matching against names the registry already
recognizes (display names, keys, documented aliases). It is not an LLM
call and not a fuzzy match.

Rules, in the order they are applied
------------------------------------
1. Normalization. Both the question and every vocabulary phrase are
   lowercased and split into alphanumeric tokens. Every other character
   is a separator, so a hyphen, en dash, colon, slash or arrow all match
   each other ("Marketing–sales" = "marketing-sales" = "marketing sales";
   "LTV:CAC" = "ltv cac"). A standalone "x" or "×" is dropped, so
   "LTV by segment × acquisition channel" = "... segment x acquisition
   channel". Phrases match on whole tokens only ("cac" never matches
   inside "cache").
2. Metric. The question is scanned left to right. At each position the
   longest vocabulary phrase that starts there wins, and scanning resumes
   after it. The first match is the primary metric; later matches of other
   metrics are reported in `secondary_metrics` and never dropped silently.
   Scanning left to right with longest-match-at-position is what makes
   "LTV:CAC by channel" resolve to LTV rather than to the longer phrase
   "cac by channel" that overlaps its tail.
3. Dimensions. "by/per/across/each/every <dimension>" or
   "<dimension> breakdown", for every dimension the registry lists in any
   metric's allowed_dimensions (segment, channel, opportunity_type). The
   dimension is always passed to the semantic layer; whether it is
   queryable is the guardrail's decision, so an unsupported split is
   answered by the guardrail and never silently replaced by blended data.
4. Segment qualifiers. A valid segment word filters. A segment-like word
   the registry does not know ("Tier 1", "Mid-Market", "Strategic") is
   passed through as the filter value so the guardrail answers with
   invalid_segment_value; it is never dropped. Qualifier detection ignores
   the tokens that were consumed by the metric's own name (a metric named
   "POC pass rate (Enterprise)" does not filter to Enterprise).
5. Grain. month / quarter / year words, same name-token exclusion.
"""
import re
from typing import Callable, Dict, Iterable, List, Optional, Tuple

DEFAULT_SEGMENTS = ("SMB", "Commercial", "Enterprise")

# Routing aids the dashboard adds on top of the semantic layer's own alias
# table (semantic/server.py `_ALIASES`), which has no entry for them.
# Every target is checked against the registry when the vocabulary is
# built. Proposed for promotion into server.py `_ALIASES` so MCP clients
# route the same way.
SUPPLEMENTARY_ALIASES = {
    "ltv": "ltv_by_segment_acquisition_channel",
    "lifetime value": "ltv_by_segment_acquisition_channel",
    "customer lifetime value": "ltv_by_segment_acquisition_channel",
    "ltv cac": "ltv_by_segment_acquisition_channel",
    "ltv to cac": "ltv_by_segment_acquisition_channel",
    "ltv cac ratio": "ltv_by_segment_acquisition_channel",
    "lifetime value to cac": "ltv_by_segment_acquisition_channel",
    "payback": "consumption_payback",
    "payback period": "consumption_payback",
    "cac payback": "consumption_payback",
    "cac payback period": "consumption_payback",
}

_GRAIN_WORDS = {
    "month": "month", "monthly": "month",
    "quarter": "quarter", "quarterly": "quarter",
    "year": "year", "yearly": "year", "annual": "year", "annually": "year",
}

_DIMENSION_LEAD_WORDS = ("by", "per", "across", "each", "every")
_DIMENSION_TRAIL_WORDS = ("breakdown", "split")

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> List[Tuple[str, int, int]]:
    """(token, start, end) for each alphanumeric run, lowercased, with
    standalone 'x' tokens removed (the '×' separator and a typed 'x' are
    the same thing). Offsets index into the original string."""
    out = []
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0).lower()
        if tok == "x":
            continue
        out.append((tok, m.start(), m.end()))
    return out


def _phrase_tokens(phrase: str) -> Tuple[str, ...]:
    return tuple(t for t, _, _ in tokenize(phrase))


def build_vocabulary(
    metrics: Dict[str, dict],
    aliases: Optional[Dict[str, str]] = None,
    supplementary_aliases: Optional[Dict[str, str]] = None,
    valid_segments: Iterable[str] = DEFAULT_SEGMENTS,
) -> dict:
    """Vocabulary from the registry's own names. `metrics` is the
    registry's `metrics` mapping; `aliases` the semantic layer's alias
    table. Precedence on identical phrases: display name, then key, then
    the semantic layer's alias, then a dashboard supplementary alias."""
    phrases: Dict[Tuple[str, ...], str] = {}

    def add(phrase: str, key: str) -> None:
        toks = _phrase_tokens(phrase)
        if toks and toks not in phrases:
            phrases[toks] = key

    for key, node in metrics.items():
        add(node["name"], key)
    for key in metrics:
        add(key.replace("_", " "), key)
    for source in (aliases or {}, SUPPLEMENTARY_ALIASES if supplementary_aliases is None
                   else supplementary_aliases):
        for phrase, key in source.items():
            if key not in metrics:
                raise KeyError(f"alias {phrase!r} targets {key!r}, which is not in the registry")
            add(phrase, key)

    dimensions: Dict[str, Tuple[str, ...]] = {}
    for node in metrics.values():
        for d in node.get("allowed_dimensions") or []:
            dimensions[d] = _phrase_tokens(d.replace("_", " "))

    by_first: Dict[str, List[Tuple[str, ...]]] = {}
    for toks in phrases:
        by_first.setdefault(toks[0], []).append(toks)
    for lst in by_first.values():
        lst.sort(key=lambda t: (-len(t), t))

    seg_map = {s.lower(): s for s in valid_segments}
    return {
        "phrases": phrases,
        "by_first": by_first,
        "dimensions": dimensions,
        "segments": seg_map,
    }


def _match_metrics(tokens: List[str], vocab: dict) -> List[dict]:
    """Left to right, longest phrase at each position, resume after it."""
    found = []
    i = 0
    while i < len(tokens):
        hit = None
        for toks in vocab["by_first"].get(tokens[i], ()):
            n = len(toks)
            if tuple(tokens[i:i + n]) == toks:
                hit = toks
                break  # sorted longest first
        if hit:
            found.append({"key": vocab["phrases"][hit], "start": i, "end": i + len(hit),
                          "phrase": " ".join(hit)})
            i += len(hit)
        else:
            i += 1
    return found


def _extract_dimensions(tokens: List[str], vocab: dict) -> List[str]:
    """Dimensions asked for, in the order they appear. A dimension word
    counts when it follows a lead word ("by segment"), precedes a trail
    word ("segment breakdown"), or is coordinated with one that does
    ("by segment and channel")."""
    mentions = []  # (position, dim, span)
    for dim, dtoks in vocab["dimensions"].items():
        variants = {dtoks, dtoks[:-1] + (dtoks[-1] + "s",)}
        n = len(dtoks)
        for i in range(len(tokens)):
            if any(tuple(tokens[i:i + n]) == v for v in variants):
                mentions.append((i, dim, n))
    mentions.sort()
    accepted = {}
    for i, dim, n in mentions:
        lead = tokens[i - 1] if i > 0 else None
        trail = tokens[i + n] if i + n < len(tokens) else None
        if lead in _DIMENSION_LEAD_WORDS or trail in _DIMENSION_TRAIL_WORDS:
            accepted[i] = dim
        elif lead in ("and", "or") and i >= 2:
            # coordinated with an already-accepted dimension that ends at i - 1
            for j, d in list(accepted.items()):
                span = len(vocab["dimensions"][d])
                if j + span == i - 1:
                    accepted[i] = dim
                    break
    out = []
    for i in sorted(accepted):
        if accepted[i] not in out:
            out.append(accepted[i])
    return out


def _segment_qualifiers(
    raw: str, toks: List[Tuple[str, int, int]], skip: set, vocab: dict
) -> Tuple[List[str], List[str]]:
    """(recognized segments in question order, unrecognized segment-like
    terms as the user typed them). `skip` is the set of token indexes
    consumed by the metric's own name. The segment-like lexicon is the
    terminology a reader is most likely to carry over from other schemas
    ("Tier N", Mid-Market, Strategic); the guardrail's invalid_segment_value
    message is the answer to it."""
    recognized: List[str] = []
    unrecognized: List[str] = []
    words = [t for t, _, _ in toks]
    n = len(words)

    def original(i: int, j: int) -> str:
        return raw[toks[i][1]:toks[j][2]]

    i = 0
    while i < n:
        if i in skip:
            i += 1
            continue
        w = words[i]
        if w in vocab["segments"]:
            seg = vocab["segments"][w]
            if seg not in recognized:
                recognized.append(seg)
        elif w == "tier" and i + 1 < n and (i + 1) not in skip:
            unrecognized.append(original(i, i + 1))
            i += 1
        elif re.fullmatch(r"tier[0-9a-z]", w) or re.fullmatch(r"tier[0-9]+", w):
            unrecognized.append(original(i, i))
        elif w == "mid" and i + 1 < n and words[i + 1] == "market" and (i + 1) not in skip:
            unrecognized.append(original(i, i + 1))
            i += 1
        elif w == "midmarket":
            unrecognized.append(original(i, i))
        elif w == "strategic":
            unrecognized.append(original(i, i))
        i += 1
    return recognized, unrecognized


def route_question(
    text: str,
    vocab: dict,
    suggest: Optional[Callable[[str], List[str]]] = None,
) -> dict:
    """Route one free-text question. Returns:

    raw_question, resolved_metric (registry key or None), matched_term,
    suggestions (only when nothing resolved), dimensions, filters
    ({"segment": value} possibly with an unrecognized value for the
    guardrail to reject), grain, secondary_metrics (other metrics named
    after the primary one), segment_subset (several valid segments named:
    display filter for a split-by-segment answer), unrecognized_segment
    (the segment-like term passed through, or None)."""
    toks = tokenize(text)
    words = [t for t, _, _ in toks]

    matches = _match_metrics(words, vocab)
    primary = matches[0] if matches else None
    secondary = []
    for m in matches[1:]:
        if m["key"] != (primary or {}).get("key") and m["key"] not in secondary:
            secondary.append(m["key"])

    skip = set(range(primary["start"], primary["end"])) if primary else set()
    # Dimensions are read from the whole question, including the metric's
    # own name: "CAC by channel" asks for a channel split.
    dimensions = _extract_dimensions(words, vocab)

    recognized, unrecognized = _segment_qualifiers(text, toks, skip, vocab)
    filters: Dict[str, str] = {}
    segment_subset: List[str] = []
    if unrecognized:
        filters["segment"] = unrecognized[0]
    elif len(recognized) == 1:
        filters["segment"] = recognized[0]
    elif len(recognized) > 1:
        segment_subset = list(recognized)
        if "segment" not in dimensions:
            dimensions.append("segment")

    grain = "month"
    for idx, w in enumerate(words):
        if idx in skip:
            continue
        if w in _GRAIN_WORDS:
            grain = _GRAIN_WORDS[w]
            break

    suggestions: List[str] = []
    if primary is None and suggest is not None:
        suggestions = suggest(text)

    return {
        "raw_question": text,
        "resolved_metric": primary["key"] if primary else None,
        "matched_term": primary["phrase"] if primary else None,
        "suggestions": suggestions,
        "dimensions": dimensions,
        "filters": filters,
        "grain": grain,
        "secondary_metrics": secondary,
        "segment_subset": segment_subset,
        "unrecognized_segment": unrecognized[0] if unrecognized else None,
    }
