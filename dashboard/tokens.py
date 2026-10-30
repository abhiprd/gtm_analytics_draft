"""Design tokens: the palette, text colors, type scale and radii that
.claude/skills/dashboard-design-conventions/SKILL.md defines, as plain Python with no
Streamlit import so the Streamlit-free card builder (lib/cards.py) and the unit tests
can use them. theme.py re-exports every name here; pages import theme, not this module.

Changing a value here means changing the skill file first (Sections 2 and 5.3-5.5).
"""

# --- Palette A: pillar/category identity (Section 2.2): never a status judgment. ---
GROWTH_NAVY = "#1E2761"
GROWTH_ICE_BLUE = "#CADCFC"
EFFICIENCY_TEAL = "#1C7293"
DURABILITY_TERRACOTTA = "#B85042"
BACKGROUND_OFF_WHITE = "#F7F8FA"

PILLAR_COLOR = {
    "growth": GROWTH_NAVY,
    "efficiency": EFFICIENCY_TEAL,
    "durability": DURABILITY_TERRACOTTA,
}

# --- Palette B: performance/status semantics (Section 2.3): never category identity. ---
FAVORABLE_GREEN = "#2E7D4F"
UNFAVORABLE_RED = "#C0392B"
CAUTION_AMBER = "#D89614"  # a non-text fill or icon only (2.53:1 on white), paired with a label
NEUTRAL_GRAY = "#6B7280"   # marks, dots and borders; neutral text uses TEXT_SECONDARY

# --- Segment palette (Section 2.4): its own hue family. ---
SEGMENT_COLOR = {
    "SMB": "#94A3B8",
    "Commercial": "#475569",
    "Enterprise": "#1E293B",
}

# --- Reason/category pair for non-pillar, non-status, non-segment categories (for example the
# trigger reason of a segment migration): one violet hue in two lightness steps. Checked with the
# dataviz palette validator when chosen (lightness band, chroma floor, color-vision and
# normal-vision separation, 3:1 contrast on white); measured 8.56:1 and 3.23:1 on white, pair
# separation dE 21.8 (protan) and 23.1 (normal). Not Palette A, so a chart of reasons is never
# read as a pillar chart.
CATEGORY_VIOLET = "#4A3AA7"
CATEGORY_VIOLET_LIGHT = "#8F85D6"
INK_STRONG = "#111827"  # text on CATEGORY_VIOLET_LIGHT (5.5:1)

# --- Text tokens (Section 2.6): never an opacity. ---
INK = GROWTH_NAVY            # 13.9:1 on white, 13.0:1 on the page fill
TEXT_SECONDARY = "#4B5563"   # 7.6:1 on white, 7.1:1 on the page fill
GRID_LINE = "#E5E7EB"        # hairline furniture, no text
MARK_MUTED = "#8B93A1"       # sparkline stroke and other quiet marks, 3.1:1 on white
CARD_BORDER = "#E3E5EB"
SURFACE = "#FFFFFF"

# --- Type scale (Section 5.3): one family, six sizes, in px. ---
FONT_FAMILY = '"Source Sans", "Source Sans 3", system-ui, -apple-system, "Segoe UI", sans-serif'
FS_XS = 13
FS_SM = 14
FS_MD = 16
FS_LG = 20
FS_XL = 28
FS_2XL = 36
TYPE_SCALE_PX = {"xs": FS_XS, "sm": FS_SM, "md": FS_MD, "lg": FS_LG, "xl": FS_XL, "2xl": FS_2XL}

# Prose is held to this many characters per line (a max-width in ch units), which keeps
# rendered lines under the 75-character limit of conventions Section 5.3.
PROSE_CH = 56

# --- Tile grid: a tile is never narrower than TILE_MIN_PX, so its label (which breaks only at
# spaces), value and unit always fit. The number of columns follows the container width, not the
# viewport: 2 columns from 2*TILE_MIN_PX + gap, 3 from 3*TILE_MIN_PX + 2*gap, 4 from 4*TILE_MIN_PX + 3*gap.
TILE_MIN_PX = 168
GRID_GAP_PX = 16

# --- Radius hierarchy (Section 5.5), in px. ---
RADIUS_CONTAINER = 12
RADIUS_CONTROL = 8
RADIUS_MARK = 4
