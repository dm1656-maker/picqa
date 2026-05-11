"""Wafer-map plotting."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from picqa.viz.labels import L


def _draw_wafer_map(
    ax: plt.Axes,
    df: pd.DataFrame,
    metric: str,
    title: str,
    *,
    vmin: float | None = None,
    vmax: float | None = None,
    annotate: bool = True,
) -> None:
    cols = sorted(df["DieCol"].unique())
    rows = sorted(df["DieRow"].unique())
    grid = np.full((len(rows), len(cols)), np.nan)
    for _, r in df.iterrows():
        gc = cols.index(r["DieCol"])
        gr = rows.index(r["DieRow"])
        grid[gr, gc] = r[metric]

    im = ax.imshow(
        grid,
        origin="lower",
        vmin=vmin,
        vmax=vmax,
        cmap="viridis",
        extent=[min(cols) - 0.5, max(cols) + 0.5,
                min(rows) - 0.5, max(rows) + 0.5],
        aspect="equal",
    )
    ax.set_xticks(cols)
    ax.set_yticks(rows)
    ax.set_xlabel(L("die_col"))
    ax.set_ylabel(L("die_row"))
    ax.set_title(title, fontsize=9)
    plt.colorbar(im, ax=ax, fraction=0.04)
    if annotate:
        for _, r in df.iterrows():
            v = r[metric]
            if not np.isnan(v):
                ax.text(
                    r["DieCol"], r["DieRow"], f"{v:.1f}",
                    ha="center", va="center",
                    fontsize=6, color="white",
                )


def plot_wafermap(
    features: pd.DataFrame,
    metric: str,
    output_path: str | Path,
    *,
    title: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
) -> Path:
    """Plot a single wafer-map for one metric (uses all rows in ``features``)."""
    if metric not in features.columns:
        raise KeyError(f"Metric '{metric}' not in DataFrame columns: {list(features.columns)}")

    fig, ax = plt.subplots(figsize=(5.5, 4.8))
    _draw_wafer_map(ax, features, metric, title or metric, vmin=vmin, vmax=vmax)
    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_wafermap_grid(
    features: pd.DataFrame,
    metrics: list[str],
    output_path: str | Path,
    *,
    group_by: list[str] | None = None,
) -> Path:
    """Grid of wafer-maps: rows = groups (e.g. wafer/session), cols = metrics."""
    if group_by is None:
        group_by = ["Wafer", "Session"]
    groups: list[tuple] = sorted({tuple(r[c] for c in group_by) for _, r in features.iterrows()})
    nrows = len(groups)
    ncols = len(metrics)
    if nrows == 0 or ncols == 0:
        raise ValueError("No groups or metrics to plot")

    fig, axes = plt.subplots(nrows, ncols, figsize=(5.5 * ncols, 3.6 * nrows))
    if nrows == 1 and ncols == 1:
        axes = np.array([[axes]])
    elif nrows == 1:
        axes = axes[None, :]
    elif ncols == 1:
        axes = axes[:, None]

    for i, key in enumerate(groups):
        mask = np.ones(len(features), dtype=bool)
        for col, val in zip(group_by, key):
            mask &= (features[col] == val)
        sub = features[mask]
        for j, metric in enumerate(metrics):
            label = " / ".join(str(v) for v in key)
            _draw_wafer_map(axes[i, j], sub, metric, f"{label}: {metric}")

    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_fwhm_wafermap(
    fwhm_df: pd.DataFrame,
    output_path: str | Path,
    *,
    title: str | None = None,
    show_q: bool = True,
    per_band_scale: bool = True,
) -> Path:
    """Wafer map of FWHM (and optionally Q-factor) per (Wafer, Band).

    Each row of the grid is one (Wafer, Band) combination. The first
    column shows FWHM (smaller = sharper, plotted with reversed
    colormap so darker = better). If ``show_q`` is True, the second
    column shows Q-factor (larger = sharper).

    ``per_band_scale=True`` colour-scales each panel within its own
    (Wafer, Band) range; setting it to False applies one global scale
    so cross-wafer comparison is direct.
    """
    df = fwhm_df.dropna(subset=["FWHM_nm", "DieCol", "DieRow"]).copy()
    if df.empty:
        raise ValueError("No FWHM data with valid die positions")

    if "Band" not in df.columns:
        df["Band"] = ""
    groups = sorted({(w, b if isinstance(b, str) else "")
                     for w, b in zip(df["Wafer"], df["Band"])})
    nrows = len(groups)
    ncols = 2 if show_q else 1

    fig, axes = plt.subplots(nrows, ncols, figsize=(6.0 * ncols, 4.0 * nrows))
    if nrows == 1 and ncols == 1:
        axes = np.array([[axes]])
    elif nrows == 1:
        axes = axes[None, :]
    elif ncols == 1:
        axes = axes[:, None]

    # Pre-compute global vmin/vmax if not per-band
    fwhm_vmin = fwhm_vmax = q_vmin = q_vmax = None
    if not per_band_scale:
        fwhm_vmin = float(df["FWHM_nm"].quantile(0.05))
        fwhm_vmax = float(df["FWHM_nm"].quantile(0.95))
        if show_q and "Q_factor" in df.columns:
            q_vmin = float(df["Q_factor"].quantile(0.05))
            q_vmax = float(df["Q_factor"].quantile(0.95))

    for i, (wafer, band) in enumerate(groups):
        sub = df[(df["Wafer"] == wafer) & (df["Band"] == band)]
        band_label = f"{band}-band" if band else ""
        label = f"{wafer} ({band_label})" if band else wafer

        # --- FWHM panel ---
        if per_band_scale and not sub.empty:
            local_vmin = float(sub["FWHM_nm"].min())
            local_vmax = float(sub["FWHM_nm"].max())
        else:
            local_vmin, local_vmax = fwhm_vmin, fwhm_vmax

        cols = sorted(sub["DieCol"].unique())
        rows = sorted(sub["DieRow"].unique())
        grid = np.full((len(rows), len(cols)), np.nan)
        for _, r in sub.iterrows():
            gc = cols.index(r["DieCol"])
            gr = rows.index(r["DieRow"])
            grid[gr, gc] = r["FWHM_nm"]

        ax = axes[i, 0]
        # Use viridis_r so smaller (better) FWHM is darker green/blue
        im = ax.imshow(
            grid, origin="lower", cmap="viridis_r",
            vmin=local_vmin, vmax=local_vmax,
            extent=[min(cols) - 0.5, max(cols) + 0.5,
                    min(rows) - 0.5, max(rows) + 0.5],
            aspect="equal",
        )
        ax.set_xticks(cols)
        ax.set_yticks(rows)
        ax.set_xlabel(L("die_col"))
        ax.set_ylabel(L("die_row"))
        median_fwhm = sub["FWHM_nm"].median()
        ax.set_title(f"FWHM (nm)  -  {label}  (median = {median_fwhm:.3f} nm)",
                     fontsize=10)
        plt.colorbar(im, ax=ax, fraction=0.04, label="FWHM (nm)")
        # Annotate cells
        for _, r in sub.iterrows():
            v = r["FWHM_nm"]
            if not np.isnan(v):
                # In viridis_r the bright (yellow) end is the SMALL value
                norm_v = ((v - local_vmin) / (local_vmax - local_vmin)
                          if local_vmax > local_vmin else 0.5)
                # Bright yellow background (norm < 0.3) → black text;
                # mid range → black for readability; very dark (norm > 0.8) → white
                if norm_v > 0.7:
                    color = "white"
                else:
                    color = "black"
                ax.text(r["DieCol"], r["DieRow"], f"{v:.2f}",
                        ha="center", va="center", fontsize=7,
                        color=color, fontweight="bold")

        # --- Q-factor panel ---
        if show_q and "Q_factor" in sub.columns:
            ax = axes[i, 1]
            if per_band_scale and not sub.empty:
                lq_min = float(sub["Q_factor"].min())
                lq_max = float(sub["Q_factor"].max())
            else:
                lq_min, lq_max = q_vmin, q_vmax

            qgrid = np.full((len(rows), len(cols)), np.nan)
            for _, r in sub.iterrows():
                gc = cols.index(r["DieCol"])
                gr = rows.index(r["DieRow"])
                qgrid[gr, gc] = r["Q_factor"]
            # Use viridis (regular) so larger (better) Q is brighter
            im = ax.imshow(
                qgrid, origin="lower", cmap="viridis",
                vmin=lq_min, vmax=lq_max,
                extent=[min(cols) - 0.5, max(cols) + 0.5,
                        min(rows) - 0.5, max(rows) + 0.5],
                aspect="equal",
            )
            ax.set_xticks(cols)
            ax.set_yticks(rows)
            ax.set_xlabel(L("die_col"))
            ax.set_ylabel(L("die_row"))
            median_q = sub["Q_factor"].median()
            ax.set_title(f"Q-factor  -  {label}  (median = {median_q:.0f})",
                         fontsize=10)
            plt.colorbar(im, ax=ax, fraction=0.04, label="Q-factor")
            for _, r in sub.iterrows():
                v = r["Q_factor"]
                if not np.isnan(v):
                    norm_v = ((v - lq_min) / (lq_max - lq_min)
                              if lq_max > lq_min else 0.5)
                    # viridis: dark=low, yellow=high. Black text on
                    # bright cells, white on dark.
                    color = "black" if norm_v > 0.7 else "white"
                    ax.text(r["DieCol"], r["DieRow"], f"{v:.0f}",
                            ha="center", va="center", fontsize=7,
                            color=color, fontweight="bold")

    if title is None:
        title = "FWHM and Q-factor wafer maps" if show_q \
                else "FWHM wafer maps"
    fig.suptitle(title, fontsize=12, y=1.0)
    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


# Direction = "min" or "max", indicating the better direction for the metric.
# Used to choose colormap (so that "good" is always brighter/yellow).
METRIC_DIRECTIONS: dict[str, str] = {
    "FSR_nm": "max",
    "dLambda_dV_pm_per_V": "min_abs",  # wants large |slope|; we'll abs() first
    "PeakIL_dB": "max",                 # 0 (less negative) is better
    "I_at_-1V_pA": "min_abs",           # less leakage is better
    "Vpi_V": "min",                     # lower Vπ is better
    "Vpi_L_V_cm": "min",
    "ER_at_-2V_dB": "max",              # higher ER is better
    "ER_at_0V_dB": "max",
    "Q_factor": "max",
    "FWHM_nm": "min",
    "EfficiencyScore": "max",
}

# Friendly label for plot titles. Falls back to the raw column name.
METRIC_LABELS: dict[str, str] = {
    "FSR_nm": "FSR (nm)",
    "dLambda_dV_pm_per_V": "|dλ/dV| (pm/V)",
    "PeakIL_dB": "Peak IL (dB)",
    "I_at_-1V_pA": "|I @ -1V| (pA)",
    "Vpi_V": "Vπ (V)",
    "Vpi_L_V_cm": "Vπ·L (V·cm)",
    "ER_at_-2V_dB": "ER @ -2V (dB)",
    "ER_at_0V_dB": "ER @ 0V (dB)",
    "Q_factor": "Q-factor",
    "FWHM_nm": "FWHM (nm)",
    "EfficiencyScore": "Efficiency Score",
}


def _direction_for_metric(metric: str) -> str:
    """Look up the direction; default to 'max' if unknown."""
    return METRIC_DIRECTIONS.get(metric, "max")


def _cmap_for_direction(direction: str):
    """Return the colormap so that BRIGHT = GOOD regardless of direction."""
    import matplotlib.pyplot as plt
    if direction in ("max", "max_abs"):
        return plt.get_cmap("viridis")        # bright = high = good
    else:  # min, min_abs
        return plt.get_cmap("viridis_r")      # bright = low = good


def _values_for_metric(series: pd.Series, direction: str) -> pd.Series:
    """Apply abs() if direction is min_abs / max_abs."""
    if direction in ("min_abs", "max_abs"):
        return series.abs()
    return series


def plot_metric_wafermap(
    df: pd.DataFrame,
    metric: str,
    output_path: str | Path,
    *,
    title: str | None = None,
    direction: str | None = None,
    per_band_scale: bool = True,
    annotate: bool = True,
    annotate_format: str | None = None,
    ncols: int = 3,
) -> Path:
    """Wafer maps of a single metric, one panel per (Wafer, Band).

    Parameters
    ----------
    df : DataFrame
        Must include columns: ``Wafer``, ``DieCol``, ``DieRow``, plus
        ``metric``. ``Band`` is used if present.
    metric : str
        Column name to map (e.g. ``"Vpi_V"``, ``"Q_factor"``).
    direction : str | None
        ``"min"``, ``"max"``, ``"min_abs"``, or ``"max_abs"``. If None,
        looked up from :data:`METRIC_DIRECTIONS`.
    per_band_scale : bool
        ``True`` (default) gives each panel its own colour scale so
        within-wafer variation is always visible. ``False`` uses one
        global scale so absolute differences are directly comparable.
    annotate : bool
        Print the value in each cell.
    annotate_format : str | None
        Format string for cell labels (e.g. ``"{:.2f}"`` or ``"{:.0f}"``).
        Auto-picked from the metric range if None.
    """
    import matplotlib.pyplot as plt

    if metric not in df.columns:
        raise KeyError(f"Metric '{metric}' not in DataFrame")
    if direction is None:
        direction = _direction_for_metric(metric)
    label = METRIC_LABELS.get(metric, metric)
    cmap = _cmap_for_direction(direction)

    work = df.dropna(subset=[metric, "DieCol", "DieRow"]).copy()
    if work.empty:
        raise ValueError(f"No valid {metric} values with die positions")
    work["_value"] = _values_for_metric(work[metric], direction)

    if "Band" in work.columns:
        groups = sorted({(w, b if isinstance(b, str) else "")
                         for w, b in zip(work["Wafer"], work["Band"])})
    else:
        groups = [(w, "") for w in sorted(work["Wafer"].unique())]

    n = len(groups)
    ncols = min(ncols, n)
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(5.5 * ncols, 4.0 * nrows),
                             squeeze=False)

    # Choose annotation format from value range
    if annotate_format is None:
        rng = work["_value"].max() - work["_value"].min()
        if rng > 1000:
            annotate_format = "{:.0f}"
        elif rng > 10:
            annotate_format = "{:.1f}"
        elif rng > 1:
            annotate_format = "{:.2f}"
        else:
            annotate_format = "{:.3f}"

    # Global scale if requested
    g_vmin = float(work["_value"].quantile(0.05)) if not per_band_scale else None
    g_vmax = float(work["_value"].quantile(0.95)) if not per_band_scale else None

    for i, key in enumerate(groups):
        ax = axes[i // ncols][i % ncols]
        wafer, band = key
        if "Band" in work.columns and band:
            sub = work[(work["Wafer"] == wafer) & (work["Band"] == band)]
        else:
            sub = work[work["Wafer"] == wafer]
        if sub.empty:
            ax.axis("off")
            continue

        if per_band_scale:
            vmin = float(sub["_value"].min())
            vmax = float(sub["_value"].max())
            # Avoid degenerate range
            if vmax == vmin:
                vmax = vmin + 1e-9
        else:
            vmin, vmax = g_vmin, g_vmax

        cols = sorted(sub["DieCol"].unique())
        rows = sorted(sub["DieRow"].unique())
        grid = np.full((len(rows), len(cols)), np.nan)
        for _, r in sub.iterrows():
            gc = cols.index(r["DieCol"])
            gr = rows.index(r["DieRow"])
            grid[gr, gc] = r["_value"]

        im = ax.imshow(
            grid, origin="lower", cmap=cmap, vmin=vmin, vmax=vmax,
            extent=[min(cols) - 0.5, max(cols) + 0.5,
                    min(rows) - 0.5, max(rows) + 0.5],
            aspect="equal",
        )
        ax.set_xticks(cols)
        ax.set_yticks(rows)
        ax.set_xlabel("Die Column")
        ax.set_ylabel("Die Row")
        median_val = sub["_value"].median()
        band_label = f"{band}-band" if band else ""
        wlabel = f"{wafer} ({band_label})" if band else wafer
        ax.set_title(f"{wlabel}  (median = {annotate_format.format(median_val)})",
                     fontsize=10)
        plt.colorbar(im, ax=ax, fraction=0.04, label=label)

        if annotate:
            for _, r in sub.iterrows():
                v = r["_value"]
                if not np.isnan(v):
                    norm_v = ((v - vmin) / (vmax - vmin)
                              if vmax > vmin else 0.5)
                    # bright (norm > 0.7) → black; dark → white
                    color = "black" if norm_v > 0.7 else "white"
                    ax.text(r["DieCol"], r["DieRow"],
                            annotate_format.format(v),
                            ha="center", va="center", fontsize=7,
                            color=color, fontweight="bold")

    # Hide unused subplots
    for j in range(n, nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")

    if title is None:
        direction_str = {"max": "↑ better", "min": "↓ better",
                         "max_abs": "|·| ↑ better", "min_abs": "|·| ↓ better"}.get(direction, "")
        title = f"Wafer maps — {label}  ({direction_str})"
    fig.suptitle(title, fontsize=12, y=1.0)
    fig.tight_layout()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_all_metric_wafermaps(
    df: pd.DataFrame,
    output_dir: str | Path,
    *,
    metrics: list[str] | None = None,
    per_band_scale: bool = True,
) -> dict[str, Path]:
    """Render a wafer-map figure for every metric in `metrics`.

    Returns ``{metric: Path}``. Skips any metric not in the DataFrame.
    Default ``metrics`` covers the full quality set (Vπ, ER, IL, leakage,
    Q, FWHM, FSR, dλ/dV).
    """
    if metrics is None:
        metrics = [
            "Vpi_V", "ER_at_-2V_dB", "PeakIL_dB", "I_at_-1V_pA",
            "Q_factor", "FWHM_nm", "FSR_nm", "dLambda_dV_pm_per_V",
            "Vpi_L_V_cm",
        ]

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for m in metrics:
        if m not in df.columns or df[m].notna().sum() == 0:
            continue
        try:
            paths[m] = plot_metric_wafermap(
                df, m, out_dir / f"wafermap_{m}.png",
                per_band_scale=per_band_scale,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Wafer map for %s skipped: %s", m, exc,
            )
    return paths
