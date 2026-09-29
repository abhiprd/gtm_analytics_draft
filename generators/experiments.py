"""experiments_registry / experiment_assignment -- generators/run_batch12.py's
supporting module.

Build spec Section 5/8: item #13 ("Testing/experimentation methodology &
platform", Wave 7, marked infrastructure) needs `experiments_registry`
("test, hypothesis, treatment/control definition, target + guardrail
metrics, result) with assignment flags on the accounts/leads actually in
each test") before it can be built at all.

Design decision -- catalog the real experiment, don't invent a parallel one
--------------------------------------------------------------------------
This project already runs one genuinely randomized experiment in its raw
data: `generators/marketing_funnel.py`'s paid/community holdout program
(`config.HOLDOUT_CHANNELS`, `config.HOLDOUT_QUARTERS`) -- six real
suppressed control cells with real assignment, real behavioural suppression
(withheld budget, withheld touches, isolated cells) and a real, already
-measured incremental lift, independently validated in
`analytics/marketing_attribution.py` and written up in
`docs/acme-corp-analytics-methods.md`'s "Marketing attribution & channel
mix" entry (Incrementality section). No other holdout, control-group, or
randomized-assignment mechanism exists anywhere else in this raw data --
checked directly (`grep -rn "holdout\|control.group\|is_control\|randomiz"`
across `docs/` and `generators/` before writing this module) -- so
formalizing that one real mechanism as this registry's sole entry is the
only choice that holds to CLAUDE.md's "independently-random columns are a
bug, not a feature" bar. A second, invented experiment with no real
randomized mechanic behind it would be exactly that bug, dressed up as
registry volume; this module does not add one.

What this module does NOT do
--------------------------------------------------------------------------
It does not recompute the incrementality result. `analytics/
marketing_attribution.py` already derives it correctly -- point-in-time-safe
cell resolution, censored-cell exclusion, a design-based two-proportion
estimator with a closed-form standard error -- and re-deriving a second,
simpler version here (e.g. a naive treated-vs-control rate difference over
whatever happens to be resolved today) would risk a competing number that
quietly disagrees with the validated one. The `MARKETING_HOLDOUT_*`
constants below are that module's already-published 2025-12-31-checkpoint
read, restated as named constants and cited back to their source, not
re-derived. `analytics/marketing_attribution.py` itself is untouched.

What this module DOES compute -- real assignment, not a fabricated one
--------------------------------------------------------------------------
`build_experiment_assignment()` re-derives, directly from the raw
`campaigns` / `leads` / `campaign_engagement_events` tables already on disk,
exactly the same intention-to-treat assignment
`analytics/marketing_attribution.py`'s `build_lead_panel()` and this
project's own `tests/test_phase1_batch7.py::holdout_membership` fixture
use: a lead's arm is the holdout flag of its first-touch (sourcing)
campaign, ordered by `(event_timestamp, event_id)`. That is a deterministic
replay of a real assignment already fixed by batch 7's generation, not a
new random draw -- this module draws no randomness of its own and needs no
seed.

Grain
-----
* `experiments_registry` -- one row per experiment (one row, for now: the
  real holdout program). `test`/`hypothesis`/`treatment-control definition`/
  `target + guardrail metrics`/`result`, per the build spec's own line.
* `experiment_assignment` -- one row per lead in the experiment's real
  population (both arms), carrying its arm and the real first-touch
  campaign that produced it. This is the "assignment flags on the
  accounts/leads actually in each test" the build spec asks for.
"""
import pandas as pd

from . import config

REGISTRY_COLUMNS = [
    "experiment_id", "experiment_name", "hypothesis",
    "population_definition", "treatment_definition", "control_definition",
    "assignment_mechanism", "cell_quarters", "start_date", "end_date",
    "target_metric", "guardrail_metrics", "designed_effect_size", "status",
    "result_metric", "result_value", "result_se", "result_z",
    "result_significant", "result_as_of_date", "result_detail", "result_source",
]

ASSIGNMENT_COLUMNS = [
    "assignment_id", "experiment_id", "lead_id", "account_id", "company_id",
    "channel", "cell_quarter", "first_touch_campaign_id", "arm", "assigned_date",
]

EXPERIMENT_ID = "EXP-0001"

# Reused, not recomputed -- analytics/marketing_attribution.py's already
# -validated pooled incrementality read, docs/acme-corp-analytics-
# methods.md's "Marketing attribution & channel mix" entry (Incrementality
# section), checkpoint as_of_date 2025-12-31 -- which is also the last day
# of this simulation's own 36-month window (config.SIM_END), i.e. the final
# read this dataset can ever produce for this test, not an interim one.
# Restated here as named constants and cited back to that source; this
# module never independently re-derives them.
MARKETING_HOLDOUT_RESULT_ASOF_DATE = "2025-12-31"
MARKETING_HOLDOUT_CELLS_TOTAL = 6
MARKETING_HOLDOUT_CELLS_RESOLVED = 5
MARKETING_HOLDOUT_POOLED_INCREMENTAL_SHARE = 0.6819
MARKETING_HOLDOUT_POOLED_SE = 0.0877
MARKETING_HOLDOUT_POOLED_Z = 4.43
MARKETING_HOLDOUT_PAID_INCREMENTAL_SHARE = 0.6477
MARKETING_HOLDOUT_PAID_Z = 3.83
MARKETING_HOLDOUT_COMMUNITY_INCREMENTAL_SHARE = 0.8157
MARKETING_HOLDOUT_COMMUNITY_Z = 1.95
# Control-arm crossover measured at the same checkpoint (analytics-methods.md
# Incrementality section) -- cited for the crossover guardrail below, not
# recomputed.
MARKETING_HOLDOUT_CONTROL_CROSSOVER_LEADS = 13
MARKETING_HOLDOUT_CONTROL_ASSIGNED_LEADS = 1_239
# Significance bar the validated result is checked against
# (holdout_suppression_is_real_and_reconciles, same doc).
MARKETING_HOLDOUT_SIGNIFICANCE_Z = 2.58


def _quarter_label(ts: pd.Timestamp) -> str:
    return f"{ts.year}Q{ts.quarter}"


def build_experiments_registry(campaigns: pd.DataFrame) -> pd.DataFrame:
    """One row: the real, already-running paid/community holdout
    incrementality test. See module docstring for why this is the
    registry's sole entry.

    `start_date`/`end_date` are real calendar dates -- the earliest and
    latest window bound across the actual holdout campaigns in `campaigns`
    -- not the quarter labels. Real dates keep the column typed like every
    other start_date/end_date in this project (dbt's staging layer
    try_casts to date, and a quarter-label string like "2023Q3" would
    fail that cast). Because the three holdout quarters are non-contiguous,
    a [start_date, end_date] span alone would wrongly imply the program ran
    continuously across all six quarters in between -- `cell_quarters`
    carries the real, non-contiguous list so nothing downstream has to
    infer continuity that isn't there.
    """
    holdout_campaigns = campaigns[campaigns["is_holdout"]]
    if holdout_campaigns.empty:
        raise ValueError("no holdout campaigns found -- experiments_registry has nothing real to catalog")
    start_date = pd.Timestamp(holdout_campaigns["start_date"].min()).date()
    end_date = pd.Timestamp(holdout_campaigns["end_date"].max()).date()

    designed_effect_size = round(1.0 - config.HOLDOUT_CONVERSION_SUPPRESSION, 4)
    crossover_rate = (MARKETING_HOLDOUT_CONTROL_CROSSOVER_LEADS
                      / MARKETING_HOLDOUT_CONTROL_ASSIGNED_LEADS)

    row = {
        "experiment_id": EXPERIMENT_ID,
        "experiment_name": "Paid & Community Channel Holdout Incrementality Test",
        "hypothesis": (
            "Multi-touch attribution credit for the paid and community "
            "sub-channels overstates their true incremental contribution to "
            "inbound conversion, because attribution answers 'who gets "
            "credit for a conversion that happened' rather than 'which "
            "conversions would not have happened without this channel.' A "
            "randomized budget/touch holdout in selected channel-quarters "
            "will convert measurably worse than its treated peers, and the "
            "resulting incremental share will read below what first-touch "
            "or linear attribution implies for the same channels."
        ),
        "population_definition": (
            "Leads whose first-touch (sourcing) campaign falls in a "
            "channel x quarter cell the holdout program covers: channel in "
            "{paid, community} (config.HOLDOUT_CHANNELS), cell quarter in "
            "{2023Q3, 2024Q2, 2025Q1} (config.HOLDOUT_QUARTERS) -- 6 cells "
            "total, 2 channels x 3 quarters."
        ),
        "treatment_definition": (
            "Leads whose first-touch campaign in that cell is the "
            "channel's regular, non-holdout campaign: full touch cadence, "
            "full budget, eligible for cross-campaign follow-up touches."
        ),
        "control_definition": (
            "Leads whose first-touch campaign in that cell is the "
            "designated holdout campaign: budget withheld to "
            "config.HOLDOUT_BUDGET_SHARE (10%) of a normal cell's spend, "
            "touch volume suppressed to config.HOLDOUT_TOUCH_SUPPRESSION "
            "(40%) of a treated lead's, and the cell stays fully isolated "
            "-- no cross-campaign touch is ever routed into it "
            "(generators/marketing_funnel.py's _resolve_touch_campaign)."
        ),
        "assignment_mechanism": (
            "Intention-to-treat: a lead's arm is the is_holdout flag of "
            "its first-touch (sourcing) campaign, fixed at that first "
            "touch and never revised on a later off-arm touch. A small, "
            "real crossover exists in both directions in the underlying "
            "touch data (a treated lead can incidentally pick up a "
            "holdout-campaign touch and vice versa once a cell's window "
            "ends) and is deliberately left in its assigned arm, which "
            "makes the measured lift conservative rather than inflated -- "
            "see docs/acme-corp-analytics-methods.md's Incrementality "
            "section."
        ),
        "cell_quarters": "; ".join(config.HOLDOUT_QUARTERS),
        "start_date": start_date,
        "end_date": end_date,
        "target_metric": (
            "lead_to_pql_rate (resolved-population lead-to-conversion "
            "rate) -- the metric tree's Pipeline-generated leaf, scoped to "
            "leads whose channel-specific resolution horizon has elapsed "
            "as of the analysis date, same point-in-time-safe scoping "
            "analytics/marketing_attribution.py's build_lead_panel() "
            "applies throughout that module."
        ),
        "guardrail_metrics": (
            f"resolved_control_cell_lead_volume >= 300 (QA plan Test D "
            f"power floor -- an incrementality test on a handful of leads "
            f"is not a test); "
            f"control_arm_crossover_rate stays low (measured "
            f"{crossover_rate:.2%}, "
            f"{MARKETING_HOLDOUT_CONTROL_CROSSOVER_LEADS}/"
            f"{MARKETING_HOLDOUT_CONTROL_ASSIGNED_LEADS} assigned-control "
            f"leads, at the {MARKETING_HOLDOUT_RESULT_ASOF_DATE} checkpoint "
            f"-- a high crossover rate would mean the control arm is no "
            f"longer a clean control)"
        ),
        "designed_effect_size": designed_effect_size,
        "status": (
            f"resolved ({MARKETING_HOLDOUT_CELLS_RESOLVED} of "
            f"{MARKETING_HOLDOUT_CELLS_TOTAL} cells fully resolved as of "
            f"{MARKETING_HOLDOUT_RESULT_ASOF_DATE}, the simulation's own "
            f"final day; community 2025Q1 remains individually censored -- "
            f"its 314-day resolution horizon does not close inside this "
            f"dataset's window -- but does not move the pooled result, "
            f"which excludes censored cells rather than averaging them in)"
        ),
        "result_metric": "measured_incremental_share_pooled",
        "result_value": MARKETING_HOLDOUT_POOLED_INCREMENTAL_SHARE,
        "result_se": MARKETING_HOLDOUT_POOLED_SE,
        "result_z": MARKETING_HOLDOUT_POOLED_Z,
        "result_significant": MARKETING_HOLDOUT_POOLED_Z >= MARKETING_HOLDOUT_SIGNIFICANCE_Z,
        "result_as_of_date": MARKETING_HOLDOUT_RESULT_ASOF_DATE,
        "result_detail": (
            f"paid {MARKETING_HOLDOUT_PAID_INCREMENTAL_SHARE} "
            f"(z={MARKETING_HOLDOUT_PAID_Z}, individually significant); "
            f"community {MARKETING_HOLDOUT_COMMUNITY_INCREMENTAL_SHARE} "
            f"(z={MARKETING_HOLDOUT_COMMUNITY_Z}, not individually "
            f"significant on its own -- rests on a single control "
            f"conversion); designed target {designed_effect_size} "
            f"(1 - config.HOLDOUT_CONVERSION_SUPPRESSION); pooled estimate "
            f"is "
            f"{abs(MARKETING_HOLDOUT_POOLED_INCREMENTAL_SHARE - designed_effect_size):.3f} "
            f"from the designed value, ~0.4 SE."
        ),
        "result_source": (
            "analytics/marketing_attribution.py (not modified by this "
            "batch) -- docs/acme-corp-analytics-methods.md, 'Marketing "
            "attribution & channel mix' entry, Incrementality section. "
            "Reused verbatim; not recomputed here."
        ),
    }
    return pd.DataFrame([row])[REGISTRY_COLUMNS]


def _first_touch_campaign(events: pd.DataFrame) -> pd.DataFrame:
    """One row per lead: the campaign of its first touch, ordered on
    (event_timestamp, event_id) -- the exact ordering
    analytics/marketing_attribution.py's build_touch_sequence() and this
    project's own tests/test_phase1_batch7.py::holdout_membership fixture
    use. `event_timestamp` is already unique within a lead by construction
    (generators/marketing_funnel.py enforces strict per-lead ordering), so
    `event_id` is a stability tie-break that never actually fires here,
    included so the result stays deterministic if that invariant ever
    weakened.
    """
    ordered = events.sort_values(["event_timestamp", "event_id"], kind="mergesort")
    return (ordered.groupby("lead_id", as_index=False)
                   .first()[["lead_id", "campaign_id"]]
                   .rename(columns={"campaign_id": "first_touch_campaign_id"}))


def build_experiment_assignment(campaigns: pd.DataFrame, leads: pd.DataFrame,
                                events: pd.DataFrame) -> pd.DataFrame:
    """One row per lead in the holdout program's real population (both
    arms), tracing to the real is_holdout flag on its real first-touch
    campaign -- not a fabricated parallel assignment. See module docstring.
    """
    first_touch = _first_touch_campaign(events)
    campaign_lookup = campaigns.set_index("campaign_id")[["channel", "is_holdout"]]

    tagged = leads.merge(first_touch, on="lead_id", how="left")
    tagged = tagged.merge(campaign_lookup, left_on="first_touch_campaign_id",
                          right_index=True, how="left", suffixes=("", "_campaign"))

    created = pd.to_datetime(tagged["created_date"])
    tagged["cell_quarter"] = created.apply(_quarter_label)

    comparable = tagged[
        tagged["channel"].isin(config.HOLDOUT_CHANNELS)
        & tagged["cell_quarter"].isin(config.HOLDOUT_QUARTERS)
    ].copy()

    comparable["arm"] = comparable["is_holdout"].map({True: "control", False: "treatment"})
    comparable = comparable.sort_values(
        ["cell_quarter", "channel", "created_date", "lead_id"], kind="mergesort"
    ).reset_index(drop=True)
    comparable["assignment_id"] = [f"ASG-{i + 1:06d}" for i in range(len(comparable))]
    comparable["experiment_id"] = EXPERIMENT_ID
    comparable["assigned_date"] = pd.to_datetime(comparable["created_date"]).dt.date

    return comparable[ASSIGNMENT_COLUMNS]
