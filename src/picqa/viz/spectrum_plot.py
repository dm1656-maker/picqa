"""Optical spectrum plots."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from picqa.io.schemas import Measurement


def plot_spectra_grid(
    measurements: list[Measurement],
    output_path: str | Path,
    *,
    test_site: str | None = None,
    bias_v: float = -2.0,
    title: str | None = None,
    ncols: int = 3,
    xlim: tuple[float, float] | None = None,
    ylim: tuple[float, float] = (-50, 0),
    mode: str = "median_band",
    dies_to_overlay: int = 14,
) -> Path:
    """Plot transmission spectra for each (wafer, session), one panel each.

    Three display modes are supported, all using the same per-panel layout
    but rendering the population of dies differently.

    Parameters
    ----------
    mode : {"median_band", "overlay", "single"}
        - ``"median_band"`` (default): draw the median spectrum across all
          dies in bold, with a shaded 5–95 percentile band. Quickly
          communicates "where is the typical envelope and how much
          variation is there?". Recommended for the global summary view.
        - ``"overlay"``: draw each die in its own colour with alpha,
          plus a thick black median curve on top. Better for spotting
          outliers, but busy.
        - ``"single"``: draw only the working die closest to (0, 0) per
          session, with no overlay. Cleanest visual; outliers are not
          visible.

    test_site : str | None
        If given, restrict to this single test site. If ``None``, all MZM
        test sites are accepted (so O- and C-band can co-exist; sessions
        of different bands end up in separate panels naturally because
        they live in different sessions).
    xlim : tuple | None
        If ``None``, auto-derive from each panel's design wavelength
        (±30 nm). This makes the same code work for O- and C-band.
    """
    if test_site is None:
        sel = [m for m in measurements
               if m.test_site in ("DCM_LMZO", "DCM_LMZC")]
    else:
        sel = [m for m in measurements if m.test_site == test_site]
    if not sel:
        raise ValueError("No matching measurements")

    groups = sorted({(m.wafer, m.session) for m in sel})
    nrows = (len(groups) + ncols - 1) // ncols
    fig = plt.figure(figsize=(4.6 * ncols, 3.6 * nrows))

    cmap = plt.get_cmap("tab20")

    for i, (w, s) in enumerate(groups):
        ax = fig.add_subplot(nrows, ncols, i + 1)
        die_measurements = [x for x in sel
                            if x.wafer == w and x.session == s]
        # Collect per-die spectra at this bias, on a common wavelength grid
        sweeps = [m.sweep_at_bias(bias_v) for m in die_measurements]
        sweeps = [(m, sw) for m, sw in zip(die_measurements, sweeps)
                  if sw is not None]
        if not sweeps:
            ax.set_title(f"{w} / {s}\n(no data at {bias_v:+.1f}V)", fontsize=9)
            continue

        # Build a unified grid (use the first sweep's wavelength axis as the
        # reference; all sweeps in a session share the same OSA grid).
        ref_wl = sweeps[0][1].wavelength_nm
        spectra_matrix = np.full((len(sweeps), len(ref_wl)), np.nan)
        for j, (_, sw) in enumerate(sweeps):
            if len(sw.wavelength_nm) == len(ref_wl):
                spectra_matrix[j] = sw.insertion_loss_db
            else:
                # Different grid; interpolate
                spectra_matrix[j] = np.interp(
                    ref_wl, sw.wavelength_nm, sw.insertion_loss_db,
                    left=np.nan, right=np.nan,
                )

        if mode == "single":
            # Pick the die closest to (0, 0)
            sweeps.sort(key=lambda ms: ms[0].die_col**2 + ms[0].die_row**2)
            chosen_m, chosen_sw = sweeps[0]
            ax.plot(chosen_sw.wavelength_nm, chosen_sw.insertion_loss_db,
                    color="tab:blue", lw=1.0)
            ax.set_title(f"{w} / {s}  (die {chosen_m.die}, n=1)", fontsize=9)

        elif mode == "median_band":
            median = np.nanmedian(spectra_matrix, axis=0)
            p05 = np.nanpercentile(spectra_matrix, 5, axis=0)
            p95 = np.nanpercentile(spectra_matrix, 95, axis=0)
            ax.fill_between(ref_wl, p05, p95, color="tab:blue",
                            alpha=0.20, label="5–95% range")
            ax.plot(ref_wl, median, color="navy", lw=1.4, label="median")
            ax.set_title(f"{w} / {s}  (n={len(sweeps)} dies)", fontsize=9)
            ax.legend(loc="lower left", fontsize=7, framealpha=0.85)

        elif mode == "overlay":
            # Each die its own distinct colour
            for j, (m, sw) in enumerate(sweeps):
                ax.plot(sw.wavelength_nm, sw.insertion_loss_db,
                        color=cmap(j % 20), alpha=0.55, lw=0.7)
            # Median on top in bold
            median = np.nanmedian(spectra_matrix, axis=0)
            ax.plot(ref_wl, median, color="black", lw=1.6, label="median")
            ax.set_title(f"{w} / {s}  (n={len(sweeps)} dies)", fontsize=9)
            ax.legend(loc="lower left", fontsize=7, framealpha=0.85)
        else:
            raise ValueError(f"Unknown mode={mode!r}")

        ax.set_xlabel("Wavelength (nm)")
        ax.set_ylabel("IL (dB)")
        # Auto-derive x-limit per panel from this session's design wavelength
        if xlim is None:
            design_wl = die_measurements[0].design_wavelength_nm or 1310.0
            ax.set_xlim(design_wl - 30, design_wl + 30)
        else:
            ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.grid(True, alpha=0.3)

    if title is None:
        title = (f"Transmission spectra @ DC bias = {bias_v:+.1f} V  "
                 f"(mode = {mode})")
    fig.suptitle(title, fontsize=12, y=1.0)
    fig.tight_layout()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_bias_shift(
    measurement: Measurement,
    output_path: str | Path,
    *,
    zoom_window_nm: tuple[float, float] | None = None,
    full_window_nm: tuple[float, float] | None = None,
) -> Path:
    """Plot all biases of one die, full range and zoomed near design wavelength.

    If ``full_window_nm`` or ``zoom_window_nm`` is ``None``, sensible defaults
    are derived from the measurement's own ``design_wavelength_nm`` so the
    same call works for O-band (1310 nm) and C-band (1550 nm) devices.
    """
    if not measurement.sweeps:
        raise ValueError("Measurement has no wavelength sweeps")

    sweeps = sorted(measurement.sweeps, key=lambda s: s.dc_bias_v)

    # Derive plot ranges
    design_wl = measurement.design_wavelength_nm or 1310.0
    if full_window_nm is None:
        # ±30 nm around the design wavelength is wide enough to show
        # several FSRs in either band.
        full_window_nm = (design_wl - 30.0, design_wl + 30.0)
    if zoom_window_nm is None:
        # ±5 nm is enough to see one notch in detail.
        zoom_window_nm = (design_wl - 5.0, design_wl + 5.0)

    # Snap windows to the actual measured range so we don't draw an empty
    # left or right margin if the sweep is narrower than ±30 nm.
    all_L = sweeps[0].wavelength_nm
    L_min, L_max = float(all_L.min()), float(all_L.max())
    full_window_nm = (max(full_window_nm[0], L_min),
                      min(full_window_nm[1], L_max))

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

    for sw in sweeps:
        axes[0].plot(sw.wavelength_nm, sw.insertion_loss_db, lw=0.6,
                     label=f"{sw.dc_bias_v:+.1f} V")
    axes[0].set_xlim(*full_window_nm)
    axes[0].set_ylim(-50, 0)
    axes[0].set_xlabel("Wavelength (nm)")
    axes[0].set_ylabel("IL (dB)")
    band_str = f" ({measurement.band}-band)" if measurement.band else ""
    axes[0].set_title(
        f"Bias-dependent spectra: {measurement.wafer}/{measurement.die}{band_str}"
    )
    axes[0].legend(loc="lower left", ncol=2, fontsize=8)
    axes[0].grid(alpha=0.3)

    lo, hi = zoom_window_nm
    for sw in sweeps:
        m = (sw.wavelength_nm >= lo) & (sw.wavelength_nm <= hi)
        axes[1].plot(sw.wavelength_nm[m], sw.insertion_loss_db[m], lw=0.8,
                     label=f"{sw.dc_bias_v:+.1f} V")
    axes[1].set_xlabel("Wavelength (nm)")
    axes[1].set_ylabel("IL (dB)")
    axes[1].set_title(f"Zoom near design wavelength ({design_wl:.0f} nm)")
    axes[1].legend(loc="lower left", ncol=2, fontsize=8)
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out
