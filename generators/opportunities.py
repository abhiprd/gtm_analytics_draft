"""opportunities + opportunity_stage_history generator.

Build spec Section 5: `opportunities` (opportunity_type, owner_role,
loss_reason, forecast_category, list_price), `opportunity_stage_history`.
Section 2: funnel by segment, `fact_opportunities` fields. Three opportunity
sources, generated in this order:

1. New-business: SMB (one per account, Closed Won, no rep, no stage
   history), Commercial/Enterprise (one per direct-entry account, Closed Won
   -- plus a synthetic Closed-Lost prospect pool drawn from market_universe's
   non-customer rows in the matching fit tier, sized to hit
   config.NEW_BUSINESS_WIN_RATE_TARGET).
2. Expansion: one per migration row in account_segment_history (build spec
   Section 2: migration "typically open[s] a renewal/expansion opportunity
   to formalize the bigger contract").
3. Renewal: one per boundary in contracts.build_contract_plan's
   renewal_events_df -- Closed Won (flat/contraction/expansion) or Closed
   Lost (churned, loss_reason populated).

Schema note (own resolved decision, flagged in the batch summary): every row
carries `company_id` (always populated, links to market_universe).
`account_id` is populated only once a deal is Closed Won -- a Closed-Lost
new-business prospect never became an account in this schema (accounts.csv
is the customer subset, as built in batch 1), so it has no account_id to
carry. This keeps every *non-null* account_id resolving to a real account
(QA plan Test A) without retroactively changing batch 1's accounts.csv or
inventing placeholder "prospect accounts."
"""
import numpy as np
import pandas as pd

from . import config
from .firmographics import fit_tier

REP_TYPE_BY_SEGMENT_NEW_BUSINESS = {"Commercial": "ISR", "Enterprise": "AE"}
OWNER_ROLE_NEW_BUSINESS = {"Commercial": "ISR", "Enterprise": "AE"}
AM_REP_TYPE_BY_SEGMENT = {"Commercial": "AM-Commercial", "Enterprise": "AM-Enterprise"}

_RAMP_FULL_DAYS = 180  # "first 2 quarters" (build spec Section 4) treated as a single ramped/ramping cutoff here

# =====================================================================
# forecast_category -- the deal's FINAL close-time forecast call
#
# Build spec Section 5 lists `forecast_category` as an `opportunities`
# field; neither reference doc states how it is generated. Resolved here:
# it is the last call the owner made on the deal before it closed, so it
# is built as a *perceived win probability* assembled from the drivers
# that were genuinely visible by then, then cut into the four-value
# vocabulary. Correlated with the outcome, never a function of it alone --
# CLAUDE.md's causal-wiring invariant ("independently-random columns are a
# bug"), which the previous implementation violated in both directions: a
# blanket "Commit" for every won deal, and an outcome-independent
# rng.choice over the other three for every lost deal.
#
# Distinct from `fact_forecast_submissions` (generators/forecast.py),
# which is a weekly *point-in-time* series and is forbidden from reading
# anything fixed at close. This field is the opposite case: it is stamped
# at close, so the deal's realized trajectory is legitimately in scope.
# The two are built independently and neither reads the other.
#
# Every draw below comes from a dedicated rng stream threaded in as
# `forecast_rng`, never from the shared sequential `rng` that generates
# amount/discount/loss_reason/stage history -- same isolation rationale
# (and same precedent) as run_batch2.py's `reassign_rng`: adding draws to
# the shared stream would shift every subsequent draw in this and every
# later iteration and silently change columns that are already correct.
# =====================================================================

# Ordered weakest to strongest. The same four-value vocabulary carried by
# fact_forecast_submissions.
FORECAST_CATEGORIES = ("Omitted", "Pipeline", "Best Case", "Commit")

# Perceived-win-probability cut points. Deliberately the same conventional
# pipeline-review bands generators/forecast.py applies to its weekly
# submissions (a Commit is a deal the owner would be surprised to lose;
# Omitted is one they have effectively written off), so the close-time
# field and the weekly series speak the same language. Kept local rather
# than imported: batch 2 must not depend on a batch 6 module.
_FORECAST_CATEGORY_CUTS = ((0.70, "Commit"), (0.40, "Best Case"), (0.15, "Pipeline"))

# Evidence shifts, all on the log-odds scale, all own resolved decisions
# (no upstream doc states a number for any of them):
#
# _CYCLE_DEPTH_SHIFT -- how far through its segment's cycle envelope
#   (config.CYCLE_LENGTH_DAYS) the deal ran. This is the available proxy
#   for "how far it progressed": _generate_stage_history emits the full
#   config.NEW_BUSINESS_STAGES list for every deal, so the stage list
#   itself carries no per-deal signal, and the stage *dates* are derived
#   from cycle_days anyway. A deal that died three weeks in was never a
#   Commit; one that ran the full envelope died in late negotiation.
# _WON_EVIDENCE_SHIFT -- by the final call a deal that is about to close
#   is visibly closing (verbal, signature routing, PO raised).
# _LOSS_REASON_SHIFT -- a `price` or `competitive` loss is a late slip off
#   a deal the owner was carrying confidently; `no_decision` is the
#   stalled deal nobody was forecasting. Directions follow the reason
#   vocabulary in config.LOSS_REASON_MIX_*.
# _POC_SHIFT -- Enterprise only, the same POC->outcome relationship
#   config.POC_PASS_RATE_GIVEN_WON/_GIVEN_LOST already encode; a passed
#   POC is the single strongest mid-cycle confidence signal this motion
#   has (QA plan Test C).
# _DISCOUNT_RESCUE_SHIFT -- position within the segment's
#   config.DISCOUNT_RATE_RANGE band. A deal bought at the top of its band
#   needed concessions to land, so it was not sitting in Commit before
#   them; a deal closed near list was never in doubt.
# _RAMPING_OPTIMISM_SHIFT -- a ramping rep's own optimism bias, the same
#   bias fact_forecast_submissions models on the rep lens. Applied to the
#   *call*, not the outcome, which is what makes a ramping rep's Commit
#   convert at a lower rate than a ramped rep's.
# _FORECAST_CALL_NOISE -- residual judgement spread, so the mapping stays
#   probabilistic. Real forecasting is signal plus noise, not a lookup.
_CYCLE_DEPTH_SHIFT = 1.2
_WON_EVIDENCE_SHIFT = 2.9
_LOSS_REASON_SHIFT = {"price": 0.5, "competitive": 0.0, "other": -0.5, "no_decision": -1.2}
_POC_SHIFT = 0.6
_DISCOUNT_RESCUE_SHIFT = 1.0
_RAMPING_OPTIMISM_SHIFT = 0.45
_FORECAST_CALL_NOISE = 1.15

# Renewal/expansion book. The base prior is the complement of
# config.ANNUAL_CHURN_RATE (itself back-derived from the QA plan's
# GRR/logo-retention benchmark rows), so a renewal starts the final call
# as a Commit and has to lose that standing. Shifts keyed on the
# contracts.build_contract_plan outcome vocabulary: an expansion renewal
# was visibly growing, a contraction was visibly wobbling, a churn was
# visibly leaving.
_RENEWAL_OUTCOME_SHIFT = {
    "retained_expansion": 0.8,
    "retained_flat": 0.0,
    "retained_contraction": -2.4,
    "churned": -3.4,
}
# Notice-period runway sharpens the final call: the longer the AM worked
# the renewal before the boundary, the more the last call converged on
# what actually happened. Own resolved decision.
_RENEWAL_RUNWAY_SHARPENING = 0.7


def _logit(p: float) -> float:
    return float(np.log(p / (1.0 - p)))


def _forecast_category(forecast_rng: np.random.Generator, perceived_logit: float) -> str:
    """Cuts a perceived-win-probability log-odds into the four-value
    vocabulary, with one residual-judgement draw from the *dedicated*
    forecast rng stream (exactly one draw per opportunity, so the stream
    stays trivially reproducible and independent of the shared rng)."""
    z = perceived_logit + forecast_rng.normal(0.0, _FORECAST_CALL_NOISE)
    p = 1.0 / (1.0 + np.exp(-z))
    for cut, category in _FORECAST_CATEGORY_CUTS:
        if p >= cut:
            return category
    return "Omitted"


def _band_position(value: float, lo: float, hi: float) -> float:
    """Where `value` sits in its segment's [lo, hi] band, clipped to 0-1."""
    if hi <= lo:
        return 0.0
    return float(np.clip((value - lo) / (hi - lo), 0.0, 1.0))


def _new_business_forecast_category(forecast_rng, segment, is_won, loss_reason, cycle_days,
                                    discount, poc_outcome, rep_is_ramped):
    """Final close-time call on a Commercial/Enterprise new-business deal.
    Every argument is already computed at the call site -- this function
    adds no draw to the shared sequential rng."""
    cyc_lo, cyc_hi = config.CYCLE_LENGTH_DAYS[segment]
    disc_lo, disc_hi = config.DISCOUNT_RATE_RANGE[segment]

    z = _logit(config.NEW_BUSINESS_WIN_RATE_TARGET[segment])
    z += _CYCLE_DEPTH_SHIFT * _band_position(cycle_days, cyc_lo, cyc_hi)
    z += _WON_EVIDENCE_SHIFT if is_won else _LOSS_REASON_SHIFT[str(loss_reason)]
    z -= _DISCOUNT_RESCUE_SHIFT * _band_position(discount, disc_lo, disc_hi)
    if poc_outcome == "pass":
        z += _POC_SHIFT
    elif poc_outcome == "fail":
        z -= _POC_SHIFT
    if not rep_is_ramped:
        z += _RAMPING_OPTIMISM_SHIFT
    return _forecast_category(forecast_rng, z)


def _renewal_forecast_category(forecast_rng, segment, outcome, is_won, loss_reason,
                               runway_days, notice_days_range, rep_is_ramped):
    """Final close-time call on a renewal/expansion boundary. Same
    no-shared-rng-draw contract as _new_business_forecast_category."""
    z = _logit(1.0 - config.ANNUAL_CHURN_RATE[segment])
    z += _RENEWAL_OUTCOME_SHIFT[str(outcome)]
    if not is_won:
        z += _LOSS_REASON_SHIFT[str(loss_reason)]
    runway = _band_position(runway_days, *notice_days_range)
    z += _RENEWAL_RUNWAY_SHARPENING * runway * (1.0 if is_won else -1.0)
    if not rep_is_ramped:
        z += _RAMPING_OPTIMISM_SHIFT
    return _forecast_category(forecast_rng, z)


def _departed_by(rep_status_history: pd.DataFrame) -> dict:
    departed = rep_status_history[rep_status_history["status"] == "departed"]
    return dict(zip(departed["rep_id"], pd.to_datetime(departed["effective_date"])))


def _eligible_reps(users: pd.DataFrame, departed_by: dict, rep_type: str, at_date) -> pd.DataFrame:
    pool = users[users["rep_type"] == rep_type]
    at_ts = pd.Timestamp(at_date)
    hired = pd.to_datetime(pool["hire_date"]) <= at_ts
    not_departed = ~pool["rep_id"].map(lambda r: r in departed_by and departed_by[r] <= at_ts)
    eligible = pool[hired & not_departed]
    if len(eligible):
        return eligible
    # Fallback only relaxes the *departure* constraint (a rep who later
    # departed could still have legitimately worked this deal earlier) --
    # never the *hire_date* constraint, which must never be violated
    # (reps.py's _guarantee_earliest_rep_per_type ensures `hired` alone is
    # never empty for any in-window date).
    hired_only = pool[hired]
    return hired_only if len(hired_only) else pool


def _pick_rep(rng: np.random.Generator, eligible: pd.DataFrame, at_date, bias_toward_ramped: bool) -> str:
    at_ts = pd.Timestamp(at_date)
    tenure_days = (at_ts - pd.to_datetime(eligible["hire_date"])).dt.days
    ramped = tenure_days >= _RAMP_FULL_DAYS
    if bias_toward_ramped:
        weights = np.where(ramped, 1.0, config.RAMPING_REP_WIN_ASSIGNMENT_FACTOR)
    else:
        weights = np.where(ramped, config.RAMPING_REP_WIN_ASSIGNMENT_FACTOR, 1.0)
    probs = weights / weights.sum()
    return rng.choice(eligible["rep_id"].to_numpy(), p=probs)


def _is_ramped(users: pd.DataFrame, rep_id: str, at_date) -> bool:
    hire_date = users.loc[users["rep_id"] == rep_id, "hire_date"].iloc[0]
    return (pd.Timestamp(at_date) - pd.Timestamp(hire_date)).days >= _RAMP_FULL_DAYS


def _sample_discount_and_list_price(rng: np.random.Generator, amount: float, segment: str):
    lo, hi = config.DISCOUNT_RATE_RANGE[segment]
    discount = rng.uniform(lo, hi)
    list_price = round(amount / (1 - discount), 2)
    return round(discount, 4), list_price


def _generate_stage_history(rng, opportunity_id, stages, created_date, close_date, final_stage_label, regress):
    total_days = max((pd.Timestamp(close_date) - pd.Timestamp(created_date)).days, 1)
    n = len(stages)
    weights = np.ones(n + 1)
    if "POC" in stages:
        # POC stall duration needs to be genuinely variable -- QA plan: "this is
        # the exact mechanism the sample readout's drill-down story depends on."
        weights[stages.index("POC")] *= 2.5
    fracs = rng.dirichlet(weights)
    cum = np.cumsum(fracs)[:-1]
    dates = [pd.Timestamp(created_date) + pd.Timedelta(days=int(round(f * total_days))) for f in cum]

    rows = [{"opportunity_id": opportunity_id, "stage": s, "entered_date": d.date()} for s, d in zip(stages, dates)]
    if regress and len(stages) >= 2:
        sqo_idx = stages.index("SQO") if "SQO" in stages else 1
        regress_date = dates[sqo_idx] + pd.Timedelta(days=int(rng.integers(3, 14)))
        # Clamp strictly before close_date -- an unclamped regression date
        # can land past close_date (dates[sqo_idx] is already close to it
        # for a short cycle), which then sorts *after* the final
        # Closed Won/Lost row below and breaks the "stage history is
        # chronologically ordered per opportunity, final row = close_date"
        # invariant (QA plan Test A).
        regress_date = min(regress_date, pd.Timestamp(close_date) - pd.Timedelta(days=1))
        regress_date = max(regress_date, dates[sqo_idx])
        rows.append({
            "opportunity_id": opportunity_id,
            "stage": stages[max(sqo_idx - 1, 0)],
            "entered_date": regress_date.date(),
        })
    rows.append({"opportunity_id": opportunity_id, "stage": final_stage_label, "entered_date": pd.Timestamp(close_date).date()})
    rows.sort(key=lambda r: r["entered_date"])
    return rows


def _poc_pass_rate(close_date, given_won: bool) -> float:
    """Injected incident #1 (config.POC_REGRESSION_INCIDENT_WINDOW): deals
    closing in this window get a depressed POC pass rate."""
    win_start, win_end = config.POC_REGRESSION_INCIDENT_WINDOW
    in_window = win_start <= close_date <= win_end
    if given_won:
        return config.POC_PASS_RATE_GIVEN_WON_INCIDENT if in_window else config.POC_PASS_RATE_GIVEN_WON
    return config.POC_PASS_RATE_GIVEN_LOST_INCIDENT if in_window else config.POC_PASS_RATE_GIVEN_LOST


def _new_business_amount(rng, segment, committed_actions_monthly):
    lo, hi = config.ACV_RANGES[segment]
    amount = committed_actions_monthly * 12 * config.PRICE_PER_ACTION
    return float(np.clip(amount, lo if lo > 0 else 100, hi))


def generate_new_business_opportunities(rng, accounts, segment_history, market_universe, users,
                                         rep_status_history, contract_plan, forecast_rng):
    """`forecast_rng` is a dedicated stream used only for the close-time
    forecast_category call (see the taxonomy block above). It is
    deliberately *not* the shared sequential `rng`: every other column here
    is drawn from `rng` in a fixed order, so adding draws to it would shift
    amount, discount, loss_reason, POC outcome and stage timing for this
    and every later opportunity."""
    departed_by = _departed_by(rep_status_history)
    committed_by_account = contract_plan.set_index("account_id")["committed_actions_monthly"]

    opp_rows, stage_rows = [], []

    # --- SMB: one Closed Won per account, no stage history, no rep ---
    smb = accounts[accounts["segment"] == "SMB"]
    for row in smb.itertuples():
        lo, hi = config.ACV_RANGES["SMB"]
        amount = float(np.clip(rng.lognormal(np.log(max(committed_by_account[row.account_id] * 12 * config.PRICE_PER_ACTION, 50)), 0.4), lo if lo > 0 else 50, hi))
        discount, list_price = _sample_discount_and_list_price(rng, amount, "SMB")
        # SMB is the one structurally unconditional Commit: a self-serve
        # signup closes the same day it is created, with no rep, no stage
        # history and no forecast cadence to have made a call in (which is
        # also why fact_forecast_submissions excludes SMB entirely, build
        # spec Section 5). There is no judgement here to model.
        opp_rows.append({
            "account_id": row.account_id, "company_id": row.company_id, "segment": "SMB",
            "opportunity_type": "new_business", "owner_role": "system", "rep_id": None,
            "is_won": True, "loss_reason": None, "forecast_category": "Commit",
            "amount": round(amount, 2), "list_price": list_price, "discount_rate": discount,
            "poc_outcome": None, "created_date": row.signup_date, "close_date": row.signup_date,
        })

    # --- Commercial / Enterprise: won (direct-entry accounts) + lost (prospect pool) ---
    first_rows = (
        segment_history.sort_values("effective_date").groupby("account_id").first().reset_index()
    )
    for segment in ["Commercial", "Enterprise"]:
        entry_ids = first_rows.loc[
            (first_rows["segment"] == segment) & (first_rows["trigger_reason"] == "initial_firmographic"),
            "account_id",
        ]
        won_accounts = accounts[accounts["account_id"].isin(entry_ids)]
        n_won = len(won_accounts)
        win_rate = config.NEW_BUSINESS_WIN_RATE_TARGET[segment]
        n_lost = round(n_won / win_rate) - n_won

        lost_pool = market_universe[(~market_universe["is_customer"])]
        lost_tier = fit_tier(lost_pool["icp_fit_score"].to_numpy(), lost_pool["is_personal_email_domain"].to_numpy())
        lost_candidates = lost_pool[lost_tier == segment]
        lost_rows_mu = lost_candidates.sample(n=n_lost, replace=False, random_state=rng.integers(0, 2**32 - 1))

        rep_type = REP_TYPE_BY_SEGMENT_NEW_BUSINESS[segment]
        stages = config.NEW_BUSINESS_STAGES[segment]
        cyc_lo, cyc_hi = config.CYCLE_LENGTH_DAYS[segment]

        # Won
        for row in won_accounts.itertuples():
            close_date = row.signup_date
            cycle_days = int(rng.integers(cyc_lo, cyc_hi + 1))
            created_date = (pd.Timestamp(close_date) - pd.Timedelta(days=cycle_days)).date()
            # eligibility keyed on created_date (when the deal was opened), not
            # close_date -- a rep hired between created_date and close_date
            # can't have been the one who opened this opportunity.
            rep_id = _pick_rep(rng, _eligible_reps(users, departed_by, rep_type, created_date), created_date, bias_toward_ramped=True)
            poc_outcome = None
            if segment == "Enterprise":
                poc_outcome = "pass" if rng.random() < _poc_pass_rate(close_date, given_won=True) else "fail"
            amount = _new_business_amount(rng, segment, committed_by_account[row.account_id])
            discount, list_price = _sample_discount_and_list_price(rng, amount, segment)
            # Most wins were called Commit, but not all: a deal that closed
            # unusually fast for its segment, needed a top-of-band discount
            # to land, or failed its POC and closed anyway is an upside
            # surprise the owner had carried lower. forecast_rng only.
            forecast_category = _new_business_forecast_category(
                forecast_rng, segment, True, None, cycle_days, discount, poc_outcome,
                _is_ramped(users, rep_id, created_date),
            )
            opp_id_placeholder = f"__won_{row.account_id}"
            opp_rows.append({
                "account_id": row.account_id, "company_id": row.company_id, "segment": segment,
                "opportunity_type": "new_business", "owner_role": OWNER_ROLE_NEW_BUSINESS[segment], "rep_id": rep_id,
                "is_won": True, "loss_reason": None, "forecast_category": forecast_category,
                "amount": round(amount, 2), "list_price": list_price, "discount_rate": discount,
                "poc_outcome": poc_outcome, "created_date": created_date, "close_date": close_date,
                "_temp_id": opp_id_placeholder,
            })
            regress = rng.random() < config.STAGE_REGRESSION_RATE
            stage_rows.extend(_generate_stage_history(rng, opp_id_placeholder, stages, created_date, close_date, "Closed Won", regress))

        # Lost
        loss_probs = list(config.LOSS_REASON_MIX_NEW_BUSINESS.values())
        loss_reasons = list(config.LOSS_REASON_MIX_NEW_BUSINESS.keys())
        for i, mu_row in enumerate(lost_rows_mu.itertuples()):
            # spread lost-deal timing across the window, same growth-weighted shape as signups
            month_idx = int(rng.integers(0, config.N_MONTHS))
            close_date = (pd.Timestamp(config.SIM_START) + pd.DateOffset(months=month_idx) + pd.Timedelta(days=int(rng.integers(0, 28)))).date()
            cycle_days = int(rng.integers(cyc_lo, cyc_hi + 1))
            created_date = (pd.Timestamp(close_date) - pd.Timedelta(days=cycle_days)).date()
            rep_id = _pick_rep(rng, _eligible_reps(users, departed_by, rep_type, created_date), created_date, bias_toward_ramped=False)
            poc_outcome = None
            if segment == "Enterprise":
                poc_outcome = "pass" if rng.random() < _poc_pass_rate(close_date, given_won=False) else "fail"
            lo, hi = config.ACV_RANGES[segment]
            amount = float(np.clip(rng.lognormal(np.log((lo + hi) / 4 or 1), 0.5), lo if lo > 0 else 50, hi))
            discount, list_price = _sample_discount_and_list_price(rng, amount, segment)
            loss_reason = rng.choice(loss_reasons, p=loss_probs)
            # Shared-stream position holder. The retired independent
            # forecast_category draw is still taken from `rng` and
            # discarded, so the shared sequential stream advances exactly
            # as it did before this field was rewired and every other
            # column this batch produces stays byte-for-byte unchanged.
            # The real category is assembled from deal drivers below.
            rng.choice(["Best Case", "Pipeline", "Omitted"], p=[0.3, 0.4, 0.3])
            # A loss is not automatically a low-confidence call: a deal that
            # ran its full cycle and died on price or a competitor was being
            # carried at Commit until it slipped, while a no_decision loss
            # that stalled early was never forecast at all. forecast_rng
            # only.
            forecast_category = _new_business_forecast_category(
                forecast_rng, segment, False, loss_reason, cycle_days, discount, poc_outcome,
                _is_ramped(users, rep_id, created_date),
            )
            opp_id_placeholder = f"__lost_{segment}_{i}"
            opp_rows.append({
                "account_id": None, "company_id": mu_row.company_id, "segment": segment,
                "opportunity_type": "new_business", "owner_role": OWNER_ROLE_NEW_BUSINESS[segment], "rep_id": rep_id,
                "is_won": False, "loss_reason": loss_reason, "forecast_category": forecast_category,
                "amount": round(amount, 2), "list_price": list_price, "discount_rate": discount,
                "poc_outcome": poc_outcome, "created_date": created_date, "close_date": close_date,
                "_temp_id": opp_id_placeholder,
            })
            regress = rng.random() < config.STAGE_REGRESSION_RATE
            stage_rows.extend(_generate_stage_history(rng, opp_id_placeholder, stages, created_date, close_date, "Closed Lost", regress))

    return opp_rows, stage_rows


def generate_expansion_opportunities(rng, accounts, segment_history, users, rep_status_history, contract_plan):
    departed_by = _departed_by(rep_status_history)
    usage_scale_by_account = contract_plan.set_index("account_id")["usage_scale"]
    company_by_account = accounts.set_index("account_id")["company_id"]

    migrations = segment_history[segment_history["trigger_reason"].isin(["usage_threshold", "firmographic_rescore"])]
    opp_rows, stage_rows = [], []
    stages = config.RENEWAL_EXPANSION_STAGES

    for row in migrations.itertuples():
        segment = row.segment  # target segment of the migration
        baseline = config.USAGE_BASELINE_ACTIONS[segment]
        committed = baseline * config.COMMITTED_VOLUME_FACTOR * usage_scale_by_account[row.account_id]
        amount = _new_business_amount(rng, segment, committed)
        discount, list_price = _sample_discount_and_list_price(rng, amount, segment)

        close_date = row.effective_date
        created_date = (pd.Timestamp(close_date) - pd.Timedelta(days=int(rng.integers(14, 46)))).date()
        rep_type = AM_REP_TYPE_BY_SEGMENT[segment]
        rep_id = _pick_rep(rng, _eligible_reps(users, departed_by, rep_type, created_date), created_date, bias_toward_ramped=True)

        opp_id_placeholder = f"__expmig_{row.account_id}_{close_date}"
        # The second structurally unconditional Commit: a migration-driven
        # expansion formalises a committed minimum the account's own usage
        # has *already* crossed (QA plan design decisions), so there is no
        # open question at the final call. Unlike the renewal book below,
        # this opportunity has no losing branch at all.
        opp_rows.append({
            "account_id": row.account_id, "company_id": company_by_account[row.account_id], "segment": segment,
            "opportunity_type": "expansion", "owner_role": "AM", "rep_id": rep_id,
            "is_won": True, "loss_reason": None, "forecast_category": "Commit",
            "amount": round(amount, 2), "list_price": list_price, "discount_rate": discount,
            "poc_outcome": None, "created_date": created_date, "close_date": close_date,
            "_temp_id": opp_id_placeholder,
        })
        stage_rows.extend(_generate_stage_history(rng, opp_id_placeholder, stages, created_date, close_date, "Closed Won", regress=False))

    return opp_rows, stage_rows


def generate_renewal_opportunities(rng, accounts, renewal_events, users, rep_status_history, forecast_rng):
    """`forecast_rng` is the same dedicated close-time-call stream
    generate_new_business_opportunities takes -- never the shared
    sequential `rng`, for the reason documented there."""
    departed_by = _departed_by(rep_status_history)
    company_by_account = accounts.set_index("account_id")["company_id"]
    opp_rows, stage_rows = [], []
    stages = config.RENEWAL_EXPANSION_STAGES

    loss_probs = list(config.LOSS_REASON_MIX_RENEWAL.values())
    loss_reasons = list(config.LOSS_REASON_MIX_RENEWAL.keys())

    for row in renewal_events.itertuples():
        segment = row.segment
        is_won = row.outcome != "churned"
        opportunity_type = "expansion" if row.outcome == "retained_expansion" else "renewal"
        close_date = row.boundary_date
        notice_days = (30, 90) if segment == "Commercial" else (60, 150)
        created_date = (pd.Timestamp(close_date) - pd.Timedelta(days=int(rng.integers(*notice_days)))).date()
        rep_type = AM_REP_TYPE_BY_SEGMENT[segment]
        rep_id = _pick_rep(rng, _eligible_reps(users, departed_by, rep_type, created_date), created_date, bias_toward_ramped=is_won)

        amount = _new_business_amount(rng, segment, row.committed_actions_monthly)
        discount, list_price = _sample_discount_and_list_price(rng, amount, segment)
        loss_reason = None if is_won else rng.choice(loss_reasons, p=loss_probs)
        if not is_won:
            # Shared-stream position holder -- see the matching note in
            # generate_new_business_opportunities. The retired draw was
            # taken only on the losing branch, so the discard is too.
            rng.choice(["Best Case", "Pipeline", "Omitted"], p=[0.3, 0.4, 0.3])
        # A renewal starts its final call as a Commit (the base prior is the
        # complement of config.ANNUAL_CHURN_RATE) and has to lose that
        # standing: a contraction was visibly wobbling, a churn visibly
        # leaving, and the longer the notice runway the AM worked, the
        # closer the last call landed to what actually happened.
        forecast_category = _renewal_forecast_category(
            forecast_rng, segment, row.outcome, is_won, loss_reason,
            (pd.Timestamp(close_date) - pd.Timestamp(created_date)).days, notice_days,
            _is_ramped(users, rep_id, created_date),
        )

        opp_id_placeholder = f"__renew_{row.account_id}_{row.sequence_number}"
        opp_rows.append({
            "account_id": row.account_id, "company_id": company_by_account[row.account_id], "segment": segment,
            "opportunity_type": opportunity_type, "owner_role": "AM", "rep_id": rep_id,
            "is_won": is_won, "loss_reason": loss_reason, "forecast_category": forecast_category,
            "amount": round(amount, 2), "list_price": list_price, "discount_rate": discount,
            "poc_outcome": None, "created_date": created_date, "close_date": close_date,
            "_temp_id": opp_id_placeholder,
        })
        stage_rows.extend(_generate_stage_history(
            rng, opp_id_placeholder, stages, created_date, close_date,
            "Closed Won" if is_won else "Closed Lost", regress=False,
        ))

    return opp_rows, stage_rows


def reassign_orphaned_ownership(rng: np.random.Generator, opp_df: pd.DataFrame, users: pd.DataFrame,
                                 rep_status_history: pd.DataFrame) -> pd.DataFrame:
    """Post-generation reassignment pass: an opportunity assigned to a rep
    who departs before the opportunity's close_date gets reassigned to a
    newly-eligible rep of the same rep_type, as of the departure date --
    the "explicit account reassignment... no orphaned ownership" invariant
    (build spec Section 5 / QA plan Test A), applied to in-flight deals the
    same way am_activity.py applies it to ongoing AM ownership. _eligible_
    reps's own assignment-time check only guarantees a rep hadn't departed
    yet *when the deal was created*; a deal that stays open past its rep's
    later departure needs this separate pass, since nothing re-picks a rep
    for already-open deals otherwise. Only rep_id changes -- amount, stage
    history, and dates all reflect what actually happened while the
    original rep owned the deal.
    """
    departed_by = _departed_by(rep_status_history)
    opp_df = opp_df.copy()
    close_ts = pd.to_datetime(opp_df["close_date"])
    depart_ts = opp_df["rep_id"].map(departed_by)
    needs_reassignment = depart_ts.notna() & (close_ts >= depart_ts)

    for idx in opp_df.index[needs_reassignment]:
        row = opp_df.loc[idx]
        rep_type = (
            REP_TYPE_BY_SEGMENT_NEW_BUSINESS[row["segment"]] if row["opportunity_type"] == "new_business"
            else AM_REP_TYPE_BY_SEGMENT[row["segment"]]
        )
        eligible = _eligible_reps(users, departed_by, rep_type, depart_ts[idx])
        eligible = eligible[eligible["rep_id"] != row["rep_id"]]
        if eligible.empty:
            continue  # no eligible replacement at this date -- leave as-is rather than fabricate one
        opp_df.loc[idx, "rep_id"] = _pick_rep(rng, eligible, depart_ts[idx], bias_toward_ramped=True)

    return opp_df


def finalize_opportunities(all_opp_rows, all_stage_rows):
    """Assigns final sequential opportunity_id (ordered by created_date) and
    remaps stage_history's placeholder ids to match."""
    opp_df = pd.DataFrame(all_opp_rows).sort_values(["created_date", "_temp_id"] if "_temp_id" in pd.DataFrame(all_opp_rows).columns else ["created_date"]).reset_index(drop=True)
    opp_df["opportunity_id"] = [f"OPP-{i:07d}" for i in range(len(opp_df))]
    id_map = dict(zip(opp_df["_temp_id"], opp_df["opportunity_id"]))
    opp_df = opp_df.drop(columns=["_temp_id"])

    stage_df = pd.DataFrame(all_stage_rows)
    stage_df["opportunity_id"] = stage_df["opportunity_id"].map(id_map)

    cols = ["opportunity_id", "account_id", "company_id", "segment", "opportunity_type", "owner_role",
            "rep_id", "is_won", "loss_reason", "forecast_category", "amount", "list_price",
            "discount_rate", "poc_outcome", "created_date", "close_date"]
    opp_df = opp_df[cols]
    stage_df = stage_df[["opportunity_id", "stage", "entered_date"]].sort_values(["opportunity_id", "entered_date"]).reset_index(drop=True)
    return opp_df, stage_df
