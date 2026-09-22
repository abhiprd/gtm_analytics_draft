"""usage_monthly + fact_workflow_chain_events generator.

Build spec Section 5: `usage_monthly` (Actions consumed, active workflows),
`fact_workflow_chain_events` (upstream/trigger vs. downstream/completion, per
account-period -- QA plan Test A's "account-period" wording is read here as
this table's actual grain, not a further per-Action-step breakdown, which
would run to tens of millions of rows for no additional validation value at
this stage).

Both tables come from one underlying trajectory per account-month
(`intended_actions`, the upstream/triggered volume): usage_monthly.actions
_consumed is defined as the *completed* (downstream) volume -- Acme meters
"Actions executed" (build spec Section 1), read here as completed, not
merely triggered, work. fact_workflow_chain_events.downstream_actions is
therefore the same number by construction, guaranteeing the two tables never
contradict each other and the downstream <= upstream invariant holds by
construction rather than by post-hoc clipping.

Two things this trajectory is *required* to honor, both pre-committed by
earlier generators:
1. batch 1's causal-wiring contract (see accounts.py's module docstring):
   a `usage_threshold`-triggered migration's committed effective_date must
   be preceded by two consecutive months where usage actually crosses the
   dollar threshold in config.MONTHLY_SPEND_MIGRATION_THRESHOLD.
2. contracts.py's pre-committed churn_date: usage must decline toward a low
   floor in the months before churn (QA plan: "at least a meaningful subset
   of accounts must show sustained near-zero usage before their renewal
   date").
"""
import numpy as np
import pandas as pd

from . import config


def _month_floor(d) -> pd.Timestamp:
    return pd.Timestamp(d).to_period("M").start_time


def _month_range(start, end):
    start_p = _month_floor(start).to_period("M")
    end_p = _month_floor(end).to_period("M")
    n = (end_p - start_p).n
    if n < 0:
        return []
    return [(start_p + i).start_time for i in range(n + 1)]


def _log_interp(month_dates, control_dates, control_values):
    x = np.array([d.toordinal() for d in month_dates], dtype=float)
    order = np.argsort([d.toordinal() for d in control_dates])
    xp_all = np.array([control_dates[i].toordinal() for i in order], dtype=float)
    fp_all = np.log(np.maximum(np.array(control_values)[order], 1.0))
    # de-duplicate identical x's (keep the last -- later control points win)
    xp, fp = [], []
    for xi, fi in zip(xp_all, fp_all):
        if xp and xp[-1] == xi:
            fp[-1] = fi
        else:
            xp.append(xi)
            fp.append(fi)
    y = np.interp(x, xp, fp)
    return np.exp(y)


def _segment_at(month_ts, history_sorted):
    """history_sorted: list of (effective_date_ts, segment), ascending."""
    seg = history_sorted[0][1]
    for eff_ts, s in history_sorted:
        if eff_ts <= month_ts:
            seg = s
        else:
            break
    return seg


def generate_usage(rng: np.random.Generator, accounts: pd.DataFrame, segment_history: pd.DataFrame,
                    contract_plan: pd.DataFrame):
    usage_rows, chain_rows = [], []

    contract_by_account = contract_plan.set_index("account_id")
    hist_by_account = {
        aid: sorted(
            [(pd.Timestamp(r.effective_date), r.segment) for r in grp.itertuples()],
            key=lambda t: t[0],
        )
        for aid, grp in segment_history.groupby("account_id")
    }
    threshold_migrations_by_account = {}
    for r in segment_history[segment_history["trigger_reason"] == "usage_threshold"].itertuples():
        threshold_migrations_by_account.setdefault(r.account_id, []).append((pd.Timestamp(r.effective_date), r.segment))
    rescore_migrations_by_account = {}
    for r in segment_history[segment_history["trigger_reason"] == "firmographic_rescore"].itertuples():
        rescore_migrations_by_account.setdefault(r.account_id, []).append((pd.Timestamp(r.effective_date), r.segment))

    for acc in accounts.itertuples():
        cp = contract_by_account.loc[acc.account_id]
        scale = cp["usage_scale"]
        churn_date = cp["churn_date"]
        churned = pd.notna(churn_date)

        history = hist_by_account[acc.account_id]
        start_month = _month_floor(acc.signup_date)
        end_month = _month_floor(churn_date) if churned else _month_floor(config.SIM_END)
        months = _month_range(start_month, end_month)
        if not months:
            continue

        start_segment = history[0][1]
        ramp_months = config.ACTIVATION_RAMP_MONTHS[start_segment]
        ramp_end_month = start_month + pd.DateOffset(months=max(ramp_months - 1, 0))
        control_dates = [start_month, ramp_end_month]
        control_values = [
            0.1 * config.USAGE_BASELINE_ACTIONS[start_segment] * scale,
            config.USAGE_BASELINE_ACTIONS[start_segment] * scale,
        ]

        for mig_date, target_segment in threshold_migrations_by_account.get(acc.account_id, []):
            threshold_key = "SMB_TO_COMMERCIAL" if target_segment == "Commercial" else "COMMERCIAL_TO_ENTERPRISE"
            threshold_dollars = config.MONTHLY_SPEND_MIGRATION_THRESHOLD[threshold_key]
            threshold_actions = threshold_dollars / config.PRICE_PER_ACTION
            # control_values here are *upstream* (intended) targets, but the
            # $/mo threshold is checked against actions_consumed, which is
            # the *downstream* (completion-discounted) value -- inflate by
            # the completion rate's low end plus a margin so the discounted
            # result still comfortably clears the threshold.
            completion_floor = config.COMPLETION_RATE_HEALTHY[0]
            control_dates += [mig_date - pd.DateOffset(months=2), mig_date - pd.DateOffset(months=1)]
            control_values += [
                threshold_actions * 1.35 / completion_floor,
                threshold_actions * 1.5 / completion_floor,
            ]
            control_dates += [mig_date]
            control_values += [config.USAGE_BASELINE_ACTIONS[target_segment] * scale]

        for mig_date, target_segment in rescore_migrations_by_account.get(acc.account_id, []):
            control_dates += [mig_date]
            control_values += [config.USAGE_BASELINE_ACTIONS[target_segment] * scale * 0.9]

        end_segment = _segment_at(end_month, history)
        growth_lo, growth_hi = config.MONTHLY_ORGANIC_GROWTH_RANGE[end_segment]
        final_organic_level = config.USAGE_BASELINE_ACTIONS[end_segment] * scale * (
            (1 + rng.uniform(growth_lo, growth_hi)) ** max(len(months) - ramp_months, 0)
        )
        if end_month not in control_dates:
            control_dates.append(end_month)
            control_values.append(final_organic_level)

        base_values = _log_interp(months, control_dates, control_values)

        # Per-account decline shape -- randomized rather than a fixed
        # constant (build spec Section 4: noise so nothing is perfectly
        # deterministic). A minority of churns are "abrupt" (loud, explicit
        # cancellation -- QA plan's loud-vs-silent mix): no slow fade at
        # all, usage stays near-normal until the account simply ends. This
        # also keeps a naive usage-only churn signal genuinely bounded
        # (QA plan: predictive but not ~0.98) rather than a perfect
        # separator, since not every churner shows the same clean decline.
        is_abrupt_churn = churned and rng.random() < 0.20
        if start_segment == "SMB":
            floor_frac = rng.uniform(0.05, 0.40)
        else:
            floor_frac = rng.uniform(0.25, 0.60)

        for i, (month_ts, base_val) in enumerate(zip(months, base_values)):
            seasonality = config.SEASONALITY_BY_MONTH[month_ts.month]
            noise = rng.lognormal(0, 0.08)
            intended = base_val * seasonality * noise

            if churned and not is_abrupt_churn:
                months_to_churn = len(months) - 1 - i  # 0 at the churn month itself
                if months_to_churn <= config.DECLINE_MONTHS_BEFORE_CHURN:
                    decline_frac = floor_frac + (1 - floor_frac) * (
                        months_to_churn / max(config.DECLINE_MONTHS_BEFORE_CHURN, 1)
                    )
                    intended = intended * decline_frac

            intended = max(intended, 1.0)
            completion_lo, completion_hi = (
                config.COMPLETION_RATE_DECLINING
                if (churned and not is_abrupt_churn and (len(months) - 1 - i) <= config.DECLINE_MONTHS_BEFORE_CHURN)
                else config.COMPLETION_RATE_HEALTHY
            )
            completion_rate = rng.uniform(completion_lo, completion_hi)
            upstream = int(round(intended))
            downstream = int(round(upstream * completion_rate))
            downstream = min(downstream, upstream)

            month_segment = _segment_at(month_ts, history)
            usage_rows.append({
                "account_id": acc.account_id,
                "month": month_ts.date(),
                "segment": month_segment,
                "actions_consumed": downstream,
                "active_workflows": max(1, int(round((downstream / 40) ** 0.5))),
            })
            chain_rows.append({
                "account_id": acc.account_id,
                "month": month_ts.date(),
                "upstream_actions": upstream,
                "downstream_actions": downstream,
            })

    usage_df = pd.DataFrame(usage_rows)
    chain_df = pd.DataFrame(chain_rows)
    return usage_df, chain_df
