"""Segment mix ("are we moving upmarket"): analytics/segment_migration.py,
compute_segment_mix() -- the function behind the weekly readout's segment_mix
section.

An independent recompute from the marts (events, shares, graduated MRR), the
reuse of the validated velocity and graduated-revenue functions, point-in-time
behaviour (rows after the evaluation month are never read), and the
unavailable paths.

Reads data/acme_gtm.duckdb (built by `cd dbt && dbt build`); skipped when the
database is absent.

Run: python3 -m pytest tests/test_phase4_segment_mix.py -v
"""
import os
import sys

import duckdb
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_PATH = os.path.join(ROOT, "data", "acme_gtm.duckdb")
pytestmark = pytest.mark.skipif(
    not os.path.exists(DB_PATH), reason="dbt-built database not present; run `cd dbt && dbt build`")

from analytics import segment_migration as sm  # noqa: E402

NOV = pd.Timestamp("2025-11-01")
SEGMENTS = ("SMB", "Commercial", "Enterprise")


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(DB_PATH, read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="module")
def events(con):
    df = con.execute("select * from main_marts.mart_segment_migration").df()
    df["migration_date"] = pd.to_datetime(df["migration_date"])
    return df


@pytest.fixture(scope="module")
def bridge(con):
    df = con.execute("select segment, month, ending_mrr from main_marts.mart_growth_bridge").df()
    df["month"] = pd.to_datetime(df["month"])
    return df


@pytest.fixture(scope="module")
def all_months(con):
    return {m: sm.compute_segment_mix(m, con=con)
            for m in pd.date_range("2020-01-01", "2025-12-01", freq="MS")}


# --------------------------------------------------------------------------
# Independent recompute
# --------------------------------------------------------------------------

class TestRecompute:
    def test_events_in_the_month_and_over_12_months_match_the_mart(self, all_months, events):
        checked = 0
        for m, r in all_months.items():
            if r["status"] != "present":
                continue
            for p in r["migration"]:
                src = events[events["from_segment"] == p["from_segment"]]
                in_month = int((src["migration_date"] == m).sum())
                trailing = int(((src["migration_date"] > m - pd.DateOffset(months=12))
                                & (src["migration_date"] <= m)).sum())
                assert (p["events_in_month"], p["events_trailing_12m"]) == (in_month, trailing), \
                    (m, p["from_segment"])
                checked += 1
        assert checked == 2 * 65

    def test_the_trailing_window_is_exactly_twelve_months_and_the_month_window_one(self, con):
        r = sm.compute_segment_mix(NOV, con=con)
        w = r["window"]
        assert w["trailing_window_first_month"] == "2024-12-01"
        assert w["trailing_window_last_month"] == "2025-11-01" == w["evaluation_month"]
        assert w["trailing_window_months"] == 12
        feb = sm.compute_segment_mix(pd.Timestamp("2025-02-01"), con=con)
        assert feb["window"]["trailing_window_first_month"] == "2024-03-01"

    def test_segment_shares_are_ending_mrr_over_the_company_total(self, all_months, bridge):
        for m, r in all_months.items():
            if r["status"] != "present":
                continue
            rows = bridge[bridge["month"] == m].set_index("segment")["ending_mrr"]
            total = float(rows[list(SEGMENTS)].sum())
            assert r["total_ending_mrr"] == pytest.approx(total)
            for s in r["segments"]:
                assert s["ending_mrr"] == pytest.approx(float(rows[s["segment"]]))
                assert s["mrr_share"] == pytest.approx(float(rows[s["segment"]]) / total)
            assert sum(s["mrr_share"] for s in r["segments"]) == pytest.approx(1.0)

    def test_prior_month_and_year_ago_shares_come_from_those_months(self, all_months, bridge):
        r = all_months[NOV]
        for label, back in (("prior_month", 1), ("12m_ago", 12)):
            m = NOV - pd.DateOffset(months=back)
            rows = bridge[bridge["month"] == m].set_index("segment")["ending_mrr"]
            total = float(rows[list(SEGMENTS)].sum())
            for s in r["segments"]:
                assert s["mrr_share_" + label] == pytest.approx(float(rows[s["segment"]]) / total)
                assert s["share_change_vs_" + label] == pytest.approx(
                    s["mrr_share"] - s["mrr_share_" + label])

    def test_the_upmarket_share_is_commercial_plus_enterprise(self, all_months):
        for m, r in all_months.items():
            if r["status"] != "present":
                continue
            up = sum(s["mrr_share"] for s in r["segments"] if s["segment"] != "SMB")
            assert r["upmarket_share"]["mrr_share"] == pytest.approx(up)
            assert r["upmarket_share"]["mrr_share"] + next(
                s["mrr_share"] for s in r["segments"] if s["segment"] == "SMB") == pytest.approx(1.0)

    def test_graduated_mrr_is_the_reclassified_mrr_in_the_window(self, all_months, events):
        r = all_months[NOV]
        for p in r["migration"]:
            src = events[(events["from_segment"] == p["from_segment"])
                         & (events["to_segment"] == p["to_segment"])]
            month = float(src[src["migration_date"] == NOV]["mrr_reclassified"].sum())
            trailing = float(src[(src["migration_date"] > NOV - pd.DateOffset(months=12))
                                 & (src["migration_date"] <= NOV)]["mrr_reclassified"].sum())
            assert p["graduated_mrr_in_month"] == pytest.approx(month)
            assert p["graduated_mrr_trailing_12m"] == pytest.approx(trailing)

    def test_graduated_share_is_over_the_source_segments_average_starting_mrr(self, con):
        r = sm.compute_segment_mix(NOV, con=con)
        pop = con.execute("select segment, month, starting_mrr, starting_accounts "
                          "from main_marts.mart_durability").df()
        pop["month"] = pd.to_datetime(pop["month"])
        for p in r["migration"]:
            seg = pop[pop["segment"] == p["from_segment"]]
            in_window = seg[(seg["month"] > NOV - pd.DateOffset(months=12)) & (seg["month"] <= NOV)]
            assert p["graduated_share_of_source_mrr_trailing_12m"] == pytest.approx(
                p["graduated_mrr_trailing_12m"] / in_window["starting_mrr"].mean())
            month_row = seg[seg["month"] == NOV].iloc[0]
            assert p["graduated_share_of_source_mrr_in_month"] == pytest.approx(
                p["graduated_mrr_in_month"] / month_row["starting_mrr"])
            assert p["velocity_in_month"] == pytest.approx(
                p["events_in_month"] / month_row["starting_accounts"])
            assert p["avg_from_segment_accounts_trailing_12m"] == pytest.approx(
                in_window["starting_accounts"].mean())

    def test_velocity_is_the_validated_functions_own_number(self, con):
        r = sm.compute_segment_mix(NOV, con=con)
        direct = sm.compute_migration_velocity(NOV.date() + pd.offsets.MonthEnd(0), con=con)
        for p in r["migration"]:
            row = direct[(direct["from_segment"] == p["from_segment"])
                         & (direct["to_segment"] == p["to_segment"])].iloc[0]
            assert p["velocity_trailing_12m"] == row["migration_rate"]
            assert p["events_trailing_12m"] == row["event_count"]

    def test_the_year_ago_velocity_is_the_same_function_a_year_earlier(self, con):
        r = sm.compute_segment_mix(NOV, con=con)
        direct = sm.compute_migration_velocity(pd.Timestamp("2024-11-30").date(), con=con)
        for p in r["migration"]:
            row = direct[(direct["from_segment"] == p["from_segment"])
                         & (direct["to_segment"] == p["to_segment"])].iloc[0]
            assert p["velocity_trailing_12m_year_ago"] == row["migration_rate"]
            assert p["events_trailing_12m_year_ago"] == row["event_count"]
            assert p["velocity_change_vs_year_ago"] == pytest.approx(
                p["velocity_trailing_12m"] - p["velocity_trailing_12m_year_ago"])

    def test_graduated_mrr_reconciles_to_the_growth_bridge(self, all_months):
        for m, r in all_months.items():
            if r["status"] == "present":
                assert r["reconciliation"]["reconciles"] and \
                    r["reconciliation"]["max_abs_diff_usd"] <= 0.01, m

    def test_rates_not_counts_move_in_the_direction_the_readout_headlines(self, all_months):
        # SMB to Commercial velocity roughly doubled over the year to 2025-11
        smb = all_months[NOV]["migration"][0]
        assert smb["velocity_trailing_12m"] > smb["velocity_trailing_12m_year_ago"] > 0
        assert all_months[NOV]["upmarket_share"]["change_vs_12m_ago"] == pytest.approx(
            0.0522593, abs=1e-6)


# --------------------------------------------------------------------------
# Point in time
# --------------------------------------------------------------------------

class TestPointInTime:
    def _copy(self, con):
        mem = duckdb.connect(":memory:")
        mem.execute("create schema main_marts")
        for table in ("mart_growth_bridge", "mart_segment_migration", "mart_durability"):
            df = con.execute(f"select * from main_marts.{table}").df()
            mem.register("src_df", df)
            mem.execute(f"create table main_marts.{table} as select * from src_df")
            mem.unregister("src_df")
        return mem

    def test_rows_after_the_evaluation_month_are_never_read(self, con):
        month = pd.Timestamp("2025-06-01")
        base = sm.compute_segment_mix(month, con=con)
        mem = self._copy(con)
        try:
            # poison everything after June 2025 in all three marts, keeping the final
            # month intact so the month is not mistaken for the truncated one
            mem.execute("update main_marts.mart_growth_bridge set ending_mrr = ending_mrr * 50 "
                        "where month > '2025-06-01' and month < '2025-12-01'")
            mem.execute("update main_marts.mart_segment_migration set mrr_reclassified = 1e9, "
                        "migration_date = migration_date where migration_date > '2025-06-01'")
            mem.execute("update main_marts.mart_durability set starting_accounts = 1, "
                        "starting_mrr = 1 where month > '2025-06-01'")
            poisoned = sm.compute_segment_mix(month, con=mem)
        finally:
            mem.close()
        assert poisoned == base

    def test_an_earlier_month_is_unaffected_by_a_later_one_existing(self, con):
        a = sm.compute_segment_mix(pd.Timestamp("2024-03-01"), con=con)
        assert a["status"] == "present"
        assert a["window"]["last_month_in_marts"] == "2025-12-01"
        assert a["evaluation_month"] == "2024-03-01"

    def test_a_mid_month_timestamp_is_read_as_that_month(self, con):
        assert sm.compute_segment_mix(pd.Timestamp("2025-11-17"), con=con) == \
            sm.compute_segment_mix(NOV, con=con)

    def test_deterministic(self, con):
        assert sm.compute_segment_mix(NOV, con=con) == sm.compute_segment_mix(NOV, con=con)


# --------------------------------------------------------------------------
# Unavailable and partial paths
# --------------------------------------------------------------------------

class TestUnavailable:
    def test_the_truncated_final_month_is_unavailable_with_a_reason(self, all_months):
        r = all_months[pd.Timestamp("2025-12-01")]
        assert r["status"] == "unavailable"
        assert r["reason"] == "evaluation_month_is_truncated_final_month"
        assert "prior month is the last representative month" in r["detail"]
        assert not any(k in r for k in ("segments", "migration", "upmarket_share", "window"))
        assert r["basis"] and r["caveats"]

    def test_a_month_after_the_data_is_unavailable(self, con):
        r = sm.compute_segment_mix(pd.Timestamp("2026-03-01"), con=con)
        assert r["status"] == "unavailable"
        assert r["reason"] == "no_segment_data_for_evaluation_month"

    def test_months_before_all_three_segments_exist_are_unavailable(self, all_months):
        early = [m for m, r in all_months.items() if r["status"] != "present"
                 and m < pd.Timestamp("2025-12-01")]
        assert early == list(pd.date_range("2020-01-01", "2020-06-01", freq="MS"))
        for m in early:
            assert all_months[m]["reason"] == "no_segment_data_for_evaluation_month"

    def test_present_months_run_from_2020_07_to_2025_11(self, all_months):
        present = [m for m, r in all_months.items() if r["status"] == "present"]
        assert present[0] == pd.Timestamp("2020-07-01") and present[-1] == NOV
        assert len(present) == 65

    def test_the_year_ago_window_is_reported_unavailable_until_two_years_of_history_exist(
            self, all_months):
        early = all_months[pd.Timestamp("2021-06-01")]
        assert early["window"]["year_ago_window_available"] is False
        assert early["window"]["year_ago_month"] is None
        assert early["upmarket_share"]["change_vs_12m_ago"] is None
        assert all(p["velocity_trailing_12m_year_ago"] is None
                   and p["velocity_change_vs_year_ago"] is None for p in early["migration"])
        assert all(s["share_change_vs_12m_ago"] is None for s in early["segments"])
        # prior-month figures are still there
        assert early["upmarket_share"]["change_vs_prior_month"] is not None
        later = all_months[pd.Timestamp("2022-06-01")]
        assert later["window"]["year_ago_window_available"] is True
        assert later["migration"][0]["velocity_trailing_12m_year_ago"] is not None

    def test_the_boundary_month_for_the_year_ago_window(self, all_months):
        # 12 months ending 12 months before must start at or after the first mart month
        assert all_months[pd.Timestamp("2021-11-01")]["window"]["year_ago_window_available"] is False
        assert all_months[pd.Timestamp("2021-12-01")]["window"]["year_ago_window_available"] is True


class TestContractStrings:
    def test_the_basis_and_caveats_state_the_upward_only_construction(self):
        assert "no downgrade path" in " ".join(sm.SEGMENT_MIX_CAVEATS)
        assert "rates" in sm.SEGMENT_MIX_CAVEATS[0]
        assert "not comparable with each other" in sm.SEGMENT_MIX_BASIS
        assert sm.SEGMENT_ORDER == ("SMB", "Commercial", "Enterprise")
        assert sm.UPMARKET_SEGMENTS == ("Commercial", "Enterprise")

    def test_the_module_is_still_free_of_randomness(self):
        src = open(os.path.join(ROOT, "analytics", "segment_migration.py")).read()
        assert "random" not in src.split('"""', 2)[2]


class TestWindowBoundary:
    """A month-end as-of takes the exact month boundary, not the same calendar day."""

    def _mem(self, events):
        mem = duckdb.connect(":memory:")
        mem.execute("create schema main_marts")
        mem.execute("create table main_marts.mart_segment_migration as select * from (values "
                    + ",".join("('%s','%s','%s',DATE '%s','usage_threshold',true,false,10,100.0)" % e
                               for e in events)
                    + ") t(account_id, from_segment, to_segment, migration_date, trigger_reason, "
                      "is_usage_threshold_migration, is_firmographic_rescore_migration, "
                      "days_in_prior_segment, mrr_reclassified)")
        mem.execute("create table main_marts.mart_durability as select * from (values "
                    "('SMB', TIMESTAMP '2025-01-01', 100.0, 1000.0), "
                    "('SMB', TIMESTAMP '2025-02-01', 100.0, 1000.0), "
                    "('Commercial', TIMESTAMP '2025-01-01', 10.0, 1000.0), "
                    "('Commercial', TIMESTAMP '2025-02-01', 10.0, 1000.0)) "
                    "t(segment, month, starting_accounts, starting_mrr)")
        return mem

    def test_a_one_month_window_ending_on_28_february_excludes_the_last_days_of_january(self):
        from datetime import date
        mem = self._mem([("A1", "SMB", "Commercial", "2025-01-30"),
                         ("A2", "SMB", "Commercial", "2025-01-29"),
                         ("A3", "SMB", "Commercial", "2025-02-10")])
        try:
            v = sm.compute_migration_velocity(date(2025, 2, 28), window_months=1, con=mem)
            g = sm.compute_graduated_revenue(date(2025, 2, 28), window_months=1, con=mem)
        finally:
            mem.close()
        assert int(v[v["from_segment"] == "SMB"]["event_count"].iloc[0]) == 1
        assert g[g["from_segment"] == "All"]["graduated_revenue_mrr"].sum() == 100.0

    def test_the_boundary_is_the_month_end_for_every_month_end(self):
        for m in pd.date_range("2024-01-31", "2025-12-31", freq="ME"):
            start, end = sm._trailing_window(m.date(), 1)
            assert start == (m - pd.offsets.MonthEnd(1)) and end == m
            start12, _ = sm._trailing_window(m.date(), 12)
            assert start12 == (m - pd.DateOffset(months=12)) + pd.offsets.MonthEnd(0)
            assert start12.day == (start12 + pd.offsets.MonthEnd(0)).day  # a month end

    def test_a_mid_month_as_of_keeps_the_calendar_day_window(self):
        from datetime import date
        start, end = sm._trailing_window(date(2025, 11, 15), 12)
        assert start == pd.Timestamp("2024-11-15") and end == pd.Timestamp("2025-11-15")
