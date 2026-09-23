"""Account health score / churn-risk model -- grain: one row per
account_id, scored as of a point-in-time as_of_date; source mart:
mart_account_health (dbt), the only table this module reads business
input from.

Two things live here, both derived from the same point-in-time feature
engineering:
  1. A churn-risk classifier (logistic regression, scikit-learn), trained
     and held-out-validated via train_churn_model(). Logistic regression,
     not a higher-capacity classifier (random forest, gradient boosting,
     a neural network), for three reasons tied to this artifact's actual
     requirements: every coefficient is directly attributable to one
     input feature, which is what makes compute_feature_group_importance()
     and _coefficient_table() below possible without a secondary
     explainability technique (SHAP, permutation importance) standing
     between the model and its own explanation; at this dataset's scale
     (~7,700 accounts, 15 model inputs after encoding) a linear model is a
     well-justified baseline, where a higher-capacity model risks fitting
     noise rather than signal without a proportionally larger dataset to
     justify the added complexity; and the score's actual downstream use
     is a ranking (quantile-based risk tiers -- see score_accounts()),
     where a linear model's ranking behavior is more predictable and
     easier to sanity-check than an ensemble's. See docs/acme-corp-
     analytics-methods.md's "Model choice and why" entry for the full
     statement.
  2. score_accounts(), which scores every account's CURRENT state (as of
     as_of_date) with that model -- a 0-100 health_score plus a risk_tier
     -- for downstream consumption (watchlist selection lives in the
     variance-diagnostic engine, not here).

QA-plan reweighting rule (docs/acme-corp-phase1-data-qa-plan.md, health-
score section; also docs/acme-corp-analytics-methods.md): engagement/login
frequency must be weighted higher in an account's first ~90 days, lower
after, or a fully-automated healthy account (high Actions, low logins by
design -- see generators/product_logins.py) gets flagged at-risk for
behaving exactly as the product intends. Implemented directly as a
feature transform (login_frequency_weighted), not left for the model to
discover on its own -- see _EARLY_TENURE_LOGIN_WEIGHT / _MATURE_TENURE_
LOGIN_WEIGHT below. check_automated_healthy_cohort() is the Test E
existence-and-not-mis-flagged check this rule is validated against.
"""
import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .model_performance import log_performance

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "acme_gtm.duckdb")
_MODEL_NAME = "account_health_score"

# QA-plan reweighting rule -- see module docstring. A 3x ratio so the
# reweight is a real behavioral change, not a token gesture.
_EARLY_TENURE_DAYS = 90
_EARLY_TENURE_LOGIN_WEIGHT = 1.0
_MATURE_TENURE_LOGIN_WEIGHT = 0.33

# Trailing window features are computed over, and how many months before
# the observed outcome (churn, or "now" for survivors) an account is
# scored at -- an early-warning framing, not a same-month prediction.
# _SCORING_LEAD_MONTHS = 5 is deliberate, not arbitrary: generators/
# config.py's DECLINE_MONTHS_BEFORE_CHURN = 4 is how many months before
# churn the generator's deterministic usage/ticket/sentiment decline
# window starts. Scoring at exactly that boundary (or inside it) lets the
# model see the designed collapse directly and produces an inflated,
# unrealistic AUC (~0.93-0.99 at lead <= 4 -- validated during build, see
# docs/acme-corp-analytics-methods.md) that doesn't reflect a genuine
# early-warning signal, just pattern-matching the generator's own
# construction. Scoring 1 month before that window starts (lead=5) is the
# actual "early warning" case the health score is supposed to solve, and
# is what the QA plan's stated 0.65-0.80 AUC target describes.
_FEATURE_WINDOW_MONTHS = 3
_SCORING_LEAD_MONTHS = 5
_RANDOM_SEED = 42

_NUMERIC_FEATURES = [
    "usage_trend_ratio",
    "ticket_count_3mo",
    "high_severity_ticket_count_3mo",
    "avg_ticket_severity_3mo",
    "has_tickets_3mo",
    "login_count_avg_3mo",
    "login_frequency_weighted",
    "am_sentiment_avg_3mo",
    "has_am_activity_3mo",
    "am_touchpoint_count_3mo",
    "tenure_days",
    "is_within_first_90_days",
]
_CATEGORICAL_FEATURES = ["segment"]

# Maps each of the twelve numeric model features to the one conceptual GTM
# input it belongs to. These four groups are not a modeling choice -- they
# are fixed by docs/acme-corp-gtm-metric-tree.md's "Account health score"
# leaf and docs/acme-corp-gtm-portfolio-build-spec.md's retention/expansion
# mechanics, both at company-model-design time, before this model existed.
# tenure_days, is_within_first_90_days, and segment are deliberately absent
# from every group: they are real model features but not one of the four
# conceptual inputs, and segment's one-hot dummies are not on the same
# standardized scale as the numeric features below (never passed through
# StandardScaler), so folding them into a percentage breakdown alongside
# the four groups would not be a like-for-like comparison.
_CONCEPTUAL_INPUT_GROUPS = {
    "usage_trend": ["usage_trend_ratio"],
    "ticket_volume_severity": [
        "ticket_count_3mo",
        "high_severity_ticket_count_3mo",
        "avg_ticket_severity_3mo",
        "has_tickets_3mo",
    ],
    "login_frequency": [
        "login_count_avg_3mo",
        "login_frequency_weighted",
    ],
    "am_sentiment": [
        "am_sentiment_avg_3mo",
        "has_am_activity_3mo",
        "am_touchpoint_count_3mo",
    ],
}


def _connect():
    return duckdb.connect(_DB_PATH, read_only=True)


def load_account_health_mart(as_of_date: date, con=None) -> pd.DataFrame:
    """Grain: one row per account_id per month, restricted to month <=
    as_of_date -- no leakage from the future. Source mart:
    mart_account_health."""
    owns_con = con is None
    con = con or _connect()
    try:
        df = con.execute(
            "select * from main_marts.mart_account_health where month <= ?",
            [as_of_date],
        ).df()
    finally:
        if owns_con:
            con.close()
    df["month"] = pd.to_datetime(df["month"])
    df["signup_date"] = pd.to_datetime(df["signup_date"])
    df["churn_month"] = pd.to_datetime(df["churn_month"])
    return df


def _month_floor(ts: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(ts).to_period("M").start_time


def _build_snapshots(mart_df: pd.DataFrame, as_of_date: date, seed: int = _RANDOM_SEED) -> pd.DataFrame:
    """One scoring_date + label per account: _SCORING_LEAD_MONTHS before
    churn for eventual churners (early-warning framing). Survivors get a
    seeded-random scoring_date drawn from their own history (from
    signup+1mo through as_of_date - _SCORING_LEAD_MONTHS) rather than one
    shared fixed date -- a fixed date would cluster every survivor's
    scoring_date on a single month, making any date-based train/test split
    degenerate (nearly all negatives landing in one split). Accounts
    without enough tenure to have a valid scoring_date are dropped -- not
    enough history to score them honestly."""
    as_of_ts = pd.Timestamp(as_of_date)
    accounts = mart_df[
        ["account_id", "segment", "signup_date", "is_eventually_churned", "churn_month"]
    ].drop_duplicates("account_id").sort_values("account_id").reset_index(drop=True)

    is_churned = accounts["is_eventually_churned"] & accounts["churn_month"].notna()
    signup_month = accounts["signup_date"].map(_month_floor)
    earliest = signup_month + pd.DateOffset(months=1)
    latest_survivor = as_of_ts - pd.DateOffset(months=_SCORING_LEAD_MONTHS)

    rng = np.random.default_rng(seed)
    span_months = ((latest_survivor.to_period("M") - earliest.dt.to_period("M")).apply(lambda o: o.n))
    span_months = span_months.clip(lower=0)
    random_offset = rng.integers(0, span_months.to_numpy() + 1)
    survivor_scoring_date = pd.Series(
        [d + pd.DateOffset(months=int(o)) for d, o in zip(earliest, random_offset)],
        index=accounts.index,
    )

    scoring_date = np.where(
        is_churned,
        accounts["churn_month"] - pd.DateOffset(months=_SCORING_LEAD_MONTHS),
        survivor_scoring_date,
    )
    accounts = accounts.assign(
        scoring_date=pd.to_datetime(scoring_date).map(_month_floor),
        label=is_churned.astype(int),
    )

    valid = (
        (accounts["scoring_date"] <= as_of_ts)
        & (accounts["scoring_date"] >= earliest)
    )
    return accounts.loc[valid, ["account_id", "segment", "scoring_date", "label"]].reset_index(drop=True)


def _compute_features(acct_hist_full: pd.DataFrame, scoring_date: pd.Timestamp,
                       signup_date: pd.Timestamp) -> dict:
    """Point-in-time features for one account as of scoring_date, computed
    only from that account's own rows (acct_hist_full, already isolated to
    one account_id by the caller) with month <= scoring_date."""
    acct_hist = acct_hist_full[acct_hist_full["month"] <= scoring_date]
    window_start = scoring_date - pd.DateOffset(months=_FEATURE_WINDOW_MONTHS - 1)
    trailing = acct_hist[acct_hist["month"] >= window_start]

    baseline_actions = acct_hist["actions_consumed"].mean()
    trailing_actions = trailing["actions_consumed"].mean()
    usage_trend_ratio = (
        trailing_actions / baseline_actions if baseline_actions and baseline_actions > 0 else np.nan
    )

    tenure_days = (scoring_date - _month_floor(signup_date)).days
    login_avg_3mo = trailing["login_count"].mean()
    login_weight = _EARLY_TENURE_LOGIN_WEIGHT if tenure_days <= _EARLY_TENURE_DAYS else _MATURE_TENURE_LOGIN_WEIGHT

    return {
        "usage_trend_ratio": usage_trend_ratio,
        "ticket_count_3mo": trailing["ticket_count"].sum(),
        "high_severity_ticket_count_3mo": trailing["high_severity_ticket_count"].sum(),
        "avg_ticket_severity_3mo": trailing["avg_ticket_severity_score"].mean(),
        "has_tickets_3mo": float(trailing["ticket_count"].sum() > 0),
        "login_count_avg_3mo": login_avg_3mo,
        "login_frequency_weighted": (login_avg_3mo or 0.0) * login_weight,
        "am_sentiment_avg_3mo": trailing["avg_am_sentiment_score"].mean(),
        "has_am_activity_3mo": float(trailing["am_touchpoint_count"].sum() > 0),
        "am_touchpoint_count_3mo": trailing["am_touchpoint_count"].sum(),
        "tenure_days": tenure_days,
        "is_within_first_90_days": float(tenure_days <= _EARLY_TENURE_DAYS),
    }


def _build_feature_matrix(mart_df: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame:
    """Grain: one row per (account_id, scoring_date) in snapshots. Source
    mart: mart_account_health (via mart_df, already point-in-time filtered
    by the caller)."""
    signup_by_account = mart_df.drop_duplicates("account_id").set_index("account_id")["signup_date"]
    # Group once (O(n)) rather than re-filtering the full mart_df per
    # snapshot (O(n) per row, O(n*m) overall) -- mart_df is 100k+ rows and
    # snapshots can be in the thousands.
    history_by_account = {
        account_id: group.sort_values("month")
        for account_id, group in mart_df.groupby("account_id", sort=False)
    }
    rows = []
    for row in snapshots.itertuples():
        acct_hist_full = history_by_account[row.account_id]
        feats = _compute_features(acct_hist_full, row.scoring_date, signup_by_account[row.account_id])
        feats.update(
            account_id=row.account_id,
            segment=row.segment,
            scoring_date=row.scoring_date,
            label=row.label,
        )
        rows.append(feats)
    return pd.DataFrame(rows)


def _make_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        [
            (
                "num",
                Pipeline(
                    [("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
                ),
                _NUMERIC_FEATURES,
            ),
            ("cat", OneHotEncoder(handle_unknown="ignore"), _CATEGORICAL_FEATURES),
        ]
    )
    return Pipeline(
        [
            ("preprocess", preprocessor),
            (
                "classify",
                LogisticRegression(max_iter=2000, random_state=_RANDOM_SEED, class_weight="balanced"),
            ),
        ]
    )


def _feature_names(preprocessor: ColumnTransformer) -> list:
    """Full list of model inputs in the order LogisticRegression.coef_
    reports them: the 12 numeric features as-named, then one column per
    segment value from the fitted OneHotEncoder. Built explicitly from the
    fitted OneHotEncoder rather than via the full pipeline's end-to-end
    get_feature_names_out(), since the nested impute+scale sub-pipeline's
    introspection support is more version-fragile than reading the fitted
    OneHotEncoder directly."""
    cat_encoder = preprocessor.named_transformers_["cat"]
    cat_names = list(cat_encoder.get_feature_names_out(_CATEGORICAL_FEATURES))
    return _NUMERIC_FEATURES + cat_names


def _coefficient_table(pipeline: Pipeline) -> pd.DataFrame:
    """Full fitted-coefficient table, one row per model input (12 numeric
    features + 3 segment dummies). Coefficients are in the STANDARDIZED /
    encoded scale the classifier actually sees (StandardScaler on numeric
    features) -- comparable to each other in relative magnitude, but not
    directly interpretable as "one raw unit of X" without unscaling. This
    is the ungrouped, per-input table; compute_feature_group_importance()
    below is a separate, coarser summary derived from this one."""
    preprocessor = pipeline.named_steps["preprocess"]
    classifier = pipeline.named_steps["classify"]
    return pd.DataFrame({
        "feature": _feature_names(preprocessor),
        "coefficient": classifier.coef_[0],
    }).sort_values("coefficient", key=np.abs, ascending=False).reset_index(drop=True)


def compute_feature_group_importance(pipeline: Pipeline) -> dict:
    """Relative importance of the four conceptual health-score inputs, read
    from an already-fitted pipeline's logistic-regression coefficients --
    a post-hoc read of a pipeline train_churn_model() already fit, not a
    training step itself and not point-in-time-sensitive on its own.
    Importance per group is the sum of |standardized coefficient| across
    that group's features (all twelve numeric features share one
    SimpleImputer+StandardScaler, so their coefficients sit on a common,
    comparable scale), normalized so the four groups sum to 100%. The
    denominator is only those four groups' features -- tenure_days,
    is_within_first_90_days, and the one-hot segment dummies are excluded
    entirely, not folded into any group and not given a fifth bucket (see
    _CONCEPTUAL_INPUT_GROUPS). login_count_avg_3mo and
    login_frequency_weighted are two representations of one underlying
    login signal (the second is a tenure-reweighted transform of the
    first) -- summing both into the login_frequency group recovers the
    model's total reliance on login behavior regardless of how the fit
    happened to split weight between the raw and reweighted versions."""
    preprocessor = pipeline.named_steps["preprocess"]
    classifier = pipeline.named_steps["classify"]
    coef_by_feature = dict(zip(_feature_names(preprocessor), classifier.coef_[0]))

    group_magnitude = {
        group: sum(abs(coef_by_feature[member]) for member in members)
        for group, members in _CONCEPTUAL_INPUT_GROUPS.items()
    }
    total = sum(group_magnitude.values())
    return {group: (magnitude / total) * 100 for group, magnitude in group_magnitude.items()}


def _high_tier_confusion(test_labels: pd.Series, test_proba: np.ndarray,
                          high_risk_quantile: float = 0.80) -> dict:
    """Confusion-matrix-shaped view of the High-risk tier specifically, at
    the SAME quantile-based operating threshold score_accounts() uses in
    production (top (1 - high_risk_quantile) share = High) -- never an
    arbitrary 0.5 cutoff, which class_weight='balanced' makes meaningless
    (see score_accounts docstring). The cutoff is derived from the held-out
    test set's own probability distribution, mirroring how score_accounts()
    derives its cutoff from the scored population rather than from labels
    -- this is what "the actual operating threshold" means for a
    quantile-tiered model, since there is no single fixed probability
    threshold to evaluate against."""
    cutoff = float(np.quantile(test_proba, high_risk_quantile))
    predicted_high = test_proba >= cutoff
    actual_positive = test_labels.to_numpy() == 1

    tp = int((predicted_high & actual_positive).sum())
    fp = int((predicted_high & ~actual_positive).sum())
    fn = int((~predicted_high & actual_positive).sum())
    tn = int((~predicted_high & ~actual_positive).sum())
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall and (precision + recall) else float("nan"))

    return {
        "operating_threshold_quantile": high_risk_quantile,
        "operating_threshold_probability": cutoff,
        "true_positive": tp, "false_positive": fp,
        "true_negative": tn, "false_negative": fn,
        "precision_high_tier": precision,
        "recall_high_tier": recall,
        "f1_high_tier": f1,
    }


def _calibration_check(test_labels: pd.Series, test_proba: np.ndarray) -> dict:
    """Lightest honest calibration read, no new library required: mean
    predicted probability vs. actual base rate on the same held-out set.
    class_weight='balanced' reweights the loss to treat the minority churn
    class as if it were as common as the majority class, which shifts
    predicted probabilities up systematically -- so raw churn_probability
    is a valid RANKING signal (what quantile-based risk_tier relies on)
    but is NOT calibrated to true likelihood, and must never be read by a
    downstream consumer as "X% chance this account churns." This check
    demonstrates that gap directly rather than merely asserting it."""
    mean_predicted = float(np.mean(test_proba))
    actual_base_rate = float(test_labels.mean())
    return {
        "mean_predicted_probability": mean_predicted,
        "actual_base_rate": actual_base_rate,
        "calibration_gap": mean_predicted - actual_base_rate,
        "calibrated": False,
    }


def train_churn_model(as_of_date: date, con=None, test_fraction: float = 0.25, log: bool = True) -> dict:
    """Trains the churn-risk classifier and validates it on a held-out
    split -- grain: one row per account_id snapshot (one point-in-time
    scoring_date per account; no account or row appears in both train and
    test). Source mart: mart_account_health. The split is a class-
    stratified random split, seeded via _RANDOM_SEED, not a temporal
    (by-scoring_date) split: churn events here concentrate earlier in the
    36-month window (accounts that would churn near the very end of the
    window haven't reached their churn point yet -- ordinary right-
    censoring, not a data bug), so a late-scoring_date holdout ends up with
    only a handful of positives and an unstable AUC estimate. Point-in-time
    discipline is preserved regardless of split strategy -- every row's
    features are already computed using only that account's own data up
    to its own scoring_date (see _compute_features), so shuffling rows
    across train/test cannot leak future information into any feature.
    Logs the holdout AUC and the rest of the statistical validation
    package (precision/recall/F1 at the production operating threshold,
    calibration gap, per-conceptual-group importance) to
    fact_model_performance_history (via analytics/model_performance.py)
    when log=True. No R²/RMSE section applies anywhere in this module --
    this is a binary classifier, not a regression model; see
    _coefficient_table() and _high_tier_confusion() for this model's fit
    and accuracy evidence instead."""
    mart_df = load_account_health_mart(as_of_date, con=con)
    snapshots = _build_snapshots(mart_df, as_of_date)
    features = _build_feature_matrix(mart_df, snapshots).sort_values("scoring_date").reset_index(drop=True)

    train_df, test_df = train_test_split(
        features, test_size=test_fraction, random_state=_RANDOM_SEED, stratify=features["label"]
    )

    pipeline = _make_pipeline()
    pipeline.fit(train_df[_NUMERIC_FEATURES + _CATEGORICAL_FEATURES], train_df["label"])

    test_proba = pipeline.predict_proba(test_df[_NUMERIC_FEATURES + _CATEGORICAL_FEATURES])[:, 1]
    auc = roc_auc_score(test_df["label"], test_proba)

    importance_pct = compute_feature_group_importance(pipeline)
    confusion = _high_tier_confusion(test_df["label"], test_proba)
    calibration = _calibration_check(test_df["label"], test_proba)
    coefficients = _coefficient_table(pipeline)

    if log:
        log_performance(_MODEL_NAME, as_of_date, "auc_holdout", float(auc))
        for group, pct in importance_pct.items():
            log_performance(_MODEL_NAME, as_of_date, f"importance_pct_{group}", float(pct))
        log_performance(_MODEL_NAME, as_of_date, "precision_high_tier", confusion["precision_high_tier"])
        log_performance(_MODEL_NAME, as_of_date, "recall_high_tier", confusion["recall_high_tier"])
        log_performance(_MODEL_NAME, as_of_date, "f1_high_tier", confusion["f1_high_tier"])
        log_performance(_MODEL_NAME, as_of_date, "true_positive_high_tier", confusion["true_positive"])
        log_performance(_MODEL_NAME, as_of_date, "false_positive_high_tier", confusion["false_positive"])
        log_performance(_MODEL_NAME, as_of_date, "true_negative_high_tier", confusion["true_negative"])
        log_performance(_MODEL_NAME, as_of_date, "false_negative_high_tier", confusion["false_negative"])
        log_performance(_MODEL_NAME, as_of_date, "mean_predicted_probability", calibration["mean_predicted_probability"])
        log_performance(_MODEL_NAME, as_of_date, "actual_base_rate", calibration["actual_base_rate"])
        log_performance(_MODEL_NAME, as_of_date, "calibration_gap", calibration["calibration_gap"])

    return {
        "pipeline": pipeline,
        "auc_holdout": auc,
        "n_train": len(train_df),
        "n_test": len(test_df),
        "n_train_positive": int(train_df["label"].sum()),
        "n_test_positive": int(test_df["label"].sum()),
        "train_scoring_date_range": (train_df["scoring_date"].min(), train_df["scoring_date"].max()),
        "test_scoring_date_range": (test_df["scoring_date"].min(), test_df["scoring_date"].max()),
        "features": features,
        "feature_group_importance_pct": importance_pct,
        "validation_package": {
            "confusion_matrix_high_tier": confusion,
            "calibration": calibration,
            "coefficients": coefficients,
        },
    }


def score_accounts(as_of_date: date, pipeline: Pipeline, con=None,
                    high_risk_quantile: float = 0.80, medium_risk_quantile: float = 0.50) -> pd.DataFrame:
    """Scores every currently-ACTIVE account's state as of as_of_date
    (features computed over the trailing _FEATURE_WINDOW_MONTHS ending at
    each account's latest available month <= as_of_date) with an already-
    trained pipeline. Grain: one row per account_id. Source mart:
    mart_account_health. Already-churned accounts are excluded -- scoring
    them at their own last month of data is scoring them at-or-past
    churn, which isn't the "who should we act on now" question this
    output serves. health_score is 0-100 (100 = healthiest, i.e.
    1 - churn_probability). risk_tier is quantile-based over the scored
    (active) population -- top (1 - high_risk_quantile) share = High,
    next slice down to medium_risk_quantile = Medium, remainder = Low --
    rather than fixed probability cutoffs: class_weight='balanced' in
    _make_pipeline shifts predicted probabilities up systematically
    (needed so the minority churn class isn't ignored at fit time), so a
    fixed 0.5 cutoff on that shifted scale mis-flags most of the active
    base as High risk. Quantile tiers make risk_tier a relative ranking
    (the standard shape for a watchlist / triage tool) instead of a
    miscalibrated absolute-probability read."""
    mart_df = load_account_health_mart(as_of_date, con=con)
    active_accounts = mart_df.loc[mart_df["customer_status"] == "Active", "account_id"].unique()
    active_mart_df = mart_df[mart_df["account_id"].isin(active_accounts)]

    latest_month = active_mart_df.groupby("account_id")["month"].max().rename("scoring_date")
    snapshot_accounts = active_mart_df.drop_duplicates("account_id").set_index("account_id")["segment"]
    snapshots = pd.DataFrame({"segment": snapshot_accounts}).join(latest_month).reset_index()

    features = _build_feature_matrix(
        active_mart_df, snapshots.assign(label=0)  # label unused for scoring, placeholder column only
    )
    churn_probability = pipeline.predict_proba(features[_NUMERIC_FEATURES + _CATEGORICAL_FEATURES])[:, 1]
    features["churn_probability"] = churn_probability
    features["health_score"] = ((1 - churn_probability) * 100).round(1)
    high_cut = features["churn_probability"].quantile(high_risk_quantile)
    medium_cut = features["churn_probability"].quantile(medium_risk_quantile)
    features["risk_tier"] = np.select(
        [churn_probability >= high_cut, churn_probability >= medium_cut],
        ["High", "Medium"],
        default="Low",
    )
    return features[
        ["account_id", "segment", "scoring_date", "tenure_days", "is_within_first_90_days",
         "usage_trend_ratio", "login_count_avg_3mo", "login_frequency_weighted",
         "churn_probability", "health_score", "risk_tier"]
    ]


def check_automated_healthy_cohort(scored_df: pd.DataFrame, mart_df: pd.DataFrame,
                                    high_usage_quantile: float = 0.75,
                                    low_login_quantile: float = 0.25) -> dict:
    """QA plan Test E: 'High-automation, low-login, high-Actions accounts
    exist and are NOT predominantly mis-flagged as at-risk.' Defines the
    cohort per-segment (top usage_quantile of trailing Actions, bottom
    login_quantile of trailing logins, within that account's own segment)
    using the same current-state window score_accounts() scored on, then
    compares the cohort's High-risk-tier rate against the overall
    population's High-risk-tier rate. 'Not predominantly mis-flagged'
    means the cohort's High-risk share must not exceed the population's --
    the reweighting rule failing would show up as the automated cohort
    getting flagged High at a HIGHER rate than everyone else, not a lower
    one."""
    merged = scored_df.merge(
        mart_df.groupby("account_id")["actions_consumed"].mean().rename("avg_actions_consumed"),
        on="account_id",
    )
    thresholds = merged.groupby("segment").agg(
        hi_actions=("avg_actions_consumed", lambda s: s.quantile(high_usage_quantile)),
        lo_login=("login_count_avg_3mo", lambda s: s.quantile(low_login_quantile)),
    )
    merged = merged.join(thresholds, on="segment")
    is_automated_healthy = (
        (merged["avg_actions_consumed"] >= merged["hi_actions"])
        & (merged["login_count_avg_3mo"] <= merged["lo_login"])
    )

    cohort = merged[is_automated_healthy]
    population_high_risk_rate = (merged["risk_tier"] == "High").mean()
    cohort_high_risk_rate = (cohort["risk_tier"] == "High").mean() if len(cohort) else np.nan

    return {
        "cohort_n": int(is_automated_healthy.sum()),
        "population_high_risk_rate": float(population_high_risk_rate),
        "cohort_high_risk_rate": float(cohort_high_risk_rate) if len(cohort) else None,
        "cohort_not_predominantly_misflagged": (
            len(cohort) > 0 and cohort_high_risk_rate <= population_high_risk_rate
        ),
    }


def run_build_time_validation(as_of_date: date) -> dict:
    """End-to-end build-time check: trains the model, logs holdout AUC,
    scores the full population as of as_of_date, and runs the Test E
    automated-but-healthy check. This is what analytics-model-validator
    consumes -- it does not itself re-train."""
    con = _connect()
    try:
        train_result = train_churn_model(as_of_date, con=con)
        mart_df = load_account_health_mart(as_of_date, con=con)
        scored = score_accounts(as_of_date, train_result["pipeline"], con=con)
        test_e = check_automated_healthy_cohort(scored, mart_df)
    finally:
        con.close()
    return {
        "auc_holdout": train_result["auc_holdout"],
        "n_train": train_result["n_train"],
        "n_test": train_result["n_test"],
        "n_train_positive": train_result["n_train_positive"],
        "n_test_positive": train_result["n_test_positive"],
        "train_scoring_date_range": train_result["train_scoring_date_range"],
        "test_scoring_date_range": train_result["test_scoring_date_range"],
        "feature_group_importance_pct": train_result["feature_group_importance_pct"],
        "validation_package": train_result["validation_package"],
        "test_e": test_e,
        "scored_accounts": scored,
    }


if __name__ == "__main__":
    result = run_build_time_validation(date(2025, 12, 31))
    print(f"Holdout AUC: {result['auc_holdout']:.4f} (n_train={result['n_train']} [{result['n_train_positive']} positive], "
          f"n_test={result['n_test']} [{result['n_test_positive']} positive])")
    print(f"Train scoring_date range: {result['train_scoring_date_range']}")
    print(f"Test scoring_date range:  {result['test_scoring_date_range']}")
    print("Test E (automated-but-healthy cohort):", result["test_e"])
    print()
    print("Feature group importance (%):", {k: round(v, 1) for k, v in result["feature_group_importance_pct"].items()})
    print()
    print("Confusion matrix (High tier, production operating threshold):")
    print(result["validation_package"]["confusion_matrix_high_tier"])
    print()
    print("Calibration:", result["validation_package"]["calibration"])
    print()
    print("Coefficient table:")
    print(result["validation_package"]["coefficients"].to_string(index=False))
