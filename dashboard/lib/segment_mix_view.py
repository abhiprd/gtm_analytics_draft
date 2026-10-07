"""Presentation rules for the weekly readout's `segment_mix` section, Streamlit-free so
they are unit-testable (tests/test_dashboard_segment_mix_view.py).

The section comes from analytics/segment_migration.py's compute_segment_mix(), carried
verbatim in the readout JSON with its own display strings. Nothing here recomputes a share,
a velocity or a change: values are formatted for display only, and a display string the
readout supplies is used as written.

States:
  present      headline, the stacked-share rows (this month, same month a year earlier),
               the card dicts (upmarket share and one per migration pair) and the notes
  unavailable  a plain-language reason from the section's own `detail`, no figures
  absent       the readout carries no segment_mix key (an older readout): one plain line

The cards are neutral gray throughout: a rising upmarket share or migration rate has no
plan or favorable direction in the metric tree, so no Palette B judgment applies. The
sign of a change in a rate is shown with "pp"; a change that rounds to zero carries no
sign. The section is not a metric-tree node, so its cards carry no Layer label.
"""
from typing import Dict, List, Optional

from . import verdict

SEGMENTS = ("SMB", "Commercial", "Enterprise")

KIND_PRESENT = "present"
KIND_UNAVAILABLE = "unavailable"
KIND_ABSENT = "absent"

NO_COMPARISON = "No year-earlier comparison"

# Reader-facing text for the section's unavailable reason codes. The section's own
# `detail` is preferred; this is the fallback when it is missing.
UNAVAILABLE_FALLBACK = {
    "evaluation_month_is_truncated_final_month": (
        "The reporting month is the final month of the data window, which is truncated. "
        "The prior month is the last representative month."),
    "no_segment_data_for_evaluation_month": "The marts have no segment rows for this month.",
}


def _missing(v) -> bool:
    return verdict.missing(v)


def _is_na(text) -> bool:
    return text is None or str(text).strip().lower() in ("", "n/a", "nan", "none")


def format_pp(change, display: Optional[str] = None) -> Optional[str]:
    """A change in a share or rate, in percentage points ('+2.0 pp'). The readout's own
    display string wins; a value-only call formats with one decimal. A change that rounds
    to zero is unsigned ('0.0 pp'). None when there is no change to show."""
    if not _is_na(display):
        text = str(display).strip()
        if "pp" not in text:
            text = f"{text} pp"
        return verdict.unsigned_if_zero(text)
    if _missing(change):
        return None
    return verdict.unsigned_if_zero(verdict.pp_text(float(change)))


def format_share(value, display: Optional[str] = None) -> Optional[str]:
    """A share or rate as a percentage ('83.5%'); the readout's display string wins."""
    if not _is_na(display):
        return str(display).strip()
    if _missing(value):
        return None
    return f"{float(value) * 100:.1f}%"


def month_label(iso: Optional[str]) -> str:
    return str(iso or "")[:7]


def basis_month(mix: Dict) -> str:
    m = month_label(mix.get("evaluation_month"))
    return f"Month of {m}" if m else "Monthly"


def basis_trailing(mix: Dict) -> str:
    m = month_label((mix.get("window") or {}).get("trailing_window_last_month") or mix.get("evaluation_month"))
    return f"Trailing 12 months to {m}" if m else "Trailing 12 months"


def year_ago_label(mix: Dict) -> str:
    return month_label((mix.get("window") or {}).get("year_ago_month"))


def share_labels(shares: Dict[str, float], decimals: int = 1) -> Dict[str, str]:
    """Display labels for one 100%-stacked bar whose parts sum to 100.0%: largest-remainder
    rounding, so rounding each part alone (12.1 + 19.1 + 68.7 = 99.9) never shows a bar that
    does not add up. The parts keep their order; a part's label differs from independent
    rounding by at most one unit in the last place. Shares that do not sum to 1 (a partial
    composition) are rounded independently."""
    scale = 10 ** decimals
    exact = {k: float(v) * 100 * scale for k, v in shares.items()}
    total = sum(exact.values())
    out_units = {k: int(v // 1) for k, v in exact.items()}
    if abs(total - 100 * scale) < 0.5:
        shortfall = 100 * scale - sum(out_units.values())
        by_remainder = sorted(exact, key=lambda k: (exact[k] - out_units[k], k), reverse=True)
        for k in by_remainder[:max(0, shortfall)]:
            out_units[k] += 1
    else:
        out_units = {k: int(round(v)) for k, v in exact.items()}
    return {k: f"{u / scale:.{decimals}f}%" for k, u in out_units.items()}


def stacked_rows(mix: Dict) -> List[Dict]:
    """Rows for the 100%-stacked share bar, earliest first: the same month a year earlier
    (when every segment carries a share for it) then the reporting month. Each row is
    {label, shares: {segment: fraction}, labels: {segment: '12.1%'} (summing to 100.0%),
    mrr: {segment: display or None}}."""
    segs = {s["segment"]: s for s in mix.get("segments") or []}
    rows: List[Dict] = []
    if all(s in segs and not _missing(segs[s].get("mrr_share_12m_ago")) for s in SEGMENTS):
        shares = {s: float(segs[s]["mrr_share_12m_ago"]) for s in SEGMENTS}
        rows.append({"label": year_ago_label(mix) or "12 months earlier",
                     "shares": shares, "labels": share_labels(shares),
                     "mrr": {s: None for s in SEGMENTS}})
    if all(s in segs and not _missing(segs[s].get("mrr_share")) for s in SEGMENTS):
        shares = {s: float(segs[s]["mrr_share"]) for s in SEGMENTS}
        rows.append({"label": month_label(mix.get("evaluation_month")) or "Reporting month",
                     "shares": shares, "labels": share_labels(shares),
                     "mrr": {s: segs[s].get("ending_mrr_display") for s in SEGMENTS}})
    return rows


def segment_change_line(mix: Dict) -> Optional[str]:
    """'Change against 12 months earlier: SMB -5.2 pp · Commercial +1.0 pp · ...'; segments
    without a comparison are omitted, and None when none has one."""
    parts = []
    for s in mix.get("segments") or []:
        shown = format_pp(s.get("share_change_vs_12m_ago"), s.get("share_change_vs_12m_ago_display"))
        if shown:
            parts.append(f"{s['segment']} {shown}")
    return ("Change in share against 12 months earlier: " + " · ".join(parts)) if parts else None


def upmarket_card(mix: Dict) -> Optional[Dict]:
    up = mix.get("upmarket_share")
    if not up:
        return None
    value = format_share(up.get("mrr_share"), up.get("mrr_share_display"))
    if value is None:
        return None
    segs = " + ".join(up.get("segments") or ["Commercial", "Enterprise"])
    change = format_pp(up.get("change_vs_12m_ago"), up.get("change_vs_12m_ago_display"))
    year_ago = format_share(up.get("mrr_share_12m_ago"))
    prior = format_pp(up.get("change_vs_prior_month"), up.get("change_vs_prior_month_display"))
    card = dict(label="Upmarket share of MRR", value_display=value, dot_color=None)
    if change:
        card["variance_display"] = change
        card["comparison_display"] = f"vs {year_ago} a year earlier" if year_ago else "vs a year earlier"
    else:
        card["comparison_display"] = NO_COMPARISON
    footer = [f"{segs} share of company ending MRR"]
    if prior:
        footer.append(f"{prior} against the prior month")
    graduated = format_share(up.get("smb_to_commercial_graduated_share_of_total_mrr_trailing_12m"))
    if graduated:
        footer.append(f"SMB to Commercial graduations, trailing 12 months: {graduated} of company ending MRR")
    footer.append(f"Basis: {basis_month(mix)}")
    card["footer"] = footer
    return card


def migration_card(mix: Dict, pair: Dict) -> Dict:
    """One segment pair: trailing-12-month migration velocity against the year before,
    with graduated MRR as a share of the source segment's MRR in the footer."""
    source = pair.get("from_segment") or "source segment"
    label = pair.get("pair_label") or f"{source} migration"
    velocity = format_share(pair.get("velocity_trailing_12m"), pair.get("velocity_trailing_12m_display"))
    card: Dict = dict(label=label, dot_color=None)
    if velocity is None:
        card["value_display"] = "Not computable"
        card["value_size"] = "sm"
        card["footer"] = [f"No {source} accounts in the window to measure migration against",
                          f"Basis: {basis_trailing(mix)}"]
        return card
    card["value_display"] = velocity
    change = format_pp(pair.get("velocity_change_vs_year_ago"), pair.get("velocity_change_vs_year_ago_display"))
    year_ago = format_share(pair.get("velocity_trailing_12m_year_ago"), pair.get("velocity_trailing_12m_year_ago_display"))
    if change and year_ago:
        card["variance_display"] = change
        card["comparison_display"] = f"vs {year_ago} a year earlier"
    else:
        card["comparison_display"] = NO_COMPARISON
    footer = ["Migration rate: migrating accounts per source-segment account"]
    share = format_share(pair.get("graduated_share_of_source_mrr_trailing_12m"),
                         pair.get("graduated_share_of_source_mrr_trailing_12m_display"))
    amount = pair.get("graduated_mrr_trailing_12m_display")
    if share:
        # A 12-month flow set against the average base over the window, not a share of the
        # segment's current MRR: it can exceed the current base (conventions 4.10).
        detail = "flow, not share of current MRR" if _is_na(amount) else f"{amount}; flow, not share of current MRR"
        footer.append(f"Graduated MRR: {share} of average {source} MRR over the window ({detail})")
    footer.append(f"Basis: {basis_trailing(mix)}")
    card["footer"] = footer
    return card


def mrr_vs_account_lines(mix: Dict) -> List[str]:
    """One visible line per migration pair on why the graduated-MRR share is larger than the
    account migration rate: the accounts that migrate carry several times the MRR of the
    average account in their segment (the readout's migrating_account_mrr_multiple_trailing_12m).
    A pair without the multiple or without both rates gets no line."""
    out = []
    for pair in mix.get("migration") or []:
        mult = pair.get("migrating_account_mrr_multiple_trailing_12m")
        share = format_share(pair.get("graduated_share_of_source_mrr_trailing_12m"),
                             pair.get("graduated_share_of_source_mrr_trailing_12m_display"))
        velocity = format_share(pair.get("velocity_trailing_12m"), pair.get("velocity_trailing_12m_display"))
        if _missing(mult) or not share or not velocity:
            continue
        source = pair.get("from_segment") or "source segment"
        label = pair.get("pair_label") or f"{source} migration"
        ending = format_share(pair.get("graduated_share_of_source_ending_mrr_trailing_12m"))
        tail = f" and {ending} of ending {source} MRR" if ending else ""
        out.append(
            f"{label}: migrating accounts carry about {float(mult):.1f}x the MRR of the average {source} "
            f"account, so graduated MRR ({share} of average {source} MRR over the window{tail}) "
            f"exceeds the account migration rate ({velocity}).")
    return out


def cards(mix: Dict) -> List[Dict]:
    out = []
    up = upmarket_card(mix)
    if up:
        out.append(up)
    out.extend(migration_card(mix, p) for p in mix.get("migration") or [])
    return out


def notes(mix: Dict) -> List[tuple]:
    """(kind, text) lines for the page's Notes & assumptions: the section's definition
    line and each of its own caveats, one line each."""
    out: List[tuple] = []
    if mix.get("note"):
        out.append(("Scope", str(mix["note"])))
    for caveat in mix.get("caveats") or []:
        out.append(("Scope", str(caveat)))
    rec = mix.get("reconciliation") or {}
    if rec and rec.get("reconciles") is False:
        out.append(("Data gap", "Graduated MRR does not reconcile to the growth bridge within tolerance."))
    return out


def unavailable_text(mix: Dict) -> str:
    """The reader-facing reason an unavailable section is blank."""
    detail = mix.get("detail")
    if detail:
        return str(detail)
    return UNAVAILABLE_FALLBACK.get(mix.get("reason"), "The segment mix could not be produced for this readout.")


def state(mix: Optional[Dict]) -> Dict:
    """Everything the page needs, in one dict. `kind` is present, unavailable or absent."""
    if not mix or "status" not in mix:
        return {"kind": KIND_ABSENT}
    if mix.get("status") == "present":
        rows = stacked_rows(mix)
        built = cards(mix)
        if not rows and not built:
            # A 'present' section that carries no usable figures is shown as unavailable
            # rather than as an empty card block.
            return {"kind": KIND_UNAVAILABLE, "reason_text": "The section carries no figures for this month.",
                    "notes": notes(mix), "evaluation_month": month_label(mix.get("evaluation_month"))}
        return {
            "kind": KIND_PRESENT,
            "headline": mix.get("headline"),
            "month": month_label(mix.get("evaluation_month")),
            "total_ending_mrr": mix.get("total_ending_mrr_display"),
            "rows": rows,
            "change_line": segment_change_line(mix),
            "cards": built,
            "mrr_vs_account_lines": mrr_vs_account_lines(mix),
            "basis_line": f"Basis: share of company ending MRR, {basis_month(mix).lower()}"
                          + (f" against {year_ago_label(mix)}" if len(rows) == 2 else ""),
            "notes": notes(mix),
        }
    return {
        "kind": KIND_UNAVAILABLE,
        "reason_text": unavailable_text(mix),
        "evaluation_month": month_label(mix.get("evaluation_month")),
        "notes": notes(mix),
    }
