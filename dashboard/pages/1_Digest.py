"""Digest -- renders analytics/weekly_readout.py's own generated output
verbatim (analytics/outputs/weekly_readout_<date>.json). This page adds no
computation of its own: every number here is read straight from the
readout artifact, which is itself read straight from
variance_diagnostic.run_diagnostic(), analytics/forecast.py and
health_score.py's scored output.

Audience tier: CRO / exec (dashboard-design-conventions.md Section 4.1's
own worked example for this tier). Layout follows Section 4.3's
inverted-pyramid order top to bottom:
  1. Verdict row      -- Layer-1 scorecards by pillar
  2. What changed     -- drill-downs (breaching nodes only, never padded)
  3. What's coming    -- the readout's forecast section (Commercial and
                          Enterprise, quarter grain), or its honest
                          unavailable state
  4. What needs a decision -- watchlist + playbook triggers
  5. Everything else  -- the segment-mix context block (below the decision
                          tier so context never pushes the actions down,
                          Section 5.1), the rule catalog and the single Notes
                          & assumptions expander (Section 11.3), never
                          rendered flat.

Every Layer label shown (1/2/3) is the readout JSON's own `layer` field,
which is itself sourced from docs/acme-corp-gtm-metric-tree.md -- this
page never relabels or re-derives a layer depth.
"""
import os
import sys

import pandas as pd
import streamlit as st

_DASHBOARD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DASHBOARD_DIR)
import theme
from lib import (answers, data, drilldown_view, exec_summary_view, forecast_logic, forecast_view, labels,
                 persistence_view, segment_mix_render, verdict)

theme.page_config("Digest | Acme Corp GTM", "\U0001F4CB")
theme.inject_global_css()

# Formulas transcribed verbatim from docs/acme-corp-gtm-metric-tree.md
# (the New logo / Expansion / Efficiency / Durability formula lines) --
# display-only citation for the Section 6 "show the formula" requirement,
# never a re-derivation. Contraction+churned revenue has no single
# multiplicative formula in the tree (it's described qualitatively), so
# its entry is the tree's own driver list instead of a formula.
LAYER1_FORMULA = {
    "new_logo_consumption_revenue": "Pipeline generated × Win rate × Avg initial commitment",
    "activation": "Days from provisioning to first production Action (TTFA)",
    "expansion_consumption_revenue": "Wallet share progression × Overage realization",
    "contraction_churned_revenue": (
        "Driven by workflow chain under-utilization, account health score, "
        "cyclical/structural usage dip and renewal win rate; the tree gives no "
        "single multiplicative formula for this node"
    ),
    "magic_number": "Net new ARR ÷ prior-period S&M cost",
    "consumption_payback": "CAC ÷ utilized-Action margin",
    "onboarding_cs_efficiency": "Manual AM/CS touchpoints ÷ volume of automated Actions delivered",
    "am_efficiency": "Expansion consumption revenue ÷ AM cost",
    "nrr": "(Starting − Contraction − Churn + Expansion) ÷ Starting consumption revenue",
    "grr": "(Starting − Contraction − Churn) ÷ Starting consumption revenue",
    "logo_retention": "Retained accounts ÷ Starting accounts",
}

PILLAR_LABEL = {"growth": "Growth", "efficiency": "Efficiency", "durability": "Durability"}


def _missing(v) -> bool:
    return verdict.missing(v)


st.title("Weekly executive readout")
theme.override_banner()
st.caption("Layer-1 scorecard, drivers, forecast and actions for the selected as-of date.")

readout_dates = data.list_readout_dates()
if not readout_dates:
    st.warning("No weekly readout has been generated yet.")
    st.stop()

title_col, control_col = st.columns([3, 1])
with control_col:
    as_of = st.selectbox(
        "As-of date", readout_dates, format_func=lambda d: d.isoformat(),
        help="One entry per date the weekly readout has been generated for.",
    )

readout = data.load_readout(as_of)
header = readout["header"]
scorecard = readout["layer1_scorecard"]
forecast = readout["forecast"]
threshold_pct = header["variance_threshold"] * 100
baseline_months = header.get("trailing_baseline_months")

with title_col:
    st.subheader(header["reporting_period_label"])

n_caveated = sum(1 for r in scorecard["rows"] if verdict.is_caveated(r))

# --- Standing requirement (Section 7): as-of date, grain, and threshold
# visible in a prominent info row, not buried in a settings panel. ---
theme.info_row([
    ("Audience", header["audience"]),
    ("As-of date", header["as_of_date"]),
    ("Grain", "Monthly"),
    ("Variance threshold", f"±{threshold_pct:.0f}%"),
    ("Nodes tracked",
     f'{scorecard["nodes_total"]} · {scorecard["nodes_breaching_threshold"]} breaching '
     f'({n_caveated} caveated) · {scorecard["nodes_not_computable"]} not computable'),
])

# --- Executive summary (Section 4.2/4.8: a generated exec summary is expected on
# this tier; Section 7: never render it unless it is real). The display
# decision lives in lib/exec_summary_view.display_state() -- prose comes back
# ONLY for status == generated AND validation.passed AND an input_hash that
# matches this readout; every other state carries no statements at all. ---
st.markdown("#### Executive summary")
summary_view = exec_summary_view.display_state(readout.get("executive_summary"), readout)
if summary_view["kind"] == exec_summary_view.KIND_GENERATED:
    cite_labels = {r["metric_key"]: r["label"] for r in scorecard["rows"]}
    lead, *rest = summary_view["statements"]
    # Completeness honesty (Section 7): while project_status.json still lists the
    # narrative artifact as anything short of built_and_validated, a generated-looking
    # block must say so on its face. Disappears by itself once the status flips.
    comp_status = theme.component_status("executive_summary_narrative")["status"]
    status_suffix = (
        "" if comp_status == "built_and_validated"
        else f" · narrative step status: {comp_status.replace('_', ' ')} (not yet independently validated)"
    )
    body = "".join(
        f'<p style="margin:0 0 10px 0;font-size:0.95rem;line-height:1.5;">{exec_summary_view.safe_html(s["text"])}</p>'
        for s in rest
    )
    theme.card_block(
        f'<p style="margin:0 0 12px 0;font-size:1.1rem;font-weight:500;line-height:1.45;">'
        f'{exec_summary_view.safe_html(lead["text"])}</p>'
        f'{body}'
        f'<div class="breadcrumb" style="margin-top:4px;">'
        f'{exec_summary_view.safe_html(summary_view["provenance"] + status_suffix)}</div>'
    )
    with st.expander("Sources and checks"):
        for i, stmt in enumerate(summary_view["statements"], start=1):
            chips = "".join(
                f'<span class="source-chip">{exec_summary_view.safe_html(exec_summary_view.format_cite(c, cite_labels))}</span>'
                for c in stmt["cites"]
            )
            st.markdown(f'<div class="source-row"><span class="breadcrumb">Statement {i}</span> {chips}</div>',
                        unsafe_allow_html=True)
        st.caption(
            f"{summary_view['checks_passed']} of {summary_view['checks_total']} automated checks passed "
            f"(prompt {summary_view['prompt_version']}). The checks confirm that each figure, date and "
            "account ID matches the readout. They do not confirm the explanation drawn from those "
            "figures: the drill-down ranks deviation from a trailing baseline, which locates a miss "
            "and does not establish its cause."
        )
        st.caption(" · ".join(
            f"{'✓' if c['passed'] else '✗'} {c['name'].replace('_', ' ')}" for c in summary_view["checks"]
        ))
else:
    # No prose, no placeholder text that could be mistaken for a summary:
    # status line + plain-language reason up front. The expander is reader-facing:
    # the reason, what is needed, and the component's status label. How to run the
    # step lives in dashboard/README.md, not on the page.
    st.info(f"**{theme.escape_md(summary_view['headline'])}.** {theme.escape_md(summary_view['reason_text'])}")
    with st.expander("Why this is blank"):
        st.write(f"**Reason:** {theme.escape_md(summary_view['reason_text'])}")
        st.write(f"**Needed:** {theme.escape_md(summary_view['needed_text'])}")
        st.write(f"**Status:** {theme.status_label('executive_summary_narrative')}")
        if summary_view["failed_checks"]:
            st.write("**Checks that failed:** " + ", ".join(c.replace("_", " ") for c in summary_view["failed_checks"]))

st.divider()

# Notes & assumptions accumulate here as sections render and are shown once,
# at the bottom of the page (Section 11.3).
notes = []
_seen_note_text = set()


def add_note(kind: str, text: str, prefix: str = "") -> None:
    """Append a Notes & assumptions line unless the same note text was
    already added (the readout repeats a metric's plan-comparability note
    inside its drill-down)."""
    if text in _seen_note_text:
        return
    _seen_note_text.add(text)
    notes.append((kind, f"{prefix}{text}"))

# =====================================================================
# 1. VERDICT ROW -- Layer-1 scorecards by pillar (Section 4.3, item 1)
# =====================================================================
st.markdown("#### Verdict — Layer-1 scorecard")
st.caption("Layer-1 metrics by pillar, latest complete month against plan. "
           "Each card states its basis: a single month or a trailing 12 months.")
notes.append(("Scope", header["reporting_period_grain_note"]))
dw = readout.get("data_window") or {}
if dw.get("evaluation_month") and dw.get("last_month_in_marts") and dw["evaluation_month"] != dw["last_month_in_marts"]:
    notes.append(("Scope", f"The scorecard month is {dw['evaluation_month'][:7]}; the data extends to "
                           f"{dw['last_month_in_marts'][:7]}, which is a truncated final month."))
notes.append(("Scope", "Status color is set per metric from its favorable direction against plan, not "
                       "from the sign of the variance."))
notes.append(("Scope", "A card tagged Caveated comparison shows its gap to plan without a status color or "
                       "arrow: the plan and the actual are not on the same footing, so the gap is not a "
                       "business finding on its own."))
notes.append(("Scope", "Dollar movements, Consumption payback, Onboarding/CS efficiency and Activation are "
                       "single-month figures. Magic number, AM efficiency, NRR, GRR and Logo retention are "
                       "trailing-12-month figures. Segment Efficiency shows single-month values, so the "
                       "same metric reads differently there."))

cards_by_key = {}
for pillar in ["growth", "efficiency", "durability"]:
    pillar_rows = [r for r in scorecard["rows"] if r["pillar"] == pillar]
    if not pillar_rows:
        continue
    breaching_n = sum(1 for r in pillar_rows if r["breaches_threshold"])
    caveated_n = sum(1 for r in pillar_rows if verdict.is_caveated(r))
    dot = theme.PILLAR_COLOR[pillar]
    caveat_text = f", {caveated_n} caveated" if caveated_n else ""
    st.markdown(
        f'<div style="margin-top:14px"><span class="pillar-dot" style="background-color:{dot}"></span>'
        f'<strong>{PILLAR_LABEL[pillar]}</strong> '
        f'<span class="breadcrumb">({breaching_n} of {len(pillar_rows)} breaching ±{threshold_pct:.0f}%{caveat_text})</span></div>',
        unsafe_allow_html=True,
    )
    cards = []
    for row in pillar_rows:
        card = verdict.card_for_row(row, pillar, baseline_months)
        cards_by_key[row["metric_key"]] = card
        cards.append(card)
    theme.scorecard_row(cards)
    # Per-metric notes go to the page's single Notes & assumptions section.
    for row in pillar_rows:
        for field, kind in (("gap_note", "Data gap"), ("plan_comparability_note", "Scope")):
            note = row.get(field)
            if not _missing(note):
                if field == "plan_comparability_note" and row["status"] == "Not computable":
                    kind = "Data gap"
                add_note(kind, note, prefix=f"{row['label']}: ")

st.divider()

# =====================================================================
# 2. WHAT CHANGED -- drill-downs (Section 4.3, item 2; Section 6)
# =====================================================================
st.markdown("#### What changed")
drilldowns = readout["drilldowns"]
st.caption(
    f"{drilldowns['count']} drill-downs: one per Layer-1 metric outside the "
    f"±{threshold_pct:.0f}% threshold."
)

for entry in drilldowns["entries"]:
    l1 = entry["layer1"]
    l2 = entry["layer2_outlier"]
    pillar = l1["pillar"]
    dot = theme.PILLAR_COLOR.get(pillar, theme.NEUTRAL_GRAY)
    l1_caveated = cards_by_key.get(l1["metric_key"], {}).get("tag") == verdict.CAVEAT_TAG
    # A caveated gap is not a verdict, so its breadcrumb carries no Ahead/Behind word.
    l1_state = f'{l1["variance_display"]}, caveated comparison' if l1_caveated else f'{l1["status"]}, {l1["variance_display"]}'
    l2_label = labels.qualified_node_label(l2["metric_key"], l2["label"]) if l2 else None
    persist = persistence_view.state(entry.get("persistence"))
    breadcrumb = (
        f'{PILLAR_LABEL.get(pillar, pillar.title())} › Layer 1: {l1["label"]} '
        f'({l1_state}) › Layer 2: '
        + (f'{l2_label} is the outlier' if l2 else "no computable outlier")
    )
    with st.expander(breadcrumb):
        # The repeat chip is neutral gray: it marks a repeated driver, not a status.
        st.markdown(
            f'<span class="pillar-dot" style="background-color:{dot}"></span>'
            f'<span class="breadcrumb">{PILLAR_LABEL.get(pillar, pillar.title())} › '
            f'{l1["label"]}</span>'
            + (theme.neutral_chip(persist["chip"]) if persist["chip"] else ""),
            unsafe_allow_html=True,
        )
        st.caption(f'Layer-1 formula: {LAYER1_FORMULA.get(l1["metric_key"], "not defined as a formula in the tree")}')

        # The Layer-1 card here is the verdict row's own card (same status, same
        # caveat treatment), never a re-derived neutral one.
        l1_card = cards_by_key.get(l1["metric_key"])
        if l1_card is None:
            l1_card = dict(label=l1["label"], value_display=l1["value_display"], pillar=pillar,
                           comparison_display=l1["comparison_display"], variance_display=l1["variance_display"],
                           favorable_direction=None, is_ahead=verdict.is_ahead_for(l1["status"]),
                           footer=[f"Layer {l1['layer']}"])
        if l2:
            l2_card = dict(
                label=l2_label, pillar=pillar,
                value_display=answers.format_for_key(l2["metric_key"], l2["value"]),
                comparison_display=f"vs {answers.format_for_key(l2['metric_key'], l2['baseline'])} trailing baseline",
                variance_display=f'{l2["deviation_pct"] * 100:+.1f}%',
                footer=["Deviation from its own trailing baseline; no plan at this layer", f"Layer {l2['layer']}"],
            )
            theme.scorecard_row([l1_card, l2_card])
        else:
            theme.scorecard_row([l1_card])
            st.info("No Layer-2 child has a computable actual with a usable baseline.")

        # Repeat marker: the engine's record, shown verbatim (lib/persistence_view.py).
        st.markdown("**Repeat marker**")
        st.caption(theme.escape_md(persist["line"]))
        if persist["caveat"]:
            st.caption(theme.escape_md(persist["caveat"]))
        if persist["note"]:
            st.caption(theme.escape_md(persist["note"]))
        if persist["break_text"]:
            st.caption(theme.escape_md(persist["break_text"]))
        if persist["rows"]:
            st.dataframe(pd.DataFrame(persist["rows"]), hide_index=True, width="stretch")
        for line in (persist["adverse_direction"], persist["basis_line"]):
            if line:
                st.caption(theme.escape_md(line))

        l3_status = entry.get("layer3_status")
        l3_rank = entry.get("layer3_ranking") or []
        if l3_status == "branch_depth_2":
            st.caption("Layer 3: this branch has no Layer-3 children in the tree; depth stops at Layer 2.")
        elif l3_rank:
            st.markdown("**Layer 3 evidence**")
            # The caption states the basis the rank was computed on (the rows' own
            # comparison_basis), not a fixed phrase: additive branches rank on absolute change.
            st.caption(drilldown_view.caption(l3_rank, 3))
            parent_label = {l2["metric_key"]: l2_label} if l2 else {}
            st.dataframe(pd.DataFrame(drilldown_view.table_dict(
                l3_rank, lambda x: labels.qualified_node_label(x["metric_key"], x["label"]),
                label_header="Metric (Layer 3)",
                extra={"Under": [parent_label.get(x.get("parent_key")) or labels.humanize(x.get("parent_key") or "")
                                 for x in l3_rank]},
            )), hide_index=True, width="stretch")
        elif entry.get("layer3_evidence"):
            st.markdown("**Layer 3 evidence**")
            ev_df = pd.DataFrame(entry["layer3_evidence"])
            parent_label = {l2["metric_key"]: l2["label"]} if l2 else {}
            if "parent_key" in ev_df.columns:
                ev_df["parent_key"] = ev_df["parent_key"].map(lambda k: parent_label.get(k) or labels.humanize(k))
            for col in ("value", "baseline"):
                if col in ev_df.columns and "metric_key" in ev_df.columns:
                    ev_df[col] = [answers.format_for_key(k, v) for k, v in zip(ev_df["metric_key"], ev_df[col])]
            ev_df = ev_df[[c for c in ev_df.columns if c not in labels.HIDDEN_FIELDS]]
            ev_df = ev_df.rename(columns={c: labels.field_label(c) for c in ev_df.columns})
            st.dataframe(ev_df, hide_index=True, width="stretch")
        else:
            st.caption("Layer 3: no computable evidence for this branch this period.")

        if entry.get("sibling_ranking"):
            sib = entry["sibling_ranking"]
            st.caption(drilldown_view.caption(sib, 2).replace("drivers", "siblings", 1))
            sib_df = pd.DataFrame(drilldown_view.table_dict(
                sib, lambda x: labels.qualified_node_label(x["metric_key"], x["label"]),
                label_header="Metric (Layer 2)"))
            st.dataframe(sib_df, hide_index=True, width="stretch")

        missing = entry.get("sibling_coverage", {}).get("missing_siblings") or []
        if missing:
            st.caption("Not in the ranking (no data): " + ", ".join(labels.clean_node_label(m["label"]) for m in missing))
        for note in entry.get("notes") or []:
            add_note("Scope", note, prefix=f"{l1['label']} drill-down: ")

for persistence_scope in persistence_view.scope_notes(drilldowns["entries"]):
    notes.append(("Scope", persistence_scope))

st.divider()

# =====================================================================
# 3. WHAT'S COMING -- forecast (Section 4.3, item 3)
# Rendered from the readout's own forecast section, verbatim: no figure
# is recomputed here. Grain is quarterly and labeled as such, separate
# from the monthly scorecard above (Section 8).
# =====================================================================
st.markdown("#### What's coming — forecast")
fstatus = forecast.get("status")
if fstatus == "present":
    labels_map = forecast["lens_labels"]
    seg_names = " and ".join(r["segment"] for r in forecast["segments"]) or "no segment"
    theme.info_row([
        ("Forecast call", forecast["forecast_as_of_date"]),
        ("Quarter", forecast["period"]),
        ("Days to quarter end", str(forecast["call_to_quarter_end_days"])),
        ("Grain", f"Quarterly, {seg_names}"),
    ])
    st.caption("No plan comparison: no plan or quota is published at this grain and unit. "
               "The divergence flag between lenses is the comparison shown.")
    thr = forecast.get("divergence_threshold")
    proposed = "proposed" in str(forecast.get("divergence_threshold_status", "")).lower()
    thr_text = (f"Threshold: spread above {thr:.0%} of the mean" + (" (proposed, not confirmed)" if proposed else "")
                if thr is not None else None)
    for i, seg_row in enumerate(forecast["segments"]):
        forecast_view.render_segment(seg_row, labels_map, key=f"digest_forecast_{i}",
                                     divergence_threshold_text=thr_text,
                                     days_left=forecast.get("call_to_quarter_end_days"))
    for seg in forecast.get("segments_without_open_deals") or []:
        st.info(f"{theme.escape_md(seg)}: no open deals with a close in {theme.escape_md(forecast['period'])} at this forecast call, "
                "so no lens values are produced for the segment.")
    st.page_link("pages/2_Forecast.py", label="Open Forecast for other call dates →", icon="\U0001F4C8")

    notes.append(("Scope", f"Forecast call selection: {forecast['selection']['rule']}"))
    notes.append(("Scope", forecast["grain"][0].upper() + forecast["grain"][1:] + "."))
    for lens, text in forecast["lens_definitions"].items():
        notes.append(("Scope", f"{labels_map[lens]} lens: {text}"))
    for caveat in forecast["caveats"]:
        notes.append(("Scope", caveat))
    notes.append(("Assumption", f"Divergence threshold: {forecast['divergence_threshold_status']}."))
    pc = forecast["plan_comparison"]
    notes.append(("Data gap", f"Forecast versus plan is {pc['status'].replace('_', ' ')}. {pc['reason']}"))
    ml = forecast["ml_lens"]
    if ml.get("computable"):
        lo, hi = ml["auc_target_range"]
        _, auc_phrase = forecast_logic.auc_statement(ml["auc_holdout"], lo, hi)
        notes.append(("Scope", (
            f"ML lens: out-of-time holdout AUC {ml['auc_holdout']:.3f}, {auc_phrase}; "
            f"manager-category lookup baseline AUC {ml['manager_lookup_baseline_auc']:.3f}; "
            f"calibration gap {ml['calibration_gap']:+.3f} against ±{ml['calibration_gap_target']:.2f}; "
            f"fitted on {ml['n_train']:,} past forecast calls and held out on {ml['n_test']:,}.")))
    else:
        notes.append(("Data gap", f"ML lens is not computable at this call date: {ml.get('reason')}."))
    notes.append(("Scope", forecast["data_window_note"]))
elif fstatus == "unavailable":
    st.info(theme.escape_md(forecast.get("detail") or "The forecast is unavailable for this readout."))
    with st.expander("Why this is blank"):
        if forecast.get("detail"):
            st.write(f"**Reason:** {theme.escape_md(forecast['detail'])}")
        if forecast.get("forecast_as_of_date"):
            st.write(f"**Forecast call considered:** {forecast['forecast_as_of_date']}")
    st.page_link("pages/2_Forecast.py", label="Open Forecast for other call dates →", icon="\U0001F4C8")
    notes.append(("Data gap", f"Forecast unavailable for this readout: {forecast.get('detail')}"))
    if forecast.get("selection"):
        notes.append(("Scope", f"Forecast call selection: {forecast['selection']['rule']}"))
    for caveat in forecast.get("caveats") or []:
        notes.append(("Scope", caveat))
else:
    st.info("This readout carries no forecast section.")
    notes.append(("Data gap", f"Forecast section status in this readout: {fstatus}."))

st.divider()

# =====================================================================
# 4. WHAT NEEDS A DECISION -- watchlist + playbook triggers
# (Section 4.3, item 4. Tables are the scoped exception recorded in
# Section 4.6: a short ranked list of named accounts, full-width, stacked.)
# =====================================================================
st.markdown("#### What needs a decision")

st.markdown("**Watchlist — churn risk**")
watchlist = readout["watchlist"]
st.caption("High-risk accounts ranked by estimated ARR at risk, then by churn probability.")
wl_df = pd.DataFrame(watchlist["rows"])
if not wl_df.empty:
    st.dataframe(
        wl_df[["rank", "account_id", "segment", "risk_tier", "health_score", "est_arr_at_risk_display"]]
        .rename(columns={
            "rank": "Rank", "account_id": "Account", "segment": "Segment",
            "risk_tier": "Risk tier", "health_score": "Health score",
            "est_arr_at_risk_display": "Est. ARR at risk",
        }),
        hide_index=True, width="stretch", height=280,
    )
notes.append(("Scope", f"Watchlist selection: {watchlist['selection_rule']}"))
for i, caveat in enumerate(watchlist["caveats"]):
    notes.append(("Assumption" if i == 0 else "Scope", f"Watchlist: {caveat}"))

st.markdown("**Automated playbook triggers**")
triggers = readout["playbook_triggers"]
trig_df = pd.DataFrame(triggers["triggers"])
trig_df["timestamp"] = pd.to_datetime(trig_df["timestamp"])
as_of_ts = pd.Timestamp(as_of)
recent = trig_df[trig_df["timestamp"] >= as_of_ts - pd.Timedelta(days=90)]
st.caption(
    f"{len(recent)} triggers fired in the 90 days ending {as_of.isoformat()}; "
    f"{triggers['count']} logged since the start of the data. Rules are binary and unranked."
)
if not recent.empty:
    shown = recent.sort_values("timestamp", ascending=False)[
        ["timestamp", "rule_id", "account_id", "resulting_action"]
    ].copy()
    shown["timestamp"] = shown["timestamp"].dt.date.astype(str)
    shown["rule_id"] = shown["rule_id"].map(labels.rule_label)
    st.dataframe(
        shown.rename(columns={"timestamp": "Date", "rule_id": "Rule", "account_id": "Account",
                              "resulting_action": "Action"}),
        hide_index=True, width="stretch", height=280,
    )
else:
    st.caption("No triggers fired in this window.")
with st.expander(f"Rule catalog ({len(triggers['rules'])} rules)"):
    for rule_id, rule in triggers["rules"].items():
        st.markdown(f"**{labels.rule_label(rule_id)}** — {theme.escape_md(labels.apply_phrase_map(rule['description']))}")
        st.caption(f"Action: {rule['resulting_action']} | Source: {labels.source_label(rule['source_mart'])}")

st.divider()

# =====================================================================
# 5. CONTEXT -- segment mix (Section 4.3: context sits below the decision
# tier, so it never pushes the watchlist down the page; Section 5.1).
# Rendered from the readout's own segment_mix section, verbatim: no share,
# rate or change is recomputed here. Not a metric-tree node, so no Layer label.
# =====================================================================
st.markdown("#### Context — segment mix")
st.caption("Share of company ending MRR by segment against the same month a year earlier, "
           "beside migration between segments over the trailing 12 months.")
mix_state = segment_mix_render.render(readout.get("segment_mix"), key="digest_segment_mix")
if mix_state["kind"] == "unavailable":
    notes.append(("Data gap", f"Segment mix unavailable for this readout: {mix_state['reason_text']}"))
elif mix_state["kind"] == "absent":
    notes.append(("Data gap", "This readout carries no segment mix section."))
for kind, text in mix_state.get("notes") or []:
    add_note(kind, text)

st.divider()
theme.notes_and_assumptions(notes)
