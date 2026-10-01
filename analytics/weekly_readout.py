"""Weekly executive readout -- grain: one readout per evaluation period
(the last complete month at or before as_of_date, company-wide/blended);
sources: analytics/variance_diagnostic.py's run_diagnostic() output (which
itself reads mart_gtm_plan, mart_growth_bridge, mart_efficiency,
mart_durability, mart_account_health, and, for Pipeline generated,
analytics/marketing_attribution.py's lead panel over fact_leads and
fact_campaign_engagement_events) plus, through that engine's watchlist,
analytics/health_score.py's scored output; analytics/playbook_triggers.py's
run_playbook_triggers() for the trigger section; and analytics/forecast.py's
run_forecast() for the forecast section (quarter grain, Commercial and
Enterprise, one row per segment).

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
away from that artifact's own validation. The forecast section follows the
same rule: its values are read from run_forecast() and re-checked against
a fresh run, never re-derived here.

Three consequences follow, all deliberate:
  * The engine's caveats travel with the numbers rather than being
    quietly smoothed over -- Activation reports "Not computable" (blended
    TTFA is identically 0 at this data's monthly grain), and the five
    plan-comparability caveats (magic number, consumption payback, AM
    efficiency, NRR, GRR) are reproduced next to the metrics they qualify.
  * The Layer-1 scorecard carries all eleven nodes every period,
    unconditionally, including those six -- the build spec asks for the
    scorecard "every week... value, vs. plan, status", and a gap reported
    is worth more than a gap hidden.
  * The drill-down section is genuinely variable-length: exactly as many
    entries as there are Layer-1 nodes whose variance breached the
    engine's threshold, which can be zero. It is never padded to a fixed
    count and never truncated.

SCOPE -- WHAT IS AND IS NOT FILLED HERE
----------------------------------------
Build spec Section 5 names seven sections. Six are assembled here from
built artifacts; the executive summary is filled by a deliberately
separate step. No section is an unbuilt placeholder.

  1. EXECUTIVE SUMMARY NARRATIVE -- a separate step, analytics/
     executive_summary.py, NOT performed by this module. Build spec Section
     5 calls for a narrative that names a specific Layer-2/Layer-3 cause for
     any real miss, generated via the Claude API (Section 3's stack). This
     module never calls an LLM and no template-based prose generator stands
     in for one -- a canned-sentence generator would read as narrative while
     carrying none of the causal reasoning the section exists for.
     assemble_readout() returns the fully-assembled structured readout,
     which is exactly the input that step consumes, with the
     `executive_summary` slot marked `not_generated` (reason
     `pending_generation`). run_build_time_validation() then carries a
     previously generated, still-valid summary forward unchanged (same
     input_hash) or leaves the slot honestly not_generated; it never
     discards a valid summary and never writes unvalidated prose. The
     `executive_summary` pipeline node fills the slot when an API key is
     available. See analytics/executive_summary.py for the contract.
  2. AUTOMATED PLAYBOOK TRIGGERS -- reads analytics/playbook_triggers.py's
     run_playbook_triggers(as_of_date) directly -- "whatever fired this
     period, unranked (binary, not prioritized)," build spec Section 5's own
     phrasing -- and, like every other section, performs no computation on
     what it reads.
  3. FORECAST -- reads analytics/forecast.py's run_forecast() (bottoms-up
     rep, bottoms-up manager, ML and CRO-adjusted lenses, reconciled per
     segment with the artifact's own divergence flag). Grain mismatch,
     resolved explicitly: the readout reports a MONTH, the forecast a
     QUARTER. The section therefore does not pretend to forecast the
     reporting month; it carries the forecast call that was current at the
     reporting period's end -- the latest weekly forecast call (a Friday
     fact_forecast_submissions snapshot) on or before the period end, via
     analytics/forecast.py's latest_forecast_call_date() -- and the quarter
     that call sits in. No data after the period end is read. When no call
     exists that early, or the call leaves no open deal scoped to its
     quarter, the section is `unavailable` with a specific reason; it is
     never an unbuilt placeholder and never a fabricated figure. The
     forecast has no plan or quota comparator in any mart at its grain and
     unit (closed-won opportunity amount, Commercial and Enterprise,
     quarterly); the section says so rather than manufacturing one.

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
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import executive_summary as es
from . import forecast as fc
from . import playbook_triggers as pbt
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

# Section-status vocabulary. Kept as named constants so a consumer can
# branch on the status string rather than pattern-match prose.
#   present        the section carries its artifact's real output
#   unavailable    the artifact is built but cannot produce a result for
#                  this readout date; the section carries a specific
#                  reason code and detail, never a figure
#   not_yet_built  the underlying artifact does not exist; no section
#                  carries this today, and the logged scalar
#                  `sections_not_yet_built` counts any that ever do
STATUS_NOT_YET_BUILT = "not_yet_built"
# The status text the scorecard shows on a node with no usable comparison.
NODE_STATUS_NOT_COMPUTABLE = "Not computable"
STATUS_PRESENT = "present"
STATUS_UNAVAILABLE = "unavailable"

# Reason codes for an unavailable forecast section.
REASON_NO_FORECAST_CALL = "no_forecast_call_on_or_before_period_end"
REASON_NO_OPEN_DEALS = "no_open_deals_scoped_to_the_forecast_quarter"


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
                     diagnostic: Optional[dict] = None,
                     forecast_run: Optional[dict] = None) -> Dict[str, Any]:
    """The whole weekly readout as one structured, JSON-serialisable
    dict. Grain: one readout per evaluation period (the last complete
    month at or before as_of_date). Source: analytics/variance_diagnostic
    .py's run_diagnostic() output, which is this module's only data
    input.

    THIS FUNCTION'S OUTPUT IS THE NARRATIVE-GENERATION SEAM. Build spec
    Section 5 specifies an executive summary that names a specific
    Layer-2/Layer-3 cause for any real miss, produced via the Claude API.
    That step lives in analytics/executive_summary.py, not here: no LLM is
    called from this function, and no template-based prose generator
    stands in for one. What this returns is precisely the input that step
    consumes -- the eleven-node scorecard with each node's variance,
    mechanism and comparability caveat; every drill-down with its Layer-2
    outlier, that outlier's deviation from its own trailing baseline, any
    Layer-3 evidence, and the notes explaining what could not be seen;
    and the watchlist with its ARR-at-risk estimate and stated
    limitations -- with the `executive_summary` slot marked
    `not_generated` until that step has run. The narrative step reads this
    structure and cites it; it never re-queries the marts, because then
    the prose and the tables could disagree.

    The returned dict's top-level keys follow build spec Section 5's
    required structure exactly -- header, executive_summary,
    layer1_scorecard, drilldowns, playbook_triggers, forecast, watchlist
    -- so a section that cannot be produced for a date is visibly present
    with an honest status (`unavailable` and why) rather than missing.

    Computes nothing. Every figure is read verbatim from `diagnostic` (and,
    for the forecast section, from `forecast_run`, an analytics/forecast.py
    run_forecast() result for the selected forecast call, run here when not
    supplied); verify_source_trace() re-checks that field by field.
    """
    result = diagnostic if diagnostic is not None else vd.run_diagnostic(
        as_of_date, threshold=threshold, watchlist_top_n=watchlist_top_n)

    month = result["evaluation_month"]
    scorecard = result["layer1_scorecard"]

    readout = {
        "artifact": "weekly_executive_readout",
        "header": _header(as_of_date, month, result),
        "executive_summary": None,  # set below, once the rest is assembled
        "layer1_scorecard": _scorecard_section(scorecard),
        "drilldowns": _drilldown_section(result["drilldowns"], scorecard),
        "playbook_triggers": _playbook_triggers_section(as_of_date),
        "forecast": _forecast_section(
            month.to_period("M").to_timestamp("M").date(), forecast_run),
        "watchlist": _watchlist_section(result["watchlist"], month),
        "data_window": {k: _none_if_nan(v) for k, v in result["data_window"].items()},
        "source_coverage": [{k: _none_if_nan(v) for k, v in r.items()}
                            for r in result["coverage"].to_dict(orient="records")],
        "provenance": _provenance(as_of_date, result),
    }
    readout["executive_summary"] = es.unevaluated_slot(readout)
    return readout


def _header(as_of_date: date, month: pd.Timestamp, result: dict) -> Dict[str, Any]:
    period_end = month.to_period("M").to_timestamp("M")
    return {
        "reporting_period_start": month.date().isoformat(),
        "reporting_period_end": period_end.date().isoformat(),
        "reporting_period_label": f"{month:%B %-d} - {period_end:%B %-d, %Y}",
        "reporting_period_grain": _PERIOD_GRAIN,
        "reporting_period_grain_note": (
            "Monthly grain. Every actuals table is segment by month and the variance engine "
            "evaluates the last complete month at or before the as-of date, so the reporting "
            "period is one month."),
        "as_of_date": as_of_date.isoformat(),
        "evaluation_month": month.date().isoformat(),
        "audience": _AUDIENCE,
        "variance_threshold": result["threshold"],
        "trailing_baseline_months": result["baseline_months"],
    }


def _playbook_triggers_section(as_of_date: date) -> Dict[str, Any]:
    """Automated playbook triggers, Wave 4 (build spec Section 8, item
    #10). Reads analytics/playbook_triggers.py's
    run_playbook_triggers(as_of_date) directly -- this module still
    performs no computation of its own on the trigger rows it renders,
    only formatting, matching every other section's discipline. Grain:
    one row per trigger firing (rule_id, account_id, timestamp,
    resulting_action, outcome)."""
    triggers = pbt.with_known_outcomes(pbt.run_playbook_triggers(as_of_date), as_of_date)
    rows = [{k: _none_if_nan(v) for k, v in rec.items()}
            for rec in triggers.to_dict(orient="records")]
    return {
        "status": STATUS_PRESENT,
        "count": len(rows),
        "triggers": rows,
        "rules": pbt.RULES,
        "note": (
            "Whatever fired this period, unranked (binary, not prioritized) -- build spec "
            "Section 5's own phrasing for this section. Each row is one binary threshold "
            "rule (see 'rules' above for each rule's stored, configurable threshold) firing "
            "for one account, computed fresh from main_marts fact tables at as_of_date. "
            "outcome is read from the operational log (fact_playbook_triggers / "
            "data/playbook_triggers.csv) and shown only where it was already knowable at "
            "as_of_date: a trigger reads pending until its rule's observation window has "
            "elapsed (analytics/playbook_triggers.py OUTCOME_CRITERIA, PROPOSED). Owner, SLA "
            "and the open task list live in the same log (open_trigger_tasks())."),
    }


_FORECAST_LENS_LABELS = {
    "bottoms_up_rep": "Bottoms-up (rep)",
    "bottoms_up_manager": "Bottoms-up (manager)",
    "ml": "ML",
    "cro_adjusted": "CRO-adjusted",
}

_FORECAST_SELECTION_RULE = (
    "The readout reports a month; the forecast is quarter-grain. The section carries the "
    "forecast call that was current at the reporting period's end: the latest weekly "
    "forecast call (a Friday forecast snapshot) on or before the period end, and the "
    "quarter that call falls in. The one field read from after the call is each open "
    "deal's close date, used only to decide which quarter the deal belongs to (the data has "
    "no separate expected-close field); no outcome after the call is read.")

_FORECAST_NOTE = (
    "Values are read from the forecast artifact's output at the selected call date: four "
    "lenses per segment (Commercial and Enterprise), shown side by side with the "
    "artifact's own divergence flag and never collapsed into one number. A fresh run of the "
    "forecast artifact is compared with this section field by field.")

_FORECAST_PLAN_COMPARISON = {
    "status": "not_available",
    "reason": (
        "No plan or quota exists at the forecast's grain and unit (closed-won opportunity "
        "amount for Commercial and Enterprise, per quarter). The plan table states monthly "
        "MRR-movement plans at company grain, and quota history is per rep across all "
        "segments, so neither is comparable without a conversion that this readout and the "
        "forecast artifact do not own. The forecast artifact's own variance logic is the "
        "divergence flag between its lenses."),
}


def _forecast_selection(period_end: date, call_date: Optional[date]) -> Dict[str, Any]:
    return {
        "rule": _FORECAST_SELECTION_RULE,
        "reporting_period_end": period_end.isoformat(),
        "forecast_call_date": call_date.isoformat() if call_date else None,
        "call_cadence": "weekly (Friday snapshots in fact_forecast_submissions)",
    }


def _forecast_unavailable(period_end: date, call_date: Optional[date], reason: str,
                          detail: str) -> Dict[str, Any]:
    return {
        "status": STATUS_UNAVAILABLE,
        "reason": reason,
        "detail": detail,
        "forecast_as_of_date": call_date.isoformat() if call_date else None,
        "selection": _forecast_selection(period_end, call_date),
        "note": _FORECAST_NOTE,
        "caveats": list(fc.FORECAST_CAVEATS),
    }


def _ml_lens_payload(model: dict) -> Dict[str, Any]:
    """The ML lens's own stated accuracy and calibration context, read from
    the fitted-model result run_forecast() already returns. Nothing is
    re-fitted or re-scored here."""
    if not model.get("computable"):
        return {"computable": False, "reason": model.get("reason")}
    targets = fc.check_ml_targets(model)
    calibration = model["validation_package"]["calibration"]
    lo, hi = fc.PUBLISHED_PARAMETERS["ml_auc_target_range"]
    return {
        "computable": True,
        "auc_holdout": float(model["auc_holdout"]),
        "auc_target_range": [lo, hi],
        "meets_auc_target": bool(model["meets_auc_target"]),
        "auc_target_position": ("above" if model["auc_holdout"] > hi
                                else "below" if model["auc_holdout"] < lo else "within"),
        "manager_lookup_baseline_auc": float(model["manager_lookup_baseline_auc"]),
        "auc_ratio_vs_leak_proof_baseline": _none_if_nan(targets["auc_ratio_vs_leak_proof_baseline"]),
        "calibration_gap": float(calibration["calibration_gap"]),
        "calibration_gap_target": fc.PUBLISHED_PARAMETERS["ml_calibration_gap_target"],
        "calibration_within_target": bool(calibration["within_target"]),
        "ml_targets_passed": bool(targets["passed"]),
        "ml_targets_detail": targets["detail"],
        "n_train": int(model["n_train"]),
        "n_test": int(model["n_test"]),
        "n_train_positive": int(model["n_train_positive"]),
        "n_test_positive": int(model["n_test_positive"]),
        "train_eval_date_range": [_none_if_nan(x) for x in model["train_eval_date_range"]],
        "test_eval_date_range": [_none_if_nan(x) for x in model["test_eval_date_range"]],
        "holdout": "out-of-time: trained on the earlier forecast calls, scored on the later "
                   "ones, never on its own training rows",
    }


def _widest_pair_display(pair: Optional[str]) -> str:
    if not pair:
        return "n/a"
    return " vs ".join(_FORECAST_LENS_LABELS.get(p, p) for p in str(pair).split(" vs "))


def _fmt_signed_usd(v: float) -> str:
    return f"-{_fmt_usd(abs(v))}" if v < 0 else f"+{_fmt_usd(v)}"


def _cro_display(row: Dict[str, Any]) -> str:
    if row["has_logged_cro_adjustment"]:
        reason = str(row["cro_reason"]).replace("_", " ")
        return f"CRO override {_fmt_signed_usd(row['cro_adjustment_amount'])} filed ({reason})"
    return "no CRO override filed"


def _days_to_quarter_end(call_date: date) -> int:
    """Calendar days from the forecast call to the end of its quarter -- a
    date fact shown so a reader can see how much of the quarter the lenses
    still cover; not a metric."""
    end = pd.Timestamp(call_date).to_period("Q").end_time.normalize()
    return int((end - pd.Timestamp(call_date)).days)


def _forecast_section(period_end: date, forecast_run: Optional[dict] = None) -> Dict[str, Any]:
    """The forecast section, build spec Section 5. Grain: one row per
    segment for the quarter containing the selected forecast call. Reads
    analytics/forecast.py only (latest_forecast_call_date() to select the
    call, run_forecast() for the lenses); performs no computation on what
    it reads."""
    call_date = fc.latest_forecast_call_date(period_end)
    if call_date is None:
        return _forecast_unavailable(
            period_end, None, REASON_NO_FORECAST_CALL,
            f"fact_forecast_submissions holds no weekly forecast call on or before "
            f"{period_end.isoformat()}, so no forecast existed at this reporting period's end.")
    if forecast_run is None:
        forecast_run = fc.run_forecast(call_date)
    elif forecast_run["as_of_date"] != call_date:
        raise ValueError(
            f"forecast_run is for {forecast_run['as_of_date']}, but the forecast call selected "
            f"for the period ending {period_end} is {call_date}")

    recon = forecast_run["reconciliation"]
    if recon.empty:
        return _forecast_unavailable(
            period_end, call_date, REASON_NO_OPEN_DEALS,
            f"No Commercial or Enterprise deal was still open after the {call_date.isoformat()} "
            f"forecast call with a close inside {forecast_run['period']}, so the forecast "
            f"artifact returns no lens values for that quarter.")

    rows = []
    for rec in recon.to_dict(orient="records"):
        row = {k: _none_if_nan(v) for k, v in rec.items()}
        for lens in ("bottoms_up_rep", "bottoms_up_manager", "ml", "cro_adjusted"):
            row[f"{lens}_display"] = _fmt_usd(row[lens]) if row[lens] is not None else "n/a"
        row["open_pipeline_display"] = _fmt_usd(row["open_pipeline_amount"])
        row["lens_spread_display"] = _fmt_pct(row["lens_spread_pct"]).lstrip("+")
        row["widest_pair_display"] = _widest_pair_display(row["widest_pair"])
        row["cro_display"] = _cro_display(row)
        rows.append(row)

    present = {r["segment"] for r in rows}
    return {
        "status": STATUS_PRESENT,
        "forecast_as_of_date": call_date.isoformat(),
        "period": forecast_run["period"],
        "call_to_quarter_end_days": _days_to_quarter_end(call_date),
        "grain": "one row per segment (Commercial, Enterprise) for the quarter containing "
                 "the forecast call; quarter-grain, not the readout's monthly grain",
        "selection": _forecast_selection(period_end, call_date),
        "lens_labels": dict(_FORECAST_LENS_LABELS),
        "lens_definitions": dict(fc.LENS_DEFINITIONS),
        "segments": rows,
        "segments_without_open_deals": [
            seg for seg in fc._FORECAST_SEGMENTS if seg not in present],
        "divergence_threshold": fc.PUBLISHED_PARAMETERS["divergence_threshold"],
        "divergence_threshold_status": fc.PUBLISHED_PARAMETERS["divergence_threshold_status"],
        "ml_lens": _ml_lens_payload(forecast_run["model"]),
        "plan_comparison": dict(_FORECAST_PLAN_COMPARISON),
        "data_window_note": forecast_run["data_window"]["note"],
        "caveats": list(fc.FORECAST_CAVEATS),
        "note": _FORECAST_NOTE,
    }


_NOT_COMPUTABLE_RULE = (
    "A node counts as Not computable when its scorecard status is 'Not computable': the "
    "engine produced no variance, either because no actual exists or because the "
    "comparison is degenerate (Activation: blended time to first Action is 0 in every "
    "month, so its trailing baseline is 0).")


def _scorecard_summary_line(sec: Dict[str, Any]) -> str:
    """The one-line node count shown above the scorecard tables. Presentation
    only: every number is read from the structured scorecard section."""
    labels = {r["metric_key"]: r["label"] for r in sec["rows"]}
    nc = sec["nodes_not_computable"]
    tail = (f" ({', '.join(labels[k] for k in sec['nodes_not_computable_keys'])})" if nc else "")
    return (f"**Nodes:** {sec['nodes_total']} tracked, {sec['nodes_breaching_threshold']} "
            f"breaching the variance threshold, {nc} Not computable{tail}.")


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
    not_computable = [r["metric_key"] for r in rows
                      if r["status"] == NODE_STATUS_NOT_COMPUTABLE]
    return {
        "status": STATUS_PRESENT,
        "nodes_total": len(rows),
        "nodes_breaching_threshold": sum(1 for r in rows if r["breaches_threshold"]),
        "nodes_not_computable": len(not_computable),
        "nodes_not_computable_keys": not_computable,
        "not_computable_rule": _NOT_COMPUTABLE_RULE,
        "rows": rows,
        "by_pillar": by_pillar,
        "note": "All 11 Layer-1 nodes are shown every period, including nodes with no "
                "computable comparison.",
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
            "One drill-down per Layer-1 node that breached the variance threshold this "
            "period; none for nodes that did not. The Layer-2 outlier in each entry is the "
            "engine's ranking of that node's siblings against their own trailing baselines. "
            "Layer-3 evidence appears only where the branch has a Layer 3 that can be computed."),
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
            "Accounts whose composite health score breaches the High-risk threshold, ranked "
            "by estimated ARR at risk, then by churn probability. Source: the account "
            "health score's scored output."),
        "caveats": [
            "Estimated ARR at risk is the account's segment-average ARR for the evaluation "
            "month (starting MRR divided by starting accounts, times 12), not its own "
            "contracted ARR; no reporting table exposes ARR at account grain. It orders the "
            "list correctly across segments and by risk within a segment, but it is an "
            "estimate.",
            "Risk level is quantile-based over the scored active population, so the "
            "watchlist's segment mix follows the risk-level definition, not an ARR ranking.",
            "Churn probability is a ranking signal, not a calibrated probability: class "
            "weighting in the health model shifts predicted probabilities upward "
            "systematically (see the health score's calibration note in "
            "docs/acme-corp-analytics-methods.md). It is not a literal likelihood of churn.",
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
            {"section": "playbook_triggers",
             "artifact": "analytics/playbook_triggers.py",
             "entry_point": "run_playbook_triggers(as_of_date) + with_known_outcomes()"},
            {"section": "forecast",
             "artifact": "analytics/forecast.py",
             "entry_point": "latest_forecast_call_date(reporting_period_end); "
                            "run_forecast(forecast_call_date)"},
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

    No prose is generated here. Where the sample readout's executive
    summary paragraph sits, this renders the statements of a generated,
    validated summary (analytics/executive_summary.py) or an explicit
    not-generated note with its reason, because an empty gap would read as
    an oversight and unvalidated text would read as a finding."""
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

    # ---- Executive summary: validated generated statements, or an honest
    # not-generated note -- never unvalidated prose ---------------------------
    a("## Executive summary")
    a("")
    out.extend(es.render_section(readout["executive_summary"]))

    # ---- Layer-1 scorecard: all 11 nodes, three pillar tables ---------
    a(f"## Layer 1 scorecard - all {readout['layer1_scorecard']['nodes_total']} nodes")
    a("")
    a(f"_{readout['layer1_scorecard']['note']}_")
    a("")
    a(_scorecard_summary_line(readout["layer1_scorecard"]))
    a(f"_{readout['layer1_scorecard']['not_computable_rule']}_")
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
    a("Dollar figures are monthly MRR movements. NRR, GRR and logo retention are "
      "trailing-12-month compounded rates, the unit the plan states them in.")
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

    # ---- Automated playbook triggers: whatever fired, unranked --------
    pt = readout["playbook_triggers"]
    a(f"## Automated playbook triggers ({pt['count']})")
    a("")
    a(f"_{pt['note']}_")
    a("")
    if pt["count"]:
        a("| Rule | Account | Timestamp | Resulting action | Outcome |")
        a("|---|---|---|---|---|")
        for r in pt["triggers"]:
            a(f"| {r['rule_id']} | {r['account_id']} | {r['timestamp']} "
              f"| {r['resulting_action']} | {r['outcome'] or 'pending'} |")
        a("")
    else:
        a("No playbook trigger fired this period. That is a real result, not a missing "
          "section.")
        a("")

    # ---- Forecast: the forecast artifact's lenses at the period-end call,
    # or a specific unavailable reason --------------------------------------
    out.extend(_render_forecast(readout["forecast"]))

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


def _ml_context_line(ml: Dict[str, Any]) -> str:
    if not ml["computable"]:
        return (f"- **ML lens:** not computable at this call - {ml['reason']}. The other three "
                "lenses carry the read.")
    lo, hi = ml["auc_target_range"]
    position = {"within": "within the target range", "above": f"above the {lo:.2f}-{hi:.2f} "
                "target range", "below": f"below the {lo:.2f}-{hi:.2f} target range"}[
        ml["auc_target_position"]]
    return (f"- **ML lens context:** out-of-time holdout AUC {ml['auc_holdout']:.3f} against a "
            f"{lo:.2f}-{hi:.2f} target ({position}), "
            f"manager-category lookup baseline AUC {ml['manager_lookup_baseline_auc']:.3f}, "
            f"calibration gap {ml['calibration_gap']:+.3f} against +/-"
            f"{ml['calibration_gap_target']:.2f} "
            f"({'within' if ml['calibration_within_target'] else 'outside'}); fitted on "
            f"{ml['n_train']:,} past forecast calls and held out on {ml['n_test']:,}; model AUC "
            f"is {ml['auc_ratio_vs_leak_proof_baseline']:.3f}x the leak-proof manager-lookup "
            f"AUC on the same held-out rows; "
            f"{'all' if ml['ml_targets_passed'] else 'not all'} pre-registered ML targets met.")


def _render_forecast(fc_sec: Dict[str, Any]) -> List[str]:
    """The '## Forecast' section. Presentation only: every figure comes from
    the structured section, which comes from analytics/forecast.py."""
    out: List[str] = []
    a = out.append
    a("## Forecast")
    a("")
    sel = fc_sec["selection"]
    if fc_sec["status"] != STATUS_PRESENT:
        a(f"**Status: {fc_sec['status']} ({fc_sec['reason']}).** {fc_sec['detail']}")
        a("")
        a(f"_{fc_sec['note']}_")
        a("")
        a(f"_{sel['rule']}_")
        a("")
        for c in fc_sec["caveats"]:
            a(f"- {c}")
        a("")
        return out

    a(f"**Forecast call:** {fc_sec['forecast_as_of_date']} - the latest weekly forecast call "
      f"on or before the {sel['reporting_period_end']} period end - covering "
      f"{fc_sec['period']} (Commercial and Enterprise), "
      f"{fc_sec['call_to_quarter_end_days']} days before that quarter ends.")
    a("")
    a(f"_{fc_sec['note']}_")
    a("")
    a(f"_{sel['rule']}_")
    a("")
    labels = fc_sec["lens_labels"]
    a(f"| Segment | Open deals | Open pipeline | {labels['bottoms_up_rep']} "
      f"| {labels['bottoms_up_manager']} | {labels['ml']} | {labels['cro_adjusted']} "
      f"| Lens spread | Divergence |")
    a("|---|---|---|---|---|---|---|---|---|")
    for r in fc_sec["segments"]:
        a(_forecast_row_line(r))
    a("")
    for r in fc_sec["segments"]:
        a(f"- **{r['segment']}:** {r['cro_display']}.")
    if fc_sec["segments_without_open_deals"]:
        a(f"- **No open deals scoped to {fc_sec['period']} after this call:** "
          f"{', '.join(fc_sec['segments_without_open_deals'])}.")
    a(_ml_context_line(fc_sec["ml_lens"]))
    a(f"- **Divergence threshold:** {fc_sec['divergence_threshold_status']}.")
    a(f"- **Versus plan or quota:** {fc_sec['plan_comparison']['status'].replace('_', ' ')} - "
      f"{fc_sec['plan_comparison']['reason']}")
    a(f"- **Data window:** {fc_sec['data_window_note']}")
    a("")
    a("Forecast caveats:")
    a("")
    for c in fc_sec["caveats"]:
        a(f"- {c}")
    a("")
    return out


def _forecast_row_line(r: Dict[str, Any]) -> str:
    flag = (f"diverges materially (widest: {r['widest_pair_display']})"
            if r["diverges_materially"] else "no material divergence")
    ml = r["ml_display"] if r["ml_computable"] else "n/a (not computable)"
    return (f"| {r['segment']} | {r['open_deals']} | {r['open_pipeline_display']} "
            f"| {r['bottoms_up_rep_display']} | {r['bottoms_up_manager_display']} | {ml} "
            f"| {r['cro_adjusted_display']} | {r['lens_spread_display']} | {flag} |")


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
      f"children of this node have a computable actual"
      f"{'' if cov['is_genuine_sibling_comparison'] else ' (single-candidate read, no sibling comparison)'}.")
    if l2 is None:
        a("- **Layer 2 outlier:** none identified - no child of this node has a computable "
          "actual with a usable trailing baseline. The Layer-1 variance stands alone.")
    else:
        dev = _fmt_pct(l2.get("deviation_pct"))
        a(f"- **Layer 2 outlier:** {l2['label']} (layer {l2['layer']}) - "
          f"{_fmt_generic(l2.get('value'))} this period vs. a "
          f"{_fmt_generic(l2.get('baseline'))} trailing baseline ({dev}), ranked by "
          f"{str(l2.get('comparison_basis')).replace('_', ' ')}; computability: "
          f"{l2['computability']}.")
        if l2.get("cross_reference_to"):
            a(f"  - Cross-reference to {l2.get('cross_reference_label') or l2['cross_reference_to']} "
              f"under Growth, not an independent driver.")

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
        a(f"- **Layer 3:** not reached - Layer-3 evidence hangs off a Layer-2 outlier and "
          f"none was identified. The branch is {depth} layers deep in the tree.")
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
        a(f"- **Layer 3:** none - this branch is {depth} layers deep in the metric tree.")
    else:
        a(f"- **Layer 3:** the tree has Layer-3 children here (branch depth {depth}), but "
          "none is computable from the reporting tables this period.")

    for n in entry.get("notes", []):
        a(f"- Note: {n}")
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


def verify_source_trace(readout: Dict[str, Any], diagnostic: dict,
                        as_of_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """Field-by-field re-check that the readout introduced no number of
    its own. Every scorecard value, drill-down variance and watchlist row
    is compared for exact equality against `diagnostic`, the engine output
    it was assembled from; the playbook-triggers section gets the same
    treatment against a freshly-run analytics/playbook_triggers.py. Grain:
    one check per assertion. Returns a list of {name, passed, detail}
    rather than raising, so a validator can see every failure at once.
    as_of_date is only needed for the playbook-triggers re-check; when
    omitted, that one check is skipped rather than failed."""
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

    nc_rows = [r["metric_key"] for r in rows if r["status"] == NODE_STATUS_NOT_COMPUTABLE]
    nc_engine = list(sc.loc[sc["status"] == NODE_STATUS_NOT_COMPUTABLE, "metric_key"])
    nc_section = readout["layer1_scorecard"]
    check("not_computable_count_matches_scorecard_status",
          nc_section["nodes_not_computable"] == len(nc_rows) == len(nc_engine)
          and nc_section["nodes_not_computable_keys"] == nc_rows == nc_engine,
          f"section reports {nc_section['nodes_not_computable']} "
          f"({nc_section['nodes_not_computable_keys']}); rows with status "
          f"'Not computable': {nc_rows}; engine: {nc_engine}")

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

    fsec = readout["forecast"]
    period_end = readout["header"]["reporting_period_end"]
    status_problem = _forecast_status_problem(fsec, period_end)
    check("forecast_section_is_built_and_declares_its_status", status_problem is None,
          "forecast is built: the section must be `present`, or `unavailable` with a specific "
          "reason, a detail and no figures -- never not_yet_built, never omitted; its forecast "
          f"call must not be after the period end; {status_problem}")

    fc_ok, fc_detail = _verify_forecast_trace(fsec, period_end)
    check("forecast_traces_exactly_to_a_fresh_run", fc_ok, fc_detail)

    check("playbook_triggers_section_is_built_and_present",
          readout["playbook_triggers"]["status"] == STATUS_PRESENT,
          "playbook triggers (Wave 4) is now built; the readout must reflect that status, "
          f"got {readout['playbook_triggers']['status']!r}")

    if as_of_date is not None:
        fresh_triggers = pbt.run_playbook_triggers(as_of_date)
        pt_mismatch = []
        readout_pt = readout["playbook_triggers"]["triggers"]
        if len(readout_pt) != len(fresh_triggers):
            pt_mismatch.append(f"row count {len(readout_pt)} != {len(fresh_triggers)}")
        else:
            for got, exp in zip(readout_pt, fresh_triggers.to_dict(orient="records")):
                for field in ("rule_id", "account_id", "resulting_action"):
                    if got[field] != exp[field]:
                        pt_mismatch.append(f"{field}: {got[field]!r} != {exp[field]!r}")
                if got["timestamp"] != _none_if_nan(exp["timestamp"]):
                    pt_mismatch.append(f"timestamp: {got['timestamp']!r} != {exp['timestamp']!r}")
        check("playbook_triggers_trace_exactly_to_a_fresh_run",
              not pt_mismatch, "; ".join(pt_mismatch))

    slot_ok, slot_detail = es.verify_slot(readout)
    check("executive_summary_slot_honors_contract", slot_ok,
          "the executive summary must be generated (passing grounding validation, input_hash "
          "matching this readout) or explicitly not_generated/validation_failed with no prose "
          "published; got: " + slot_detail)

    return checks


def _forecast_status_problem(fsec: Dict[str, Any], period_end_iso: str) -> Optional[str]:
    """None when the forecast section honestly declares a status the built
    artifact allows; otherwise what is wrong with it."""
    status = fsec.get("status")
    if status not in (STATUS_PRESENT, STATUS_UNAVAILABLE):
        return f"status {status!r} is neither present nor unavailable"
    if status == STATUS_UNAVAILABLE:
        if fsec.get("reason") not in (REASON_NO_FORECAST_CALL, REASON_NO_OPEN_DEALS):
            return f"unavailable without a specific reason code (got {fsec.get('reason')!r})"
        if not fsec.get("detail"):
            return "unavailable without a detail"
        if "segments" in fsec:
            return "an unavailable section must carry no forecast figures"
    call = fsec.get("forecast_as_of_date")
    if call is not None and call > period_end_iso:
        return f"forecast call {call} is after the period end {period_end_iso}"
    return None


_FORECAST_NUMERIC_FIELDS = (
    "open_deals", "open_pipeline_amount", "deals_without_submission", "bottoms_up_rep",
    "bottoms_up_manager", "ml", "deals_priced_structurally", "cro_adjustment_amount",
    "cro_adjusted", "cro_adjusted_ml_forecast", "lenses_computable", "lens_max", "lens_min",
    "lens_mean", "lens_spread_pct")
_FORECAST_EXACT_FIELDS = (
    "segment", "period", "ml_computable", "has_logged_cro_adjustment", "diverges_materially",
    "widest_pair", "cro_reason")


def _verify_forecast_trace(fsec: Dict[str, Any], period_end_iso: str) -> Tuple[bool, str]:
    """Re-selects the forecast call and re-runs analytics/forecast.py from
    scratch, then compares the readout's forecast section to that fresh run
    at exact equality (no tolerance: assembly does no arithmetic). Also
    confirms the selection, the lens set, the divergence threshold, the
    ML-lens context and the caveat text are the forecast artifact's own."""
    problems: List[str] = []
    period_end = date.fromisoformat(period_end_iso)
    call = fc.latest_forecast_call_date(period_end)
    got_call = fsec.get("forecast_as_of_date")
    if got_call != (call.isoformat() if call else None):
        problems.append(f"forecast call {got_call!r} != freshly selected {call!r}")
    if (fsec.get("selection") or {}).get("forecast_call_date") != got_call:
        problems.append("selection.forecast_call_date differs from forecast_as_of_date")

    if call is None:
        if fsec["status"] != STATUS_UNAVAILABLE or fsec.get("reason") != REASON_NO_FORECAST_CALL:
            problems.append(f"no forecast call exists by {period_end}, yet section is "
                            f"{fsec['status']}/{fsec.get('reason')}")
        return not problems, "; ".join(problems)

    run = fc.run_forecast(call)
    recon = run["reconciliation"]
    if recon.empty:
        if fsec["status"] != STATUS_UNAVAILABLE or fsec.get("reason") != REASON_NO_OPEN_DEALS:
            problems.append(f"fresh run has no reconciliation rows, yet section is "
                            f"{fsec['status']}/{fsec.get('reason')}")
        return not problems, "; ".join(problems)

    if fsec["status"] != STATUS_PRESENT:
        return False, f"fresh run has {len(recon)} reconciliation row(s), yet section is " \
                      f"{fsec['status']}"
    if fsec["period"] != run["period"]:
        problems.append(f"period {fsec['period']!r} != {run['period']!r}")
    if fsec["call_to_quarter_end_days"] != _days_to_quarter_end(call):
        problems.append("call_to_quarter_end_days differs from the calendar")
    got_rows = fsec["segments"]
    fresh_rows = recon.to_dict(orient="records")
    if len(got_rows) != len(fresh_rows):
        problems.append(f"segment rows {len(got_rows)} != {len(fresh_rows)}")
    else:
        for got, exp in zip(got_rows, fresh_rows):
            for f_ in _FORECAST_NUMERIC_FIELDS:
                if not _same_number(got[f_], exp[f_]):
                    problems.append(f"{exp['segment']}.{f_}: {got[f_]!r} != {exp[f_]!r}")
            for f_ in _FORECAST_EXACT_FIELDS:
                if _none_if_nan(exp[f_]) != got[f_]:
                    problems.append(f"{exp['segment']}.{f_}: {got[f_]!r} != {exp[f_]!r}")
    if sorted(fsec["lens_labels"]) != sorted(fc._LENS_COLUMNS):
        problems.append("lens set differs from the forecast artifact's four lenses")
    ml_fresh = _ml_lens_payload(run["model"])
    if fsec["ml_lens"] != json.loads(json.dumps(ml_fresh, default=_json_default)):
        problems.append("ml_lens context differs from the fresh run's")
    if fsec["divergence_threshold"] != fc._DIVERGENCE_THRESHOLD:
        problems.append("divergence_threshold differs from the forecast artifact's")
    if fsec["caveats"] != list(fc.FORECAST_CAVEATS):
        problems.append("caveats differ from the forecast artifact's FORECAST_CAVEATS")
    if fsec["data_window_note"] != run["data_window"]["note"]:
        problems.append("data_window_note differs from the forecast artifact's")
    return not problems, "; ".join(problems)


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
    the forecast section rendered per its status (its lens table matching
    the payload, or an unavailable reason with no figures), and the
    executive summary rendered as exactly what its status says (validated
    statements, or a not-generated note with no prose). Grain: one check
    per assertion."""
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
    check("playbook_triggers_section_rendered_with_its_count",
          f"## Automated playbook triggers ({readout['playbook_triggers']['count']})" in markdown,
          "the rendered heading must carry the same count as the structured payload")
    fsec = readout["forecast"]
    if fsec["status"] == STATUS_PRESENT:
        forecast_rendered = (
            "## Forecast" in markdown
            and f"**Forecast call:** {fsec['forecast_as_of_date']} " in markdown
            and f"covering {fsec['period']} " in markdown
            and f"{fsec['call_to_quarter_end_days']} days before that quarter ends" in markdown)
        forecast_detail = "a present forecast must render its section heading, call date and quarter"
    else:
        forecast_rendered = (
            "## Forecast" in markdown
            and f"**Status: {fsec['status']} ({fsec['reason']}).**" in markdown
            and "Forecast call:" not in markdown)
        forecast_detail = ("an unavailable forecast must render its status and reason and no "
                           "forecast figures")
    check("forecast_section_rendered_per_status", forecast_rendered, forecast_detail)
    slot = readout["executive_summary"]
    if slot["status"] == es.STATUS_GENERATED:
        missing_statements = [s["text"][:60] for s in slot["statements"]
                              if s["text"] not in markdown]
        rendered_ok = not missing_statements and slot["input_hash"][:12] in markdown
        detail = f"generated statements missing from the document: {missing_statements}"
    else:
        rendered_ok = (f"Executive summary: {slot['status'].replace('_', ' ')} "
                       f"({slot.get('reason')})") in markdown and \
            not any(s.get("text", "") in markdown for s in slot.get("statements", []))
        detail = "a non-generated summary must render its status and reason and publish no prose"
    check("executive_summary_rendered_per_status", rendered_ok, detail)
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
    summary_line = _scorecard_summary_line(readout["layer1_scorecard"])
    check("scorecard_rendered_values_match_structured_payload",
          not scorecard_mismatches and summary_line in markdown,
          f"rows whose rendered value/comparison/variance/status did not match "
          f"the structured payload verbatim: {scorecard_mismatches}; node-count line "
          f"rendered: {summary_line in markdown}")

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

    playbook_trigger_mismatches = []
    for r in readout["playbook_triggers"]["triggers"]:
        expected = (f"| {r['rule_id']} | {r['account_id']} | {r['timestamp']} "
                    f"| {r['resulting_action']} | {r['outcome'] or 'pending'} |")
        if expected not in markdown:
            playbook_trigger_mismatches.append((r["rule_id"], r["account_id"]))
    check("playbook_triggers_rendered_values_match_structured_payload",
          not playbook_trigger_mismatches,
          f"trigger rows whose rendered line did not match the structured payload verbatim: "
          f"{playbook_trigger_mismatches}")

    forecast_mismatches = []
    if fsec["status"] == STATUS_PRESENT:
        for r in fsec["segments"]:
            flag = (f"diverges materially (widest: {r['widest_pair_display']})"
                    if r["diverges_materially"] else "no material divergence")
            ml_cell = r["ml_display"] if r["ml_computable"] else "n/a (not computable)"
            expected = (f"| {r['segment']} | {r['open_deals']} | {r['open_pipeline_display']} "
                        f"| {r['bottoms_up_rep_display']} | {r['bottoms_up_manager_display']} "
                        f"| {ml_cell} | {r['cro_adjusted_display']} | {r['lens_spread_display']} "
                        f"| {flag} |")
            if expected not in markdown:
                forecast_mismatches.append(r["segment"])
            if f"- **{r['segment']}:** {r['cro_display']}." not in markdown:
                forecast_mismatches.append(f"{r['segment']} CRO line")
        ml = fsec["ml_lens"]
        if ml["computable"]:
            ml_expected = (f"out-of-time holdout AUC {ml['auc_holdout']:.3f} against a "
                           f"{ml['auc_target_range'][0]:.2f}-{ml['auc_target_range'][1]:.2f} "
                           f"target")
            if ml_expected not in markdown or f"held out on {ml['n_test']:,}" not in markdown:
                forecast_mismatches.append("ML lens context")
        elif "**ML lens:** not computable" not in markdown:
            forecast_mismatches.append("ML lens not-computable statement")
        for c in fsec["caveats"]:
            if f"- {c}" not in markdown:
                forecast_mismatches.append("caveat: " + c[:40])
    check("forecast_rendered_values_match_structured_payload",
          not forecast_mismatches,
          f"forecast rows or lines whose rendering did not match the structured payload "
          f"verbatim: {forecast_mismatches}")

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
    that the narrative step (analytics/executive_summary.py) and the
    dashboard consume. One file pair per as_of_date."""
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


def _prior_executive_summary(as_of_date: date, out_dir: str) -> Optional[Dict[str, Any]]:
    """The executive_summary slot of the readout JSON already on disk for
    this as_of_date, if any -- so re-assembling the readout never discards
    a generated summary whose input has not changed."""
    path = es.readout_json_path(as_of_date, out_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f).get("executive_summary")
    except (OSError, ValueError):
        return None


def run_build_time_validation(as_of_date: date, threshold: float = vd._VARIANCE_THRESHOLD,
                              watchlist_top_n: int = 25, write: bool = True,
                              log: bool = True, out_dir: str = _OUTPUT_DIR) -> Dict[str, Any]:
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
    # (the forecast section ran forecast.run_forecast() itself; the trace check
    # below runs it again from scratch, so the comparison is between two
    # independent runs, not one object compared with itself)
    # No API call here: carry forward a still-valid generated summary, or
    # leave the slot honestly not_generated (reason no_api_key / pending).
    readout["executive_summary"] = es.offline_slot(
        readout, _prior_executive_summary(as_of_date, out_dir))
    markdown = render_markdown(readout)
    trace_checks = verify_source_trace(readout, diagnostic, as_of_date=as_of_date)
    render_checks = verify_rendered_document(markdown, readout)
    all_checks = trace_checks + render_checks
    passed = sum(c["passed"] for c in all_checks)

    paths = write_readout(readout, markdown, out_dir) if write else {}

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
        log_performance(_MODEL_NAME, as_of_date, "playbook_triggers_fired",
                        float(readout["playbook_triggers"]["count"]))
        log_performance(_MODEL_NAME, as_of_date, "sections_not_yet_built",
                        float(sum(1 for s in _REQUIRED_SECTIONS
                                  if isinstance(readout[s], dict)
                                  and readout[s].get("status") == STATUS_NOT_YET_BUILT)))
        log_performance(_MODEL_NAME, as_of_date, "forecast_section_available",
                        1.0 if readout["forecast"]["status"] == STATUS_PRESENT else 0.0)

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
    print(f"Playbook triggers          : {out['readout']['playbook_triggers']['status']} "
          f"({out['readout']['playbook_triggers']['count']} fired)")
    _f = out["readout"]["forecast"]
    print(f"Forecast                   : {_f['status']}"
          f"{' (call ' + _f['forecast_as_of_date'] + ', ' + _f['period'] + ')' if _f['status'] == STATUS_PRESENT else ' (' + _f['reason'] + ')'}")
    slot = out["readout"]["executive_summary"]
    print(f"Executive summary          : {slot['status']}"
          f"{' (' + slot['reason'] + ')' if slot.get('reason') else ''}")
    print()
    for c in out["trace_checks"] + out["render_checks"]:
        print(f"[{'PASS' if c['passed'] else 'FAIL'}] {c['name']}"
              f"{'' if c['passed'] else '  -- ' + c['detail']}")
    print(f"\n{out['checks_passed']}/{out['checks_total']} checks passed")
    for kind, path in out["paths"].items():
        print(f"wrote {kind}: {path}")
