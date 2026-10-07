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
6. Scope words. A scope word beside a broader metric name outranks it: "win rate for
   renewals" resolves to Renewal win rate, not Win rate (SCOPE_OVERRIDES).
7. Unsupported splits. A "by <phrase>" or "per <phrase>" split that is not a dimension the
   registry lists is never dropped silently: it is returned in `unsupported_splits` so the
   page can say so and offer the nearest real node. A "by" inside a matched metric name, a
   time phrase ("by end of quarter") and a grain word ("by month") are not splits.
"""
import re
from typing import Callable, Dict, Iterable, List, Optional, Tuple

DEFAULT_SEGMENTS = ("SMB", "Commercial", "Enterprise")

# Routing aids the dashboard adds on top of the semantic layer's own alias table
# (semantic/server.py `_ALIASES`). Every phrase the dashboard once added here (LTV, lifetime
# value, LTV:CAC, payback, CAC payback and their variants) now lives in `_ALIASES`, so MCP
# clients and this page route the same way, and this table is empty. The mechanism stays for
# a future page-only phrase; a test fails if an entry duplicates a server alias.
SUPPLEMENTARY_ALIASES: Dict[str, str] = {}

# A scope word in the question outranks the broader metric name it sits beside: the longest
# phrase at a position would otherwise take "win rate" in "win rate for renewals" and leave
# "renewals" as a secondary mention. Each rule names the tokens, the key they override and
# the key that wins; it applies only when the winning key is in the vocabulary.
SCOPE_OVERRIDES = (
    {"tokens": ("renewal", "renewals"), "from_key": "win_rate", "to_key": "renewal_win_rate"},
)

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
        # "across all segments", "by every channel": a quantifier between the lead word
        # and the dimension does not change the request.
        if lead in ("all", "every", "each", "the") and i >= 2 and tokens[i - 2] in _DIMENSION_LEAD_WORDS:
            lead = tokens[i - 2]
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


_SPLIT_START_WORDS = ("by", "per", "across", "each", "every")
_SPLIT_BREAK_WORDS = ("by", "per", "across")
# Tokens that end the phrase after "by": a preposition or time word starts a new clause.
_SPLIT_STOP_WORDS = {
    "for", "in", "of", "vs", "versus", "during", "over", "last", "this", "since", "from", "to",
    "with", "on", "at", "where", "when", "than", "compared", "between", "within", "as", "is",
    "are", "was", "were", "and", "or", "but", "then", "now", "today",
}
_SPLIT_DETERMINERS = {"the", "a", "an", "all", "each", "every", "any", "our", "my", "their"}
_TIME_WORDS = {"end", "next", "early", "late", "mid", "yesterday", "tomorrow", "eod", "eom", "eoq",
               "eoy", "date"}
_MAX_SPLIT_TOKENS = 4


def _is_time_like(word: str) -> bool:
    return word.isdigit() or bool(re.fullmatch(r"q[1-4]", word)) or word in _TIME_WORDS


def _dimension_variants(vocab: dict) -> set:
    out = set()
    for dtoks in vocab["dimensions"].values():
        out.add(dtoks)
        out.add(dtoks[:-1] + (dtoks[-1] + "s",))
    return out


def unsupported_splits(text: str, toks: List[Tuple[str, int, int]], protected: set, vocab: dict) -> List[str]:
    """Phrases after a "by"/"per"/"across"/"each"/"every" that are neither a dimension the
    registry lists, a grain word, nor a time phrase, as the reader typed them. `protected`
    holds the token indexes inside a matched metric name (a "by" there is part of the name).
    Items are separated by commas, slashes, ampersands, plus signs, "and" and "or"; a
    preposition, a segment name or another lead word ends the phrase."""
    words = [t for t, _, _ in toks]
    variants = _dimension_variants(vocab)
    out: List[str] = []
    i = 0
    while i < len(words):
        if words[i] not in _SPLIT_START_WORDS or i in protected:
            i += 1
            continue
        j = i + 1
        items: List[List[int]] = [[]]
        while j < len(words):
            w = words[j]
            gap = text[toks[j - 1][2]:toks[j][1]] if j > i + 1 else ""
            if w in _SPLIT_BREAK_WORDS or w in vocab["segments"] or w in ("and", "or"):
                if w in ("and", "or") and items[-1]:
                    items.append([])
                    j += 1
                    continue
                break
            if w in _SPLIT_STOP_WORDS:
                break
            if any(c in gap for c in ",/&+;") and items[-1]:
                items.append([])
            items[-1].append(j)
            j += 1
        for item in items:
            # Drop leading determiners only ("by the region" -> "region").
            lead = 0
            while lead < len(item) and words[item[lead]] in _SPLIT_DETERMINERS:
                lead += 1
            item = item[lead:]
            if not item:
                continue
            first = words[item[0]]
            phrase_words = tuple(words[k] for k in item)
            if _is_time_like(first) or first in _GRAIN_WORDS:
                continue
            if any(phrase_words[:n] in variants for n in range(1, len(phrase_words) + 1)):
                continue
            span = item[:_MAX_SPLIT_TOKENS]
            out.append(text[toks[span[0]][1]:toks[span[-1]][2]])
        i = max(i + 1, j)
    seen, uniq = set(), []
    for ph in out:
        k = " ".join(ph.lower().split())
        if k not in seen:
            seen.add(k)
            uniq.append(ph)
    return uniq


def _apply_scope_overrides(primary: Optional[dict], words: List[str], vocab: dict) -> Optional[dict]:
    """Swap the primary match for the more specific metric a scope word names
    (SCOPE_OVERRIDES): 'win rate for renewals' -> Renewal win rate."""
    if not primary:
        return primary
    keys = set(vocab["phrases"].values())
    consumed = set(range(primary["start"], primary["end"]))
    for rule in SCOPE_OVERRIDES:
        if primary["key"] != rule["from_key"] or rule["to_key"] not in keys:
            continue
        if any(w in rule["tokens"] for i, w in enumerate(words) if i not in consumed):
            return {**primary, "key": rule["to_key"], "phrase": f"{primary['phrase']} + scope word"}
    return primary


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
    (the segment-like term passed through, or None), unsupported_splits (split phrases the
    registry has no dimension for, as typed; empty when nothing resolved)."""
    toks = tokenize(text)
    words = [t for t, _, _ in toks]

    matches = _match_metrics(words, vocab)
    primary = matches[0] if matches else None
    primary = _apply_scope_overrides(primary, words, vocab)
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

    protected = {k for m in matches for k in range(m["start"], m["end"])}
    splits = unsupported_splits(text, toks, protected, vocab)

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
        "unsupported_splits": splits if primary else [],
    }
