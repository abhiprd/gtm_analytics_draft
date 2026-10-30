"""Stat-tile HTML (dashboard/lib/cards.py): the direction glyph follows the sign of the
change and never the judgment, color and a status word carry the judgment, a caveated tile
carries a marker and a neutral delta, the sparkline appears only when given a series, and
the type tokens stay inside the six-step scale."""
import json
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dashboard import tokens as T  # noqa: E402
from dashboard.lib import cards as C  # noqa: E402
from dashboard.lib import verdict as V  # noqa: E402

OUT = os.path.join(REPO, "analytics", "outputs")


def tile(**over):
    base = dict(label="Onboarding/CS efficiency", value_display="4.22 per 1M Actions", pillar="efficiency",
                variance_display="-30.0%", comparison_display="vs 6.03 per 1M Actions plan",
                favorable_direction="lower", is_ahead=True, status_word="Ahead")
    base.update(over)
    return base


def delta_html(html):
    m = re.search(r'<span class="delta-main" style="color:([^"]+)">([^<]*)</span>', html)
    return (m.group(1), m.group(2)) if m else (None, None)


class TestDeltaLine:
    def test_a_favorable_decrease_is_a_down_arrow_in_green_with_its_word(self):
        html = C.card_inner(tile())
        color, text = delta_html(html)
        assert color == T.FAVORABLE_GREEN and text == "▼ -30.0%"
        assert ">Ahead<" in html
        assert "▲ -" not in html  # the contradiction: an up arrow beside a negative change

    def test_an_unfavorable_increase_is_an_up_arrow_in_red(self):
        html = C.card_inner(tile(variance_display="+8.0%", is_ahead=False, status_word="Behind"))
        color, text = delta_html(html)
        assert color == T.UNFAVORABLE_RED and text == "▲ +8.0%" and ">Behind<" in html

    def test_a_neutral_delta_keeps_its_direction_in_secondary_text_with_no_word(self):
        html = C.card_inner(tile(favorable_direction=None, is_ahead=None, status_word=None,
                                 variance_display="+337.6%"))
        color, text = delta_html(html)
        assert color == T.TEXT_SECONDARY and text == "▲ +337.6%"
        assert "delta-word" not in html

    def test_judged_tiles_without_an_explicit_word_get_favorable_or_unfavorable(self):
        up = C.card_inner(tile(status_word=None, variance_display="+3.0 pp", favorable_direction="higher"))
        down = C.card_inner(tile(status_word=None, variance_display="-3.0 pp", favorable_direction="higher",
                                 is_ahead=False))
        assert ">Favorable<" in up and ">Unfavorable<" in down

    def test_zero_change_has_no_glyph_and_no_judgment_color(self):
        html = C.card_inner(tile(variance_display="0.0%", favorable_direction=None, is_ahead=None, status_word=None))
        assert delta_html(html) == (T.TEXT_SECONDARY, "0.0%")

    def test_not_computable_row_shows_no_glyph(self):
        html = C.card_inner(tile(variance_display="n/a", favorable_direction=None, is_ahead=None,
                                 status_word="Not computable", comparison_display=None))
        assert delta_html(html)[1] == "n/a" and ">Not computable<" in html

    @pytest.mark.parametrize("d", ["2025-06-30", "2025-11-30"])
    def test_every_committed_tile_glyph_matches_the_readouts_own_sign_in_the_html(self, d):
        """The oracle is the sign of the readout's own `variance_pct`, not the displayed string."""
        with open(os.path.join(OUT, f"weekly_readout_{d}.json")) as f:
            rows = json.load(f)["layer1_scorecard"]["rows"]
        for r in rows:
            html = C.card_inner(V.card_for_row(r, r["pillar"], 8))
            _, text = delta_html(html)
            if V.is_degenerate(r):  # a constant series has no delta line
                assert text is None, r["metric_key"]
                continue
            vp = r.get("variance_pct")
            if vp is None or vp != vp:  # Not computable: "n/a", no glyph
                assert text == "n/a", (r["metric_key"], text)
                continue
            pct = vp * 100
            expected = "▲" if pct >= 0.05 else "▼" if pct <= -0.05 else ""
            glyph = text[:1] if text[:1] in ("▲", "▼") else ""
            assert glyph == expected, (r["metric_key"], vp, text)

    @pytest.mark.parametrize("d", ["2025-06-30", "2025-11-30"])
    def test_a_caveated_tile_never_carries_an_ahead_or_behind_phrase(self, d):
        with open(os.path.join(OUT, f"weekly_readout_{d}.json")) as f:
            rows = json.load(f)["layer1_scorecard"]["rows"]
        checked = 0
        for r in rows:
            if r.get("plan_comparability") != "caveated" or r["status"] == "Not computable":
                continue
            html = C.card_inner(V.card_for_row(r, r["pillar"], 8))
            checked += 1
            for phrase in ("Ahead", "Behind", "Favorable", "Unfavorable"):
                assert phrase not in html, (r["metric_key"], phrase)
            assert V.NOT_JUDGED in html
        assert checked >= 5


class TestTileAnatomy:
    def test_caveated_marker_and_about_disclosure(self):
        html = C.card_inner(V.card_for_row(
            dict(metric_key="magic_number", label="Magic number", layer=1, pillar="efficiency", month="2025-11-01",
                 actual=2.5, plan=0.8, trailing_baseline=2.0, baseline_variance_pct=0.2, favorable_direction="higher",
                 plan_comparability="caveated", status="Ahead", unit="multiple", unit_label="Ratio",
                 value_display="2.51x", comparison_display="0.77x plan", variance_display="+225.9%"),
            "efficiency", 8))
        assert 'class="tile-flag"' in html and "Caveated comparison" in html
        assert "card-tag" not in html  # the full chip is not repeated on every tile
        assert "About this number" in html and "Layer 1" in html
        assert "delta-word" not in html

    def test_sparkline_only_when_a_series_is_given(self):
        assert "tile-spark" not in C.card_inner(tile())
        html = C.card_inner(tile(sparkline=[1, 2, 3, 2, 4, 5, 4, 6, 7, 6, 8, 9], spark_label="Trend"))
        assert html.count("<polyline") == 1 and 'role="img"' in html
        assert T.MARK_MUTED in html and T.PILLAR_COLOR["efficiency"] in html

    def test_a_constant_or_one_point_series_draws_nothing(self):
        assert C.sparkline_svg([3, 3, 3], "#000", "x") == ""
        assert C.sparkline_svg([3], "#000", "x") == ""

    def test_long_value_splits_number_and_unit(self):
        assert 'class="card-unit"' in C.card_inner(tile())

    def test_text_is_escaped(self):
        html = C.card_inner(tile(label="<b>x</b> $5", variance_display="+<1%"))
        assert "<b>" not in html and "&#36;5" in html


class TestTokens:
    def test_six_type_steps_in_ascending_order(self):
        sizes = list(T.TYPE_SCALE_PX.values())
        assert len(sizes) == 6 and sizes == sorted(sizes) and len(set(sizes)) == 6

    def test_one_font_family_and_no_serif_or_second_family(self):
        assert T.FONT_FAMILY.startswith('"Source Sans"')
        for name in ("Source Serif", "Inter", "Georgia"):
            assert name not in T.FONT_FAMILY

    @staticmethod
    def _luminance(hex_):
        rgb = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def ratio(self, fg, bg):
        a, b = sorted((self._luminance(fg), self._luminance(bg)), reverse=True)
        return (a + 0.05) / (b + 0.05)

    @pytest.mark.parametrize("fg", [T.INK, T.TEXT_SECONDARY, T.FAVORABLE_GREEN, T.UNFAVORABLE_RED])
    @pytest.mark.parametrize("bg", [T.SURFACE, T.BACKGROUND_OFF_WHITE])
    def test_text_colors_clear_4_5_to_1_on_every_surface(self, fg, bg):
        assert self.ratio(fg, bg) >= 4.5

    def test_amber_is_below_text_contrast_so_it_is_never_a_text_color(self):
        assert self.ratio(T.CAUTION_AMBER, T.SURFACE) < 3.0


# ---------------------------------------------------------------------------
# Source scan: no literal font family, uppercase transform or off-token font size outside
# tokens.py. A line may opt out with the marker below, with the reason on the same line.
# ---------------------------------------------------------------------------
import glob  # noqa: E402

ALLOW = "scan-allow"
DASH = os.path.join(REPO, "dashboard")


def _dashboard_sources():
    files = [os.path.join(DASH, "theme.py"), os.path.join(DASH, "home.py"), os.path.join(DASH, "app.py"),
             os.path.join(DASH, "chartkit.py")]
    files += sorted(glob.glob(os.path.join(DASH, "pages", "*.py")))
    files += sorted(glob.glob(os.path.join(DASH, "lib", "*.py")))
    return files


def _lines():
    for path in _dashboard_sources():
        with open(path) as f:
            for n, line in enumerate(f, start=1):
                if ALLOW not in line:
                    yield os.path.relpath(path, REPO), n, line


def test_no_uppercase_transform_anywhere():
    bad = [(p, n) for p, n, line in _lines() if "text-transform" in line]
    assert not bad, bad


def test_no_literal_font_family_outside_tokens():
    bad = [(p, n, line.strip()) for p, n, line in _lines()
           if re.search(r"font-family\s*:", line) or re.search(r"(Source Serif|Georgia|\"Inter\"|'Inter')", line)]
    assert not bad, bad


def test_every_css_font_size_is_a_type_token():
    bad = [(p, n, line.strip()) for p, n, line in _lines()
           if re.search(r"font-size\s*:\s*(?!\s|var\(--fs-)", line)]
    assert not bad, bad


def test_no_python_literal_font_size_in_a_plotly_font():
    bad = [(p, n, line.strip()) for p, n, line in _lines() if re.search(r"font=dict\([^)]*size=\d", line)
           or re.search(r"textfont=dict\([^)]*size=\d", line)]
    assert not bad, bad


def test_focused_date_segment_text_is_the_surface_color():
    """A focused date segment is painted with the ink fill, so the ink text override must not apply to it."""
    css = open(os.path.join(DASH, "theme.py")).read()
    line = next(l for l in css.splitlines() if '[data-testid="stDateInput"] [role="spinbutton"]:focus' in l)
    assert "color: {t.SURFACE} !important" in line and "-webkit-text-fill-color: {t.SURFACE} !important" in line


def test_expander_summaries_are_44px_tap_targets_on_narrow_screens():
    css = open(os.path.join(DASH, "theme.py")).read()
    media = css[css.index("@media (max-width: 640px)"):]
    assert re.search(r'\[data-testid="stExpander"\] summary \{\{ min-height: 44px', media)


# ---------------------------------------------------------------------------
# Responsive card grid: columns come from the container width and a tile never goes below its
# minimum, so no value, unit or label is squeezed at any viewport.
# ---------------------------------------------------------------------------
def _theme_source():
    return open(os.path.join(DASH, "theme.py")).read()


def test_card_grid_has_no_fixed_column_count():
    src = _theme_source()
    start = src.index("def scorecard_row(")
    body = src[start:src.index("def info_row(")]
    assert "grid-template-columns" not in body and "repeat(" not in body
    assert 'data-n="{n}"' in body and "card-grid-wrap" in body
    # No inline repeat(N, ...) column template anywhere on a card grid.
    for path in _dashboard_sources():
        text = open(path).read()
        assert not re.search(r'class="card-grid[^"]*"[^>]*style="grid-template-columns:repeat\(', text), path


def test_card_grid_columns_come_from_container_queries_at_the_tile_minimum():
    src = _theme_source()
    assert "container-type: inline-size" in src
    for expr in ("2 * t.TILE_MIN_PX + t.GRID_GAP_PX", "3 * t.TILE_MIN_PX + 2 * t.GRID_GAP_PX",
                 "4 * t.TILE_MIN_PX + 3 * t.GRID_GAP_PX"):
        assert f"@container (min-width: {{{expr}}}px)" in src, expr
    assert T.TILE_MIN_PX >= 160  # wide enough for "Not computable" at the lg step plus padding


def test_words_never_break_mid_word_inside_a_card():
    src = _theme_source()
    assert re.search(r"\.grid-card \*[^{]*\{\{[^}]*overflow-wrap: normal;[^}]*word-break: normal", src)
    assert "white-space: nowrap" in src[src.index(".tile-about summary {{"):src.index(".tile-about summary::-webkit")]


def test_plain_values_are_one_unbreakable_piece_and_split_values_keep_their_number_whole():
    plain = C.card_inner(tile(value_display="$760.6K"))
    assert 'class="card-value nw"' in plain
    split = C.card_inner(tile(value_display="4.22 per 1M Actions"))
    assert '<span class="card-num">4.22</span>' in split and 'class="card-unit"' in split
    sm = C.card_inner(tile(value_display="Not computable", value_size="sm"))
    assert 'class="card-value sm"' in sm  # wraps only at its space
