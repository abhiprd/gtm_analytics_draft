"""Forecast -- calls analytics/forecast.py's run_forecast() directly (the
Wave 2 artifact: bottoms-up rep/manager, ML, and CRO-overlay lenses
reconciled per segment for the quarter containing the forecast call). No
forecast math lives in this page; it renders exactly what the artifact
returns, with log=False baked into run_forecast() so viewing the dashboard
never writes to fact_model_performance_history.

Audience: hybrid analyst-with-verdict (dashboard-design-conventions.md
Section 4.5): analyst density (all four lenses visible by default), with each
segment opening on a one-glance verdict (the CRO-adjusted headline and a
divergence badge). The per-segment rendering is shared with the Digest's
forecast section (lib/forecast_view.py), so both pages show the same figures
in the same form for the same forecast call.
"""
import os
import sys
from datetime import date

import pandas as pd
import streamlit as st

_DASHBOARD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_DASHBOARD_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, _DASHBOARD_DIR)
from analytics import forecast as fc
import theme
from lib import data, forecast_logic, forecast_view

theme.page_config("Forecast | Acme Corp GTM", "\U0001F4C8")
theme.inject_global_css()

LENS_LABELS = {
    "bottoms_up_rep": "Bottoms-up (rep)",
    "bottoms_up_manager": "Bottoms-up (manager)",
    "ml": "ML",
    "cro_adjusted": "CRO-adjusted",
}

st.title("Forecast")
theme.override_banner()
st.caption(
    "Commercial and Enterprise. Four lenses per segment — bottoms-up (rep), bottoms-up (manager), "
    "ML and CRO-adjusted — reconciled side by side with a divergence flag."
)


def _readout_forecast_dates() -> dict:
    """{forecast call date -> (readout as-of date, forecast section)} for
    every readout whose forecast section is present."""
    out = {}
    for d in data.list_readout_dates():
        f = (data.load_readout(d) or {}).get("forecast") or {}
        if f.get("status") == "present":
            out[f["forecast_as_of_date"]] = (d, f)
    return out


readout_calls = _readout_forecast_dates()
# Default to the newest readout's forecast call so the Digest and this page
# open on the same figures.
default_date = (date.fromisoformat(max(readout_calls)) if readout_calls else date(2025, 11, 14))
as_of_date = st.date_input(
    "Forecast call date", value=default_date, min_value=date(2023, 6, 1), max_value=date(2025, 12, 20),
    help="Weekly forecast calls run through 2025-12-26. The lenses price the deals open at the "
         "call date whose close lands in the call date's quarter.",
)


@st.cache_data(ttl=600, show_spinner="Training the win-probability model and reconciling lenses...")
def _run(as_of_date: date) -> dict:
    result = fc.run_forecast(as_of_date)
    reconciliation = result["reconciliation"].copy()
    model = result["model"]
    return {
        "period": result["period"],
        "reconciliation": reconciliation,
        "model_computable": model.get("computable"),
        "auc_holdout": model.get("auc_holdout"),
        "meets_auc_target": model.get("meets_auc_target"),
        "n_train": model.get("n_train"),
        "n_test": model.get("n_test"),
        "data_window_note": result["data_window"]["note"],
    }


result = _run(as_of_date)
recon = result["reconciliation"]

# --- Section 7 honesty pattern: quarter, days to quarter end and grain visible up
# front, in the same card grid the Digest's forecast section uses. The call date is
# the control above, shown once. Grain is quarterly by construction (every dollar
# traces to fact_opportunities / fact_forecast_submissions rolled to the quarter of
# a weekly forecast call); no grain toggle is offered (Section 8). ---
days_left = forecast_logic.days_to_quarter_end(result["period"], as_of_date)
theme.info_row([
    ("Quarter", result["period"]),
    ("Days to quarter end", str(days_left) if days_left is not None else "n/a"),
    ("Grain", "Quarterly, Commercial and Enterprise"),
])
st.caption("No plan comparison: no plan or quota is published at this grain and unit. "
           "The divergence flag between lenses is the comparison shown.")

# --- Consistency with the Digest: when this call date is the one a weekly
# readout carries, the two must agree. A difference is reported, never hidden:
# the ML lens within 1% is rebuild noise (informational); any other difference is
# a warning. ---
match = readout_calls.get(as_of_date.isoformat())
if match:
    readout_date, section = match
    findings = forecast_logic.compare_to_readout(
        recon.to_dict("records"), section["segments"], readout_date.isoformat())
    warnings = [f for f in findings if f["severity"] == "warning"]
    infos = [f for f in findings if f["severity"] == "info"]
    if warnings:
        st.warning("Differs from the weekly readout. " + theme.escape_md(" ".join(f["text"] for f in warnings)))
    if infos:
        st.info(theme.escape_md(" ".join(f["text"] for f in infos)))
    if not findings:
        st.caption(f"Matches the weekly readout for the period ending {readout_date.isoformat()} "
                   "(same call date, same figures).")

st.divider()

if recon.empty:
    st.warning("No reconciliation rows returned for this call date.")
    theme.notes_and_assumptions([("Scope", c) for c in fc.FORECAST_CAVEATS])
    st.stop()

for seg_name in ("Commercial", "Enterprise"):
    if seg_name not in set(recon["segment"]):
        st.info(f"{theme.escape_md(seg_name)}: no open deals with a close in {theme.escape_md(result['period'])} at this "
                "forecast call, so no lens values are produced for the segment.")

for i, (_, row) in enumerate(recon.iterrows()):
    forecast_view.render_segment(
        row.to_dict(), LENS_LABELS, key=f"forecast_page_{i}",
        divergence_threshold_text=f"Threshold: spread above {fc._DIVERGENCE_THRESHOLD:.0%} of the mean (proposed, not confirmed)",
        days_left=days_left)
    st.divider()

# --- ML lens quality: model diagnostics, behind an expander so it does not
# crowd the per-segment verdict above. ---
with st.expander("ML lens quality (model diagnostics)"):
    if result["model_computable"]:
        lo, hi = 0.70, 0.85
        pos, phrase = forecast_logic.auc_statement(result["auc_holdout"], lo, hi)
        # Within the range: favorable. Below: unfavorable. Above: not low, so neutral
        # (the range has a ceiling because a very high AUC warrants a leakage check).
        auc_color = {"within": theme.FAVORABLE_GREEN, "below": theme.UNFAVORABLE_RED}.get(pos, theme.NEUTRAL_GRAY)
        auc_glyph = {"within": "●", "below": "▼", "above": "▲"}[pos]
        st.markdown(
            f'Out-of-time holdout AUC '
            f'<span style="color:{auc_color};font-weight:700;">'
            f'{result["auc_holdout"]:.3f} {auc_glyph}</span> '
            f'({phrase}), trained on '
            f'{result["n_train"]} snapshots, held out {result["n_test"]}.',
            unsafe_allow_html=True,
        )
    else:
        st.info("ML lens not computable for this call date (insufficient training data).")

notes = [
    ("Scope", "Commercial and Enterprise only. SMB's no-touch, 0-7 day motion has no weekly forecast cadence."),
]
notes += [("Scope", f"{LENS_LABELS[k]} lens: {v}") for k, v in fc.LENS_DEFINITIONS.items()]
notes += [("Scope", c) for c in fc.FORECAST_CAVEATS]
notes.append(("Assumption", f"Divergence flag: lens spread above {fc._DIVERGENCE_THRESHOLD:.0%} of the mean of "
                            "the computable lenses. The threshold is proposed, not confirmed."))
notes.append(("Scope", "The ML lens varies by up to about 0.5% across rebuilds of the same data; the "
                       "comparison with the weekly readout treats a difference within 1% as informational."))
notes.append(("Data gap", "No plan or quota is published at this grain and unit (closed-won opportunity "
                          "amount for Commercial and Enterprise, per quarter), so no forecast-versus-plan "
                          "comparison is shown."))
notes.append(("Scope", "The ML classifier excludes the manager's forecast category from its features and "
                       "reads deal mechanics only, so a gap to the bottoms-up lenses is a difference "
                       "between deal mechanics and human judgment."))
notes.append(("Scope", result["data_window_note"]))
theme.notes_and_assumptions(notes)
