"""Presentation rules for the pipeline-coverage section of the Forecast page,
Streamlit-free so they are unit-testable (tests/test_dashboard_coverage_view.py).

The reading is produced by analytics/pipeline_coverage.py's run_pipeline_coverage()
(called in-process) and carries its own plain-language `display` strings. This module
only decides how those are laid out; it never computes a coverage figure, a gap, a
ratio or a status. The only arithmetic is number formatting (dollar and percent
strings for fields the artifact already carries as numbers).

A COVERAGE READING, NOT A FORECAST. The label travels with the block, the next-quarter
view carries no verdict, and the reconciliation is a side-by-side comparison with the
forecast lens: the two figures are never merged.

Status wording. The coverage bands are PROPOSED (status_rule), the evidence for them is
a small set of mid-quarter readings and part of the link between coverage and final
attainment is mechanical, so the status is a neutral gray "Proposed band" chip carrying
the band text, never a green or red verdict (conventions Section 2.3).
"""
import re
from typing import Dict, List, Optional, Tuple

from . import forecast_logic, labels

fmt_usd = forecast_logic.fmt_usd

STATUS_WORD = {"covered": "Covered", "thin": "Thin", "shortfall": "Shortfall", "quota_met": "Quota met"}
BAND_STATUSES = tuple(STATUS_WORD)

# The reason codes the artifact emits for an unavailable segment, in the artifact's own
# words where it already states the reason in plain language; the dashboard rewrites them
# only to take the build-process wording out ("simulated window", "artifact").
UNAVAILABLE_FALLBACK = "The coverage reading is not available for this segment at this date."

NEXT_QUARTER_NOTE_FALLBACK = ("Indicative only: next quarter's quota is not set, so this quarter's stated quota "
                              "is carried forward, and pipeline that has not been created yet is not visible.")


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and v != v)


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _pct(fraction, digits: int = 1) -> str:
    return "n/a" if _missing(fraction) else f"{float(fraction) * 100:.{digits}f}%"


def _x(value, digits: int = 2) -> str:
    return "n/a" if _missing(value) else f"{float(value):.{digits}f}x"


def _deals(n) -> str:
    n = int(n)
    return f"{n} deal" if n == 1 else f"{n} deals"


_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def keep_dates_whole(text: str) -> str:
    """Non-breaking hyphens inside ISO dates, so a date in a card footer never wraps
    across two lines ('2024-' / '11-15')."""
    return _ISO_DATE.sub("\\1\u2011\\2\u2011\\3", str(text))


def _disp(seg: Dict, key: str, default: str = "n/a") -> str:
    shown = (seg.get("display") or {}).get(key)
    return shown if shown else default


def _days(n) -> str:
    n = int(n)
    return f"{n} day" if n == 1 else f"{n} days"


def _win_rate(seg: Dict) -> str:
    """'25.5%' from the display string '25.5% over 442 closed deals since 2024-11-15'."""
    shown = _disp(seg, "realized_conversion", "")
    return shown.split(" over ")[0] if shown and shown != "unavailable" else "n/a"


def _window_text(seg: Dict) -> str:
    """The conversion window actually used, from the reading's own window fields."""
    start, end = seg.get("conversion_window_start"), seg.get("conversion_window_end")
    if start and end:
        return f"deals closed {start} to {end}"
    return "deals closed since the later of 2023-01-01 and 365 days before the date"


def _amount_and_word(gap_text: str) -> Tuple[str, str]:
    parts = str(gap_text).rsplit(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (gap_text, "")


# --------------------------------------------------------------------------
# Status chip: neutral gray, proposed band, never a verdict color
# --------------------------------------------------------------------------

def band_text(status: str, status_rule: Optional[Dict]) -> Optional[str]:
    """The band a status stands for, from the artifact's own status_rule thresholds
    ('0.75x to below 1.00x of required'); None for a status without a band."""
    rule = status_rule or {}
    covered, thin = rule.get("covered_min_coverage_vs_required"), rule.get("thin_min_coverage_vs_required")
    if status == "quota_met":
        return "no quota left to book"
    if _missing(covered) or _missing(thin):
        return None
    if status == "covered":
        return f"{float(covered):.2f}x of required or more"
    if status == "thin":
        return f"{float(thin):.2f}x to below {float(covered):.2f}x of required"
    if status == "shortfall":
        return f"below {float(thin):.2f}x of required"
    return None


def status_chip(seg: Dict, status_rule: Optional[Dict]) -> Optional[str]:
    """Chip text for a present segment: 'Proposed band: Thin, 0.75x to below 1.00x of
    required'. None for an unavailable segment (the page shows a reason box instead)."""
    status = seg.get("coverage_status")
    if seg.get("status") != "present" or status not in BAND_STATUSES:
        return None
    word = _disp(seg, "status_text", STATUS_WORD[status])
    band = band_text(status, status_rule)
    return f"Proposed band: {word}, {band}" if band else f"Proposed band: {word}"


# --------------------------------------------------------------------------
# Cards
# --------------------------------------------------------------------------

def gap_wording(seg: Dict) -> str:
    """'$181.7K short' or '$1.27M ahead': the artifact's own display string; when it is
    absent, the same wording from the signed field (positive = shortfall)."""
    shown = (seg.get("display") or {}).get("conversion_implied_gap")
    if shown and shown != "n/a":
        return shown
    gap = seg.get("conversion_implied_gap_usd")
    if _missing(gap):
        return "n/a"
    return f"{fmt_usd(abs(float(gap)))} short" if float(gap) > 0 else f"{fmt_usd(abs(float(gap)))} ahead"


def gap_sentence(seg: Dict) -> Optional[str]:
    """Coverage language for the gap: 'At the recent win rate the open pipeline would close
    about $184.9K, $181.7K less than the quota still to book.' Built from the artifact's
    display strings; None when the reading lacks them."""
    expected = (seg.get("display") or {}).get("conversion_implied_expected_close")
    gap = gap_wording(seg)
    if not expected or expected == "n/a" or gap == "n/a":
        return None
    amount, word = _amount_and_word(gap)
    relation = {"short": "less than", "ahead": "more than"}.get(word)
    if not relation:
        return None
    return (f"At the recent win rate the open pipeline would close about {expected}, "
            f"{amount} {relation} the quota still to book.")


def segment_summary(seg: Dict) -> Optional[str]:
    """The one-sentence verdict line under a segment heading. A segment with quota left to
    book reads in coverage language (coverage, required multiple, what the pipeline would
    close); a segment whose quota is met keeps the artifact's own summary. Falls back to the
    artifact's summary whenever a display string is missing."""
    d = seg.get("display") or {}
    fallback = d.get("summary")
    if seg.get("coverage_status") == "quota_met" or seg.get("status") != "present":
        return fallback
    needed = ("status_text", "open_pipeline", "remaining_quota", "pipeline_coverage_ratio",
              "required_pipeline_multiple", "coverage_vs_required", "realized_conversion")
    if int(seg.get("open_pipeline_deals") or 0) == 0 and d.get("remaining_quota") and d.get("required_pipeline_multiple"):
        return (f"{seg.get('segment')}: {d.get('status_text', 'Shortfall')}. No open new-business pipeline against "
                f"{d['remaining_quota']} still to book; {d['required_pipeline_multiple']} is needed at the recent "
                f"{_win_rate(seg)} win rate.")
    sentence = gap_sentence(seg)
    if not sentence or any(not d.get(k) or d.get(k) == "n/a" for k in needed):
        return fallback
    return (f"{seg.get('segment')}: {d['status_text']}. {d['open_pipeline'].replace(' across ', ' open across ', 1)} "
            f"against {d['remaining_quota']} still to book is {d['pipeline_coverage_ratio']} coverage; "
            f"{d['required_pipeline_multiple']} is needed at the recent {_win_rate(seg)} win rate, so the pipeline "
            f"is {d['coverage_vs_required']} of required. {sentence}")


def segment_qualifier(segment: str, backtest_summary: Optional[Dict]) -> Optional[str]:
    """How far to trust a mid-quarter reading for this segment, from the backtest summary:
    average error and, where deals created after mid-quarter exist, that the reading is a
    floor. None when the report carries no figure for the segment."""
    row = ((backtest_summary or {}).get("by_segment") or {}).get(segment) or {}
    mape = row.get("mape_coverage_implied")
    if _missing(mape):
        return None
    text = f"Average error in the mid-quarter backtest: {_pct(mape, 0)} for {segment}."
    bias, late = row.get("aggregate_bias_pct"), row.get("late_created_share_of_actual")
    if not _missing(bias) and not _missing(late) and float(late) > 0:
        direction = "below" if float(bias) < 0 else "above"
        text += (f" Readings run about {_pct(abs(float(bias)), 0)} {direction} actual bookings in aggregate, because "
                 f"{_pct(late, 0)} of {segment} bookings come from deals created after mid-quarter: treat the "
                 "reading as a floor.")
    return text


EVALUATION_NOTE = "Outside the mid-quarter backtest window: this date is not validated."


def evaluation_point_note(as_of: Optional[str], mid_quarter_date: Optional[str]) -> Optional[str]:
    """A visible line when the evaluation date is not the quarter's mid-quarter checkpoint,
    the only point the backtest covers. `mid_quarter_date` comes from the artifact's own
    mid_quarter_eval_date helper; None (helper unavailable) shows nothing."""
    if not as_of or not mid_quarter_date or str(as_of) == str(mid_quarter_date):
        return None
    return f"{EVALUATION_NOTE} The backtested reading for this quarter is dated {mid_quarter_date}."


def coverage_value(seg: Dict) -> Tuple[str, Optional[str]]:
    """(value, value_size) of the coverage-versus-required card. A segment whose quota is
    met has no coverage ratio (null): it reads 'Quota met', never 0.00x."""
    if seg.get("coverage_status") == "quota_met" or _missing(seg.get("coverage_vs_required")):
        return ("Quota met" if seg.get("coverage_status") == "quota_met" else "Not defined"), "sm"
    return f"{_disp(seg, 'coverage_vs_required')} of required", None


def segment_cards(seg: Dict, period: str, as_of: str) -> List[Dict]:
    """The four equal-height cards of one present segment (theme.scorecard_row keys). Every
    card closes with a 'Basis:' footer. No card carries a favorable/unfavorable color: the
    bands are proposed and the gap is a dollar reading, not a plan comparison."""
    met = seg.get("coverage_status") == "quota_met"
    remaining = dict(
        label="Remaining quota", value_display=_disp(seg, "remaining_quota"), pillar="growth",
        footer=[f"Quota {_disp(seg, 'quota')}; won to date {_disp(seg, 'won_to_date')} "
                f"({_disp(seg, 'attainment_to_date')} of quota)",
                _disp(seg, "quota_basis"),
                f"Basis: {period} quota, quarter to date"],
    )
    none_open = int(seg.get("open_pipeline_deals") or 0) == 0
    pipe_footer = (["No open new-business pipeline for this quarter"] if none_open else [])
    pipe_footer.append(f"{seg.get('owner_role', 'Rep')}-owned deals closing in {period}")
    if int(seg.get("open_pipeline_after_quarter_deals") or 0) > 0:
        pipe_footer.append(_cap(_disp(seg, "pipeline_after_quarter_end")))
    pipe_footer.append(keep_dates_whole(f"Basis: new business only, open at {as_of}"))
    pipeline = dict(
        label="Open new-business pipeline",
        value_display="None open" if none_open else _disp(seg, "open_pipeline"), pillar="growth",
        value_size="sm" if none_open else None, footer=pipe_footer,
    )
    value, size = coverage_value(seg)
    if met:
        cov_footer = ["No quota left to book, so no coverage ratio applies",
                      keep_dates_whole(f"Win rate {_disp(seg, 'realized_conversion')}")]
    else:
        cov_footer = [f"Coverage {_disp(seg, 'pipeline_coverage_ratio')} against "
                      f"{_disp(seg, 'required_pipeline_multiple')} needed",
                      keep_dates_whole(f"Win rate {_disp(seg, 'realized_conversion')}")]
    cov_footer.append(keep_dates_whole(f"Basis: coverage ratio over required multiple; win rate from {_window_text(seg)}"))
    coverage = dict(
        label="Coverage vs required", value_display=value, value_size=size, pillar="growth", footer=cov_footer,
    )
    if met:
        gap_footer = [
            f"At the recent win rate the open pipeline would close about {_disp(seg, 'conversion_implied_expected_close')}.",
            "Expected surplus over the quota still to book (none remaining); "
            f"{_disp(seg, 'won_to_date')} won against {_disp(seg, 'quota')} quota.",
        ]
    else:
        gap_footer = [gap_sentence(seg) or "Gap not available for this reading."]
    gap = dict(
        label="Conversion-implied gap", value_display=gap_wording(seg), pillar="growth",
        footer=gap_footer + ["Basis: remaining quota minus open pipeline times win rate"],
    )
    return [remaining, pipeline, coverage, gap]


# --------------------------------------------------------------------------
# Enterprise POC view (indicative)
# --------------------------------------------------------------------------

def poc_view_block(poc: Optional[Dict]) -> Optional[Dict]:
    """{title, chip, lines} for the Enterprise POC-conditioned view, or None when the
    segment carries none. An unavailable view carries its reason and no figures."""
    if not poc:
        return None
    chip = _cap(str(poc.get("label") or "indicative, not a forecast"))
    title = "Enterprise POC outcome view"
    if poc.get("status") != "present":
        reason = labels.apply_phrase_map(poc.get("reason")) or "The POC outcome view is not available at this date."
        return dict(title=title, chip=chip, chips=[chip], lines=[_cap(str(reason))], window_start=poc.get("window_start"))
    rates = poc.get("rates") or {}

    def rate_line(key: str, word: str) -> str:
        r = rates.get(key) or {}
        return (f"POC {word}: {int(r.get('closed_deals', 0))} closed deals, {int(r.get('won_deals', 0))} won "
                f"({_pct(r.get('rate'))})")

    lines = [
        f"Closed Enterprise deals since {poc.get('window_start')}: {rate_line('pass', 'passed')}; "
        f"{rate_line('fail', 'failed')}.",
        f"Open deals: {_deals(poc.get('open_pass_deals', 0))} passed ({fmt_usd(float(poc.get('open_pass_usd') or 0))}), "
        f"{_deals(poc.get('open_fail_deals', 0))} failed ({fmt_usd(float(poc.get('open_fail_usd') or 0))}), "
        f"{_deals(poc.get('open_unrevealed_deals', 0))} not yet revealed "
        f"({fmt_usd(float(poc.get('open_unrevealed_usd') or 0))}).",
    ]
    if not _missing(poc.get("poc_conditioned_expected_close_usd")):
        lines.append(f"Expected close pricing each open deal by its POC outcome: "
                     f"{fmt_usd(float(poc['poc_conditioned_expected_close_usd']))}.")
    sample = (f"Not backtested; thin sample: {int((rates.get('pass') or {}).get('closed_deals', 0))} passed and "
              f"{int((rates.get('fail') or {}).get('closed_deals', 0))} failed closed deals.")
    lines.insert(0, sample)
    return dict(title=title, chip=chip, chips=[chip, "Not backtested; thin sample"], lines=lines,
                window_start=poc.get("window_start"))


# --------------------------------------------------------------------------
# Unavailable segments
# --------------------------------------------------------------------------

def unavailable_message(seg: Dict, data_window: Optional[Dict] = None) -> str:
    """Plain-language reason for a segment whose reading is unavailable. No figures from
    the reading: only the reason and the dates it names."""
    name = seg.get("segment", "This segment")
    code = seg.get("reason_code")
    last_close = (data_window or {}).get("last_opportunity_close")
    if code == "no_quota":
        text = "No quota-bearing rep has an active day in this quarter, so there is no quota to cover."
    elif code == "before_conversion_window":
        text = ("The evaluation date precedes January 2023. No lost deal is logged before then, so any "
                "earlier win rate is a structural 100% and no realized win rate exists.")
    elif code == "insufficient_closed_deals":
        n, start, end = seg.get("conversion_closed_deals"), seg.get("conversion_window_start"), seg.get("conversion_window_end")
        window = f" between {start} and {end}" if start and end else ""
        have = f"Only {int(n)} closed deals{window}" if not _missing(n) else "Too few closed deals"
        text = (f"{have}. Too few to state a win rate, and no lost deals are logged before 2023, so the "
                "window cannot reach further back.")
    elif code == "no_wins_in_window":
        text = "No deal was won in the win-rate window, so the required pipeline multiple is undefined."
    elif code == "after_data_window":
        when = f" ({last_close})" if last_close else ""
        text = (f"The evaluation date is on or after the last close in the data{when}. No deal can be open, "
                "so a reading would reflect an empty pipeline, not coverage.")
    else:
        reason = seg.get("reason")
        text = _cap(str(reason)) if reason else UNAVAILABLE_FALLBACK
    return f"{name}: coverage reading unavailable. {text}"


# --------------------------------------------------------------------------
# Next quarter
# --------------------------------------------------------------------------

def hidden_segments(reading: Dict) -> List[str]:
    """Segments whose reading is unavailable: they are suppressed from the next-quarter
    block and the reconciliation table, so no figure for them appears elsewhere."""
    return [s.get("segment", "") for s in (reading or {}).get("segments") or [] if s.get("status") != "present"]


def not_shown_line(segment: str) -> str:
    return f"Not shown: coverage unavailable for {segment}."


def next_quarter_view(block: Optional[Dict], data_window: Optional[Dict] = None, hidden=()) -> Dict:
    """How the next-quarter block is shown.

      unavailable  an honest blank: `message` for the info box and `detail` for the
                   'Why this is blank' expander; never a zero.
      present      one compact line per segment, no verdict; Commercial with no deal yet
                   reads 'none yet', never 0.00x.
      absent       the reading carries no next-quarter block: nothing is shown.
    """
    if not block:
        return dict(kind="absent", period=None, lines=[], message=None, detail=None, needed=None, note=None)
    period = block.get("period") or "Next quarter"
    if block.get("status") != "present":
        last_close = (data_window or {}).get("last_opportunity_close")
        if block.get("reason_code") == "beyond_data_window" and last_close:
            message = (f"{period} coverage is blank: the data ends {last_close}, before {period} starts, so no "
                       "pipeline exists for it. This is not zero coverage.")
            detail = (f"The last close recorded in the data is {last_close}. {period} starts after that date, so "
                      "no open deal can be dated into it.")
            needed = f"Opportunity data with closes after {last_close}."
        else:
            reason = block.get("reason")
            message = f"{period} coverage is blank. {_cap(str(reason))}" if reason else f"{period} coverage is blank."
            detail = _cap(str(reason)) if reason else "The reading carries no reason."
            needed = "Data for the period."
        return dict(kind="unavailable", period=period, lines=[], message=message, detail=detail,
                    needed=needed, note=None)
    lines = []
    note = None
    for s in block.get("segments") or []:
        d = s.get("display") or {}
        if s.get("segment") in hidden:
            lines.append((s.get("segment", ""), f"not shown: coverage unavailable for {s.get('segment', '')}"))
            continue
        if int(s.get("open_pipeline_deals") or 0) == 0:
            text = (f"none yet, no deal is open for {period}; carried-forward quota "
                    f"{d.get('carried_forward_quota', 'n/a')}; no verdict")
        else:
            text = (f"{d.get('open_pipeline', 'n/a')} closing next quarter; "
                    f"{d.get('pipeline_coverage_ratio', 'n/a')} of the carried-forward quota "
                    f"({d.get('carried_forward_quota', 'n/a')}); no verdict")
        lines.append((s.get("segment", ""), text))
        note = note or d.get("note")
    return dict(kind="present", period=period, lines=lines, message=None, detail=None, needed=None,
                note=_cap(note) if note else NEXT_QUARTER_NOTE_FALLBACK)


# --------------------------------------------------------------------------
# Reconciliation with the forecast's manager lens
# --------------------------------------------------------------------------

def _difference_text(diff_usd, diff_pct) -> str:
    if _missing(diff_usd):
        return "n/a"
    direction = "above" if float(diff_usd) > 0 else "below" if float(diff_usd) < 0 else "equal to"
    amount = fmt_usd(abs(float(diff_usd)))
    if direction == "equal to":
        return "Equal"
    pct = f" ({_pct(abs(float(diff_pct)))})" if not _missing(diff_pct) else ""
    return f"{amount} {direction} the forecast lens{pct}"


RECON_HEADERS = ("Segment", "Open pipeline, coverage reading", "Open pipeline, forecast (new business)",
                 "Expected close, coverage reading", "Expected close, forecast manager lens",
                 "Difference", "Forecast pipeline, all opportunity types")


def reconciliation_view(rec: Optional[Dict], hidden=()) -> Dict:
    """{available, tie_text, headers, rows, explanation} for the 'Compared with the
    forecast' table. Every cell is a formatted artifact field; the two expected-close
    figures sit side by side and are never combined."""
    if not rec or rec.get("status") != "present":
        return dict(available=False, tie_text=None, headers=RECON_HEADERS, rows=[], explanation=None,
                    hidden_notes=[])
    rows = []
    hidden_notes = []
    for r in rec.get("by_segment") or []:
        if r.get("segment") in hidden:
            hidden_notes.append(not_shown_line(r.get("segment", "")))
            continue
        expected = r.get("coverage_reading_conversion_implied_expected_close_usd")
        rows.append((
            r.get("segment", ""),
            f"{fmt_usd(float(r['coverage_reading_open_pipeline_usd']))} across {_deals(r['coverage_reading_open_deals'])}",
            f"{fmt_usd(float(r['forecast_new_business_open_pipeline_usd']))} across {_deals(r['forecast_new_business_open_deals'])}",
            "n/a" if _missing(expected) else fmt_usd(float(expected)),
            fmt_usd(float(r["forecast_manager_lens_new_business_weighted_usd"])),
            _difference_text(r.get("difference_usd"), r.get("difference_pct_of_forecast_lens")),
            f"{fmt_usd(float(r['forecast_open_pipeline_all_opportunity_types_usd']))} across "
            f"{_deals(r['forecast_open_deals_all_opportunity_types'])}",
        ))
    tie_text = ("Open pipeline ties exactly to the forecast's new-business pipeline."
                if rec.get("ties_on_open_pipeline") else
                "Open pipeline does not tie to the forecast's new-business pipeline for every segment.")
    explanation = ("The two views agree on which deals are open. They price those dollars differently: the coverage "
                   "reading applies one realized win rate per segment, the forecast manager lens weights each deal by "
                   "its forecast category, so the expected-close figures differ by design. They answer different "
                   "questions and are shown side by side, never combined. The forecast's all-type pipeline also "
                   "includes renewal and expansion deals that quota does not cover.")
    return dict(available=True, tie_text=tie_text, headers=RECON_HEADERS, rows=rows, explanation=explanation,
                hidden_notes=hidden_notes)


def scope_line(reading: Dict) -> str:
    """The visible new-business-only line above the cards."""
    period = reading.get("period") or "the quarter"
    return (f"Open pipeline counts new business only: ISR- and AE-owned deals closing in {period}. The forecast "
            "lenses above price all opportunity types, including renewal and expansion, so their pipeline "
            "figure is larger than the one shown here; the comparison is below.")


# --------------------------------------------------------------------------
# Header context row
# --------------------------------------------------------------------------

def artifact_status_text(status_label: str, built: bool) -> str:
    """Section 7: the section states the artifact's validation status on its face until
    it is built and validated."""
    return status_label if built else f"{status_label}, not yet independently validated"


def info_items(reading: Dict, status_text: str) -> List[Tuple[str, str]]:
    days_left = reading.get("days_to_quarter_end")
    quarter = f"{reading.get('period', 'n/a')}, {_days(days_left)} left" if not _missing(days_left) else str(reading.get("period", "n/a"))
    return [
        ("Evaluation date", f"{reading.get('as_of_date', 'n/a')}, the forecast call date"),
        ("Quarter", quarter),
        ("Grain", "Quarterly, new business"),
        ("Artifact status", status_text),
    ]


# --------------------------------------------------------------------------
# Notes & assumptions
# --------------------------------------------------------------------------

def classify_caveat(text: str) -> str:
    """Notes kind for one artifact caveat: an Assumption (a rule applied), a Data gap (the
    data cannot show it) or a Scope statement (what the reading covers)."""
    t = str(text).lower()
    if "data window ends" in t or "not yet visible" in t or "has not been created yet" in t \
            or "cannot see pipeline" in t:
        return "Data gap"
    if "never pro-rated" in t or "not pro-rated" in t or "stand-in" in t:
        return "Assumption"
    return "Scope"


# The comparators the artifact's backtest scores the reading against, in the order shown.
# Every one that the committed report carries is quoted; a missing one is named as missing
# and the note says the comparison is incomplete, so a subset is never quoted silently.
COMPARATORS = (
    ("mape_naive_won_to_date", "won to date alone"),
    ("mape_naive_trailing_4q_mean", "the prior four-quarter mean"),
    ("mape_naive_constant_rate_025", "a fixed constant rate (won to date plus 25% of open pipeline)"),
    ("mape_naive_pace", "pace (won to date scaled by the share of the quarter elapsed)"),
)
_SHORT_NAME = {"mape_naive_won_to_date": "won to date alone", "mape_naive_trailing_4q_mean": "prior four-quarter mean",
               "mape_naive_constant_rate_025": "constant rate", "mape_naive_pace": "pace"}
BACKTEST_SEGMENTS = ("Commercial", "Enterprise")


def backtest_notes(summary: Optional[Dict]) -> List[Tuple[str, str]]:
    """Scope lines quoting the committed backtest of the mid-quarter reading: the reading's
    average error pooled and by segment next to every comparator the report carries, then
    the plain conclusion drawn from the report's own beats-baseline flags. Returns [] when
    the report has no backtest; no figure is invented or hard-coded."""
    if not summary:
        return []
    pooled = summary.get("pooled") or {}
    by_seg = summary.get("by_segment") or {}
    if _missing(pooled.get("n")) or _missing(pooled.get("mape_coverage_implied")):
        return []
    present = [k for k, _ in COMPARATORS if not _missing(pooled.get(k))]
    missing = [_SHORT_NAME[k] for k, _ in COMPARATORS if _missing(pooled.get(k))]
    out = []

    def figures(row: Dict) -> str:
        parts = [f"reading {_pct(row['mape_coverage_implied'])}"]
        parts += [f"{_SHORT_NAME[k]} {_pct(row[k])}" for k in present if not _missing(row.get(k))]
        return "; ".join(parts)

    # Each line is one sentence under the notes' display limit, so the conclusion is on the
    # face of the notes and not behind a Details toggle.
    out.append(("Scope", f"Mid-quarter backtest, {int(pooled['n'])} segment-quarters, average error: {figures(pooled)}"))
    for seg in BACKTEST_SEGMENTS:
        row = by_seg.get(seg) or {}
        if not _missing(row.get("mape_coverage_implied")):
            out.append(("Scope", f"{seg}: {figures(row)}"))
    if pooled.get("beats_both_naive_baselines") is True:
        out.append(("Scope", "Including open pipeline beats won to date alone and the prior four-quarter mean."))
    elif pooled.get("beats_both_naive_baselines") is False:
        out.append(("Scope", "The reading does not beat both won to date alone and the prior four-quarter mean."))
    if pooled.get("beats_constant_rate_baseline") is False:
        out.append(("Scope", "A fixed constant-rate formula (won to date plus 25% of open pipeline) scores as well or "
                             "better, so the reading's value is the coverage and gap framing, not extra accuracy."))
    elif pooled.get("beats_constant_rate_baseline") is True:
        out.append(("Scope", "The reading also beats the fixed constant-rate comparator."))
    weak_pace = [seg for seg in BACKTEST_SEGMENTS if (by_seg.get(seg) or {}).get("beats_pace_baseline") is False]
    if weak_pace:
        out.append(("Scope", f"{' and '.join(weak_pace)} does not beat the pace comparator (won to date scaled by the "
                             "share of the quarter elapsed)."))
    if missing or pooled.get("beats_constant_rate_baseline") is None:
        gaps = missing or ["constant rate"]
        out.append(("Scope", f"The comparison is incomplete: {', '.join(gaps)} not in this report."))
    hind, none_ = pooled.get("mape_hindsight_free_scoping"), pooled.get("mape_no_scoping")
    if not _missing(hind) and not _missing(none_):
        out.append(("Scope",
                    f"Scoping by created date plus the trailing median cycle (no hindsight) gives {_pct(hind)} pooled "
                    f"error against {_pct(pooled['mape_coverage_implied'])}; counting every open deal gives {_pct(none_)}."))
    return out


def _is_late_created_caveat(text: str) -> bool:
    t = str(text)
    return "Commercial" in t and ("not yet visible" in t or "cannot see pipeline" in t)


def commercial_floor_note(summary: Optional[Dict]) -> Optional[Tuple[str, str]]:
    """One Data gap line for the Commercial late-created-deal effect, from the backtest
    summary; replaces the artifact's overlapping caveats on the same point."""
    by_seg = (summary or {}).get("by_segment") or {}
    com, ent = by_seg.get("Commercial") or {}, by_seg.get("Enterprise") or {}
    bias, late = com.get("aggregate_bias_pct"), com.get("late_created_share_of_actual")
    if _missing(bias) or _missing(late):
        return None
    direction = "below" if float(bias) < 0 else "above"
    text = (f"Commercial readings run about {_pct(abs(float(bias)), 0)} {direction} actual bookings in aggregate: "
            f"{_pct(late, 0)} of Commercial bookings come from deals created after mid-quarter, so the reading is a floor.")
    ent_late = ent.get("late_created_share_of_actual")
    if not _missing(ent_late):
        text += f" The same share for Enterprise is {_pct(ent_late, 0)}."
    return ("Data gap", text)


def band_evidence_note(summary: Optional[Dict]) -> str:
    """The Scope line on how much the proposed bands rest on."""
    n_seg = (summary or {}).get("segment_quarters")
    history = f"{int(n_seg)} segment-quarters" if not _missing(n_seg) else "a small number of segment-quarters"
    return (f"The status bands rest on {history} of history, and the link between coverage and final "
            "attainment is partly mechanical because won to date sits on both sides of it; the bands stay proposed.")


LENS_TERM_NOTE = ("The forecast lenses' 'pipeline coverage' wording in a CRO override reason is the CRO's logged "
                  "reason for the override, not this reading.")


def notes_for(reading: Optional[Dict], backtest_summary: Optional[Dict] = None) -> List[Tuple[str, str]]:
    """Every coverage note for the page's single Notes & assumptions block, as
    (kind, text) pairs; artifact caveats are shown as written (the overlapping Commercial
    late-created-deal caveats become one line when the backtest summary is present)."""
    if not reading:
        return [("Scope", "Pipeline coverage is a coverage reading, not a forecast; the forecast lenses stay the "
                          "only view of what will close, and the two are shown side by side, never combined.")]
    items: List[Tuple[str, str]] = []
    rule = reading.get("status_rule") or {}
    if rule:
        items.append(("Assumption", (
            "Coverage status bands: "
            f"covered at {_x(rule.get('covered_min_coverage_vs_required'))} of required or more, thin from "
            f"{_x(rule.get('thin_min_coverage_vs_required'))}, shortfall below that, quota met when no quota "
            "is left. The bands are proposed, not confirmed.")))
    floor = commercial_floor_note(backtest_summary)
    kept_late_caveat = False
    seen = set()
    for text in list(reading.get("caveats") or []) + [c for s in reading.get("segments") or []
                                                      for c in s.get("caveats") or []]:
        if text in seen:
            continue
        seen.add(text)
        if _is_late_created_caveat(text):
            if floor or kept_late_caveat:
                continue
            kept_late_caveat = True
        items.append((classify_caveat(text), text))
    if floor:
        items.append(floor)
    items.extend(backtest_notes(backtest_summary))
    items.append(("Scope", band_evidence_note(backtest_summary)))
    items.append(("Scope", "The backtest evaluates mid-quarter readings; a reading on another date uses the same "
                           "definitions and is outside that backtest."))
    items.append(("Scope", LENS_TERM_NOTE))
    window = (reading.get("data_window") or {}).get("note")
    if window:
        items.append(("Scope", window))
    return [(kind, keep_dates_whole(text)) for kind, text in items]


ERROR_NOTICE = ("Pipeline coverage is not available for this call date. The forecast lenses above are "
                "unaffected.")
