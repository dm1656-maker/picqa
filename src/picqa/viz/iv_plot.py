"""IV plotting."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from picqa.io.schemas import Measurement
from picqa.viz.labels import L


def plot_iv_grid(
    measurements: list[Measurement],
    output_path: str | Path,
    *,
    test_site: str = "DCM_LMZO",
    title: str | None = None,
    ncols: int = 3,
) -> Path:
    """One subplot per (wafer, session); IV curves for all dies overlaid."""
    sel = [m for m in measurements if m.test_site == test_site and m.iv is not None]
    if not sel:
        raise ValueError(f"No IV data for test_site={test_site}")

    if title is None:
        title = L("iv_title")

    groups = sorted({(m.wafer, m.session) for m in sel})
    nrows = (len(groups) + ncols - 1) // ncols

    fig = plt.figure(figsize=(4.3 * ncols, 3.4 * nrows))
    for i, (w, s) in enumerate(groups):
        ax = fig.add_subplot(nrows, ncols, i + 1)
        grp = [m for m in sel if m.wafer == w and m.session == s]
        for m in grp:
            ax.semilogy(
                m.iv.voltage,
                np.abs(m.iv.current) + 1e-13,
                alpha=0.6,
                lw=0.8,
            )
        ax.set_title(f"{w} / {s}\n({L('n_dies', n=len(grp))})", fontsize=9)
        ax.set_xlabel(L("voltage"))
        ax.set_ylabel(L("current_abs"))
        ax.set_ylim(1e-13, 1e-3)
        ax.grid(True, which="both", alpha=0.3)

    fig.suptitle(title, fontsize=12, y=1.0)
    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out
