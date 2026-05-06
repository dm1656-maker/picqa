"""FWHM and Q-factor visualisation.

Two plot kinds:

1. ``plot_fwhm_annotated`` — single-die spectrum with the FWHM clearly
   marked on the chosen peak. Mirrors the textbook "FWHM at -3 dB"
   illustration: peak line, half-max line, vertical edges, FWHM arrow.

2. ``plot_q_factor_distribution`` — population-level summary across
   wafers (box plot of Q per wafer + scatter of FWHM vs Q).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyArrowPatch

from picqa.analysis.fwhm import _flatten_envelope, fwhm_of_peak
from picqa.io.schemas import Measurement


def plot_fwhm_annotated(
    measurement: Measurement,
    output_path: str | Path,
    *,
    bias_v: float = -2.0,
    feature: str = "peak",
    drop_db: float = 3.0,
    flatten: bool = True,
    title: str | None = None,
) -> Path:
    """Plot one die's spectrum with the FWHM measurement annotated.

    Reproduces the textbook illustration: peak line, half-max line at
    -3 dB, vertical dashed edges marking the crossing points, and a
    horizontal arrow labelled ``FWHM = X.XX nm``.

    Parameters
    ----------
    feature : {"peak", "notch"}
        Whether to measure the highest peak or the deepest notch.
    drop_db : float
        How far below the peak to measure the width (3.0 = -3 dB FWHM).
    flatten : bool
        Subtract the grating-coupler envelope first (default True). If
        False the raw transmission is used.
    """
    sw = measurement.sweep_at_bias(bias_v)
    if sw is None:
        raise ValueError(f"No sweep at bias {bias_v} V")

    wl = sw.wavelength_nm
    il_raw = sw.insertion_loss_db
    il = _flatten_envelope(wl, il_raw) if flatten else il_raw.copy()

    target = measurement.design_wavelength_nm
    result = fwhm_of_peak(
        wl, il_raw, feature=feature, flatten=flatten,
        target_wavelength_nm=target, drop_db=drop_db,
    )
    if result is None:
        raise RuntimeError("Could not locate a suitable peak/notch for FWHM")
    centre, fwhm, amp, left, right = result

    fig, ax = plt.subplots(figsize=(9.5, 5.4))
    band_str = f" ({measurement.band}-band)" if measurement.band else ""

    ax.plot(wl, il, color="tab:blue", lw=1.2,
            label=f"MZM {bias_v:+.1f} V (flattened)" if flatten
            else f"MZM {bias_v:+.1f} V")

    # Peak line at peak amplitude (= 0 dB after flattening, more or less)
    ax.axhline(amp, color="red", ls="--", lw=0.9, alpha=0.55)

    # Half-max horizontal line
    if feature == "peak":
        threshold = amp - drop_db
        threshold_label = f"{-drop_db:.0f} dB (half-max)"
    else:
        threshold = amp + drop_db
        threshold_label = f"+{drop_db:.0f} dB above notch"
    ax.axhline(threshold, color="red", lw=2.0, alpha=0.9, label=threshold_label)

    # Vertical edges
    ax.axvline(left, color="red", ls="--", lw=1.0, ymin=0, ymax=0.65)
    ax.axvline(right, color="red", ls="--", lw=1.0, ymin=0, ymax=0.65)

    # FWHM arrow + label
    arrow_y = threshold - 1.5  # below the threshold line
    arrow = FancyArrowPatch(
        (left, arrow_y), (right, arrow_y),
        arrowstyle="<->", color="darkgoldenrod",
        mutation_scale=18, lw=2.0,
    )
    ax.add_patch(arrow)
    ax.text((left + right) / 2, arrow_y - 1.5,
            f"FWHM = {fwhm:.3f} nm",
            ha="center", va="top", fontsize=12, color="black",
            fontweight="bold")

    # Q factor box
    q_factor = centre / fwhm if fwhm > 0 else float("nan")
    info_text = (
        f"중심 파장 (centre): {centre:.3f} nm\n"
        f"FWHM: {fwhm*1000:.1f} pm  ({fwhm:.4f} nm)\n"
        f"Q-factor: {q_factor:,.1f}\n"
        f"Drop level: {drop_db:.1f} dB"
    )
    ax.text(0.98, 0.97, info_text, transform=ax.transAxes,
            fontsize=9, ha="right", va="top",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#FFFACD",
                      edgecolor="gray", alpha=0.9))

    # Zoom near the peak
    span = max(fwhm * 5, 6.0)
    ax.set_xlim(centre - span, centre + span)
    ax.set_ylim(amp - 25, amp + 5) if feature == "peak" else ax.set_ylim(amp - 5, amp + 30)

    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Flattened transmission (dB)" if flatten
                  else "Insertion loss (dB)")
    if title is None:
        title = (f"FWHM analysis: {measurement.wafer}/{measurement.die}"
                 f"{band_str} @ {bias_v:+.1f} V")
    ax.set_title(title)
    ax.legend(loc="lower left", fontsize=9)
    ax.grid(alpha=0.3)

    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_q_factor_distribution(
    fwhm_df: pd.DataFrame,
    output_path: str | Path,
    *,
    title: str | None = None,
) -> Path:
    """Box plot of Q per wafer + scatter of FWHM vs Q across all dies."""
    df = fwhm_df.copy()
    df = df.dropna(subset=["Q_factor", "FWHM_nm"])
    if df.empty:
        raise ValueError("No valid Q-factor measurements")

    wafers = sorted(df["Wafer"].dropna().unique())
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))

    # (a) Q box plot
    data, labels = [], []
    for w in wafers:
        sub = df[df["Wafer"] == w]
        if len(sub):
            data.append(sub["Q_factor"].values)
            labels.append(f"{w}\n(n={len(sub)})")
    axes[0].boxplot(data, tick_labels=labels, showmeans=True)
    axes[0].set_ylabel("Q-factor")
    axes[0].set_title("Q-factor per wafer")
    axes[0].grid(alpha=0.3)

    # (b) FWHM vs Q scatter
    for w in wafers:
        sub = df[df["Wafer"] == w]
        axes[1].scatter(sub["FWHM_nm"] * 1000, sub["Q_factor"],
                        alpha=0.7, s=40, label=w)
    axes[1].set_xlabel("FWHM (pm)")
    axes[1].set_ylabel("Q-factor")
    axes[1].set_title("FWHM vs Q-factor")
    axes[1].legend()
    axes[1].grid(alpha=0.3)

    if title is None:
        feat = df["Feature"].iloc[0] if "Feature" in df.columns else "peak"
        title = f"Q-factor / FWHM distribution ({feat})"
    fig.suptitle(title, fontsize=12, y=1.02)
    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out
