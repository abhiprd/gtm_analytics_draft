---
name: dashboard-design-conventions
description: Read before building or editing any Streamlit dashboard page for the Acme Corp GTM portfolio. Covers color semantics, chart-type selection, audience-adaptive layout, information hierarchy, grain/resolution rules, and Streamlit implementation patterns. This is the single source of truth for visual and presentation decisions — nothing about a dashboard page's look is a matter of individual taste, it's a rule in this file or a decision that needs to be added to it.
---

# Dashboard design conventions

This file exists because the first version of the dashboard was functional but visually flat and inconsistent — right axes, wrong chart types, no distinction between what an exec needs to see and what an analyst needs to see, and no shared visual language with the rest of the portfolio (the deck already has one; the dashboard ignored it). Every rule below is here to prevent a specific failure mode, not as decoration.

Read this in full before building or editing a page. If a design question comes up that this file doesn't answer, answer it, then add the answer here — don't let the same judgment call get made differently on two different pages.

---

## 1. Why dashboard design is a discipline, not a preference

A dashboard has one job the deck doesn't: it has to work when nobody is walking the reader through it. A deck has a narrator. A dashboard is read cold, often in under 30 seconds, often by someone deciding whether to keep looking or move on. That changes the rules:

- **The eye goes to color and size before it goes to text.** If the highest-contrast element on the page isn't the most important number, the page is lying to the reader's instincts even if every label is accurate.
- **A reader forms a verdict before reading a single label**, from position, color, and size alone. If a metric card is red, the reader has already concluded "bad" before reading which metric it is. That verdict had better be correct.
- **Consistency is what lets a reader stop reading.** Once someone learns that red always means "below plan, unfavorable" on this dashboard, they stop needing to check the legend. Break that pattern once, anywhere, and they have to start reading captions again everywhere — the entire efficiency gain of a well-designed dashboard is destroyed by a single inconsistent page.

Everything below serves one or more of these three facts.

---

## 2. Color

### 2.1 Color is a channel for meaning, not decoration

Every color used on a dashboard page must mean the same thing every time it appears, on every page. A color that sometimes means "bad" and sometimes just means "this pillar" is a color that's actively misleading the reader half the time.

This is the single most common failure mode in dashboards built without a convention doc: someone picks a "nice palette," assigns it to categories, and then separately needs a red/green semantic scale, and the two systems collide (e.g., a category that happens to be red gets misread as "bad performance" when it's actually just "the Growth pillar").

**Resolution for this project: two separate palettes that never share a hue.**

### 2.2 Palette A — pillar/category identity (inherited from the deck, must stay identical)

These colors mean "which pillar or category this belongs to" and carry **no** performance judgment. Never use them to signal good/bad.

| Pillar | Color | Hex |
|---|---|---|
| Growth | Navy | `#1E2761` |
| Growth (light/fill) | Ice Blue | `#CADCFC` |
| Efficiency | Teal | `#1C7293` |
| Durability | Terracotta | `#B85042` |
| Background/neutral | Off-white | `#F7F8FA` |

These are the deck's colors. The dashboard must use the same ones — a reader who's seen the deck and then opens the dashboard should recognize the company's visual identity instantly. If a page needs a 4th or 5th categorical color (e.g., segment: SMB/Commercial/Enterprise), extend the palette by desaturating or shifting lightness within the same family rather than introducing a new hue family — see 2.4.

### 2.3 Palette B — performance/status semantics (never reuse for category)

These colors mean "how is this doing," and must be used identically everywhere a judgment is being conveyed — scorecards, variance badges, trend arrows, health scores, forecast confidence.

| Meaning | Color | Hex | Use for |
|---|---|---|---|
| Favorable / on-or-above plan | Green | `#2E7D4F` | Positive variance, healthy status, "up" arrows where up is good |
| Unfavorable / below plan | Red | `#C0392B` | Negative variance, at-risk status, "down" arrows where down is bad |
| Caution / needs attention, not yet critical | Amber | `#D89614` | Within-tolerance-but-trending-wrong, watchlist items, early-warning flags |
| Neutral / no judgment applicable | Gray | `#6B7280` | No prior-period comparison available, not-yet-validated data, informational-only figures |

**Never use red/green for anything that isn't a judgment.** A chart that's just showing three segments over time should not accidentally use `#2E7D4F` and `#C0392B` for two of them — a reader's eye will read "SMB = bad, Commercial = good" even though the chart never meant that. This is the single most common accidental-meaning bug in dashboards — audit every chart's color assignment against this rule specifically.

**Direction is metric-specific, not universally "up = green."** Down is favorable for churn, contraction, CAC, and payback period. Up is favorable for NRR, GRR, win rate, pipeline. The color logic must be driven by "favorable vs. unfavorable relative to plan," computed per-metric, never by a blanket "positive number = green, negative = red" rule applied to the raw delta. Get this wrong and a shrinking churn rate — genuinely good news — renders red because the number itself is negative.

### 2.4 Extending the palette for segment (SMB / Commercial / Enterprise)

Segment needs its own 3-way categorical distinction, separate from both pillar and status. Use a single consistent hue family, varied by lightness/saturation, so segment is visually legible as "one family, three members" rather than three unrelated colors:

| Segment | Color | Hex |
|---|---|---|
| SMB | Light slate | `#94A3B8` |
| Commercial | Mid slate | `#475569` |
| Enterprise | Dark slate | `#1E293B` |

Chosen deliberately outside both Palette A (pillar) and Palette B (status) hue ranges so a segment-colored chart is never misread as a pillar chart or a status chart.

### 2.5 Accessibility floor

- Every red/green distinction must also be distinguishable by shape or label for colorblind readers (~8% of men) — pair color with an up/down arrow glyph or explicit "+"/"−" sign, never color alone.
- Text on any colored background must hit WCAG AA contrast (4.5:1 for body text, 3:1 for large text/headlines). Test navy-on-ice-blue and terracotta-on-white specifically — these are the two combinations most likely to fail if used carelessly (e.g., navy text on a light navy fill).
- Never encode a judgment in color saturation/intensity alone ("more red = worse") without a number next to it. Gradient color scales are fine for heatmaps but always need a legend with actual values.

---

## 3. Chart-type selection

This is a decision framework, not a preference list. For any chart, answer these three questions in order:

1. **What is the data shape?** (single value, trend over time, comparison across categories, part-of-whole, distribution, relationship between two variables)
2. **What is the question the reader is asking?** ("what is it," "is it changing," "how does X compare to Y," "what's driving this")
3. **Who is reading it, and how much time do they have?** (see Section 4)

### 3.1 Selection matrix

| Data shape / question | Use | Don't use | Why |
|---|---|---|---|
| A single headline number with a comparison point (vs. plan, vs. prior period) | Scorecard/metric card: big number + delta badge + sparkline | Gauge/speedometer chart | A gauge wastes area conveying one number; a card conveys the number, the direction, and the trend in the same footprint |
| A metric over time, one series | Line chart | Bar chart per period | Line makes the *trend* legible at a glance; bars make the reader count and compare, which is slower for "is it going up" |
| A metric over time, comparing actual vs. plan/forecast | Line chart, two series (solid = actual, dashed = plan/forecast), shaded band for forecast uncertainty if available | Two separate charts side by side | Overlaying is the only way to make the *gap* itself visible, and the gap is usually the point |
| Comparing a small number of categories (≤7) at one point in time | Horizontal bar chart, sorted by value | Pie/donut chart | Bars let the reader rank and compare magnitude precisely; pie charts are only good for "roughly what share," and humans are bad at comparing angles |
| Part-of-whole composition, ≤5 categories, and the *composition itself* (not the ranking) is the point | Stacked bar (single bar, for a snapshot) or 100%-stacked bar (for composition over time) | Pie chart with >4 slices | A pie chart with more than ~4 slices becomes unreadable; a stacked bar handles more categories and stays comparable across periods |
| Funnel / sequential conversion (pipeline stages, onboarding steps) | Funnel chart, ordered top to bottom, absolute counts labeled at each stage with stage-to-stage conversion % | Bar chart of stage counts (loses the "funnel" narrowing intuition) | Funnel shape directly encodes "where are we losing volume," which is the actual question being asked |
| Distribution of a metric across accounts/deals (e.g., deal size, health scores) | Histogram or box plot | Line chart of individual values | Distribution questions ("is this normal, are there outliers") need a shape, not a sequence |
| Relationship between two continuous variables (e.g., activation speed vs. NRR) | Scatter plot, with a trend line if correlation is the point | Two separate line charts | Scatter is the only chart type that directly shows correlation/relationship; two line charts force the reader to mentally overlay them |
| A metric broken down by both a category and time (e.g., pipeline by channel by month) | Small multiples (one small chart per category, same axes) or stacked area | A single chart with 5+ overlapping lines | 5+ overlapping lines is the most common "unreadable chart" failure — small multiples trade one complex chart for several simple ones, which is almost always a net win for legibility |
| A single ratio or percentage against a target (win rate vs. benchmark) | Bullet chart (bar + target tick mark) or scorecard with benchmark shown as a reference line/label | Gauge chart | Bullet charts pack "actual, target, and qualitative range (poor/ok/good)" into a compact horizontal shape; gauges are visually heavy for the same information |
| Hierarchical drill-down (Layer 1 → 2 → 3) | Expandable/nested cards or a breadcrumb-navigated drill-down view, not a single chart | Treemap (tempting, usually wrong here) | This project's hierarchy carries *causal* meaning (parent = math of children) — a treemap only conveys relative size, which understates what the hierarchy actually represents. Use the card-based drill-down pattern described in Section 6. |

### 3.2 Hard rules regardless of chart type

- **Never truncate a y-axis to exaggerate a trend.** If a metric moved from 94% to 96%, the chart shows that as a small move, because it is one. Truncating the axis to make it look dramatic is a credibility risk the first time a sharp-eyed exec notices — and CROs notice.
- **Always label the y-axis with units** ($ , %, count) — never leave a reader guessing whether a chart is dollars or percent.
- **Never use 3D charts.** They distort magnitude perception and add zero information.
- **Every chart with more than one series needs a legend or direct labeling** — never make the reader guess which line is which from color memory alone, especially since color already carries pillar/status meaning elsewhere on the page.
- **Sort categorical comparisons by value, not alphabetically**, unless the category has a natural order (funnel stages, segments SMB→Commercial→Enterprise). Alphabetical sorting makes ranking comparisons harder for no benefit.

---

## 4. Audience-adaptive design

The same underlying metric tree serves at least three different readers on this project's dashboard, and they need materially different pages, not just different data filters.

### 4.1 The three audiences on this dashboard

**CRO / exec (Digest page)**
- Has 30–60 seconds. Wants the verdict first, detail only on demand.
- Cares about: is the business on plan, where's the biggest gap, what's the forecast, what needs a decision from them.
- Does NOT want: raw tables, every Layer-3 leaf metric, methodology explanations up front.

**Functional owner / analyst (Segment Efficiency, channel-owner views)**
- Has minutes, not seconds, and is here to diagnose, not just to check status.
- Cares about: the specific Layer-2/3 drivers under their function, trend detail, ability to filter/slice by segment or channel, why a number moved.
- Wants more density than the exec page — this is the one place dense tables and multi-series charts are appropriate.

**Ad hoc / exploratory (Ask the Metric Tree)**
- Open-ended question, unknown shape of answer.
- Needs conversational/query-driven access to the same underlying metric registry, not a fixed layout — this page is correctly built differently from the other two (chat-style interface over the MCP semantic layer) and doesn't need the visual density rules below, but its *answers*, when they render a chart or number, still follow every rule in Sections 2–3.
- **An answer about any non-leaf metric must include its immediate children, not just its own value.** A question about win rate should render win rate's own number alongside its Layer-3 drivers (stage-to-stage conversion, POC pass rate, rep capacity/ramp mix, loss-reason mix) in the same response — "what is win rate" and "why is win rate declining" are the same question from this dashboard's reader, and a bare number forces a second question the system already had the answer to. Default to one level of children below whatever the query resolves to; let the reader drill further from there rather than re-asking for the breakdown separately. See 4.7 for the standing tree panel this pairs with.

### 4.2 What actually changes between exec and analyst pages

| Dimension | Exec page (Digest) | Analyst page (Segment Efficiency, etc.) |
|---|---|---|
| Default depth shown | Layer 1 only, Layer 2 on click-through | Layer 2/3 visible by default |
| Number of charts above the fold | 3–5 scorecards max outside the verdict row (the verdict row itself is the 11 Layer-1 scorecards, Section 4.3), one hero chart | As many as needed to diagnose — density is a feature here, not a flaw |
| Table usage | Avoid; use scorecards/cards instead | Tables are appropriate and expected |
| Language | Plain business language ("New logo revenue is $2.1M, 4% below plan") | Can use metric-tree terminology and formula references directly |
| Filters/controls | Minimal — as-of-date and maybe segment | Full filter set: segment, channel, rep, date range, grain |
| Narrative text | A generated exec-summary sentence/paragraph is appropriate and expected | Narrative is optional; the analyst is doing their own interpretation |
| Color usage | Status semantics (Palette B) dominate — the page is answering "good or bad" | Category semantics (Palette A/segment) can dominate — the page is answering "what's different across X" |
| Drill-down depth per click | One level at a time (L1 → L2), never jump straight to L3 | Can expose L2 and L3 simultaneously since the reader already knows what they're looking for |

### 4.3 The inverted-pyramid rule for exec pages

Write and lay out exec-facing pages the way a wire-service news story is written: the verdict first, then the one supporting fact, then further detail only for a reader who keeps going. Concretely, top-to-bottom on the Digest page:

1. **Verdict row** — the 11 real Layer-1 scorecards, grouped under their three pillars (Growth / Efficiency / Durability), each a single number + variance badge. Note the pillars themselves are not Layer 1 — they sit one level above it (`acme-corp-gtm-metric-tree.md`'s three pillars, each broken into top-level/Layer-1 metrics, per `variance_diagnostic.py`'s own tree-integrity check, which asserts exactly 11 Layer-1 nodes). A pillar heading/group label is not a metric and must never carry its own Layer badge. This alone should let a reader form a correct overall picture in 5 seconds.
2. **What changed** — the one or two Layer-2/3 drivers that most explain this period's movement (this is what the "variance-threshold" selector controls — surface only what crossed the threshold, not everything).
3. **What's coming** — forecast against plan.
4. **What needs a decision** — watchlist / automated playbook triggers.
5. **Everything else** — available via drill-down, never pre-rendered on the main page.

Never invert this. A page that opens with a wall of Layer-3 detail and makes the reader scroll to find the verdict has failed at the one job an exec page has.

### 4.4 Progressive disclosure, mechanically

- Default-collapsed sections for anything below the current audience's default depth (Section 4.2's row 1).
- Use Streamlit's `st.expander` for "why this number" / methodology detail — available on click, invisible by default. This is also where the "why is this blank" honesty pattern belongs (see Section 7).
- Click-through, not hover-only, for drill-down — hover tooltips are fine for a supplementary data point (exact value, date) but should never be the only way to reach Layer-2/3 detail, since hover doesn't work on touch and isn't discoverable.

### 4.5 A resolved fourth pattern: hybrid analyst-with-verdict

Forecast doesn't fit cleanly into any of the three tiers in 4.1 and needed its own call. Treat a page as this pattern when the underlying data is inherently diagnostic (several reconciled views of the same question, meant for someone actively comparing them — RevOps/sales leadership diagnosing lens divergence, not a single exec glance) but a CRO glancing at it for 30 seconds still needs a one-line verdict before the detail. Concretely: keep 4.2's analyst density (all lenses visible by default, no click-gating), but still open each section with a clear headline value + status badge before the diagnostic detail, borrowing the exec page's "verdict first" habit without adopting full inverted-pyramid/Layer-1-only treatment. Don't default a new page into this pattern casually — it exists because Forecast's specific shape (multiple internally-consistent reconciled figures answering the same question) doesn't fit the other three; a page that's just "an analyst page with a big number at the top" is probably still a plain analyst page.

### 4.6 Exec pages and tables — a scoped exception

4.2 says exec pages avoid tables. Digest's watchlist and automated-playbook-trigger sections are a deliberate, narrow exception: a short, ranked, named-account action list is exactly the case that rule should bend for — a card layout would either hide the account IDs a CRO needs to act on, or cost far more vertical space for the same handful of rows. The exception is narrow: full-width, stacked sections (never side-by-side columns, which truncate on a normal viewport), capped to what the underlying selection rule actually returns (never padded), and reserved for the "what needs a decision" tier of the inverted pyramid (4.3, item 4) — not a general license to drop a table onto an exec page wherever it's convenient.

### 4.7 The metric tree must be visible, not just answerable

A chat box with no visible sense of what's in scope fails the same way an empty search bar does — the reader doesn't know what's askable, so they either ask too narrow a question or give up. **The Ask the Metric Tree page must show the tree itself, always, alongside the chat interface** — not only as an answer to a question, but as a standing navigational element:

- A persistent tree/outline panel (sidebar, or a collapsible panel above the chat) listing all 11 Layer-1 nodes under their three pillars, expandable to Layer 2/3 — the same hierarchy `acme-corp-gtm-metric-tree.md` defines, not a redesigned or simplified version of it.
- Clicking any node in that panel populates the chat with a ready question about it (e.g., clicking "Win rate" asks "What is win rate and what's driving it?") rather than requiring the reader to type a well-formed question from nothing — this is what turns the tree panel from a reference into the actual on-ramp for the page.
- This panel is not optional polish — it's the fix for the specific failure mode named above: a blank canvas with unlimited possible questions and no visible boundary on what's actually in the registry.

---

### 4.8 Generated narrative block

The Digest's executive summary is model-written prose, so it carries its own presentation and gating rules:

- **Gate before render.** Prose renders only when the slot's status is `generated`, its validation passed, every statement is well-formed, and its input hash matches the readout it sits in. The gate is a pure function (`dashboard/lib/exec_summary_view.py`) so it is unit-testable without Streamlit. Every other state renders no prose.
- **Generated state.** One white grid card (`.grid-card`): the first statement as the lead (1.1rem, weight 500), the rest as 0.95rem body, then one gray provenance line inside the card (model, generated date, "figures validated against the readout"). The card's fill bleeds 20px, so a spacer follows it.
- **Completeness suffix.** Until the narrative step is `built_and_validated` in `dashboard/project_status.json`, the provenance line states its status ("narrative step status: in progress (not yet independently validated)"). The suffix disappears when the status flips.
- **Citations.** They live in a collapsed "Sources and checks" expander as neutral gray chips, never colored: a citation is provenance, not a status judgment (Palette B). The expander also carries the caveat that validated figures are not the same as a correct explanation.
- **Not-generated state.** The reason is plain language in an info box above the fold, never a raw reason code or dict. "Why this is blank" shows reason, what is needed and the component status only: no status-file text, file paths, CLI commands or reason codes (the generate command lives in `dashboard/README.md`). Failed-check names may be listed; validator detail text is never rendered.

### 4.9 Scorecards, the tree panel and chat answers

- **Equal-height card rows** are one CSS grid in a single markdown call (`theme.scorecard_row`), not `st.columns` plus per-card containers: forcing equal height on Streamlit's containers produced a border-without-fill artifact.
- **Scorecard anatomy:** the label block always reserves two lines; optional gray footer lines (unit, baseline) sit inside the card; a long value keeps its number large and sets the unit small. A card with no comparison says "No comparison loaded for this metric" rather than showing a bare number.
- **Tree panel (Ask the Metric Tree):** a sidebar with tertiary, left-aligned buttons and a pillar heading with its dot and tagline. Each node carries a gray "Layer N · status" line using a six-state vocabulary: ● Queryable, ◐ Queryable (partial), ○ Not computable, ◌ No variation in data, ◇ Non-additive overlay, ↗ Cross-reference. The panel uses no judgment color.
- **Chat avatars** are neutral gray: Streamlit's default red and orange fills read as Palette B status colors.
- **Answer layout:** resolved-metric identity card, formula (inline only up to 220 characters, otherwise under "Query details"), a grain/filter/split line, headline cards, chart, data table, then the immediate-children table. Guardrail rejections, overlays and not-computable results use a neutral `st.info`, never an error box. The newest exchange stays on screen and earlier ones collapse.
- **Notes helper:** `theme.notes_and_assumptions` accepts only the labels Assumption, Scope and Data gap; `theme.escape_md` makes text render literally in markdown (dollar signs, underscores, asterisks).
- **Charts and grain:** NRR and GRR charts are windowed to 24 months wherever they appear. Quarter-grain content (the forecast) is labelled with its grain and segment scope above the block, separate from the monthly scorecard.

### 4.10 Caveated, degenerate and partial values

- **Caveated comparisons.** A row whose plan comparison is flagged `caveated` shows the signed gap and plan value in neutral gray with no arrow, and a gray "Caveated comparison" tag inside the card. A period-over-period move on the same basis keeps its status color and carries the tag. Do not tag a row the readout does not flag.
- **Constant series.** A value identical in every period is a gap, not a result: show "Not computable" with the reason and "No variation in data" tag, no number, no flat chart (extends the all-null rule in Section 7). The tree panel uses the "◌ No variation in data" state.
- **Basis line on every card.** Digest: "Month of YYYY-MM" or "Trailing 12 months to YYYY-MM". Segment Efficiency: "Monthly". Ask: "Basis: last complete month".
- **Truncated final month.** The data's last month is a partial artifact. It is excluded from Ask headlines and the Segment Efficiency default, drawn as an open marker labelled "Partial month", and flagged in data tables. Read it from the readout's `data_window.last_month_in_marts`, never hard-coded.
- **Zero and rate deltas.** A delta that rounds to zero at its displayed precision has no color or arrow. Rate changes are labelled "pp".
- **Reader-facing text.** Table names, file paths, error codes and CLI commands never reach the page; guardrail codes map to plain labels. Notes show one short line per item with a "Details" toggle (inline `<details>`, since Streamlit forbids nested expanders) for the rest.
- **Charts.** Bars sort largest on top on every page. A reference line is labelled when a natural baseline exists (for example 100% on retention). Axis ranges fit the data.
- **AUC wording.** "Above the target range" is neutral gray; "below" is unfavorable; "within" is favorable.
- **Censored tails.** A series whose final months are incomplete by construction (for example partial workflow chains, which exist only in the months before a churn) never headlines those months: the headline is the last complete month, the excluded months are drawn as open markers labelled "Excluded: incomplete window" and flagged in the data table, and the card carries a visible tag. The affected nodes and the number of months live in one tested table (`dashboard/lib/censoring.py`) tied to the engine's constant. This extends the partial-month rule.
- **Not available vs not computable.** An artifact that is built but cannot be served by a surface reads "Not available through this query interface; shown in the weekly readout" (child rows: "Not queryable here"); "Not computable" is reserved for nodes with no data.
- **Ranking captions and dashes.** A ranked table states the basis the rank was computed on (relative deviation from the node's own baseline, or absolute change for additive components); a row with no data shows a dash instead of a rank.
- **Default segment view.** For a metric that is constant by construction in one segment (SMB win rate), a question that names no segment opens on the meaningful segments with a visible line saying so.
- **Unsupported splits.** A requested split that is not available gets a plain notice and, where a related node exists, a suggestion button; it is never silently dropped or rerouted.
- **Flows and rounding.** A trailing-12-month flow over an average base is labelled "flow, not share of current MRR". 100%-stacked bar labels use largest-remainder rounding so they sum to 100.0.
- **Proposed-band chips.** A status whose thresholds are proposed and not confirmed (for example coverage bands) is a neutral gray chip carrying the band text ("Proposed band: Shortfall, below 0.75x of required"), never a Palette B status color. The band text comes from the artifact's own `status_rule`, not from the page.
- **Non-forecast labels.** A block that reads like a forecast but is not one carries a gray label chip above it ("Coverage reading, not a forecast").
- **Quarter-level blanks.** A next-quarter view that cannot exist because the data ends first is an info box ("blank: the data ends before the quarter starts; not zero coverage") plus a "Why this is blank" expander with Reason, Needed and Component status; never 0.00x. A card whose ratio is null because the target is already met reads "Quota met".
- **Non-breaking dates.** ISO dates in card footers use non-breaking hyphens so they never wrap mid-date.
- **Quoting backtests.** A page that quotes a backtest takes the figures only from a committed report and omits the line when no report carries one.
- **Repeat markers.** A streak or repeat marker is a neutral gray chip labelled "Repeat: N consecutive months", never "Persistent trend", with no status color, no causal wording, and no header count of flagged nodes. Its scope line ("does not establish a trend or a cause", with the threshold and its status) goes in Notes & assumptions. Inside the drill-down, show the streak line and the streak table; non-flagged records show "Streak N of K months" and not-applicable records show the engine's reason.
- **Context blocks.** Mix and migration views sit below the decision tier (watchlist, triggers), use neutral gray cards with a "Basis: ..." footer, and carry no Layer label when they are not tree nodes. Segment-share composition is a 100%-stacked bar across two periods in the segment palette with direct labels; changes are labelled "pp".
- **Scalar views.** A node that is a scalar slice of a wider quantity carries the slice in its display label (for example "Loss-reason mix (competitive share)"); `labels.NODE_QUALIFIERS` holds the qualifiers. The "See Growth:" cross-reference prefix is never shown to the reader.

## 5. Information hierarchy and layout

### 5.1 Z-pattern / F-pattern reading order

Readers scan top-left → top-right → down → bottom-left → bottom-right (a rough Z, or F for text-heavy pages). Layout follows this:

- Highest-priority verdict content: top-left.
- Time/context controls (as-of date, grain, audience selector): top-right — visible but not competing for primary attention.
- Supporting detail and secondary charts: middle band.
- Actions/next-steps (watchlist, triggers): bottom, but never buried below a fold that requires scrolling past low-value content to reach.

### 5.2 Grouping and visual separation

- Related metrics are grouped inside a visually bounded container (card, bordered section) — never let related numbers float freely with the same whitespace separating them as unrelated numbers. Grouping *is* a claim about relatedness; get it wrong and the reader infers a relationship that isn't there, or misses one that is.
- Use whitespace, not rules/borders, as the primary separator between unrelated sections. Borders are for grouping *within* a section (e.g., a card boundary); heavy use of borders/dividers everywhere flattens the hierarchy instead of clarifying it.
- Never use a decorative accent bar/color stripe as a section divider — this is the same rule the deck QA established (accent-stripe rule) and it applies equally here: a colored bar reads as a status signal given Palette B's meaning, so a purely decorative bar creates a false judgment signal. Use a small colored dot/icon or a plain heading instead.
- Card fill: every card in a row should feel visually balanced (similar height/density), not one dense card next to three mostly-empty ones — this is the "uneven card-fill" bug from the deck QA, and it recurs in dashboards even more easily since Streamlit's default layout doesn't equalize card heights automatically. Pad short cards with a relevant secondary stat (sparkline, benchmark comparison) rather than leaving dead space.

### 5.3 Typography hierarchy

- One typeface family for headers, one for body/data — don't introduce a third.
- Font sizing should have exactly 3–4 steps (page title, section header, card label, body/data), each clearly distinct — not a continuum of slightly-different sizes that don't read as a clear hierarchy.
- The headline number on a scorecard is the largest text on the page except the page title. If a chart's axis labels are competing in size with the scorecard headline numbers, the hierarchy is broken.

### 5.4 Font choice (resolved)

The deck uses Cambria (headers) / Calibri (body) — both are not reliably web-embeddable/licensed for a web app the way they are for a locally-rendered PowerPoint file. For the Streamlit dashboard:

- **Headers:** Source Serif 4 (Google Fonts) — closest open, web-licensed match to Cambria's serif character while remaining fully legal to embed.
- **Body/data:** Inter (Google Fonts) — a well-hinted, highly legible sans-serif at small sizes, which matters more here than in the deck since dashboard text runs smaller and denser than slide text.

This is a deliberate divergence from the deck's exact typeface, not an oversight — note it as such if anyone compares the two side by side. The color palette and layout language stay identical; only the specific font files change, for licensing reasons.

---

## 6. Drill-down and hierarchy display

The metric tree's defining property — every parent is the literal mathematical result of its children — must be visually legible, not just true in the data. A drill-down UI that doesn't make the math traceable is throwing away the project's central design principle.

- **Always label the layer correctly and explicitly** — "Layer 1" / "Layer 2" / "Layer 3" (or equivalent visual weight/indent depth) must match the metric's actual depth in `acme-corp-gtm-metric-tree.md`, not the depth it happens to appear at in a particular view. (This is the exact bug class caught earlier in this project — Win Rate mislabeled as Layer 1 when it's Layer 2 under New Logo Revenue. Any drill-down view must be checked against the tree file directly, never assumed from context.)
- When a user clicks into a parent metric, show its formula (e.g., "Pipeline generated × Win rate × Avg initial commitment") with the actual current value of each factor inline — the drill-down should let the reader verify the math themselves, not just assert a relationship.
- Breadcrumb the path (Growth > New logo > Win rate) so the reader always knows their current depth and can navigate back up without hitting "browser back."
- A Layer-1 card should visually preview that it's expandable (chevron, "view drivers" affordance) — don't rely on the reader guessing that a card is clickable.

---

## 7. Honesty patterns (preserve and extend — do not regress)

The current Digest page already does two things worth treating as a standing requirement for every page, not just Digest:

1. **"Executive summary narrative: not yet generated" with a "why this is blank" expander**, rather than either fabricating a narrative or silently omitting the section. This is the correct pattern for *any* component whose underlying model or generation step hasn't actually run — never render a plausible-looking placeholder, and never just delete the section as if it were never planned. Show the honest empty state with a one-line reason.
2. **Explicit as-of-date, grain, and variance-threshold display** in a visible info row, not hidden in a settings panel — the reader should never have to guess what window or resolution they're looking at.

**Extend this pattern to every model-backed component on every page:** if a component's underlying artifact is `planned` or `in-progress` per `dashboard/project_status.json`'s 4-state model (not yet `built-and-validated`; fall back to `docs/acme-corp-analytics-methods.md`'s own Target/Achieved entry or the build spec's built/simulated marker for anything not yet tracked in that file), the page must say so visibly, not render it as if it were live. This is the dashboard-level equivalent of the project's no-fabrication rule, and it's the single most important thing `dashboard-visual-qa` checks for (see that agent's file) — a good-looking chart backed by a model that doesn't exist yet is worse than an honest blank, because it's actively misleading anyone who screenshots it.

Never show a number without a comparison point (vs. plan, vs. prior period, vs. benchmark) unless there genuinely isn't one yet — and if there isn't one yet, say that explicitly rather than showing a bare number that invites the reader to assume it's fine.

**A "no comparison" gray card and a "within-threshold, real comparison" gray card are not the same state, and must not render identically.** The variance-diagnostic engine emits four statuses (Ahead/Behind/On track/Not computable), not two — "On track" has a real value and a real comparison point that simply falls inside the variance threshold; "Not computable" has neither. Collapsing both to the same neutral color *and* the same arrow glyph (found live as a real readability bug — a reader can't tell them apart at the 5-second pace Section 1 designs for) fails this section's own standard just as badly as a fabricated favorable/unfavorable color would. Resolution: keep both neutral-gray (neither gets a directional favorable/unfavorable judgment), but give them distinct glyphs/text — e.g. a plain dot + "On track" + the real comparison value for the former, and an explicit "n/a" + "Not computable" with no directional glyph at all for the latter, since there is genuinely nothing to compare.

**A component whose *artifact* is `built_and_validated` but whose *value* is a genuine structural data gap (e.g. MQL → SAL acceptance rate — the lead source carries no stage or disposition field) is not the same case as a `planned`/`in-progress` component, and must not go through the same pending-state treatment.** The artifact isn't missing — it correctly computed NULL, which is itself the honest answer. Render this as an explicit stated gap on the card/value itself ("Not computable" + the real reason), not the generic `render_pending()` treatment, which would misleadingly imply the artifact itself doesn't exist yet. Check `project_status.json`'s own `note` field on the component before deciding which of the two this is — don't guess from the fact that a value happens to be null.

**When a chart's underlying query can return every value null** (the same structural-gap case as above, reached through a query interface rather than a fixed page layout — e.g. Ask the Metric Tree resolving to MQL → SAL acceptance rate), check for an all-null result *before* attempting to plot anything, and show the honest-gap message first. An empty chart axis and a table of blank rows, with the real explanation appearing only afterward as a warning, is the wrong order — found live as a real bug — even though the explanation was accurate and present. The reader's first signal should be the gap, not a confusing blank plot they have to scroll past to understand.

---

## 8. Grain and resolution — hard constraint for this build

**Maximum resolution for this project is weekly. Daily is out of scope** — not a future nice-to-have, an explicit scope decision for this demo.

**Every Layer-1 scorecard metric is monthly, with no exceptions**, because every Layer-1 node ultimately resolves to a dollar figure (`fact_revenue_monthly`) or a metric whose only available resolution is monthly at the generator level (see table below). This means:

- The Digest page (all Layer-1 cards) is correctly built as an all-monthly page. Do not add a grain toggle to this page — there is nothing at a finer grain to toggle to, and offering a control that doesn't change anything is worse than not offering it.
- **Never mix grains on the same page** unless the metric is genuinely annual/monthly by nature and labeled as such — mixing a monthly card next to a weekly chart on the same page, without a very clear visual/textual separation of what window each one covers, misleads the reader into comparing incomparable things.
- A grain toggle only belongs on pages/sections showing Layer-2/3 metrics that have real event-level timestamps (see table). Where offered, default to monthly and let the user opt into weekly — don't default to the finest available grain, since finer grain is noisier and the reader's first view should be the stable one.

### 8.1 Native grain by metric — the actual constraint table

**Weekly-capable** (real event timestamps exist in staging — a grain toggle is legitimate here):
- Pipeline generated, by channel
- Marketing–sales handoff quality (MQL SLA, MQL→SAL rate)
- Win rate's Layer-3 drivers: stage-to-stage timing, POC pass rate, loss-reason mix
- SDR/outbound activity volume, AM touchpoint cadence
- Support ticket volume/severity
- Deal-level diagnostics generally (anything sourced from `fact_opportunities`/`fact_opportunity_stage_history`)

**Monthly-only** (a real bottleneck in the underlying generated data, not a dbt aggregation choice — do not build a weekly toggle for these, it would imply resolution that doesn't exist):
- Every dollar/ARR figure: New logo, Expansion, Contraction+Churn, NRR, GRR (all via `fact_revenue_monthly`)
- Magic number, Consumption payback, AM efficiency
- Account health score (usage-trend input is monthly, which bottlenecks the whole composite even though other inputs like support tickets are event-level)
- Workflow chain under-utilization
- Onboarding/CS efficiency
- Activation/TTFA — this one is easy to get wrong: it looks event-like (a single "first Action" moment) but usage data has no daily timestamp anywhere in this project, so "first Action" can only resolve to "first month with Actions > 0." Treat it as monthly, not weekly.

If a page ever needs to show a monthly metric next to its weekly-capable drivers (e.g., New logo revenue — monthly — next to Pipeline generated by channel — weekly-capable), keep them in visually separate sections with distinct axis/period labeling, never on the same chart or same x-axis.

---

## 9. Streamlit implementation patterns

- **Scorecards:** `st.metric()` for the headline + delta, but wrap it in a bordered `st.container(border=True)` sized/styled to match the card treatment established in the deck (not the bare default `st.metric` styling, which has no pillar-color coding). Apply Palette A as the card's accent (small dot or thin left-edge icon, never a full-width color bar per Section 5.2) and Palette B to the delta text/arrow color.
- **Charts:** use a single charting library consistently across all pages (Plotly is recommended for this project — it supports the annotation, dual-series overlay, and hover-label needs in Sections 3.1–3.2 better than `st.line_chart`'s native wrapper, and integrates cleanly with Streamlit via `st.plotly_chart`). Don't mix native `st.*_chart` calls and Plotly on different pages — the visual style (fonts, gridlines, tooltips) will diverge subtly and break consistency.
- **Layout:** `st.columns()` for the verdict row (Section 4.3, item 1) with explicit width ratios so cards render evenly, not Streamlit's default equal-split unless that's actually the intended ratio.
- **Expanders** (`st.expander`) for: methodology/"why this is blank" (Section 7), Layer-2/3 drill-down detail on analyst pages, any content below the audience's default depth (Section 4.4).
- **Caching:** any page pulling from the MCP semantic layer or a dbt mart should cache query results (`st.cache_data`) keyed on the as-of-date/grain/filter selection — don't re-query on every widget interaction if the underlying data hasn't changed.
- **Theming:** set the palette and fonts once in a shared `theme.py`/`config.toml` (Streamlit's native theming config) rather than repeating hex codes inline on every page — this is the mechanical enforcement of "consistency across pages" and should be the first thing `dashboard-page-builder` checks exists before building a new page. This project's `dashboard/theme.py` and `dashboard/.streamlit/config.toml` are that implementation; import from `theme.py` rather than hardcoding a hex/font on any new page.
- **Cards:** `theme.scorecard_row` (one CSS grid in a single markdown call) is the only card implementation for scorecards on every page, and `.grid-card` is used for info rows and text cards. `st.container(border=True)` with a fill override is not used: Streamlit 1.64 exposes no stable selector for a bordered container, so the fill cannot be applied reliably.
- **Test/QA data overrides:** any environment override of a page's data source (e.g. `ACME_DASHBOARD_OUTPUTS_DIR`) must show a visible warning on every page it affects, so a fixture can never be mistaken for real output.

---

## 10. Pre-ship checklist for any dashboard page

Before a page is reported done, verify:

- [ ] Every color used means the same thing it means on every other page (Palette A for category, Palette B for status, segment palette for segment — never crossed)
- [ ] Status color direction (favorable/unfavorable) is computed per-metric, not by raw sign
- [ ] Chart type matches Section 3.1's matrix for its actual data shape and question
- [ ] Audience match: exec pages show Layer 1 by default with progressive disclosure; analyst pages show appropriate density (Section 4.2)
- [ ] Inverted-pyramid order on exec pages: verdict → what changed → what's coming → what needs a decision (Section 4.3)
- [ ] No grain mixing without explicit visual separation; no grain toggle offered where no finer grain actually exists (Section 8)
- [ ] Every Layer label (1/2/3) matches the metric tree's actual depth, verified against `acme-corp-gtm-metric-tree.md` directly
- [ ] Every model-backed component whose artifact isn't `built-and-validated` per `dashboard/project_status.json` (or the methods doc/build spec for anything not yet tracked there) shows an honest blank/pending state, not a fabricated or placeholder-looking value (Section 7)
- [ ] As-of-date, grain, and any threshold/filter state are visibly displayed, not hidden
- [ ] Fonts match Section 5.4 (Source Serif 4 / Inter), pulled from shared theme config, not hardcoded per-page
- [ ] The page was actually rendered and visually inspected (screenshot), not just checked for code correctness — see `dashboard-page-builder`'s process requirements
- [ ] No assistant-voice hedging language anywhere on the page (Section 11.1) — check specifically for "quietly assumed," "not guessed at," "to be safe," or any phrase narrating the system's own uncertainty
- [ ] No directional editorializing on a metric's movement — the number, comparison, and Palette B color/arrow carry the judgment, not a sentence (Section 11.2)
- [ ] Every assumption/caveat/methodology note lives in a single "Notes & assumptions" section per page, not as inline hedges (Section 11.3)
- [ ] Ask the Metric Tree: a persistent, clickable tree panel is visible alongside the chat, and any answer about a non-leaf metric includes its immediate children (Sections 4.1, 4.7)

---

## 11. Dashboard copy voice — production language, not assistant language

Every piece of text on a dashboard page — labels, captions, tooltips, generated narrative, empty-state messages, methodology notes — must read like it was written by a BI tool's product team, not by an assistant explaining its own reasoning to the person who asked for it. This is a distinct failure mode from Section 7's honesty patterns: Section 7 says *what* has to be disclosed (a gap, an assumption, a pending state); this section says *how* to write it once you've decided to.

### 11.1 The tell: hedging language that narrates the system's own uncertainty

Phrases like "quietly assumed," "not guessed at," "we're assuming," "to be safe," or any construction that explains the system's own epistemic state read as a chatbot talking about itself, not a dashboard stating a fact. A production dashboard states the assumption as a fact with a label, full stop — it doesn't narrate the deliberation behind it.

| Don't write | Write instead |
|---|---|
| "This was quietly assumed to be 80% margin, not guessed at from thin air" | "Assumption: 80% gross margin" |
| "We're not fabricating a number here — it's genuinely not computable" | "Not computable — no stage or disposition field in the lead source" |
| "To be safe, we're showing this as pending rather than claiming it's done" | "Status: In progress" |
| "This number went from bad to good, which is worth noting positively" | "$2.1M, up from $1.8M (+17% vs. prior period)" |

### 11.2 No directional editorializing

Never narrate a metric's own improvement or decline as commentary ("this is genuinely good news," "unfortunately this is trending the wrong way," "positive-to-negative framing here"). State the number, the comparison, and let Palette B's color/arrow (Section 2.3) carry the judgment. A reader infers "good" or "bad" from the status color and the delta sign — a sentence editorializing on top of that is redundant at best and presumptuous at worst ("good news" for whom, exactly — the reader might be the one accountable for the miss).

### 11.3 Notes and assumptions get one clear, consistent section — never inline hedges

Every page with an assumption, caveat, or methodology note surfaces it in the same place, styled the same way, every time — not scattered as parenthetical hedges inside sentences. Use a labeled "Notes & assumptions" block (an `st.expander`, per Section 9, consistent with the existing "why this is blank" pattern in Section 7) with one line per item, each starting with a plain label:

```
Notes & assumptions
- Assumption: 80% gross margin (reused across Consumption Payback and LTV)
- Scope: CAC excludes sales headcount cost — marketing spend only
- Data gap: MQL → SAL acceptance rate is not computable — no stage or disposition field in the lead source
```

On the Ask the Metric Tree page, where one page renders many answers, the data caveats of every answer go into the page's single expander; guardrail rejections, non-additive overlays and all-null gaps stay as plain statements above the fold with the answer (Section 7's gap-first rule).

Never bury an assumption inside the narrative sentence above a chart ("assuming an 80% margin, which we think is reasonable, the payback period is..."). The chart/number stands on its own; the assumption lives in its own section, so a reader auditing methodology knows exactly where to look, every time, on every page.

### 11.4 Plain professional language, not conversational register

No first person ("we," "I"), no rhetorical questions, no conversational connectors ("so," "basically," "here's the thing"). Write the way an existing enterprise BI tool's UI copy reads — short declarative sentences, a label before a value, a reason after a gap. If a sentence would sound out of place printed on a Salesforce or Tableau dashboard, rewrite it.

This applies to every generated narrative on the dashboard (the exec-summary sentence in Section 4.2, chat answers on the Ask the Metric Tree page per Sections 4.1/4.7, methodology expanders per Section 7) — generated text is not exempt from this voice just because a model wrote it at render time rather than a human writing it at build time.
