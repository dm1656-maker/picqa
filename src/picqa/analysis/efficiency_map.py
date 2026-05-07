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

from picqa.viz.labels import L


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
    "Q_factor": "max",                  # sharper resonance is better
    "FWHM_nm": "min",                   # narrower FWHM is better
}


# Default metric weights. These can be overridden by the caller. Sum need not
# equal 1; results are normalised at the end. Note: Q_factor and FWHM_nm are
# strongly correlated (Q = λ/FWHM, so they encode the same information),
# therefore only Q_factor is given weight by default. Including both would
# effectively double-count spectral selectivity.
DEFAULT_WEIGHTS: dict[str, float] = {
    "Vpi_V": 2.0,                       # most important: actual modulation strength
    "ER_at_-2V_dB": 1.5,                # extinction ratio is core spec
    "PeakIL_dB": 1.0,                   # insertion loss
    "I_at_-1V_pA": 1.0,                 # leakage / contact quality
    "Q_factor": 0.75,                   # spectral selectivity (FWHM-derived)
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
    score_column: str = "EfficiencyScore",
    threshold_pct: float = 75.0,
    min_consistency: int = 2,
    higher_is_better: bool = True,
) -> pd.DataFrame:
    """Find die positions that are consistently good across all wafers.

    A "sweet spot" is a (DieCol, DieRow) where ``score_column`` lands in the
    top ``threshold_pct`` percentile on at least ``min_consistency`` wafers.
    This identifies positions where the process consistently produces good
    devices, not just lucky individual wafers.

    Parameters
    ----------
    score_column : str
        Which column to rank by. Defaults to ``"EfficiencyScore"`` (the
        composite metric); can be set to ``"Q_factor"``, ``"FWHM_nm"``,
        ``"Vpi_V"`` etc. for axis-specific analysis.
    higher_is_better : bool
        ``True`` (default) treats larger values as better (top tier). Set
        to ``False`` for metrics like FWHM, Vπ, leakage where smaller is
        better — the function will then look for the BOTTOM ``threshold_pct``
        percentile instead.
    """
    if score_column not in scored.columns:
        raise KeyError(f"Column '{score_column}' not in scored DataFrame; "
                       f"run compute_efficiency_score first or pass a "
                       f"valid metric column")

    df = scored.dropna(subset=[score_column]).copy()
    if df.empty:
        return pd.DataFrame()

    # Per-wafer percentile rank
    df["_RankPct"] = (
        df.groupby("Wafer")[score_column]
          .transform(lambda s: s.rank(pct=True) * 100)
    )
    if higher_is_better:
        df["IsTop"] = df["_RankPct"] >= threshold_pct
    else:
        # Bottom is best — look for the lowest percentile
        df["IsTop"] = df["_RankPct"] <= (100.0 - threshold_pct)

    # Group by die position; count how many wafers have it in the top
    pos_stats = (
        df.groupby(["DieCol", "DieRow"])
          .agg(n_wafers_top=("IsTop", "sum"),
               n_wafers_total=("Wafer", "nunique"),
               mean_score=(score_column, "mean"),
               median_score=(score_column, "median"))
          .reset_index()
    )
    pos_stats["consistency_pct"] = (
        100.0 * pos_stats["n_wafers_top"] / pos_stats["n_wafers_total"]
    )
    pos_stats["is_sweet_spot"] = pos_stats["n_wafers_top"] >= min_consistency
    pos_stats["score_column"] = score_column
    return pos_stats.sort_values(
        ["is_sweet_spot", "n_wafers_top", "mean_score"],
        ascending=[False, False, not higher_is_better],
    )


def find_sweet_spots_multi_metric(
    scored: pd.DataFrame,
    *,
    metrics: list[tuple[str, bool]] | None = None,
    threshold_pct: float = 75.0,
    min_consistency: int = 2,
) -> dict[str, pd.DataFrame]:
    """Run :func:`find_sweet_spots` for several metrics in one call.

    Parameters
    ----------
    metrics : list of (column, higher_is_better) tuples
        Each tuple specifies one analysis. Defaults cover the most useful
        per-axis views: efficiency (high=better), Q-factor (high=better),
        FWHM (low=better), Vπ (low=better).

    Returns
    -------
    dict
        ``{column_name: sweet_spots_df}``. Caller can iterate to render
        per-metric maps or to find positions that are sweet spots in
        multiple axes simultaneously.
    """
    if metrics is None:
        metrics = [
            ("EfficiencyScore", True),
            ("Q_factor", True),
            ("FWHM_nm", False),
            ("Vpi_V", False),
        ]
    out: dict[str, pd.DataFrame] = {}
    for col, higher in metrics:
        if col not in scored.columns:
            continue
        try:
            out[col] = find_sweet_spots(
                scored,
                score_column=col,
                threshold_pct=threshold_pct,
                min_consistency=min_consistency,
                higher_is_better=higher,
            )
        except (KeyError, ValueError):
            continue
    return out


def find_combined_sweet_spots(
    multi_sweet: dict[str, pd.DataFrame],
    *,
    min_axes_agreeing: int = 2,
) -> pd.DataFrame:
    """Find die positions that are sweet spots on **multiple axes**.

    Combines per-metric sweet-spot tables to flag positions that are
    consistently good in at least ``min_axes_agreeing`` different
    quality measures (e.g. both Q-factor AND Vπ are top-tier on at
    least 2 wafers each).

    Returns a single DataFrame with columns:
        DieCol, DieRow, n_axes, axes_str, total_n_wafers_top
    sorted so the most multi-axis-strong positions come first.
    """
    if not multi_sweet:
        return pd.DataFrame()

    rows: dict[tuple[int, int], dict] = {}
    for col, df in multi_sweet.items():
        if df.empty or "is_sweet_spot" not in df.columns:
            continue
        sweet = df[df["is_sweet_spot"]]
        for _, r in sweet.iterrows():
            key = (int(r["DieCol"]), int(r["DieRow"]))
            entry = rows.setdefault(key, {
                "DieCol": key[0], "DieRow": key[1],
                "axes": [], "total_n_wafers_top": 0,
            })
            entry["axes"].append(col)
            entry["total_n_wafers_top"] += int(r["n_wafers_top"])

    out_rows = []
    for (col_pos, row_pos), entry in rows.items():
        if len(entry["axes"]) >= min_axes_agreeing:
            out_rows.append({
                "DieCol": entry["DieCol"],
                "DieRow": entry["DieRow"],
                "n_axes": len(entry["axes"]),
                "axes_str": "+".join(sorted(entry["axes"])),
                "total_n_wafers_top": entry["total_n_wafers_top"],
            })

    if not out_rows:
        return pd.DataFrame(columns=["DieCol", "DieRow", "n_axes",
                                      "axes_str", "total_n_wafers_top"])
    return (pd.DataFrame(out_rows)
            .sort_values(["n_axes", "total_n_wafers_top"],
                         ascending=[False, False])
            .reset_index(drop=True))


# ----------------------------------------------------------------------- #
# Visualisation
# ----------------------------------------------------------------------- #
def plot_efficiency_wafermap(
    scored: pd.DataFrame,
    output_path: str | Path,
    *,
    group_by: list[str] | None = None,
    title: str | None = None,
) -> Path:
    """Wafer map of the EfficiencyScore.

    If multiple wafers/bands are present, draws one panel each.
    """
    import matplotlib.pyplot as plt

    if title is None:
        title = L("efficiency_score_title")

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
        ax.set_xlabel(L("die_col"))
        ax.set_ylabel(L("die_row"))
        label = " / ".join(str(v) for v in key)
        ax.set_title(f"{label}  ({L('n_dies', n=len(sub))}, "
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
    title: str | None = None,
) -> Path:
    """Plot how many wafers each die position is in the top tier on."""
    import matplotlib.pyplot as plt

    if title is None:
        title = L("sweet_spot_title")

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
    axes[0].set_xlabel(L("die_col"))
    axes[0].set_ylabel(L("die_row"))
    axes[0].set_title(L("n_wafers_top"))
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
    axes[1].set_xlabel(L("die_col"))
    axes[1].set_ylabel(L("die_row"))
    axes[1].set_title(L("mean_eff_across"))
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


def plot_multi_metric_sweet_spots(
    multi_sweet: dict[str, pd.DataFrame],
    output_path: str | Path,
    *,
    title: str | None = None,
) -> Path:
    """Per-metric sweet-spot maps in one figure (one panel per metric).

    Each panel shows the n_wafers_top heat for that metric and marks
    sweet spots with stars. Useful for comparing axis-specific
    behaviour (e.g. "the Q-factor sweet spots are not the same as
    the Vπ sweet spots").
    """
    import matplotlib.pyplot as plt

    items = [(col, df) for col, df in multi_sweet.items()
             if not df.empty]
    if not items:
        raise ValueError("No sweet-spot data to plot")

    n = len(items)
    ncols = min(2, n)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(6.0 * ncols, 4.5 * nrows),
                             squeeze=False)

    for k, (col, df) in enumerate(items):
        ax = axes[k // ncols][k % ncols]
        cols = sorted(df["DieCol"].unique())
        rows = sorted(df["DieRow"].unique())
        grid = np.full((len(rows), len(cols)), np.nan)
        for _, r in df.iterrows():
            gc = cols.index(r["DieCol"])
            gr = rows.index(r["DieRow"])
            grid[gr, gc] = r["n_wafers_top"]
        im = ax.imshow(grid, origin="lower", cmap="YlOrRd",
                       vmin=0,
                       extent=[min(cols) - 0.5, max(cols) + 0.5,
                               min(rows) - 0.5, max(rows) + 0.5],
                       aspect="equal")
        ax.set_xticks(cols)
        ax.set_yticks(rows)
        ax.set_xlabel(L("die_col"))
        ax.set_ylabel(L("die_row"))
        n_sweet = int(df["is_sweet_spot"].sum())
        ax.set_title(f"{col}  ({n_sweet} sweet spots)", fontsize=10)
        plt.colorbar(im, ax=ax, fraction=0.04, label="# wafers in top tier")

        # Annotate
        for _, r in df.iterrows():
            n_top = int(r["n_wafers_top"])
            marker = "★" if r["is_sweet_spot"] else ""
            label = f"{n_top}\n{marker}" if marker else str(n_top)
            ax.text(r["DieCol"], r["DieRow"], label,
                    ha="center", va="center", fontsize=7,
                    fontweight="bold" if r["is_sweet_spot"] else "normal")

    # Hide unused subplots
    for j in range(n, nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")

    if title is None:
        title = "Per-metric sweet spots — same wafers, different quality axes"
    fig.suptitle(title, fontsize=12, y=1.0)
    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_combined_sweet_spots(
    combined: pd.DataFrame,
    output_path: str | Path,
    *,
    all_die_positions: pd.DataFrame | None = None,
    title: str | None = None,
) -> Path:
    """Single-panel map of multi-axis sweet spots.

    Shows die positions where multiple metrics agree on top-tier
    quality. Cell colour encodes the number of axes that flagged the
    position; cell text lists which axes (e.g. ``Q+Vπ``).

    ``all_die_positions`` is an optional DataFrame with columns
    ``DieCol`` and ``DieRow``; passing it lets the plot include
    blank cells for non-sweet positions, giving a complete wafer
    layout instead of just the sweet-spot subset.
    """
    import matplotlib.pyplot as plt

    if combined.empty:
        # Even with no sweet spots we still want a (mostly empty) figure
        # so the report doesn't break
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.text(0.5, 0.5,
                "(no positions are sweet spots on ≥2 metrics)",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=11, color="gray")
        ax.set_xticks([]); ax.set_yticks([])
        if title:
            ax.set_title(title)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=130, bbox_inches="tight")
        plt.close(fig)
        return out

    # Build the grid
    if all_die_positions is not None and not all_die_positions.empty:
        cols = sorted(all_die_positions["DieCol"].unique())
        rows = sorted(all_die_positions["DieRow"].unique())
        present_positions = {(int(r.DieCol), int(r.DieRow))
                             for r in all_die_positions.itertuples()}
    else:
        cols = sorted(combined["DieCol"].unique())
        rows = sorted(combined["DieRow"].unique())
        present_positions = {(c, r) for c in cols for r in rows}

    grid = np.full((len(rows), len(cols)), np.nan)
    labels: dict[tuple[int, int], str] = {}
    for _, r in combined.iterrows():
        gc = cols.index(r["DieCol"])
        gr = rows.index(r["DieRow"])
        grid[gr, gc] = r["n_axes"]
        # Shorten the axis label for readability
        axes_short = (r["axes_str"]
                      .replace("EfficiencyScore", "Eff")
                      .replace("Q_factor", "Q")
                      .replace("FWHM_nm", "FWHM")
                      .replace("Vpi_V", "Vπ"))
        labels[(int(r["DieCol"]), int(r["DieRow"]))] = axes_short

    fig, ax = plt.subplots(figsize=(7.5, 6.0))
    vmax = max(2, int(np.nanmax(grid)) if np.isfinite(np.nanmax(grid)) else 2)
    im = ax.imshow(grid, origin="lower", cmap="YlOrRd",
                   vmin=2, vmax=vmax,
                   extent=[min(cols) - 0.5, max(cols) + 0.5,
                           min(rows) - 0.5, max(rows) + 0.5],
                   aspect="equal")
    ax.set_xticks(cols)
    ax.set_yticks(rows)
    ax.set_xlabel(L("die_col"))
    ax.set_ylabel(L("die_row"))
    plt.colorbar(im, ax=ax, fraction=0.045, ticks=range(2, vmax + 1),
                 label="# of metrics where this position is sweet")

    # Annotate cells
    for (c, r), text in labels.items():
        ax.text(c, r, "★\n" + text,
                ha="center", va="center", fontsize=8,
                fontweight="bold")

    # Lightly mark all measured positions that aren't sweet
    for c, r in present_positions:
        if (c, r) not in labels:
            ax.plot(c, r, ".", color="lightgray", markersize=3, zorder=1)

    if title is None:
        title = ("Combined sweet spots — positions strong on multiple "
                 "quality axes")
    ax.set_title(title, fontsize=11)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out
