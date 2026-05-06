"""Plots for PN modulator characterisation."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from picqa.viz.labels import L


def plot_pn_length_dependence(
    segment_features: pd.DataFrame,
    output_path: str | Path,
    *,
    title: str = "PN modulator length dependence",
) -> Path:
    """Two panels: IL_drop vs length (left) and dIL/dV vs length (right).

    Each die is one line; wafers are color-coded.
    """
    df = segment_features.dropna(subset=["Length_um"]).copy()
    if df.empty:
        raise ValueError("No PN segment features to plot")

    wafers = sorted(df["Wafer"].dropna().unique())
    cmap = plt.get_cmap("tab10")
    color_map = {w: cmap(i % 10) for i, w in enumerate(wafers)}

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    for keys, sub in df.groupby(["Wafer", "Session", "Die"]):
        sub = sub.sort_values("Length_um")
        wafer = sub.iloc[0]["Wafer"]
        color = color_map[wafer]
        axes[0].plot(sub["Length_um"], sub["IL_drop_vs_REF_dB"],
                     color=color, alpha=0.4, lw=0.7, marker="o", ms=3)
        axes[1].plot(sub["Length_um"], sub["dIL_dV_dB_per_V"],
                     color=color, alpha=0.4, lw=0.7, marker="o", ms=3)

    # Per-wafer mean trend lines
    for wafer in wafers:
        wsub = df[df["Wafer"] == wafer]
        means = wsub.groupby("Length_um")[["IL_drop_vs_REF_dB",
                                           "dIL_dV_dB_per_V"]].mean().reset_index()
        axes[0].plot(means["Length_um"], means["IL_drop_vs_REF_dB"],
                     color=color_map[wafer], lw=2.5, marker="s", ms=7,
                     label=f"{wafer} mean")
        axes[1].plot(means["Length_um"], means["dIL_dV_dB_per_V"],
                     color=color_map[wafer], lw=2.5, marker="s", ms=7,
                     label=f"{wafer} mean")

    axes[0].set_xlabel(L("length_um"))
    axes[0].set_ylabel(L("il_drop_vs_ref"))
    axes[0].set_title(L("pn_il_drop_title"))
    axes[0].grid(alpha=0.3)
    axes[0].legend(fontsize=8, loc="lower left")

    axes[1].set_xlabel(L("length_um"))
    axes[1].set_ylabel(L("dil_dv"))
    axes[1].set_title(L("pn_modulation_title"))
    axes[1].grid(alpha=0.3)
    axes[1].legend(fontsize=8, loc="upper left")

    fig.suptitle(title, fontsize=12, y=1.02)
    fig.tight_layout()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_pn_summary(
    length_fit: pd.DataFrame,
    output_path: str | Path,
    *,
    title: str = "PN modulator process characterisation",
) -> Path:
    """Three panels: loss boxplot per wafer, modulation eff boxplot, trade-off scatter."""
    df = length_fit.copy()
    # Mark working / failed dies (very low modulation efficiency = failed contact)
    df["IsWorking"] = df["Modulation_per_um_dB_per_V_per_um"].abs().fillna(0) > 5e-6

    wafers = sorted(df["Wafer"].dropna().unique())

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5))

    # (a) Loss per wafer (working only) — dB/cm
    data, labels = [], []
    for w in wafers:
        sub = df[(df["Wafer"] == w) & df["IsWorking"]]
        if len(sub):
            # multiply by 1e4 to get dB/cm
            data.append(np.abs(sub["Loss_per_um_dB_per_um"].dropna().values) * 1e4)
            labels.append(f"{w}\n(n={len(sub)})")
    if data:
        axes[0].boxplot(data, tick_labels=labels, showmeans=True)
    axes[0].set_ylabel("|Doping loss| (dB/cm)")
    axes[0].set_title("PN doping loss (working dies)")
    axes[0].grid(alpha=0.3)

    # (b) Modulation efficiency boxplot — dB/V/mm
    data, labels = [], []
    for w in wafers:
        sub = df[(df["Wafer"] == w) & df["IsWorking"]]
        if len(sub):
            data.append(np.abs(sub["Modulation_per_um_dB_per_V_per_um"].dropna().values) * 1e3)
            labels.append(f"{w}\n(n={len(sub)})")
    if data:
        axes[1].boxplot(data, tick_labels=labels, showmeans=True)
    axes[1].set_ylabel("|Modulation efficiency| (dB/V/mm)")
    axes[1].set_title("Electroabsorption modulation efficiency")
    axes[1].grid(alpha=0.3)

    # (c) Trade-off scatter
    markers = ["o", "s", "^", "D", "v", "P", "X"]
    for w, marker in zip(wafers, markers):
        sub = df[(df["Wafer"] == w) & df["IsWorking"]]
        if len(sub):
            axes[2].scatter(
                np.abs(sub["Loss_per_um_dB_per_um"]) * 1e4,
                np.abs(sub["Modulation_per_um_dB_per_V_per_um"]) * 1e3,
                marker=marker, alpha=0.7, s=40, label=w,
            )
    axes[2].set_xlabel("|Loss| (dB/cm)")
    axes[2].set_ylabel("|Modulation efficiency| (dB/V/mm)")
    axes[2].set_title("Loss-modulation trade-off")
    axes[2].grid(alpha=0.3)
    axes[2].legend(fontsize=8)

    fig.suptitle(title, fontsize=12, y=1.02)
    fig.tight_layout()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out
