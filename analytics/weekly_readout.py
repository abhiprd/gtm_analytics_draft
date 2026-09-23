"""Weekly executive readout -- grain: one readout per evaluation period
(the last complete month at or before as_of_date, company-wide/blended);
sources: analytics/variance_diagnostic.py's run_diagnostic() output only
(which itself reads mart_gtm_plan, mart_growth_bridge, mart_efficiency,
mart_durability, mart_account_health) plus, through that engine's
watchlist, analytics/health_score.py's scored output.

WHAT THIS IS
------------
The Wave-1 forcing function (build spec Section 8): the artifact that
proves the metric tree, the account health score, the segment-migration
analysis and the variance-diagnostic engine work end to end against real
generated data, by assembling their outputs into one document with the
structure build spec Section 5 specifies -- header, executive summary,
Layer-1 scorecard, drill-downs, playbook triggers, forecast, watchlist.

WHAT THIS IS NOT: IT COMPUTES NOTHING
--------------------------------------
This module performs no business computation whatsoever. There is no
arithmetic on a metric value anywhere below: every number it renders is
read verbatim from run_diagnostic()'s already-validated output, and
verify_source_trace() re-checks that claim field by field against a
freshly-run diagnostic. Formatting a float into "$45.2K" is presentation;
deriving a new figure is not done, and a future contributor adding one
would be moving that computation out of the artifact that owns it and
away from that artifact's own validation.

Three consequences follow, all deliberate:
  * The engine's caveats travel with the numbers rather than being
    quietly smoothed over -- magic_number and am_efficiency report "Not
    computable" (no rep-cost source exists), Activation reports the same
    (blended TTFA is identically 0 at this data's monthly grain), and the
    three plan-comparability caveats (consumption payback, NRR, GRR)
    are reproduced next to the metrics they qualify.
  * The Layer-1 scorecard carries all eleven nodes every period,
    unconditionally, including those three -- the build spec asks for the
    scorecard "every week... value, vs. plan, status", and a gap reported
    is worth more than a gap hidden.
  * The drill-down section is genuinely variable-length: exactly as many
    entries as there are Layer-1 nodes whose variance breached the
    engine's threshold, which can be zero. It is never padded to a fixed
    count and never truncated.

SCOPE -- THREE SECTIONS ARE DELIBERATELY NOT BUILT HERE
--------------------------------------------------------
Each is a separate, named piece of work. Each gets an explicit
"not_yet_built"/"deferred" placeholder in the assembled structure and in
the rendered document, rather than being silently omitted (which would
make the readout look complete when it is not) or filled with invented
content (which would make it dishonest).

  1. EXECUTIVE SUMMARY NARRATIVE -- deferred, built separately. Build
     spec Section 5 calls for a narrative that names a specific
     Layer-2/Layer-3 cause for any real miss, generated via the Claude
     API (Section 3's stack list). No LLM call is made from this module,
     and no template-based prose generator stands in for one -- a
     canned-sentence generator would read as narrative while carrying
     none of the causal reasoning the section exists for. What is built
     instead is the seam: assemble_readout() returns the fully-assembled
     structured readout, which is exactly the input a narrative step
     consumes.
  2. AUTOMATED PLAYBOOK TRIGGERS -- Wave 4, unbuilt. The same resolved
     scope decision analytics/variance_diagnostic.py records: build spec
     Section 8 places "Automated playbook triggers" in Wave 4 with the
     stated dependency "needs Wave 1's thresholds validated against real
     data first". Nothing here reads or writes fact_playbook_triggers,
     which does not exist.
  3. FORECAST -- Wave 2, unbuilt. Build spec Section 8 places the
     forecast (sales bottoms-up + ML/regression + CRO overlay) in Wave 2,
     after this wave. Its methods-doc entry is still TBD.

DETERMINISM
-----------
No stochastic step exists in this module -- no sampling, no simulation,
no train/test split -- so no random seed applies, matching
analytics/segment_migration.py's and analytics/variance_diagnostic.py's
precedent. The one indirect exception is inherited: the watchlist section
renders analytics/health_score.py's scored output, and that model is
seeded inside health_score.py via its own _RANDOM_SEED = 42. This module
neither fits nor re-fits it.
"""
import json
import os
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from . import variance_diagnostic as vd
from .model_performance import log_performance

_MODEL_NAME = "weekly_executive_readout"

# Build spec Section 5: "Header: reporting period, audience."
_AUDIENCE = "Chief Revenue Officer - GTM leadership team"

# Where the rendered deliverable lands. Version-controlled (unlike
# data/acme_gtm.duckdb, which is gitignored and rebuilt), so a reader can
# inspect the real-data readout without running the pipeline.
_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")

# =====================================================================
# Reporting-period grain -- a resolved decision, stated rather than
# assumed
# =====================================================================
#
# The design brief's hand-illustrated sample readout is weekly ("August
# 24 - August 30, 2026"). Every actuals mart in this project is segment x
# month, and variance_diagnostic._evaluation_month() evaluates the last
# COMPLETE month at or before as_of_date, because diffing a partial
# period's actual against a whole period's plan is a unit mismatch in
# disguise. A weekly readout over monthly marts would either re-window
# the marts here (a computation this artifact explicitly does not do) or
# repeat the same monthly figure four times with a weekly label on it.
# The reporting period is therefore the evaluation month itself, and the
# document says so in its header rather than borrowing the sample's
# weekly framing.
_PERIOD_GRAIN = "month"

# Vocabulary for a section that exists in the build spec's required
# structure but whose underlying artifact has not been built yet. Kept as
# named constants so a consumer can branch on the status string rather
# than pattern-match prose.
STATUS_NOT_YET_BUILT = "not_yet_built"
STATUS_DEFERRED = "deferred"
STATUS_PRESENT = "present"

_NARRATIVE_PLACEHOLDER = "> _Executive summary narrative: not yet generated._"


# =====================================================================
# Presentation helpers -- formatting only, never arithmetic on a metric
# =====================================================================
#
# Every function below turns a value that run_diagnostic() already
# produced into a string. None of them combines, rescales, inverts or
# otherwise derives a figure: onboarding/CS efficiency, for instance, is
# rendered as touches-per-Action (the metric tree's own orientation,
# "Manual AM/CS touchpoints / volume of automated Actions delivered")
# rather than inverted to the Actions-per-touch the illustrative sample
# readout happened to show, because inverting it here would be this
# module computing a number the mart never published.

_UNITS = {
    "new_logo_consumption_revenue": "usd",
    "activation": "months",
    "expansion_consumption_revenue": "usd",
    "contraction_churned_revenue": "usd",
    "magic_number": "multiple",
    "consumption_payback": "months",
    "onboarding_cs_efficiency": "touches_per_action",
    "am_efficiency": "multiple",
    "nrr": "rate",
    "grr": "rate",
    "logo_retention": "rate",
}

_UNIT_LABELS = {
    "usd": "USD, monthly MRR movement",
    "months": "months",
    "multiple": "multiple (x)",
    "touches_per_action": "AM/CS touchpoints per automated Action",
    "rate": "rate (trailing-12-month compounded)",
}


def _fmt_usd(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:,.2f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:,.1f}K"
    return f"${v:,.0f}"


def _fmt_value(metric_key: str, v: Optional[float]) -> str:
    """Display string for a Layer-1 value. Presentation only."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    unit = _UNITS.get(metric_key)
    if unit == "usd":
        return _fmt_usd(v)
    if unit == "months":
        return f"{v:,.2f} mo"
    if unit == "multiple":
        return f"{v:,.2f}x"
    if unit == "touches_per_action":
        return f"{v:.2e} touches/Action"
    if unit == "rate":
        return f"{v:.1%}"
    return f"{v:,.4g}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    return f"{v:+.1%}"


def _fmt_generic(v: Optional[float]) -> str:
    """Layer-2/Layer-3 values carry heterogeneous units (a rate, a dollar
    figure, a count), and the tree does not declare a unit per node, so
    they are rendered in a single neutral numeric format rather than
    given a unit this module would have to guess at."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    return f"{v:,.4g}"


def _none_if_nan(v: Any) -> Any:
    """NaN -> None so the structured readout is JSON-clean. Not a value
    change: NaN and None both mean 'the engine produced no figure here'."""
    if v is None:
        return None
    if isinstance(v, (float, np.floating)) and np.isnan(v):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    return v


def _comparison_display(row: dict) -> str:
    """The 'vs. plan' cell, in the sample readout's own shape: a plan
    figure where a plan exists ('$210K plan'), the prior period's value
    where the mechanism is a trailing baseline ('2.4d last month'), and a
    plain statement of the gap where neither applies."""
    mechanism = row["mechanism"]
    key = row["metric_key"]
    if mechanism == "plan_diff":
        return f"{_fmt_value(key, row['plan'])} plan" if row["plan"] is not None else "no plan row"
    if mechanism == "trailing_baseline":
        if row["prior_month_value"] is not None:
            return f"{_fmt_value(key, row['prior_month_value'])} last month"
        return "no trailing baseline"
    # not_computable -- the plan figure still exists and is still worth
    # showing; what is missing is the actual.
    if row["plan"] is not None:
        return f"{_fmt_value(key, row['plan'])} plan (no computable actual)"
    return "not computable"


# =====================================================================
# Assembly -- the narrative seam
# =====================================================================

def assemble_readout(as_of_date: date,
                     threshold: float = vd._VARIANCE_THRESHOLD,
                     watchlist_top_n: int = 25,
                     diagnostic: Optional[dict] = None) -> Dict[str, Any]:
    """The whole weekly readout as one structured, JSON-serialisable
    dict. Grain: one readout per evaluation period (the last complete
    month at or before as_of_date). Source: analytics/variance_diagnostic
    .py's run_diagnostic() output, which is this module's only data
    input.

    THIS FUNCTION'S OUTPUT IS THE NARRATIVE-GENERATION SEAM, AND
    GENERATING THAT NARRATIVE IS A SEPARATE, DELIBERATELY DEFERRED PIECE
    OF WORK. Build spec Section 5 specifies an executive summary that
    names a specific Layer-2/Layer-3 cause for any real miss, produced
    via the Claude API. That step is not built here and is not simulated
    here: no LLM is called, and no template-based prose generator stands
    in for one. What this returns is precisely the input such a step
    consumes -- the eleven-node scorecard with each node's variance,
    mechanism and comparability caveat; every drill-down with its Layer-2
    outlier, that outlier's deviation from its own trailing baseline, any
    Layer-3 evidence, and the notes explaining what could not be seen;
    and the watchlist with its ARR-at-risk estimate and stated
    limitations. A narrative step should read this structure and cite it;
    it should not re-query the marts, because then the prose and the
    tables could disagree.

    The returned dict's top-level keys follow build spec Section 5's
    required structure exactly -- header, executive_summary,
    layer1_scorecard, drilldowns, playbook_triggers, forecast, watchlist
    -- so a section that is not built yet is visibly present with an
    honest status rather than missing.

    Computes nothing. Every figure is read verbatim from `diagnostic`;
    verify_source_trace() re-checks that field by field.
    """
    result = diagnostic if diagnostic is not None else vd.run_diagnostic(
        as_of_date, threshold=threshold, watchlist_top_n=watchlist_top_n)

    month = result["evaluation_month"]
    scorecard = result["layer1_scorecard"]

    readout = {
        "artifact": "weekly_executive_readout",
        "header": _header(as_of_date, month, result),
        "executive_summary": _executive_summary_placeholder(),
        "layer1_scorecard": _scorecard_section(scorecard),
        "drilldowns": _drilldown_section(result["drilldowns"], scorecard),
        "playbook_triggers": _playbook_triggers_placeholder(),
        "forecast": _forecast_placeholder(),
        "watchlist": _watchlist_section(result["watchlist"], month),
        "data_window": {k: _none_if_nan(v) for k, v in result["data_window"].items()},
        "source_coverage": [{k: _none_if_nan(v) for k, v in r.items()}
                            for r in result["coverage"].to_dict(orient="records")],
        "provenance": _provenance(as_of_date, result),
    }
    return readout


def _header(as_of_date: date, month: pd.Timestamp, result: dict) -> Dict[str, Any]:
    period_end = month.to_period("M").to_timestamp("M")
    return {
        "reporting_period_start": month.date().isoformat(),
        "reporting_period_end": period_end.date().isoformat(),
        "reporting_period_label": f"{month:%B %-d} - {period_end:%B %-d, %Y}",
        "reporting_period_grain": _PERIOD_GRAIN,
        "reporting_period_grain_note": (
            "Monthly, not weekly. Every actuals mart in this project is segment x month "
            "and the variance-diagnostic engine evaluates the last complete month at or "
            "before as_of_date; a weekly period would either re-window the marts inside "
            "this artifact (a computation it does not do) or repeat one monthly figure "
            "under four weekly labels."),
        "as_of_date": as_of_date.isoformat(),
        "evaluation_month": month.date().isoformat(),
        "audience": _AUDIENCE,
        "variance_threshold": result["threshold"],
        "trailing_baseline_months": result["baseline_months"],
    }


def _executive_summary_placeholder() -> Dict[str, Any]:
    return {
        "status": STATUS_DEFERRED,
        "placeholder_marker": _NARRATIVE_PLACEHOLDER,
        "note": (
            "Narrative generation is a separate, deliberately deferred piece of work. "
            "Build spec Section 5 specifies an executive summary that names a specific "
            "Layer-2/Layer-3 cause for any real miss, generated via the Claude API "
            "(Section 3's stack). No LLM is called from analytics/weekly_readout.py and "
            "no template-based prose generator substitutes for one -- canned sentences "
            "would read as narrative while carrying none of the causal reasoning the "
            "section exists for. assemble_readout()'s full return value is the structured "
            "input that step is designed to consume."),
        "consumes": ["layer1_scorecard", "drilldowns", "watchlist", "data_window",
                     "source_coverage"],
    }


def _playbook_triggers_placeholder() -> Dict[str, Any]:
    return {
        "status": STATUS_NOT_YET_BUILT,
        "triggers": [],
        "note": (
            "Automated playbook triggers is a Wave 4 artifact, not yet built. Build spec "
            "Section 8 places it in Wave 4 with the stated dependency 'needs Wave 1's "
            "thresholds validated against real data first', which is only coherent if the "
            "triggers are built after this wave's thresholds exist and have been "
            "validated -- the same resolved scope decision recorded in "
            "analytics/variance_diagnostic.py and in the methods doc. The source table it "
            "will log to, fact_playbook_triggers, does not exist yet either. The section "
            "is carried here with this status so the readout's structure stays "
            "forward-compatible; no trigger is invented to fill it."),
    }


def _forecast_placeholder() -> Dict[str, Any]:
    return {
        "status": STATUS_NOT_YET_BUILT,
        "note": (
            "Forecast (sales bottoms-up + ML/regression + CRO overlay) is a Wave 2 "
            "artifact, not yet built -- build spec Section 8 places it in the wave after "
            "this one, and its entry in docs/acme-corp-analytics-methods.md is still TBD. "
            "The section is carried here with this status so the readout's structure stays "
            "forward-compatible; no forecast number is fabricated to fill it."),
    }


def _scorecard_section(scorecard: pd.DataFrame) -> Dict[str, Any]:
    """All eleven Layer-1 nodes, unconditionally, grouped into the design
    brief's three pillar tables. Every field is read from the engine's
    scorecard frame; `layer` in particular is read, never assigned here,
    so a Layer-2 node cannot appear in a Layer-1 table."""
    rows = []
    for rec in scorecard.to_dict(orient="records"):
        node = vd.get_node(rec["metric_key"])
        row = {k: _none_if_nan(v) for k, v in rec.items()}
        row["unit"] = _UNITS.get(rec["metric_key"])
        row["unit_label"] = _UNIT_LABELS.get(_UNITS.get(rec["metric_key"]))
        row["value_display"] = _fmt_value(rec["metric_key"], row["actual"])
        row["comparison_display"] = _comparison_display(row)
        row["variance_display"] = _fmt_pct(row["variance_pct"])
        row["gap_note"] = node.gap_note
        rows.append(row)

    by_pillar = {p: [r for r in rows if r["pillar"] == p] for p in vd.PILLARS}
    return {
        "status": STATUS_PRESENT,
        "nodes_total": len(rows),
        "nodes_breaching_threshold": sum(1 for r in rows if r["breaches_threshold"]),
        "nodes_not_computable": sum(1 for r in rows if r["mechanism"] == "not_computable"),
        "rows": rows,
        "by_pillar": by_pillar,
        "note": (
            "All eleven Layer-1 nodes are shown every period, unconditionally, per build "
            "spec Section 5 -- including the nodes whose actual is not computable from any "
            "mart. A reported gap is more useful than a hidden one."),
    }


def _drilldown_section(drilldowns: List[vd.Drilldown], scorecard: pd.DataFrame) -> Dict[str, Any]:
    """Variable length by construction: one entry per Layer-1 node whose
    variance breached the engine's threshold, in scorecard order. Zero is
    a valid and meaningful result; the count is never padded."""
    sc_by_key = {r["metric_key"]: r for r in scorecard.to_dict(orient="records")}
    entries = []
    for dd in drilldowns:
        d = dd.to_dict()
        sc = {k: _none_if_nan(v) for k, v in sc_by_key[dd.layer1_key].items()}
        d["layer1"]["value"] = sc["actual"]
        d["layer1"]["value_display"] = _fmt_value(dd.layer1_key, sc["actual"])
        d["layer1"]["comparison_display"] = _comparison_display(sc)
        d["layer1"]["variance_display"] = _fmt_pct(sc["variance_pct"])
        d["layer1"]["status"] = sc["status"]
        d["sibling_ranking"] = _ranking_records(dd.sibling_ranking)
        d["layer3_ranking"] = _ranking_records(dd.layer3_evidence)
        if d["layer2_outlier"] is not None:
            top = next((r for r in d["sibling_ranking"]
                        if r["metric_key"] == d["layer2_outlier"]["metric_key"]), None)
            d["layer2_outlier"]["value"] = top["value"] if top else None
            d["layer2_outlier"]["baseline"] = top["baseline"] if top else None
            d["layer2_outlier"]["deviation_pct"] = top["deviation_pct"] if top else None
            d["layer2_outlier"]["comparison_basis"] = top["comparison_basis"] if top else None
        entries.append(d)
    return {
        "status": STATUS_PRESENT,
        "count": len(entries),
        "entries": entries,
        "note": (
            "Variable length: one drill-down per Layer-1 node that actually breached the "
            "variance threshold this period, and none for any node that did not. Never "
            "padded to a fixed count, never truncated. The Layer-2 outlier in each entry "
            "is the engine's own ranking of that node's TRUE siblings against their own "
            "trailing baselines, and Layer-3 evidence appears only where the branch "
            "genuinely has a Layer 3 that a mart can compute."),
    }


def _ranking_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    out = []
    for rec in df.to_dict(orient="records"):
        row = {k: _none_if_nan(v) for k, v in rec.items()}
        row["value_display"] = _fmt_generic(row.get("value"))
        row["baseline_display"] = _fmt_generic(row.get("baseline"))
        row["deviation_display"] = _fmt_pct(row.get("deviation_pct"))
        out.append(row)
    return out


def _watchlist_section(watchlist: pd.DataFrame, month: pd.Timestamp) -> Dict[str, Any]:
    """The engine's own watchlist, rendered as-is. No second risk model
    is built, fitted or re-ranked here."""
    rows = []
    for i, rec in enumerate(watchlist.to_dict(orient="records"), start=1):
        row = {k: _none_if_nan(v) for k, v in rec.items()}
        row["rank"] = i
        row["est_arr_at_risk_display"] = _fmt_usd(row["est_arr_at_risk_usd"]) \
            if row.get("est_arr_at_risk_usd") is not None else "n/a"
        rows.append(row)
    return {
        "status": STATUS_PRESENT,
        "count": len(rows),
        "rows": rows,
        "selection_rule": (
            "Accounts whose composite health score breaches the risk threshold "
            "(risk_tier == 'High'), ranked by estimated ARR at risk, then by churn "
            "probability -- analytics/variance_diagnostic.py's build_watchlist(), which "
            "consumes analytics/health_score.py's scored output directly."),
        "caveats": [
            "est_arr_at_risk_usd is the account's SEGMENT-AVERAGE ARR for the evaluation "
            "month (mart_durability starting_mrr / starting_accounts x 12), not its own "
            "contracted ARR -- no mart_* table exposes ARR at account grain. It orders the "
            "watchlist correctly across segments and by risk within a segment, but it is "
            "an estimate and is named as one.",
            "risk_tier is quantile-based over the scored active population, so the "
            "watchlist's segment mix follows the tier definition rather than an "
            "ARR-ranking judgement.",
            "churn_probability is a ranking signal, not a calibrated probability: "
            "class_weight='balanced' shifts the health model's predicted probabilities up "
            "systematically (see the health score's calibration note in "
            "docs/acme-corp-analytics-methods.md). It must not be read as a literal "
            "likelihood of churn.",
        ],
        "evaluation_month": month.date().isoformat(),
    }


def _provenance(as_of_date: date, result: dict) -> Dict[str, Any]:
    """Which artifact every section came from, and what this one did to
    it (nothing, by design). Published with the readout so a reader can
    check any figure against the artifact that owns it."""
    return {
        "assembled_by": "analytics/weekly_readout.py",
        "computation_performed_here": "none",
        "sources": [
            {"section": "layer1_scorecard",
             "artifact": "analytics/variance_diagnostic.py",
             "entry_point": "run_diagnostic()['layer1_scorecard']"},
            {"section": "drilldowns",
             "artifact": "analytics/variance_diagnostic.py",
             "entry_point": "run_diagnostic()['drilldowns']"},
            {"section": "watchlist",
             "artifact": "analytics/variance_diagnostic.py -> analytics/health_score.py",
             "entry_point": "run_diagnostic()['watchlist'] (build_watchlist -> score_accounts)"},
            {"section": "source_coverage",
             "artifact": "analytics/variance_diagnostic.py",
             "entry_point": "run_diagnostic()['coverage']"},
            {"section": "data_window",
             "artifact": "analytics/variance_diagnostic.py",
             "entry_point": "run_diagnostic()['data_window']"},
        ],
        "metric_definitions": "docs/acme-corp-gtm-metric-tree.md (via variance_diagnostic._TREE)",
        "as_of_date": as_of_date.isoformat(),
        "variance_threshold": result["threshold"],
        "variance_threshold_status": (
            "+/-8%, proposed and not yet confirmed -- build spec Section 7 lists the "
            "drill-down threshold as an open question. This readout consumes the engine's "
            "threshold; it does not set or override one."),
        "segment_migration_analysis": (
            "analytics/segment_migration.py is Wave 1's third artifact and is not a source "
            "for any section of this readout. Its outputs (migration velocity, "
            "trigger-reason mix, graduated revenue) are population-level descriptive "
            "series that the build spec's readout structure has no section for -- "
            "graduated revenue is deliberately excluded from the source segment's "
            "churn/contraction, so it does not belong in the Growth scorecard rows either. "
            "Stated here rather than left as a silent omission."),
    }


# =====================================================================
# Rendering -- the shareable deliverable
# =====================================================================

def render_markdown(readout: Dict[str, Any]) -> str:
    """The assembled readout as a Markdown document, in the shape of the
    design brief's sample readout: header, three pillar scorecard tables,
    then a variable-length drill-down section. Presentation only -- it
    renders assemble_readout()'s dict and adds no figure of its own.

    No prose narrative is generated. Where the sample readout's executive
    summary paragraph sits, this emits an explicit placeholder marker,
    because an empty gap would read as an oversight and invented text
    would read as a finding."""
    h = readout["header"]
    out: List[str] = []
    a = out.append

    a("# Acme Corp - Weekly executive readout")
    a("")
    a(f"**Reporting period:** {h['reporting_period_label']} "
      f"({h['reporting_period_grain']}ly grain)")
    a(f"**Audience:** {h['audience']}")
    a(f"**As of:** {h['as_of_date']}  ")
    a(f"**Drill-down threshold:** +/-{h['variance_threshold']:.0%} variance "
      f"(proposed, not yet confirmed)")
    a("")
    a(f"_{h['reporting_period_grain_note']}_")
    a("")

    dw = readout["data_window"]
    if dw.get("truncation_warning"):
        a(f"> **Data-window warning.** {dw['truncation_warning']}")
        a("")

    # ---- Executive summary: placeholder, never generated prose --------
    a("## Executive summary")
    a("")
    a(readout["executive_summary"]["placeholder_marker"])
    a(">")
    a(f"> {readout['executive_summary']['note']}")
    a("")

    # ---- Layer-1 scorecard: all 11 nodes, three pillar tables ---------
    a(f"## Layer 1 scorecard - all {readout['layer1_scorecard']['nodes_total']} nodes")
    a("")
    a(f"_{readout['layer1_scorecard']['note']}_")
    a("")
    pillar_titles = {"growth": "Growth", "efficiency": "Efficiency", "durability": "Durability"}
    for pillar, title in pillar_titles.items():
        rows = readout["layer1_scorecard"]["by_pillar"].get(pillar, [])
        a(f"### Layer 1 - {title}")
        a("")
        a("| Metric | Value | vs. plan | Variance | Status |")
        a("|---|---|---|---|---|")
        for r in rows:
            a(f"| {r['label']} | {r['value_display']} | {r['comparison_display']} "
              f"| {r['variance_display']} | {r['status']} |")
        a("")
    a("Dollar figures are monthly MRR movements (`mart_growth_bridge`); NRR, GRR and logo "
      "retention are trailing-12-month compounded rates (`mart_durability`), which is the "
      "unit `mart_gtm_plan` states them in.")
    a("")

    caveated = [r for r in readout["layer1_scorecard"]["rows"]
                if r.get("plan_comparability_note") or r.get("gap_note")]
    if caveated:
        a("### Scorecard notes")
        a("")
        for r in caveated:
            note = r.get("plan_comparability_note") or r.get("gap_note")
            a(f"- **{r['label']}** ({r['plan_comparability']}): {note}")
        a("")

    # ---- Drill-downs: variable length, never padded --------------------
    dd = readout["drilldowns"]
    count = dd["count"]
    a(f"## This period's drill-downs ({count})")
    a("")
    a(f"_{dd['note']}_")
    a("")
    if count == 0:
        a("No Layer-1 node breached the variance threshold this period, so there are no "
          "drill-downs. That is a real result, not a missing section.")
        a("")
    for i, entry in enumerate(dd["entries"], start=1):
        a(_render_drilldown(i, entry))

    # ---- Not-yet-built sections, stated as such -----------------------
    pt = readout["playbook_triggers"]
    a("## Automated playbook triggers")
    a("")
    a(f"**Status: {pt['status']}.** {pt['note']}")
    a("")

    fc = readout["forecast"]
    a("## Forecast")
    a("")
    a(f"**Status: {fc['status']}.** {fc['note']}")
    a("")

    # ---- Watchlist -----------------------------------------------------
    wl = readout["watchlist"]
    a(f"## Watchlist ({wl['count']} accounts)")
    a("")
    a(f"_{wl['selection_rule']}_")
    a("")
    if wl["count"]:
        a("| # | Account | Segment | Risk tier | Churn probability | Health score "
          "| Est. ARR at risk |")
        a("|---|---|---|---|---|---|---|")
        for r in wl["rows"]:
            a(f"| {r['rank']} | {r['account_id']} | {r['segment']} | {r['risk_tier']} "
              f"| {r['churn_probability']:.3f} | {r['health_score']:.1f} "
              f"| {r['est_arr_at_risk_display']} |")
        a("")
    else:
        a("No account breached the health-score risk threshold this period.")
        a("")
    for c in wl["caveats"]:
        a(f"- {c}")
    a("")

    # ---- Provenance ----------------------------------------------------
    p = readout["provenance"]
    a("## Provenance")
    a("")
    a(f"Assembled by `{p['assembled_by']}`. Computation performed during assembly: "
      f"**{p['computation_performed_here']}** - every figure above is read verbatim from "
      f"the artifact that owns it and is re-checked against that artifact field by field.")
    a("")
    a("| Section | Source artifact | Entry point |")
    a("|---|---|---|")
    for s in p["sources"]:
        a(f"| {s['section']} | `{s['artifact']}` | `{s['entry_point']}` |")
    a("")
    a(f"- Metric definitions: {p['metric_definitions']}")
    a(f"- Variance threshold: {p['variance_threshold_status']}")
    a(f"- Segment migration: {p['segment_migration_analysis']}")
    a("")
    return "\n".join(out)


def _render_drilldown(index: int, entry: Dict[str, Any]) -> str:
    l1 = entry["layer1"]
    l2 = entry["layer2_outlier"]
    out: List[str] = []
    a = out.append

    a(f"### {index}. {_label_of(l1['metric_key'])} - {l1['value_display']} vs. "
      f"{l1['comparison_display']} ({l1['variance_display']}, {l1['mechanism']})")
    a("")

    cov = entry["sibling_coverage"]
    a(f"- **Layer 2 coverage:** {cov['computable_siblings']} of {cov['eligible_siblings']} "
      f"children of this node have a mart-computable actual"
      f"{'' if cov['is_genuine_sibling_comparison'] else ' - single-candidate read, not an outlier selection among siblings'}.")
    if l2 is None:
        a("- **Layer 2 outlier:** none identifiable - no child of this node has a "
          "mart-computable actual with a usable trailing baseline. The Layer-1 variance "
          "stands on its own.")
    else:
        dev = _fmt_pct(l2.get("deviation_pct"))
        a(f"- **Layer 2 outlier:** {l2['label']} (layer {l2['layer']}, child of "
          f"`{l2['parent_key']}`) - {_fmt_generic(l2.get('value'))} this period vs. a "
          f"{_fmt_generic(l2.get('baseline'))} trailing baseline ({dev}), ranked by "
          f"`{l2.get('comparison_basis')}`; computability: {l2['computability']}.")
        if l2.get("cross_reference_to"):
            a(f"  - This node is the tree's cross-reference to "
              f"`{l2['cross_reference_to']}` under Growth, not an independent driver.")

    if entry["sibling_ranking"]:
        a("")
        a("| Rank | Layer-2 sibling | Layer | Value | Trailing baseline | Deviation "
          "| Computability |")
        a("|---|---|---|---|---|---|---|")
        for r in entry["sibling_ranking"]:
            a(f"| {r.get('rank', '')} | {r['label']} | {r['layer']} | {r['value_display']} "
              f"| {r['baseline_display']} | {r['deviation_display']} | {r['computability']} |")

    a("")
    status = entry["layer3_status"]
    depth = entry["branch_max_depth_in_tree"]
    if l2 is None:
        a(f"- **Layer 3:** not reached - Layer-3 evidence hangs off a Layer-2 outlier, and "
          f"none was identifiable here. The branch runs {depth} layers deep in the tree.")
    elif status == vd.L3_SURFACED and entry["layer3_evidence"]:
        leaves = ", ".join(f"{e['label']} (layer {e['layer']})" for e in entry["layer3_evidence"])
        a(f"- **Layer 3 evidence:** {leaves}.")
        a("")
        a("| Rank | Layer-3 leaf | Layer | Value | Trailing baseline | Deviation |")
        a("|---|---|---|---|---|---|")
        for r in entry["layer3_ranking"]:
            a(f"| {r.get('rank', '')} | {r['label']} | {r['layer']} | {r['value_display']} "
              f"| {r['baseline_display']} | {r['deviation_display']} |")
    elif status == vd.L3_BRANCH_DEPTH_2:
        a(f"- **Layer 3:** none - this branch is genuinely {depth} layers deep in the "
          "metric tree. No Layer 3 is fabricated to force symmetry.")
    else:
        a(f"- **Layer 3:** the tree has Layer-3 children here (branch depth {depth}), but "
          "none is computable from any `mart_*` table this period.")

    for n in entry.get("notes", []):
        a(f"- _Note:_ {n}")
    a("")
    return "\n".join(out)


def _label_of(metric_key: str) -> str:
    return vd.get_node(metric_key).label


# =====================================================================
# Validation -- what "correct" means for a pure-assembly artifact
# =====================================================================
#
# There is no accuracy concept here: no coefficient, no AUC, no
# confusion matrix, no R^2. Per .claude/skills/analytics-engineering-
# conventions' "Structural/logic artifacts" category, forcing one onto an
# artifact that makes no prediction produces theater, not rigor. The
# correctness claim this artifact actually makes is narrower and fully
# checkable: EVERY FIGURE IN THE READOUT IS THE SOURCE ARTIFACT'S OWN
# ALREADY-VALIDATED OUTPUT, UNCHANGED, AND THE DOCUMENT'S STRUCTURE
# MATCHES WHAT THE BUILD SPEC REQUIRES. Each check below is deterministic
# with no sampling variance, so each targets exact equality rather than a
# tolerance band -- a band would imply an error source that does not
# exist.

_REQUIRED_SECTIONS = ("header", "executive_summary", "layer1_scorecard", "drilldowns",
                      "playbook_triggers", "forecast", "watchlist")
_EXPECTED_LAYER1_NODES = 11


def verify_source_trace(readout: Dict[str, Any], diagnostic: dict) -> List[Dict[str, Any]]:
    """Field-by-field re-check that the readout introduced no number of
    its own. Every scorecard value, drill-down variance and watchlist row
    is compared for exact equality against `diagnostic`, the engine output
    it was assembled from. Grain: one check per assertion. Returns a list
    of {name, passed, detail} rather than raising, so a validator can see
    every failure at once."""
    checks: List[Dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    sc = diagnostic["layer1_scorecard"]
    rows = readout["layer1_scorecard"]["rows"]

    check("required_sections_present",
          all(s in readout for s in _REQUIRED_SECTIONS),
          f"expected {list(_REQUIRED_SECTIONS)}; got {sorted(readout)}")

    check("layer1_scorecard_has_all_11_nodes",
          len(rows) == _EXPECTED_LAYER1_NODES == len(sc),
          f"readout {len(rows)}, engine {len(sc)}, expected {_EXPECTED_LAYER1_NODES}")

    check("layer1_scorecard_node_keys_match_engine",
          [r["metric_key"] for r in rows] == list(sc["metric_key"]),
          "scorecard rows must be the engine's own rows, in its own order")

    check("every_scorecard_row_is_layer_1",
          all(r["layer"] == 1 for r in rows) and
          all(vd.get_node(r["metric_key"]).layer == 1 for r in rows),
          "a Layer-2 node must never appear in the Layer-1 scorecard")

    engine_rows = {r["metric_key"]: r for r in sc.to_dict(orient="records")}
    mismatches = []
    for r in rows:
        e = engine_rows[r["metric_key"]]
        for field in ("actual", "plan", "variance_pct", "trailing_baseline",
                      "baseline_variance_pct", "prior_month_value"):
            if not _same_number(r[field], e[field]):
                mismatches.append(f"{r['metric_key']}.{field}: {r[field]!r} != {e[field]!r}")
        for field in ("status", "mechanism", "pillar", "plan_comparability"):
            if r[field] != e[field]:
                mismatches.append(f"{r['metric_key']}.{field}: {r[field]!r} != {e[field]!r}")
        if bool(r["breaches_threshold"]) != bool(e["breaches_threshold"]):
            mismatches.append(f"{r['metric_key']}.breaches_threshold")
    check("scorecard_values_trace_exactly_to_engine", not mismatches, "; ".join(mismatches))

    breaching = list(sc.loc[sc["breaches_threshold"], "metric_key"])
    dd_keys = [e["layer1"]["metric_key"] for e in readout["drilldowns"]["entries"]]
    check("drilldown_count_equals_breach_count",
          len(dd_keys) == len(breaching) == readout["drilldowns"]["count"],
          f"drill-downs {len(dd_keys)}, breaching nodes {len(breaching)} - "
          "never padded, never truncated")
    check("drilldown_keys_are_exactly_the_breaching_nodes",
          dd_keys == breaching, f"{dd_keys} != {breaching}")

    structural = []
    for e in readout["drilldowns"]["entries"]:
        l1_key = e["layer1"]["metric_key"]
        if e["layer1"]["layer"] != 1 or vd.get_node(l1_key).layer != 1:
            structural.append(f"{l1_key} heads a drill-down but is not Layer 1")
        if not _same_number(e["layer1"]["variance_pct"], engine_rows[l1_key]["variance_pct"]):
            structural.append(f"{l1_key} variance differs from the engine's")
        l2 = e["layer2_outlier"]
        if l2 is not None:
            if l2["layer"] != 2 or vd.get_node(l2["metric_key"]).layer != 2:
                structural.append(f"{l2['metric_key']} is not Layer 2")
            if l2["parent_key"] != l1_key:
                structural.append(f"{l2['metric_key']} is not a child of {l1_key}")
            for leaf in e["layer3_evidence"]:
                if leaf["layer"] != 3 or leaf["parent_key"] != l2["metric_key"]:
                    structural.append(f"{leaf['metric_key']} is not a Layer-3 child of "
                                      f"{l2['metric_key']}")
        elif e["layer3_evidence"]:
            structural.append(f"{l1_key} has Layer-3 evidence with no Layer-2 outlier")
        if e["layer3_status"] == vd.L3_BRANCH_DEPTH_2 and e["layer3_evidence"]:
            structural.append(f"{l1_key} reports branch_depth_2 yet surfaced a Layer 3")
    check("drilldown_layers_are_structurally_sound", not structural, "; ".join(structural))

    wl = diagnostic["watchlist"]
    wl_rows = readout["watchlist"]["rows"]
    wl_mismatch = []
    if len(wl_rows) != len(wl):
        wl_mismatch.append(f"row count {len(wl_rows)} != {len(wl)}")
    else:
        engine_wl = wl.to_dict(orient="records")
        for got, exp in zip(wl_rows, engine_wl):
            if got["account_id"] != exp["account_id"]:
                wl_mismatch.append(f"order: {got['account_id']} != {exp['account_id']}")
            for field in ("churn_probability", "health_score", "est_arr_at_risk_usd"):
                if not _same_number(got[field], exp[field]):
                    wl_mismatch.append(f"{got['account_id']}.{field}")
    check("watchlist_traces_exactly_to_engine", not wl_mismatch, "; ".join(wl_mismatch))

    check("unbuilt_sections_declare_themselves",
          readout["playbook_triggers"]["status"] == STATUS_NOT_YET_BUILT
          and readout["forecast"]["status"] == STATUS_NOT_YET_BUILT
          and readout["playbook_triggers"]["triggers"] == [],
          "playbook triggers (Wave 4) and forecast (Wave 2) must be present and "
          "explicitly not_yet_built, never omitted and never fabricated")

    check("narrative_is_deferred_not_generated",
          readout["executive_summary"]["status"] == STATUS_DEFERRED
          and "not yet generated" in readout["executive_summary"]["placeholder_marker"]
          and "prose" not in readout["executive_summary"]
          and not any(k for k in readout["executive_summary"] if k in ("text", "narrative")),
          "the executive summary must carry a placeholder marker, never generated prose")

    return checks


def _same_number(a: Any, b: Any) -> bool:
    """Exact equality, with NaN and None treated as the same 'no figure'.
    No tolerance: assembly does no arithmetic, so any difference at all
    means a computation crept in."""
    a_missing = a is None or (isinstance(a, (float, np.floating)) and np.isnan(a))
    b_missing = b is None or (isinstance(b, (float, np.floating)) and np.isnan(b))
    if a_missing or b_missing:
        return a_missing and b_missing
    return float(a) == float(b)


def verify_rendered_document(markdown: str, readout: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Checks the rendered Markdown says what the structured readout
    says: all eleven Layer-1 labels present, one heading per drill-down,
    the unbuilt sections named as unbuilt, and no generated prose where
    the narrative placeholder belongs. Grain: one check per assertion."""
    checks: List[Dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    labels = [r["label"] for r in readout["layer1_scorecard"]["rows"]]
    missing = [l for l in labels if l not in markdown]
    check("all_11_layer1_labels_rendered",
          len(labels) == _EXPECTED_LAYER1_NODES and not missing, f"missing {missing}")
    drilldown_headings = re.findall(r"^### \d+\. ", markdown, flags=re.MULTILINE)
    check("drilldown_heading_count_matches",
          len(drilldown_headings) == readout["drilldowns"]["count"],
          f"expected exactly {readout['drilldowns']['count']} numbered drill-down headings "
          f"(`### N. `), found {len(drilldown_headings)} -- counting only these, not the "
          "pillar-scorecard or 'Scorecard notes' headings, which also start with '### '")
    check("playbook_triggers_section_rendered_as_unbuilt",
          "## Automated playbook triggers" in markdown
          and f"Status: {STATUS_NOT_YET_BUILT}" in markdown)
    check("forecast_section_rendered_as_unbuilt", "## Forecast" in markdown)
    check("narrative_placeholder_rendered",
          _NARRATIVE_PLACEHOLDER in markdown,
          "the exec-summary slot must carry the placeholder marker, not prose")
    check("watchlist_section_rendered", "## Watchlist" in markdown)

    # Numeric re-derivation: the checks above confirm labels/headings/status
    # strings are present, but say nothing about whether a rendered NUMBER
    # matches the structured payload it was formatted from -- a formatter
    # bug (wrong _UNITS entry, a swapped column) would pass every check
    # above while showing a wrong figure. Rebuild each table row's exact
    # expected line from the same *_display fields render_markdown() itself
    # used, and require that exact line to appear -- this is what actually
    # closes the gap, not a second independent formatter (which would just
    # be a second place to get the formatting wrong).
    scorecard_mismatches = []
    for r in readout["layer1_scorecard"]["rows"]:
        expected = (f"| {r['label']} | {r['value_display']} | {r['comparison_display']} "
                    f"| {r['variance_display']} | {r['status']} |")
        if expected not in markdown:
            scorecard_mismatches.append(r["label"])
    check("scorecard_rendered_values_match_structured_payload",
          not scorecard_mismatches,
          f"rows whose rendered value/comparison/variance/status did not match "
          f"the structured payload verbatim: {scorecard_mismatches}")

    watchlist_mismatches = []
    for r in readout["watchlist"]["rows"]:
        expected = (f"| {r['rank']} | {r['account_id']} | {r['segment']} | {r['risk_tier']} "
                    f"| {r['churn_probability']:.3f} | {r['health_score']:.1f} "
                    f"| {r['est_arr_at_risk_display']} |")
        if expected not in markdown:
            watchlist_mismatches.append(r["account_id"])
    check("watchlist_rendered_values_match_structured_payload",
          not watchlist_mismatches,
          f"accounts whose rendered row did not match the structured payload verbatim: "
          f"{watchlist_mismatches}")

    drilldown_heading_mismatches = []
    for dd in readout["drilldowns"]["entries"]:
        l1 = dd["layer1"]
        expected = (f"{_label_of(l1['metric_key'])} - {l1['value_display']} vs. "
                    f"{l1['comparison_display']} ({l1['variance_display']}, {l1['mechanism']})")
        if expected not in markdown:
            drilldown_heading_mismatches.append(l1["metric_key"])
    check("drilldown_headings_match_structured_payload",
          not drilldown_heading_mismatches,
          f"drill-downs whose rendered heading did not match the structured payload verbatim: "
          f"{drilldown_heading_mismatches}")

    return checks


# =====================================================================
# Run / persist
# =====================================================================

def write_readout(readout: Dict[str, Any], markdown: str,
                  out_dir: str = _OUTPUT_DIR) -> Dict[str, str]:
    """Writes the rendered Markdown deliverable and the structured payload
    that a future narrative step would consume. One file pair per
    as_of_date."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = readout["header"]["as_of_date"]
    md_path = os.path.join(out_dir, f"weekly_readout_{stamp}.md")
    json_path = os.path.join(out_dir, f"weekly_readout_{stamp}.json")
    with open(md_path, "w") as f:
        f.write(markdown)
    with open(json_path, "w") as f:
        json.dump(readout, f, indent=2, default=_json_default)
    return {"markdown": md_path, "structured": json_path}


def _json_default(o: Any) -> Any:
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return o.isoformat()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if is_dataclass(o):
        return asdict(o)
    raise TypeError(f"not JSON-serialisable: {type(o)}")


def run_build_time_validation(as_of_date: date, threshold: float = vd._VARIANCE_THRESHOLD,
                              watchlist_top_n: int = 25, write: bool = True,
                              log: bool = True) -> Dict[str, Any]:
    """Everything analytics-model-validator needs to independently
    re-check this artifact: the engine run it was assembled from, the
    assembled structure, the rendered document, and both check suites.
    Logs only structural/trace scalars -- there is no AUC, coefficient
    table or confusion matrix here to log, by the nature of an assembly
    artifact."""
    diagnostic = vd.run_diagnostic(as_of_date, threshold=threshold,
                                   watchlist_top_n=watchlist_top_n)
    readout = assemble_readout(as_of_date, threshold=threshold,
                               watchlist_top_n=watchlist_top_n, diagnostic=diagnostic)
    markdown = render_markdown(readout)
    trace_checks = verify_source_trace(readout, diagnostic)
    render_checks = verify_rendered_document(markdown, readout)
    all_checks = trace_checks + render_checks
    passed = sum(c["passed"] for c in all_checks)

    paths = write_readout(readout, markdown) if write else {}

    if log:
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_total", float(len(all_checks)))
        log_performance(_MODEL_NAME, as_of_date, "structural_checks_passed", float(passed))
        log_performance(_MODEL_NAME, as_of_date, "layer1_nodes_in_scorecard",
                        float(readout["layer1_scorecard"]["nodes_total"]))
        log_performance(_MODEL_NAME, as_of_date, "layer1_nodes_not_computable",
                        float(readout["layer1_scorecard"]["nodes_not_computable"]))
        log_performance(_MODEL_NAME, as_of_date, "drilldowns_rendered",
                        float(readout["drilldowns"]["count"]))
        log_performance(_MODEL_NAME, as_of_date, "watchlist_accounts",
                        float(readout["watchlist"]["count"]))
        log_performance(_MODEL_NAME, as_of_date, "sections_not_yet_built",
                        float(sum(1 for s in ("playbook_triggers", "forecast")
                                  if readout[s]["status"] == STATUS_NOT_YET_BUILT)))

    return {"readout": readout, "markdown": markdown, "diagnostic": diagnostic,
            "trace_checks": trace_checks, "render_checks": render_checks,
            "checks_passed": passed, "checks_total": len(all_checks), "paths": paths}


if __name__ == "__main__":
    # 2025-11-30, matching analytics/variance_diagnostic.py's own canonical
    # build-time checkpoint: the simulation's final month (2025-12) carries
    # an end-of-window truncation artifact, so 2025-11 is the last
    # representative evaluation period.
    AS_OF = date(2025, 11, 30)
    out = run_build_time_validation(AS_OF)

    print(f"=== Weekly executive readout -- as of {AS_OF} ===")
    print(f"Layer-1 nodes in scorecard : {out['readout']['layer1_scorecard']['nodes_total']}")
    print(f"Nodes breaching threshold  : "
          f"{out['readout']['layer1_scorecard']['nodes_breaching_threshold']}")
    print(f"Drill-downs rendered       : {out['readout']['drilldowns']['count']}")
    print(f"Watchlist accounts         : {out['readout']['watchlist']['count']}")
    print(f"Playbook triggers          : {out['readout']['playbook_triggers']['status']}")
    print(f"Forecast                   : {out['readout']['forecast']['status']}")
    print(f"Executive summary          : {out['readout']['executive_summary']['status']}")
    print()
    for c in out["trace_checks"] + out["render_checks"]:
        print(f"[{'PASS' if c['passed'] else 'FAIL'}] {c['name']}"
              f"{'' if c['passed'] else '  -- ' + c['detail']}")
    print(f"\n{out['checks_passed']}/{out['checks_total']} checks passed")
    for kind, path in out["paths"].items():
        print(f"wrote {kind}: {path}")
