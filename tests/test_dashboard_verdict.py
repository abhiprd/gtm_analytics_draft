"""Scorecard-row treatment (dashboard/lib/verdict.py): caveated rows carry a marker and no
judgment color, a constant Not-computable series is a gap rather than a number, and a
delta that rounds to zero is neutral. Rows are shaped like the weekly readout's
layer1_scorecard rows; the committed readouts are also exercised by key."""
import json
import math
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard.lib import verdict as V  # noqa: E402


def row(**over):
    base = dict(metric_key="new_logo_consumption_revenue", label="New logo", layer=1, pillar="growth",
                month="2025-11-01", actual=45183.95, plan=19800.0, trailing_baseline=19400.0,
                baseline_variance_pct=1.3, prior_month_value=30000.0, favorable_direction="higher",
                plan_comparability="comparable", plan_comparability_note=None, status="Ahead",
                unit="usd", unit_label="USD, monthly MRR movement", value_display="$45.2K",
                comparison_display="$19.8K plan", variance_display="+128.2%")
    base.update(over)
    return base


class TestCaveated:
    def test_detection_reads_plan_comparability_only(self):
        assert V.is_caveated(row(plan_comparability="caveated"))
        assert not V.is_caveated(row(plan_comparability="comparable"))
        assert not V.is_caveated(row(plan_comparability="no_plan_by_design"))

    def test_caveated_card_has_marker_and_no_judgment(self):
        c = V.card_for_row(row(plan_comparability="caveated", metric_key="magic_number",
                               variance_display="+225.9%"), "efficiency", 8)
        assert c["marker"] == V.CAVEAT_TAG and "tag" not in c
        assert c["favorable_direction"] is None and c["is_ahead"] is None
        assert (V.CAVEAT_TAG, V.CAVEAT_FOOTER) in c["about"]
        assert "status_word" not in c  # a caveated gap carries no Ahead/Behind word

    def test_comparable_ahead_and_behind_keep_their_status(self):
        up = V.card_for_row(row(), "growth")
        down = V.card_for_row(row(status="Behind", variance_display="-9.0%"), "growth")
        assert up["is_ahead"] is True and up["favorable_direction"] == "higher" and "marker" not in up
        assert up["status_word"] == "Ahead" and down["status_word"] == "Behind"
        assert down["is_ahead"] is False

    def test_on_track_is_neutral_with_its_own_word(self):
        c = V.card_for_row(row(status="On track", variance_display="+0.4%"), "growth")
        assert c["is_ahead"] is None and c["status_word"] == "On track" and c["variance_display"] == "+0.4%"

    def test_not_computable_has_no_directional_glyph(self):
        c = V.card_for_row(row(status="Not computable", variance_display="n/a"), "growth")
        assert c["variance_display"] == "n/a" and c["status_word"] == "Not computable"
        assert V.delta_glyph(c["variance_display"]) == ""

    def test_every_card_ends_with_its_layer_in_about(self):
        assert V.card_for_row(row(layer=1))["about"][-1] == ("Layer", "Layer 1")
        assert V.card_for_row(row(layer=2))["about"][-1] == ("Layer", "Layer 2")

    def test_comparison_reads_as_against_the_plan(self):
        assert V.card_for_row(row())["comparison_display"] == "vs $19.8K plan"


class TestDegenerate:
    def degenerate(self, **over):
        fields = dict(metric_key="activation", status="Not computable", actual=0.0, prior_month_value=0.0,
                      trailing_baseline=0.0, value_display="0.00 mo", plan_comparability="no_plan_by_design",
                      variance_display="n/a", comparison_display="0.00 mo last month")
        fields.update(over)
        return row(**fields)

    def test_identical_actual_prior_and_baseline_is_degenerate(self):
        assert V.is_degenerate(self.degenerate())

    def test_not_computable_without_a_baseline_is_not_degenerate(self):
        assert not V.is_degenerate(self.degenerate(trailing_baseline=None))

    def test_only_not_computable_rows_can_be_degenerate(self):
        assert not V.is_degenerate(row(actual=0.0, prior_month_value=0.0, trailing_baseline=0.0))

    def test_card_shows_not_computable_in_place_of_the_number(self):
        c = V.card_for_row(self.degenerate(), "growth")
        assert c["value_display"] == "Not computable"
        assert "0.00 mo" not in c["value_display"]
        assert c.get("is_ahead") is None and c.get("comparison_display") is None


class TestZeroDeltaNeutrality:
    @pytest.mark.parametrize("text", ["+0.0%", "-0.0%", "+0.00x", "+$0", "+0.0 pp", "-0.0"])
    def test_zero_displays(self, text):
        assert V.display_rounds_to_zero(text)

    @pytest.mark.parametrize("text", ["+0.1%", "-1.2 pp", "+$1.2K", None, "n/a", ""])
    def test_non_zero_displays(self, text):
        assert not V.display_rounds_to_zero(text)

    def test_a_zero_variance_row_gets_no_status_color(self):
        c = V.card_for_row(row(status="Ahead", variance_display="+0.0%"), "growth")
        assert c["is_ahead"] is None and c["favorable_direction"] is None

    def test_rate_moves_are_labeled_pp(self):
        assert V.pp_text(0.0123) == "+1.2 pp" and V.pp_text(-0.079) == "-7.9 pp"


class TestBasis:
    def test_ttm_metrics_say_trailing_12_months(self):
        for key in ("magic_number", "am_efficiency", "nrr", "grr", "logo_retention"):
            assert V.basis_label(row(metric_key=key)).startswith("Trailing 12 months to 2025-11")

    def test_other_metrics_say_the_month(self):
        assert V.basis_label(row(metric_key="consumption_payback")) == "Month of 2025-11"

    def test_a_row_basis_field_wins(self):
        assert V.basis_label(row(basis="Quarter")) == "Quarter"


OUT = os.path.join(REPO, "analytics", "outputs")


@pytest.mark.parametrize("d", ["2025-06-30", "2025-11-30"])
def test_committed_readout_rows_get_cards_and_caveats_follow_the_flag(d):
    with open(os.path.join(OUT, f"weekly_readout_{d}.json")) as f:
        rows = json.load(f)["layer1_scorecard"]["rows"]
    for r in rows:
        c = V.card_for_row(r, r["pillar"], 8)
        assert c["about"][-1] == ("Layer", f"Layer {r['layer']}")
        if r.get("plan_comparability") == "caveated" and r["status"] != "Not computable":
            assert c["marker"] == V.CAVEAT_TAG and c["is_ahead"] is None
        if V.is_degenerate(r):
            assert c["value_display"] == "Not computable"


# ---------------------------------------------------------------------------
# Scientific notation, per-1M-Actions scaling, negative zero
# ---------------------------------------------------------------------------
import re  # noqa: E402

SCI = re.compile(r"\d[eE][+-]?\d")


def _card_text(c):
    """Every string a card can show: its fields, footer lines and About rows."""
    parts = [str(v) for v in c.values() if isinstance(v, str)]
    parts += list(c.get("footer") or [])
    parts += [f"{k} {v}" for k, v in c.get("about") or []]
    return " ".join(parts)


def onboarding_row(**over):
    base = row(metric_key="onboarding_cs_efficiency", unit="touches_per_action", favorable_direction="lower",
               actual=5.261609e-06, plan=6.1649e-06, trailing_baseline=5.5439e-06, prior_month_value=5.4422e-06,
               baseline_variance_pct=-0.05, status="Ahead", variance_display="-14.7%",
               value_display="5.26e-06 touches/Action", comparison_display="6.16e-06 touches/Action plan",
               unit_label="AM/CS touchpoints per automated Action")
    base.update(over)
    return base


class TestNoScientificNotation:
    def test_onboarding_card_is_per_million_actions(self):
        c = V.card_for_row(onboarding_row(), "efficiency", 8)
        assert c["value_display"] == "5.26 per 1M Actions"
        assert c["comparison_display"] == "vs 6.16 per 1M Actions plan"
        assert any(k.endswith("trailing baseline") and v.startswith("5.54 per 1M Actions") for k, v in c["about"])
        assert "per 1M" in " ".join(v for _, v in c["about"])

    def test_no_card_text_contains_an_exponent(self):
        c = V.card_for_row(onboarding_row(), "efficiency", 8)
        assert not SCI.search(_card_text(c))

    @pytest.mark.parametrize("unit", ["usd", "rate", "months", "multiple", "touches_per_action", "mystery"])
    @pytest.mark.parametrize("value", [5.26e-06, 0.000123, 1.965e8, 1e-12, 42.0])
    def test_baseline_formatter_never_emits_an_exponent(self, unit, value):
        assert not SCI.search(V.format_baseline(value, unit))

    def test_plain_number_keeps_three_significant_digits_below_one(self):
        assert V.plain_number(5.26e-06) == "0.00000526" and V.plain_number(0.0789) == "0.0789"
        assert V.plain_number(1.965e8) == "196,500,000" and V.plain_number(0) == "0"

    def test_strip_scientific_is_a_last_resort_guard(self):
        assert not SCI.search(V.strip_scientific("a 4.22e-06 b 1.5E+05"))
        assert V.strip_scientific("v2e1x") == "v2e1x"

    @pytest.mark.parametrize("d", ["2025-06-30", "2025-11-30"])
    def test_committed_readouts_render_without_exponents(self, d):
        with open(os.path.join(OUT, f"weekly_readout_{d}.json")) as f:
            rows = json.load(f)["layer1_scorecard"]["rows"]
        for r in rows:
            c = V.card_for_row(r, r["pillar"], 8)
            blob = _card_text(c)
            assert not SCI.search(blob), (r["metric_key"], blob)


class TestNegativeZero:
    @pytest.mark.parametrize("text,expected", [("-0.0 pp", "0.0 pp"), ("+0.0%", "0.0%"), ("-0.00", "0.00"),
                                                ("-0.3 pp", "-0.3 pp"), ("+1.2%", "+1.2%"), (None, None)])
    def test_zero_has_no_sign(self, text, expected):
        assert V.unsigned_if_zero(text) == expected

    def test_a_zero_variance_card_prints_no_sign(self):
        c = V.card_for_row(row(variance_display="-0.0%", status="Ahead"), "growth")
        assert c["variance_display"] == "0.0%"


def test_degenerate_reason_does_not_print_the_constant():
    c = V.card_for_row(TestDegenerate().degenerate(), "growth")
    reason = [f for f in c["footer"] if "vary" in f]
    assert len(reason) == 1 and "0.00" not in reason[0] and "every month" not in reason[0]


# ---------------------------------------------------------------------------
# Delta glyph = sign of the displayed change; judgment is carried by color and a word.
# ---------------------------------------------------------------------------
class TestDeltaGlyph:
    @pytest.mark.parametrize("text,glyph", [
        ("+128.2%", "▲"), ("-30.0%", "▼"), ("−8.0%", "▼"), ("+1.2 pp", "▲"), ("-0.9 pp", "▼"),
        ("+$1.2K", "▲"), ("-$54.1K", "▼"), ("+0.31x", "▲"), ("+3", "▲"),
    ])
    def test_glyph_follows_the_sign(self, text, glyph):
        assert V.delta_glyph(text) == glyph

    @pytest.mark.parametrize("text", ["+0.0%", "-0.0 pp", "0.0%", "n/a", "", None, "12.5%"])
    def test_no_glyph_for_zero_unsigned_or_missing(self, text):
        assert V.delta_glyph(text) == ""

    def test_a_favorable_decrease_is_a_down_arrow(self):
        # Onboarding/CS efficiency: lower is better, so -30.0% against plan is Ahead, and the
        # glyph still points down.
        c = V.card_for_row(onboarding_row(variance_display="-30.0%", status="Ahead"), "efficiency", 8)
        assert c["is_ahead"] is True and c["favorable_direction"] == "lower"
        assert V.delta_glyph(c["variance_display"]) == "▼"

    @pytest.mark.parametrize("d", ["2025-06-30", "2025-11-30"])
    def test_every_committed_row_glyph_matches_the_readouts_own_sign(self, d):
        """The oracle is the sign of the readout's `variance_pct`; delta_glyph is under test."""
        with open(os.path.join(OUT, f"weekly_readout_{d}.json")) as f:
            rows = json.load(f)["layer1_scorecard"]["rows"]
        for r in rows:
            c = V.card_for_row(r, r["pillar"], 8)
            vp = r.get("variance_pct")
            if V.is_degenerate(r) or vp is None or vp != vp:
                assert V.delta_glyph(c.get("variance_display")) == "", r["metric_key"]
                continue
            pct = vp * 100
            expected = "▲" if pct >= 0.05 else "▼" if pct <= -0.05 else ""
            assert V.delta_glyph(c["variance_display"]) == expected, (r["metric_key"], vp, c["variance_display"])


# ---------------------------------------------------------------------------
# Sparkline: drawn only from 12 consecutive complete months that end at the row's own actual.
# ---------------------------------------------------------------------------
def monthly(values_by_key):
    return values_by_key


def months_to(end, n):
    keys, y, m = [], int(end[:4]), int(end[5:7])
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return keys[::-1]


class TestTrendPoints:
    def series(self, n=14, last=45183.95):
        keys = months_to("2025-11", n)
        vals = [100.0 + i for i in range(n - 1)] + [last]
        return dict(zip(keys, vals))

    def test_twelve_points_ending_at_the_actual(self):
        pts = V.trend_points(self.series(), row())
        assert pts is not None and len(pts) == 12 and pts[-1] == 45183.95

    def test_a_series_that_disagrees_with_the_headline_is_dropped(self):
        assert V.trend_points(self.series(last=40000.0), row()) is None

    def test_fewer_than_twelve_months_or_a_gap_is_dropped(self):
        assert V.trend_points(self.series(n=11), row()) is None
        s = self.series()
        s["2025-05"] = None
        assert V.trend_points(s, row()) is None

    def test_constant_or_missing_series_is_dropped(self):
        flat = {k: 5.0 for k in months_to("2025-11", 12)}
        assert V.trend_points(flat, row(actual=5.0)) is None
        assert V.trend_points(None, row()) is None
        assert V.trend_points({}, row()) is None

    def test_card_carries_the_sparkline_only_when_the_series_is_valid(self):
        assert "sparkline" in V.card_for_row(row(), "growth", 8, self.series())
        assert "sparkline" not in V.card_for_row(row(), "growth", 8, self.series(last=1.0))
        assert "sparkline" not in V.card_for_row(row(), "growth", 8, None)

    @pytest.mark.parametrize("d", ["2025-06-30", "2025-11-30"])
    def test_committed_readout_months_are_consecutive(self, d):
        with open(os.path.join(OUT, f"weekly_readout_{d}.json")) as f:
            r = json.load(f)["layer1_scorecard"]["rows"][0]
        keys = V._previous_months(V._month_key(r["month"]), 12)
        assert len(keys) == 12 and keys[-1] == str(r["month"])[:7] and len(set(keys)) == 12


# ---------------------------------------------------------------------------
# Integration: the engine's monthly series ends at the readout's own actual for every tile that
# draws a sparkline, for both committed readout dates.
# ---------------------------------------------------------------------------
DB = os.path.join(REPO, "data", "acme_gtm.duckdb")


@pytest.mark.skipif(not os.path.exists(DB), reason="needs data/acme_gtm.duckdb")
@pytest.mark.parametrize("d", ["2025-06-30", "2025-11-30"])
def test_sparkline_series_ends_at_the_readout_actual_for_every_drawn_tile(d):
    from datetime import date
    from analytics import variance_diagnostic as vd
    with open(os.path.join(OUT, f"weekly_readout_{d}.json")) as f:
        rows = json.load(f)["layer1_scorecard"]["rows"]
    series = V.monthly_series(vd.blend_layer1_actuals(date.fromisoformat(d)))
    drawn, omitted = [], []
    for r in rows:
        c = V.card_for_row(r, r["pillar"], 8, series.get(r["metric_key"]))
        if "sparkline" in c:
            assert len(c["sparkline"]) == 12
            assert math.isclose(c["sparkline"][-1], r["actual"], rel_tol=1e-6), r["metric_key"]
            drawn.append(r["metric_key"])
        else:
            omitted.append(r["metric_key"])
    assert len(drawn) >= 9
    assert all(V.is_degenerate(r) for r in rows if r["metric_key"] in omitted)
