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
