"""Combine multiple device parameters into a single per-die efficiency score.

The goal is to answer the question:
**"Which positions on a wafer produce the best devices?"**

Approach
--------
Each parameter is normalised to a 0–1 score where 1 means "best".
Some metrics are larger-is-better (e.g. extinction ratio), some are
smaller-is-better (e.g. leakage current, Vπ — lower is more efficient).

The per-die efficiency score is then a weighted sum of the parameter
scores. Default weights treat all metrics equally; callers can override
to emphasise particular figures of merit.

A score of NaN propagates through the sum, so dies with missing or
failed-contact measurements are flagged separately rather than silently
penalised.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


# Default normalisation directions. ``"min"`` means smaller value is better
# (gets a higher normalised score), ``"max"`` is the opposite.
DEFAULT_DIRECTIONS: dict[str, str] = {
    "FSR_nm": "max",                    # larger FSR → wider wavelength range
    "dLambda_dV_pm_per_V": "min_abs",   # but |dλ/dV| should be high → use min on inverse
    "PeakIL_dB": "max",                 # higher (less negative) IL is better
    "PeakIL_near_1310_dB": "max",       # alias
    "I_at_-1V_pA": "min_abs",           # less leakage is better
    "Vpi_V": "min",                     # lower Vπ → higher efficiency
    "Vpi_L_V_cm": "min",                # lower Vπ·L → better figure of merit
    "ER_at_-2V_dB": "max",              # higher extinction ratio is better
    "ER_at_0V_dB": "max",
    "Loss_per_um_dB_per_um": "min_abs", # less doping loss
    "Modulation_per_um_dB_per_V_per_um": "min_abs",  # higher mod efficiency = more negative slope
}


# Default metric weights. These can be overridden by the caller. Sum need not
# equal 1; results are normalised at the end.
DEFAULT_WEIGHTS: dict[str, float] = {
    "Vpi_V": 2.0,                       # most important: actual modulation strength
    "ER_at_-2V_dB": 1.5,                # extinction ratio is core spec
    "PeakIL_dB": 1.0,                   # insertion loss
    "I_at_-1V_pA": 1.0,                 # leakage / contact quality
    "FSR_nm": 0.5,                      # geometric uniformity
}


@dataclass
class EfficiencyConfig:
    """Configuration for the efficiency scorer."""

    metrics: list[str] = field(default_factory=lambda: list(DEFAULT_WEIGHTS.keys()))
    directions: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_DIRECTIONS))
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    # When True, dies with NaN in any used metric are scored NaN; otherwise
    # missing metrics are simply skipped (and weights renormalised per row).
    require_all: bool = False


def _normalise_column(values: pd.Series, direction: str) -> pd.Series:
    """Map a column to [0, 1] where 1 is best.

    Uses robust min-max scaling on the 5th–95th percentile range so a single
    outlier can't compress the score.
    """
    if direction not in {"min", "max", "min_abs", "max_abs"}:
        raise ValueError(f"Unknown direction {direction!r}")

    raw = values.copy().astype(float)
    if direction in {"min_abs", "max_abs"}:
        raw = raw.abs()
    finite = raw.replace([np.inf, -np.inf], np.nan).dropna()
    if finite.empty:
        return pd.Series(np.nan, index=values.index)

    lo = float(np.percentile(finite, 5))
    hi = float(np.percentile(finite, 95))
    if hi == lo:
        # All identical → everyone gets 1.0
        return pd.Series(np.where(raw.notna(), 1.0, np.nan), index=values.index)

    clipped = raw.clip(lo, hi)
    if direction in {"min", "min_abs"}:
        score = (hi - clipped) / (hi - lo)
    else:
        score = (clipped - lo) / (hi - lo)
    return score


def compute_efficiency_score(
    features: pd.DataFrame,
    *,
    config: EfficiencyConfig | None = None,
    group_by: list[str] | None = None,
) -> pd.DataFrame:
    """Add per-die efficiency scores to a feature table.

    Parameters
    ----------
    features : DataFrame
        One row per die. Must contain at minimum ``Wafer``, ``Die``,
        ``DieCol``, ``DieRow``.
    config : EfficiencyConfig | None
        Custom metric list / weights / directions. ``None`` uses defaults.
    group_by : list[str] | None
        If given, scores are normalised within each group (e.g. per
        ``["Wafer", "Band"]``) so each group's best die gets 1.0. Useful
        for cross-band comparisons where absolute scales differ.

    Returns
    -------
    DataFrame
        Original columns plus one normalised score column per metric
        (``Score_<metric>``) and an ``EfficiencyScore`` aggregate (0–1).
    """
    if config is None:
        config = EfficiencyConfig()

    out = features.copy()
    if features.empty:
        out["EfficiencyScore"] = pd.Series(dtype=float)
        return out

    # Restrict to metrics actually present in the table
    metrics = [m for m in config.metrics if m in out.columns]
    if not metrics:
        out["EfficiencyScore"] = np.nan
        return out

    # Normalise each metric, optionally per group
    for m in metrics:
        col = f"Score_{m}"
        direction = config.directions.get(m, "max")
        if group_by:
            out[col] = (
                out.groupby(group_by, dropna=False)[m]
                .transform(lambda s: _normalise_column(s, direction))
            )
        else:
            out[col] = _normalise_column(out[m], direction)

    # Weighted sum
    score_cols = [f"Score_{m}" for m in metrics]
    weights = np.array([config.weights.get(m, 1.0) for m in metrics], dtype=float)

    if config.require_all:
        # Every metric must be present, otherwise EfficiencyScore is NaN
        scores_arr = out[score_cols].to_numpy(dtype=float)
        weighted = scores_arr * weights
        out["EfficiencyScore"] = weighted.sum(axis=1) / weights.sum()
    else:
        # Per-row dynamic re-weighting that ignores NaN columns
        scores_arr = out[score_cols].to_numpy(dtype=float)
        valid = ~np.isnan(scores_arr)
        weight_matrix = np.where(valid, weights, 0.0)
        score_matrix = np.where(valid, scores_arr, 0.0)
        denom = weight_matrix.sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            out["EfficiencyScore"] = np.where(
                denom > 0, (score_matrix * weight_matrix).sum(axis=1) / denom, np.nan
            )

    return out


# ----------------------------------------------------------------------- #
# Position analysis
# ----------------------------------------------------------------------- #
def best_dies(
    scored: pd.DataFrame,
    n: int = 10,
    *,
    group_by: list[str] | None = None,
) -> pd.DataFrame:
    """Return the top-n dies sorted by ``EfficiencyScore``.

    If ``group_by`` is given, returns top-n per group (e.g. per wafer).
    """
    if "EfficiencyScore" not in scored.columns:
        raise KeyError("DataFrame is missing 'EfficiencyScore'; run "
                       "compute_efficiency_score first")
    df = scored.dropna(subset=["EfficiencyScore"])
    if group_by:
        return (df.sort_values("EfficiencyScore", ascending=False)
                  .groupby(group_by, dropna=False).head(n))
    return df.nlargest(n, "EfficiencyScore")


def position_summary(scored: pd.DataFrame) -> pd.DataFrame:
    """Aggregate efficiency by die-level position bins.

    Reports mean / median efficiency for:
    * **center vs edge** (radius ≤ 2.5 → center)
    * **quadrant** (NE, NW, SE, SW)
    * **radius bin** (rounded radius)
    """
    if "EfficiencyScore" not in scored.columns:
        raise KeyError("Run compute_efficiency_score first")

    df = scored.dropna(subset=["EfficiencyScore", "DieCol", "DieRow"]).copy()
    if df.empty:
        return pd.DataFrame()

    df["Radius"] = np.hypot(df["DieCol"].astype(float),
                            df["DieRow"].astype(float))
    df["Region"] = np.where(df["Radius"] <= 2.5, "center", "edge")

    def _quad(c, r):
        if c >= 0 and r >= 0:
            return "NE"
        if c < 0 and r >= 0:
            return "NW"
        if c < 0 and r < 0:
            return "SW"
        return "SE"

    df["Quadrant"] = df.apply(lambda x: _quad(x["DieCol"], x["DieRow"]), axis=1)
    df["RadiusBin"] = df["Radius"].round().astype(int)

    rows: list[dict] = []
    rows.append({"category": "Region", "level": "center",
                 "n": len(df[df["Region"] == "center"]),
                 "mean": df[df["Region"] == "center"]["EfficiencyScore"].mean(),
                 "median": df[df["Region"] == "center"]["EfficiencyScore"].median()})
    rows.append({"category": "Region", "level": "edge",
                 "n": len(df[df["Region"] == "edge"]),
                 "mean": df[df["Region"] == "edge"]["EfficiencyScore"].mean(),
                 "median": df[df["Region"] == "edge"]["EfficiencyScore"].median()})
    for q in ["NE", "NW", "SW", "SE"]:
        sub = df[df["Quadrant"] == q]
        rows.append({"category": "Quadrant", "level": q, "n": len(sub),
                     "mean": sub["EfficiencyScore"].mean(),
                     "median": sub["EfficiencyScore"].median()})
    for r in sorted(df["RadiusBin"].unique()):
        sub = df[df["RadiusBin"] == r]
        rows.append({"category": "Radius", "level": f"r={r}",
                     "n": len(sub),
                     "mean": sub["EfficiencyScore"].mean(),
                     "median": sub["EfficiencyScore"].median()})
    return pd.DataFrame(rows)


def find_sweet_spots(
    scored: pd.DataFrame,
    *,
    threshold_pct: float = 75.0,
    min_consistency: int = 2,
) -> pd.DataFrame:
    """Find die positions that are consistently good across all wafers.

    A "sweet spot" is a (DieCol, DieRow) where the efficiency score is in
    the top ``threshold_pct`` percentile on at least ``min_consistency``
    wafers. This identifies positions where the process consistently
    produces good devices, not just lucky individual wafers.
    """
    if "EfficiencyScore" not in scored.columns:
        raise KeyError("Run compute_efficiency_score first")

    df = scored.dropna(subset=["EfficiencyScore"]).copy()
    if df.empty:
        return pd.DataFrame()

    # Per-wafer percentile rank
    df["WaferRankPct"] = (
        df.groupby("Wafer")["EfficiencyScore"]
          .transform(lambda s: s.rank(pct=True) * 100)
    )
    df["IsTop"] = df["WaferRankPct"] >= threshold_pct

    # Group by die position; count how many wafers have it in the top
    pos_stats = (
        df.groupby(["DieCol", "DieRow"])
          .agg(n_wafers_top=("IsTop", "sum"),
               n_wafers_total=("Wafer", "nunique"),
               mean_score=("EfficiencyScore", "mean"),
               median_score=("EfficiencyScore", "median"))
          .reset_index()
    )
    pos_stats["consistency_pct"] = (
        100.0 * pos_stats["n_wafers_top"] / pos_stats["n_wafers_total"]
    )
    pos_stats["is_sweet_spot"] = pos_stats["n_wafers_top"] >= min_consistency
    return pos_stats.sort_values(
        ["is_sweet_spot", "n_wafers_top", "mean_score"],
        ascending=[False, False, False],
    )


# ----------------------------------------------------------------------- #
# Visualisation
# ----------------------------------------------------------------------- #
def plot_efficiency_wafermap(
    scored: pd.DataFrame,
    output_path: str | Path,
    *,
    group_by: list[str] | None = None,
    title: str = "Per-die efficiency score",
) -> Path:
    """Wafer map of the EfficiencyScore.

    If multiple wafers/bands are present, draws one panel each.
    """
    import matplotlib.pyplot as plt

    if group_by is None:
        # Auto-detect: split by Wafer (and Band if present and varies)
        group_by = ["Wafer"]
        if "Band" in scored.columns and scored["Band"].nunique() > 1:
            group_by.append("Band")

    df = scored.dropna(subset=["EfficiencyScore", "DieCol", "DieRow"]).copy()
    if df.empty:
        raise ValueError("No scored dies with valid position information")

    groups = sorted({tuple(r[c] for c in group_by) for _, r in df.iterrows()})
    n = len(groups)
    ncols = min(3, n)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.5 * ncols, 4.5 * nrows),
                             squeeze=False)

    cols_all = sorted(df["DieCol"].unique())
    rows_all = sorted(df["DieRow"].unique())

    for i, key in enumerate(groups):
        ax = axes[i // ncols][i % ncols]
        mask = np.ones(len(df), dtype=bool)
        for col, val in zip(group_by, key):
            mask &= (df[col] == val)
        sub = df[mask]

        grid = np.full((len(rows_all), len(cols_all)), np.nan)
        for _, r in sub.iterrows():
            gc = cols_all.index(r["DieCol"])
            gr = rows_all.index(r["DieRow"])
            grid[gr, gc] = r["EfficiencyScore"]

        im = ax.imshow(
            grid, origin="lower", vmin=0, vmax=1, cmap="RdYlGn",
            extent=[min(cols_all) - 0.5, max(cols_all) + 0.5,
                    min(rows_all) - 0.5, max(rows_all) + 0.5],
            aspect="equal",
        )
        ax.set_xticks(cols_all)
        ax.set_yticks(rows_all)
        ax.set_xlabel("Die Column")
        ax.set_ylabel("Die Row")
        label = " / ".join(str(v) for v in key)
        ax.set_title(f"{label}  (n={len(sub)}, "
                     f"mean={sub['EfficiencyScore'].mean():.2f})")
        plt.colorbar(im, ax=ax, fraction=0.04, label="EfficiencyScore (0–1)")
        # Annotate scores
        for _, r in sub.iterrows():
            score = r["EfficiencyScore"]
            if not np.isnan(score):
                color = "white" if score < 0.5 else "black"
                ax.text(r["DieCol"], r["DieRow"], f"{score:.2f}",
                        ha="center", va="center", fontsize=7, color=color)

    # Hide unused subplots
    for j in range(n, nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")

    fig.suptitle(title, fontsize=12, y=1.0)
    fig.tight_layout()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_sweet_spots(
    sweet_spots: pd.DataFrame,
    output_path: str | Path,
    *,
    title: str = "Sweet-spot map: positions consistently in the top tier",
) -> Path:
    """Plot how many wafers each die position is in the top tier on."""
    import matplotlib.pyplot as plt

    if sweet_spots.empty:
        raise ValueError("No sweet-spot data to plot")

    df = sweet_spots.copy()
    cols = sorted(df["DieCol"].unique())
    rows = sorted(df["DieRow"].unique())
    grid = np.full((len(rows), len(cols)), np.nan)
    grid_score = np.full((len(rows), len(cols)), np.nan)
    for _, r in df.iterrows():
        gc = cols.index(r["DieCol"])
        gr = rows.index(r["DieRow"])
        grid[gr, gc] = r["n_wafers_top"]
        grid_score[gr, gc] = r["mean_score"]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    im = axes[0].imshow(
        grid, origin="lower", cmap="YlOrRd",
        extent=[min(cols) - 0.5, max(cols) + 0.5,
                min(rows) - 0.5, max(rows) + 0.5],
        aspect="equal",
    )
    axes[0].set_xticks(cols)
    axes[0].set_yticks(rows)
    axes[0].set_xlabel("Die Column")
    axes[0].set_ylabel("Die Row")
    axes[0].set_title("# of wafers where this position is in the top tier")
    plt.colorbar(im, ax=axes[0], fraction=0.04)
    for _, r in df.iterrows():
        n_top = int(r["n_wafers_top"])
        marker = "★" if r["is_sweet_spot"] else ""
        axes[0].text(r["DieCol"], r["DieRow"],
                     f"{n_top}\n{marker}",
                     ha="center", va="center", fontsize=7,
                     fontweight="bold" if r["is_sweet_spot"] else "normal")

    im2 = axes[1].imshow(
        grid_score, origin="lower", cmap="RdYlGn", vmin=0, vmax=1,
        extent=[min(cols) - 0.5, max(cols) + 0.5,
                min(rows) - 0.5, max(rows) + 0.5],
        aspect="equal",
    )
    axes[1].set_xticks(cols)
    axes[1].set_yticks(rows)
    axes[1].set_xlabel("Die Column")
    axes[1].set_ylabel("Die Row")
    axes[1].set_title("Mean efficiency score across all wafers")
    plt.colorbar(im2, ax=axes[1], fraction=0.04)
    for _, r in df.iterrows():
        ms = r["mean_score"]
        if not np.isnan(ms):
            axes[1].text(r["DieCol"], r["DieRow"], f"{ms:.2f}",
                         ha="center", va="center", fontsize=7,
                         color="white" if ms < 0.5 else "black")

    fig.suptitle(title, fontsize=12, y=1.02)
    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out
