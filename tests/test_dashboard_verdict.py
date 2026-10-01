"""Scorecard-row treatment (dashboard/lib/verdict.py): caveated rows carry a tag and no
judgment color, a constant Not-computable series is a gap rather than a number, and a
delta that rounds to zero is neutral. Rows are shaped like the weekly readout's
layer1_scorecard rows; the committed readouts are also exercised by key."""
import json
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

    def test_caveated_card_has_tag_and_no_judgment(self):
        c = V.card_for_row(row(plan_comparability="caveated", metric_key="magic_number",
                               variance_display="+225.9%"), "efficiency", 8)
        assert c["tag"] == V.CAVEAT_TAG
        assert c["favorable_direction"] is None and c["is_ahead"] is None
        assert V.CAVEAT_FOOTER in c["footer"]

    def test_comparable_ahead_and_behind_keep_their_status(self):
        up = V.card_for_row(row(), "growth")
        down = V.card_for_row(row(status="Behind", variance_display="-9.0%"), "growth")
        assert up["is_ahead"] is True and up["favorable_direction"] == "higher" and "tag" not in up
        assert down["is_ahead"] is False

    def test_on_track_is_neutral_with_its_own_glyph(self):
        c = V.card_for_row(row(status="On track", variance_display="+0.4%"), "growth")
        assert c["is_ahead"] is None and c["variance_display"].startswith("● On track")

    def test_every_card_ends_with_its_layer(self):
        assert V.card_for_row(row(layer=1))["footer"][-1] == "Layer 1"


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
        assert c["footer"][-1] == f"Layer {r['layer']}"
        if r.get("plan_comparability") == "caveated" and r["status"] != "Not computable":
            assert c["tag"] == V.CAVEAT_TAG and c["is_ahead"] is None
        if V.is_degenerate(r):
            assert c["value_display"] == "Not computable"


# ---------------------------------------------------------------------------
# Scientific notation, per-1M-Actions scaling, negative zero
# ---------------------------------------------------------------------------
import re  # noqa: E402

SCI = re.compile(r"\d[eE][+-]?\d")


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
        assert c["comparison_display"] == "6.16 per 1M Actions plan"
        assert any("trailing baseline: 5.54 per 1M Actions" in f for f in c["footer"])
        assert "per 1M" in " ".join(c["footer"])

    def test_no_card_text_contains_an_exponent(self):
        c = V.card_for_row(onboarding_row(), "efficiency", 8)
        text = " ".join(str(v) for v in c.values() if isinstance(v, str)) + " ".join(c["footer"])
        assert not SCI.search(text)

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
            blob = " ".join(str(v) for v in c.values() if isinstance(v, str)) + " ".join(c["footer"])
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
