"""Territory dimension -- generators/run_batch9.py's supporting module.

Build spec Section 5/8: item #21 ("Territory / account coverage & routing,
including whitespace and TAM-allocation") needs a real territory field
before it can be built for real -- `dim_market_universe.sql` and
`mart_tam_whitespace.sql` both say so explicitly, in comments this batch's
dbt changes remove. Neither doc specifies territory granularity or
structure beyond the word itself; this module is that resolved design
decision, grounded against data already in the simulation rather than
picked arbitrarily.

Design decision -- territory is a deterministic sub-division of `region`,
not an independent dimension
--------------------------------------------------------------------------
`region` (firmographics.REGIONS: North America/EMEA/APAC/LATAM) already
exists on every market_universe company and, by copy, every account.
Territory answers "which coverage unit handles this account," which is a
finer cut of the same geography, not a second, unrelated axis -- so
territory is defined as a function of region, never drawn independently of
it. That keeps the causal-wiring invariant intact: a company's territory is
always explainable by its own region, the same way `accounts.channel`
values are drawn conditioned on segment in accounts.py rather than as a
free-floating independent column.

Granularity -- grounded against rep headcount, not picked arbitrarily
--------------------------------------------------------------------------
Only ISR (Commercial new-business) and AE (Enterprise new-business) are
account-owning, quota-bearing roles a prospecting/coverage territory would
route to (see "Which reps get a territory" below) -- config.N_ISR=20 +
config.N_AE=24 = 44 reps total, the real headcount this dimension has to
carve up into meaningful coverage units.

REGION_PROBS (firmographics.py) puts North America at 55% of the company
population -- proportionally that is ~24 of the 44 account-owning reps
under a single territory, which is larger than any single coverage unit
this org's other territories would need (EMEA's 25% share is ~11 reps,
APAC's 15% is ~7, LATAM's 5% is ~2). A real GTM org splits a region once it
outgrows what one territory can reasonably cover; EMEA/APAC/LATAM each stay
a single territory since splitting an 11-, 7-, or 2-rep pool further would
produce sub-territories too thin to be a meaningful routing unit. North
America is therefore split in two (NA-East / NA-West); EMEA, APAC and LATAM
each map 1:1 onto their own single-territory value. Five territories total.

The NA-East/NA-West split itself uses an uneven 56/44 weighting rather than
a 50/50 coin flip -- own resolved decision, deliberately not perfectly
balanced, consistent with real territories carrying real imbalance rather
than an artificially even split for its own sake.

Which reps get a territory -- account-owning roles only
--------------------------------------------------------------------------
ISR and AE are new-business, quota-bearing roles (reps.py's
_QUOTA_BASE_RANGE) that prospect and close within a geographic patch --
exactly what a coverage/routing territory exists to assign. SE
(sales-engineer, Enterprise-only technical support on AE-owned deals) and
AM-Commercial/AM-Enterprise (retention/expansion) are deliberately excluded:
  - SE reps don't own a book or a deal; they're pulled onto an AE's
    already-territoried opportunity as needed (sales_activities.py's
    SALES_ACTIVITY_SE_SHARE_OF_DEMO), so a territory of their own would be
    an unused column, not a real routing concept.
  - AM reps already own a *portfolio* of specific existing accounts
    (reps.py's book_size, assigned via opportunity ownership in
    opportunities.py), not a geographic prospecting patch -- their coverage
    unit is the book itself, which routing/whitespace analysis (this
    artifact's actual target: uncovered *prospects*) has no use for.
Territory is therefore specifically a new-business coverage/routing
concept, scoped to ISR/AE, not a blanket attribute of every rep.

Rep territory counts -- deliberately imbalanced against company-population
share, not proportionally matched
--------------------------------------------------------------------------
Target headcount per (rep_type, territory) below sums to exactly N_ISR=20
and N_AE=24, and to a combined per-territory total of NA-East=15,
NA-West=12, EMEA=10, APAC=4, LATAM=3 (44 total). Compared against each
territory's approximate company-population share (NA-East ~31%, NA-West
~24%, EMEA ~25%, APAC ~15%, LATAM ~5%, from the region/NA-split weights
above), the rep-share/company-share ratio is:

    territory | company share | rep share | ratio
    ----------|---------------|-----------|------
    NA-East   |     ~31%      |   ~34%    |  1.10
    NA-West   |     ~24%      |   ~27%    |  1.12
    EMEA      |     ~25%      |   ~23%    |  0.92
    APAC      |     ~15%      |    ~9%    |  0.60  <- under-resourced
    LATAM     |      ~5%      |    ~7%    |  1.40  <- over floor-staffed

This is a deliberate, not incidental, imbalance -- own resolved decision.
APAC is genuinely under-resourced relative to its market opportunity (a
real coverage gap the Wave 5 routing artifact should be able to find);
LATAM sits above its proportional share because five territories need a
minimum-viable floor of reps to function at all (a 2.2-rep proportional
share isn't staffable). Splitting every territory's headcount exactly
proportional to its company population would produce a dataset with no
genuine coverage-gap signal for that future artifact to detect -- the same
"independently-random columns are a bug" bar this project holds every
outcome column to, applied here to a structural/geographic assignment
instead of a probabilistic one.
"""
import numpy as np
import pandas as pd

TERRITORIES = ["NA-East", "NA-West", "EMEA", "APAC", "LATAM"]

# Region each territory rolls up to -- the mapping every referential-
# integrity check in this batch's test suite verifies losslessly reverses.
REGION_FOR_TERRITORY = {
    "NA-East": "North America",
    "NA-West": "North America",
    "EMEA": "EMEA",
    "APAC": "APAC",
    "LATAM": "LATAM",
}

# NA-East/NA-West split of North America's company population -- own
# resolved decision, deliberately uneven (not 50/50).
NA_TERRITORY_SPLIT = {"NA-East": 0.56, "NA-West": 0.44}

# Account-owning rep types eligible for a territory. See module docstring.
TERRITORY_ELIGIBLE_REP_TYPES = ("ISR", "AE")

# Target headcount per (rep_type, territory) -- see module docstring for the
# derivation and the deliberate imbalance against company-population share.
# Must sum to config.N_ISR (20) and config.N_AE (24) respectively; asserted
# in run_batch9.py against the actual users.csv population rather than
# silently drifting if headcount constants ever change.
REP_TERRITORY_TARGET_COUNTS = {
    ("ISR", "NA-East"): 7, ("ISR", "NA-West"): 5, ("ISR", "EMEA"): 5,
    ("ISR", "APAC"): 2, ("ISR", "LATAM"): 1,
    ("AE", "NA-East"): 8, ("AE", "NA-West"): 7, ("AE", "EMEA"): 5,
    ("AE", "APAC"): 2, ("AE", "LATAM"): 2,
}


def assign_company_territory(rng: np.random.Generator, region: np.ndarray) -> np.ndarray:
    """Territory for every market_universe row (and, by shared company_id,
    every account and non-customer prospect) -- a deterministic function of
    `region`, with North America's rows further split NA-East/NA-West via a
    seeded 56/44 draw. Never independent of region: every non-NA row maps
    1:1 onto its own region's territory value."""
    territory = np.asarray(region, dtype=object).copy()
    na_mask = territory == "North America"
    n_na = int(na_mask.sum())
    if n_na:
        na_split = rng.choice(
            ["NA-East", "NA-West"], size=n_na,
            p=[NA_TERRITORY_SPLIT["NA-East"], NA_TERRITORY_SPLIT["NA-West"]],
        )
        territory[na_mask] = na_split
    return territory


def assign_rep_territory(rng: np.random.Generator, users_df: pd.DataFrame) -> pd.DataFrame:
    """Territory for every ISR/AE rep in `users_df`, per the fixed,
    deliberately-imbalanced REP_TERRITORY_TARGET_COUNTS above. SE and AM
    reps are absent from the returned frame entirely (see module docstring)
    -- this is not a lookup with nulls for the excluded roles, since a null
    territory would read as "unassigned" rather than "not a territory
    concept for this role."

    Raises if a rep_type's actual headcount doesn't match the sum of its
    target counts, rather than silently mis-sizing territories if headcount
    constants (config.N_ISR/N_AE) ever change without this module being
    updated alongside them.
    """
    rows = []
    for rep_type in TERRITORY_ELIGIBLE_REP_TYPES:
        rep_ids = users_df.loc[users_df["rep_type"] == rep_type, "rep_id"].to_numpy()
        targets = {t: c for (rt, t), c in REP_TERRITORY_TARGET_COUNTS.items() if rt == rep_type}
        expected_total = sum(targets.values())
        if len(rep_ids) != expected_total:
            raise ValueError(
                f"rep_type '{rep_type}' has {len(rep_ids)} reps in users_df but "
                f"REP_TERRITORY_TARGET_COUNTS sums to {expected_total} -- update the "
                f"targets in generators/territories.py to match config.N_ISR/N_AE"
            )
        shuffled = rng.permutation(rep_ids)
        cursor = 0
        for territory in TERRITORIES:
            n = targets.get(territory, 0)
            for rep_id in shuffled[cursor:cursor + n]:
                rows.append({"rep_id": rep_id, "territory": territory})
            cursor += n

    return pd.DataFrame(rows, columns=["rep_id", "territory"])
