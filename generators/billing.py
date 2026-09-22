"""subscriptions + mrr_by_account_month + committed_vs_utilized_monthly generator.

Build spec Section 5: `subscriptions`, `mrr_by_account_month`, "committed-
vs-utilized Action volume per account per month (the input Consumption
Payback needs to exclude subsidized, non-consuming accounts)." Section 1
pricing mechanics: SMB is pure metered with no commitment; Commercial/
Enterprise pay a committed usage minimum plus monthly overage.

Everything here is derived from contracts.build_contract_plan's output (for
committed volume and contract periods) and usage.generate_usage's output
(for utilized volume) -- no new randomness is introduced in this module,
by design: billing is a deterministic function of usage and commitment, not
an independent draw.
"""
import pandas as pd

from . import config


def build_subscriptions(contract_plan: pd.DataFrame, renewal_events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    sub_seq = 0

    smb = contract_plan[contract_plan["segment"] == "SMB"]
    for r in smb.itertuples():
        sub_seq += 1
        churned = pd.notna(r.churn_date)
        rows.append({
            "subscription_id": f"SUB-{sub_seq:07d}", "account_id": r.account_id, "segment": "SMB",
            "start_date": r.signup_date,
            "end_date": pd.Timestamp(r.churn_date).date() if churned else None,
            "contract_type": "metered_month_to_month", "committed_actions_monthly": None,
            "status": "churned" if churned else "active",
        })

    events_by_account = {aid: grp.sort_values("sequence_number") for aid, grp in renewal_events.groupby("account_id")}
    status_map = {
        "churned": "churned", "retained_contraction": "contracted",
        "retained_expansion": "expanded", "retained_flat": "renewed",
    }
    ce = contract_plan[contract_plan["segment"].isin(["Commercial", "Enterprise"])]
    for r in ce.itertuples():
        events = events_by_account.get(r.account_id)
        contract_type = "annual" if r.segment == "Commercial" else "multi_year"
        period_start = pd.Timestamp(r.contract_start_date).date()
        committed = r.committed_actions_monthly
        still_open = True

        if events is not None:
            for ev in events.itertuples():
                sub_seq += 1
                rows.append({
                    "subscription_id": f"SUB-{sub_seq:07d}", "account_id": r.account_id, "segment": r.segment,
                    "start_date": period_start, "end_date": ev.boundary_date,
                    "contract_type": contract_type, "committed_actions_monthly": round(committed),
                    "status": status_map[ev.outcome],
                })
                if ev.outcome == "churned":
                    still_open = False
                    break
                period_start = ev.boundary_date
                committed = ev.committed_actions_monthly

        if still_open:
            sub_seq += 1
            rows.append({
                "subscription_id": f"SUB-{sub_seq:07d}", "account_id": r.account_id, "segment": r.segment,
                "start_date": period_start, "end_date": None,
                "contract_type": contract_type, "committed_actions_monthly": round(committed),
                "status": "active",
            })

    return pd.DataFrame(rows)


def _committed_lookup(subscriptions: pd.DataFrame) -> dict:
    """account_id -> sorted list of (start_ts, end_ts_or_None, committed_actions_monthly)."""
    lookup = {}
    for aid, grp in subscriptions.groupby("account_id"):
        periods = []
        for r in grp.itertuples():
            start_ts = pd.Timestamp(r.start_date)
            end_ts = pd.Timestamp(r.end_date) if pd.notna(r.end_date) else None
            periods.append((start_ts, end_ts, r.committed_actions_monthly))
        lookup[aid] = sorted(periods, key=lambda p: p[0])
    return lookup


def _committed_for_month(periods, month_ts):
    for start_ts, end_ts, committed in periods:
        if start_ts <= month_ts and (end_ts is None or month_ts < end_ts):
            return committed
    return None


def build_billing_monthly(usage_monthly: pd.DataFrame, subscriptions: pd.DataFrame):
    """Returns (mrr_by_account_month, committed_vs_utilized_monthly)."""
    lookup = _committed_lookup(subscriptions)

    mrr_rows, cvu_rows = [], []
    for r in usage_monthly.itertuples():
        month_ts = pd.Timestamp(r.month)
        periods = lookup.get(r.account_id, [])
        committed = _committed_for_month(periods, month_ts)

        if committed is None or pd.isna(committed):  # SMB: pure metered, no commitment
            mrr = r.actions_consumed * config.PRICE_PER_ACTION
            committed_out = None
        else:
            mrr = max(committed, r.actions_consumed) * config.PRICE_PER_ACTION
            committed_out = round(committed)

        mrr_rows.append({"account_id": r.account_id, "month": r.month, "segment": r.segment, "mrr": round(mrr, 2)})
        cvu_rows.append({
            "account_id": r.account_id, "month": r.month, "segment": r.segment,
            "committed_actions_monthly": committed_out, "utilized_actions_monthly": r.actions_consumed,
        })

    return pd.DataFrame(mrr_rows), pd.DataFrame(cvu_rows)
