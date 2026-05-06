"""Plots for projects 1 (uniformity) and 2 (V-phi)."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from picqa.analysis.phase_extraction import vphi_trace
from picqa.analysis.wafer_uniformity import add_radius_column
from picqa.io.schemas import Measurement
from picqa.viz.labels import L


# --------------------------------------------------------------------- #
# V-λ (Voltage vs notch wavelength shift) — single-panel detailed view
# --------------------------------------------------------------------- #
def plot_v_lambda(
    measurement: Measurement,
    output_path: str | Path,
    *,
    title: str | None = None,
) -> Path:
    """V-λ plot: voltage vs notch wavelength shift Δλ.

    Each measured DC bias is plotted as a point; a linear fit gives the
    tuning slope dλ/dV. The slope is the **wavelength modulation
    efficiency** (nm/V) — steeper slopes mean less voltage is needed to
    move the notch by a given amount.
    """
    df = vphi_trace(measurement)
    if df.empty:
        raise ValueError("Cannot build V-λ trace (no notches found)")

    biases = df["Bias_V"].to_numpy(dtype=float)
    notches = df["Notch_nm"].to_numpy(dtype=float)
    # Reference Δλ to the bias closest to 0 V
    ref_idx = int(np.argmin(np.abs(biases)))
    delta_lambda_pm = (notches - notches[ref_idx]) * 1000.0  # nm → pm

    # Linear fit
    slope_pm_per_v, intercept_pm = np.polyfit(biases, delta_lambda_pm, 1)
    slope_nm_per_v = slope_pm_per_v / 1000.0

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    ax.plot(biases, delta_lambda_pm, "o", color="tab:blue", markersize=9,
            markeredgecolor="navy", label=L("measured"))
    bs = np.linspace(biases.min() - 0.1, biases.max() + 0.1, 100)
    ax.plot(bs, slope_pm_per_v * bs + intercept_pm, "--", color="tab:red", lw=1.6,
            label=f"{L('linear_fit')}: slope = {slope_nm_per_v*1000:.2f} pm/V")

    # Annotate every measured point with its bias and Δλ
    for V, dL in zip(biases, delta_lambda_pm):
        ax.annotate(f"({V:+.1f}V, {dL:+.0f}pm)",
                    xy=(V, dL),
                    xytext=(6, 6), textcoords="offset points",
                    fontsize=8, color="navy")

    ax.axhline(0, color="gray", lw=0.5)
    ax.axvline(0, color="gray", lw=0.5)
    ax.set_xlabel(L("voltage"), fontsize=11)
    ax.set_ylabel(L("wavelength_shift_pm"), fontsize=11)
    band_str = f" {measurement.band}-band" if measurement.band else ""
    if title is None:
        title = L("vlambda_title",
                  wafer=measurement.wafer, die=measurement.die, band=band_str)
    ax.set_title(title, fontsize=12)

    # Stats box in lower-right corner
    eff_text = (
        f"{L('modulation_eff')}\n"
        f"  |dλ/dV| = {abs(slope_nm_per_v)*1000:.1f} pm/V\n"
        f"  = {abs(slope_nm_per_v):.4f} nm/V"
    )
    ax.text(0.98, 0.04, eff_text, transform=ax.transAxes,
            fontsize=9, ha="right", va="bottom",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#FFFACD",
                      edgecolor="gray", alpha=0.9))
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.3)

    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


# --------------------------------------------------------------------- #
# Project 2: V-phi curve
# --------------------------------------------------------------------- #
def plot_vphi_curve(
    measurement: Measurement,
    output_path: str | Path,
    *,
    title: str | None = None,
) -> Path:
    """Plot V vs Δφ for a single MZM die, with linear fit and Vπ marked."""
    df = vphi_trace(measurement)
    if df.empty:
        raise ValueError("Cannot build V-phi trace (no notches found)")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))

    # Left panel: notch wavelength vs bias
    axes[0].plot(df["Bias_V"], df["Notch_nm"], "o-", lw=1.5, ms=6)
    slope, intercept = np.polyfit(df["Bias_V"], df["Notch_nm"], 1)
    bs = np.linspace(df["Bias_V"].min(), df["Bias_V"].max(), 50)
    axes[0].plot(bs, slope * bs + intercept, "--",
                 alpha=0.6, label=f"slope = {slope*1000:.1f} pm/V")
    axes[0].set_xlabel(L("voltage"))
    axes[0].set_ylabel(L("tracked_notch_nm"))
    axes[0].set_title(L("notch_shift_vs_bias"))
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    # Right panel: phase shift vs bias, with Vπ
    axes[1].plot(df["Bias_V"], df["dPhi_over_pi"], "o-", lw=1.5, ms=6,
                 color="tab:orange")
    s, b = np.polyfit(df["Bias_V"], df["dPhi_over_pi"], 1)
    axes[1].plot(bs, s * bs + b, "--", alpha=0.6, color="tab:orange")
    axes[1].axhline(0, color="gray", lw=0.5)
    axes[1].axhline(1, color="green", lw=0.7, ls=":", label="Δφ = π")
    axes[1].axhline(-1, color="green", lw=0.7, ls=":")
    if abs(s) > 1e-9:
        vpi = abs(1.0 / s)
        axes[1].set_title(L("vphi_relation", vpi=vpi))
    else:
        axes[1].set_title(L("vphi_relation", vpi=float("nan")))
    axes[1].set_xlabel(L("voltage"))
    axes[1].set_ylabel(L("phase_shift_over_pi"))
    axes[1].legend()
    axes[1].grid(alpha=0.3)

    if title is None:
        band_str = f" {measurement.band}-band" if measurement.band else ""
        title = L("vphi_title",
                  wafer=measurement.wafer, die=measurement.die, band=band_str)
    fig.suptitle(title, fontsize=12, y=1.01)
    fig.tight_layout()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_vpi_distribution(
    features_with_phase: pd.DataFrame,
    output_path: str | Path,
    *,
    title: str | None = None,
) -> Path:
    """Box plot of Vπ per wafer (working dies only) plus a Vπ·L scatter."""
    df = features_with_phase.copy()
    if "FailedContact" in df.columns:
        df = df[~df["FailedContact"]]
    df = df.dropna(subset=["Vpi_V"])

    if df.empty:
        raise ValueError("No working dies with valid Vπ found")

    if title is None:
        title = L("vpi_distribution_title")

    wafers = sorted(df["Wafer"].dropna().unique())
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))

    # (a) Vπ box plot
    data, labels = [], []
    for w in wafers:
        sub = df[df["Wafer"] == w]
        if len(sub):
            data.append(sub["Vpi_V"].values)
            labels.append(f"{w}\n({L('n_dies', n=len(sub))})")
    axes[0].boxplot(data, tick_labels=labels, showmeans=True)
    axes[0].set_ylabel("Vπ (V)")
    axes[0].set_title(L("vpi_per_wafer"))
    axes[0].grid(alpha=0.3)

    # (b) Vπ vs Vπ·L scatter
    if "Vpi_L_V_cm" in df.columns and df["Vpi_L_V_cm"].notna().any():
        for w in wafers:
            sub = df[df["Wafer"] == w]
            axes[1].scatter(sub["Vpi_V"], sub["Vpi_L_V_cm"],
                            alpha=0.7, s=40, label=w)
        axes[1].set_xlabel("Vπ (V)")
        axes[1].set_ylabel(L("vpi_l_vcm"))
        axes[1].set_title(L("vpi_l_fom"))
        axes[1].legend()
        axes[1].grid(alpha=0.3)
    else:
        if "ER_at_-2V_dB" in df.columns:
            for w in wafers:
                sub = df[df["Wafer"] == w]
                axes[1].scatter(sub["Vpi_V"], sub["ER_at_-2V_dB"],
                                alpha=0.7, s=40, label=w)
            axes[1].set_xlabel("Vπ (V)")
            axes[1].set_ylabel("ER @ -2 V (dB)")
            axes[1].set_title("Vπ vs Extinction Ratio")
            axes[1].legend()
            axes[1].grid(alpha=0.3)

    fig.suptitle(title, fontsize=12, y=1.02)
    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


# --------------------------------------------------------------------- #
# Project 1: uniformity
# --------------------------------------------------------------------- #
def plot_radial_dependence(
    features: pd.DataFrame,
    metric: str,
    output_path: str | Path,
    *,
    title: str | None = None,
) -> Path:
    """Scatter of metric vs die radius, color-coded by wafer.

    Adds a per-wafer mean line at each integer-rounded radius.
    """
    if metric not in features.columns:
        raise KeyError(metric)

    df = add_radius_column(features)
    if "FailedContact" in df.columns:
        df = df[~df["FailedContact"]]
    df = df.dropna(subset=[metric, "Radius"])
    if df.empty:
        raise ValueError(f"No data for {metric}")

    wafers = sorted(df["Wafer"].dropna().unique())
    cmap = plt.get_cmap("tab10")
    color_of = {w: cmap(i % 10) for i, w in enumerate(wafers)}

    fig, ax = plt.subplots(figsize=(9, 5))

    for w in wafers:
        sub = df[df["Wafer"] == w]
        ax.scatter(sub["Radius"], sub[metric], color=color_of[w],
                   alpha=0.45, s=40, label=f"{w} (n={len(sub)})")
        # Per-radius mean trendline
        means = sub.groupby(sub["Radius"].round())[metric].mean()
        ax.plot(means.index, means.values, "-", color=color_of[w], lw=2)

    ax.set_xlabel("Die radius (units of die spacing)")
    ax.set_ylabel(metric)
    ax.set_title(title or f"{metric} vs wafer radius")
    ax.legend(fontsize=8, loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_center_vs_edge(
    features: pd.DataFrame,
    metrics: list[str],
    output_path: str | Path,
    *,
    edge_radius: float = 2.5,
    title: str = "Center vs edge comparison",
) -> Path:
    """Side-by-side boxplot pairs (center vs edge) for several metrics."""
    df = features.copy()
    if "FailedContact" in df.columns:
        df = df[~df["FailedContact"]]
    df = add_radius_column(df)
    df["Region"] = np.where(df["Radius"] <= edge_radius, "center", "edge")

    n = len(metrics)
    fig, axes = plt.subplots(1, n, figsize=(4.0 * n, 4.4))
    if n == 1:
        axes = [axes]

    for ax, metric in zip(axes, metrics):
        if metric not in df.columns:
            ax.set_title(f"{metric}\n(missing)")
            continue
        center = df[df["Region"] == "center"][metric].dropna()
        edge = df[df["Region"] == "edge"][metric].dropna()
        ax.boxplot([center.values, edge.values],
                   tick_labels=[f"center\n(n={len(center)})",
                                f"edge\n(n={len(edge)})"],
                   showmeans=True)
        ax.set_ylabel(metric)
        ax.set_title(metric)
        ax.grid(alpha=0.3)

    fig.suptitle(title, fontsize=12, y=1.02)
    fig.tight_layout()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out
