"""Advanced V-phi analysis for MZ modulators (Project 2 — full version).

Replicates the six-panel analysis figure used in production silicon photonic
characterisation pipelines:

1. **Transmission spectra (as measured)** with a polynomial fit of the
   grating-coupler envelope used as reference.
2. **Normalised spectra** = measured − reference, isolating the modulator's
   own response.
3. **Focus on the deepest notch**, with a parabolic fit at each bias to
   pinpoint the notch wavelength to sub-resolution accuracy.
4. **IV** on a semilog axis.
5. **Phase shift vs voltage** — three independent fits using the left,
   right, and central notches to cross-check.
6. **VpiL vs voltage** — the Vπ·L figure of merit at every bias point.

Key relationships
-----------------
* Notch shift Δλ around 0V → phase shift  Δφ = 2π · Δλ / FSR
* Vπ at a given bias V    → Vπ = V · π / |Δφ|
* Vπ·L                    → Vπ multiplied by the active phase-shifter length
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from picqa.analysis.phase_extraction import parse_phaseshifter_length_um
from picqa.io.schemas import Measurement, WavelengthSweep
from picqa.viz.labels import L


# --------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------- #
def fit_reference_envelope(
    sweep: WavelengthSweep,
    *,
    order: int = 3,
    notch_depth_db: float = 5.0,
) -> np.ndarray:
    """Fit a polynomial to the grating-coupler envelope of one sweep.

    Notch points (where IL drops more than ``notch_depth_db`` below the local
    moving max) are excluded from the fit so the polynomial follows the
    upper envelope rather than averaging through the dips.

    Returns the polynomial evaluated at every wavelength in ``sweep``.
    """
    L = sweep.wavelength_nm
    IL = sweep.insertion_loss_db

    # Crude upper-envelope mask: keep points within ``notch_depth_db`` of a
    # rolling 200-sample max
    win = max(50, len(IL) // 30)
    rolling_max = np.array([
        np.max(IL[max(0, i - win):min(len(IL), i + win)])
        for i in range(len(IL))
    ])
    keep = IL >= (rolling_max - notch_depth_db)

    coeffs = np.polyfit(L[keep], IL[keep], order)
    return np.polyval(coeffs, L)


def find_notches(
    L: np.ndarray, IL: np.ndarray, *,
    prominence_db: float = 5.0,
) -> np.ndarray:
    """Indices of transmission minima in ``IL``."""
    from scipy.signal import find_peaks
    peaks, _ = find_peaks(-IL, prominence=prominence_db)
    return peaks


def parabolic_peak_fit(
    L: np.ndarray, IL: np.ndarray, peak_idx: int, *,
    half_window_nm: float = 0.3,
) -> tuple[float, float]:
    """Fit a parabola around a notch and return ``(λ_peak, IL_peak)``.

    Falls back to the discrete sample if the fit is ill-conditioned.
    """
    L_peak0 = L[peak_idx]
    mask = np.abs(L - L_peak0) <= half_window_nm
    if mask.sum() < 5:
        return float(L_peak0), float(IL[peak_idx])

    Lw = L[mask]
    ILw = IL[mask]
    try:
        # IL = a (L-L0)^2 + b (L-L0) + c   (centred for numerical stability)
        coeffs = np.polyfit(Lw - L_peak0, ILw, 2)
        a, b, c = coeffs
        if a <= 0:  # not a minimum, just return the discrete sample
            return float(L_peak0), float(IL[peak_idx])
        dL = -b / (2 * a)
        L_min = L_peak0 + dL
        IL_min = c + b * dL + a * dL ** 2
        # Sanity check: keep within window
        if abs(dL) > half_window_nm:
            return float(L_peak0), float(IL[peak_idx])
        return float(L_min), float(IL_min)
    except (np.linalg.LinAlgError, ValueError):
        return float(L_peak0), float(IL[peak_idx])


def track_notches_across_bias(
    measurement: Measurement,
    *,
    ref_il_at_each_sweep: dict[float, np.ndarray] | None = None,
    n_notches: int = 3,
) -> dict[float, list[tuple[float, float]]]:
    """For each sweep, find ``n_notches`` notches and track them by wavelength.

    The 0V sweep is used to seed ``n_notches`` reference wavelengths (taking
    the deepest notches there). At every other bias we then select notches
    that are *closest to those seed wavelengths* — not the deepest ones —
    so the same physical resonance is followed across all biases. This is
    the only way to get a clean phase-vs-bias curve when the reference
    polynomial flattens the spectral envelope and several notches end up
    at similar depths.

    Returns ``{bias_v: [(λ_peak_nm, IL_normalised_db), ...]}``. Lists are
    ordered by increasing wavelength (so index 0 = leftmost peak,
    n_notches-1 = rightmost).
    """
    out: dict[float, list[tuple[float, float]]] = {}

    # Step 1 — seed from the 0V sweep
    sw0 = next((s for s in measurement.sweeps if abs(s.dc_bias_v) < 0.01), None)
    if sw0 is None:
        for sw in measurement.sweeps:
            out[sw.dc_bias_v] = []
        return out

    ref0 = (ref_il_at_each_sweep or {}).get(sw0.dc_bias_v)
    IL0_norm = sw0.insertion_loss_db if ref0 is None else sw0.insertion_loss_db - ref0
    seed_peaks = find_notches(sw0.wavelength_nm, IL0_norm, prominence_db=5.0)
    if seed_peaks.size == 0:
        for sw in measurement.sweeps:
            out[sw.dc_bias_v] = []
        return out

    # Pick n deepest, then sort by wavelength
    depths = IL0_norm[seed_peaks]
    chosen = seed_peaks[np.argsort(depths)][:n_notches]
    chosen = chosen[np.argsort(sw0.wavelength_nm[chosen])]
    seed_lambdas = sw0.wavelength_nm[chosen]

    # Step 2 — for every bias, pick the closest peak to each seed wavelength.
    # As biases shift, update the per-notch tracker so we don't lose lock.
    trackers = list(seed_lambdas)
    sweeps_sorted = sorted(measurement.sweeps, key=lambda s: abs(s.dc_bias_v))
    for sw in sweeps_sorted:
        ref = (ref_il_at_each_sweep or {}).get(sw.dc_bias_v)
        IL_norm = sw.insertion_loss_db if ref is None else sw.insertion_loss_db - ref
        peaks = find_notches(sw.wavelength_nm, IL_norm, prominence_db=3.0)
        if peaks.size == 0:
            out[sw.dc_bias_v] = []
            continue
        peak_lambdas = sw.wavelength_nm[peaks]

        chosen_for_bias: list[tuple[float, float]] = []
        new_trackers: list[float] = []
        for tracker in trackers:
            j = int(np.argmin(np.abs(peak_lambdas - tracker)))
            # Reject if the closest peak is more than 2 nm away — that would
            # mean we lost the notch entirely (e.g. fell out of sweep range)
            if abs(peak_lambdas[j] - tracker) > 2.0:
                lam_fit, il_fit = float("nan"), float("nan")
                new_trackers.append(tracker)
            else:
                lam_fit, il_fit = parabolic_peak_fit(
                    sw.wavelength_nm, IL_norm, peaks[j],
                )
                new_trackers.append(lam_fit)
            chosen_for_bias.append((lam_fit, il_fit))
        trackers = new_trackers
        out[sw.dc_bias_v] = chosen_for_bias
    return out


# --------------------------------------------------------------------- #
# Main 6-panel plot
# --------------------------------------------------------------------- #
def plot_vpi_analysis(
    measurement: Measurement,
    output_path: str | Path,
    *,
    poly_order: int = 3,
    n_notches: int = 3,
) -> Path:
    """Reproduce the six-panel V-φ analysis figure.

    Layout (top row, left → right): measured spectra + reference fit;
    normalised spectra; focus on left peak with bias-by-bias notch fits.
    Bottom row: IV; phase vs bias; Vπ·L vs bias.
    """
    if not measurement.sweeps:
        raise ValueError("Measurement has no wavelength sweeps")
    if measurement.iv is None:
        raise ValueError("Measurement has no IV data")

    sweeps = sorted(measurement.sweeps, key=lambda s: s.dc_bias_v)
    biases = np.array([s.dc_bias_v for s in sweeps])
    n_biases = len(sweeps)
    cmap = plt.get_cmap("viridis")
    colours = [cmap(i / max(1, n_biases - 1)) for i in range(n_biases)]

    # 1. Reference polynomial from the 0V trace (works in either band)
    sw0 = next(s for s in sweeps if abs(s.dc_bias_v) < 0.01)
    ref_at_0V = fit_reference_envelope(sw0, order=poly_order)
    # Same coefficients, evaluated on each sweep's wavelength grid.
    coeffs = np.polyfit(sw0.wavelength_nm[
        np.isfinite(ref_at_0V)
    ], ref_at_0V[np.isfinite(ref_at_0V)], poly_order)
    refs = {s.dc_bias_v: np.polyval(coeffs, s.wavelength_nm) for s in sweeps}

    # 2. Track notches in normalised spectra
    tracked = track_notches_across_bias(
        measurement, ref_il_at_each_sweep=refs, n_notches=n_notches
    )

    # Pick the left-most notch present in every bias as the "Focus" peak
    common_left_lambda = None
    if all(len(tracked[b]) >= 1 for b in biases):
        # Use the leftmost notch of the 0V trace as the seed
        seed_lam = tracked[0.0][0][0] if 0.0 in tracked and tracked[0.0] else None
        if seed_lam is None:
            seed_lam = tracked[biases[0]][0][0]
        common_left_lambda = seed_lam

    # ----------------- Build figure -----------------
    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(2, 3, hspace=0.35, wspace=0.28)

    # --- (1) measured + reference ---
    ax = fig.add_subplot(gs[0, 0])
    for c, sw in zip(colours, sweeps):
        ax.plot(sw.wavelength_nm, sw.insertion_loss_db, color=c, lw=0.8)
    ax.plot(sw0.wavelength_nm, ref_at_0V, "k--", lw=1.2,
            label=L("fit_polynomial", order=poly_order))
    ax.set_xlabel(L("wavelength"))
    ax.set_ylabel(L("il_db"))
    ax.set_title(L("transmission_measured"))
    ax.legend(loc="lower left", fontsize=9)
    ax.grid(alpha=0.3)

    # --- (2) normalised + vertical notch markers ---
    ax = fig.add_subplot(gs[0, 1])
    fsr_estimates = []
    for c, sw in zip(colours, sweeps):
        norm = sw.insertion_loss_db - refs[sw.dc_bias_v]
        ax.plot(sw.wavelength_nm, norm, color=c, lw=0.8,
                label=f"{sw.dc_bias_v:+.1f}V")
        for lam, _ in tracked[sw.dc_bias_v]:
            ax.axvline(lam, color=c, lw=0.5, alpha=0.6)
    # Headline FSR from 0V notches
    if tracked.get(0.0) and len(tracked[0.0]) >= 2:
        lams = [l for l, _ in tracked[0.0]]
        fsr = float(np.median(np.diff(sorted(lams))))
        fsr_estimates.append(fsr)
    fsr_label = f"FSR {fsr_estimates[0]:.1f}nm" if fsr_estimates else "FSR ~"
    # Compute IL as median of the per-bias normalised minima at the focus peak
    if tracked.get(0.0):
        il_value = float(min(d for _, d in tracked[0.0]))
        il_label = f"IL {il_value:.1f}dB "
    else:
        il_label = ""
    ax.text(0.02, 0.05, f"{il_label}{fsr_label}",
            transform=ax.transAxes, fontsize=9,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.7))
    # Trim to ±FSR/2 around design wavelength for clarity
    design = measurement.design_wavelength_nm or 1310.0
    half = fsr_estimates[0] if fsr_estimates else 5.0
    ax.set_xlim(design - half, design + half)
    ax.set_xlabel(L("wavelength"))
    ax.set_ylabel(L("il_db"))
    ax.set_title(L("analysis_normalised"))
    ax.legend(loc="upper right", fontsize=8, ncol=1)
    ax.grid(alpha=0.3)

    # --- (3) focus on the chosen notch ---
    ax = fig.add_subplot(gs[0, 2])
    if common_left_lambda is not None:
        # Decide which notch index (0 = leftmost) is actually closest to seed
        for c, sw in zip(colours, sweeps):
            norm = sw.insertion_loss_db - refs[sw.dc_bias_v]
            tracked_for_bias = tracked[sw.dc_bias_v]
            if not tracked_for_bias:
                continue
            # leftmost notch:
            lam_focus, il_focus = tracked_for_bias[0]
            mask = np.abs(sw.wavelength_nm - lam_focus) <= 0.6
            ax.plot(sw.wavelength_nm[mask], norm[mask],
                    color=c, lw=1.0, label=f"{sw.dc_bias_v:+.1f}V")
            ax.plot(lam_focus, il_focus, "o", color="tab:blue",
                    markersize=8, markeredgecolor="k", zorder=10)
        ax.set_xlim(common_left_lambda - 0.6, common_left_lambda + 1.0)
    ax.set_xlabel(L("wavelength"))
    ax.set_ylabel(L("il_db"))
    ax.set_title(L("focus_left_peak"))
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)

    # --- (4) IV ---
    ax = fig.add_subplot(gs[1, 0])
    ax.semilogy(measurement.iv.voltage,
                np.abs(measurement.iv.current) + 1e-13, "ko-",
                markersize=5, lw=0.8)
    ax.set_xlabel(L("voltage"))
    ax.set_ylabel(L("current"))
    ax.set_title(L("iv_analysis"))
    ax.grid(alpha=0.3, which="both")

    # --- (5) phase vs bias from each notch ---
    ax = fig.add_subplot(gs[1, 1])
    fsr_for_phase = fsr_estimates[0] if fsr_estimates else None
    if fsr_for_phase is not None:
        # Build a (bias × notch_index) matrix of wavelengths
        # Only use biases where we have at least n_notches notches
        n_use = min(len(tracked[b]) for b in biases) if all(tracked[b] for b in biases) else 0
        if n_use >= 1:
            # Reference is the bias closest to 0
            ref_b_idx = int(np.argmin(np.abs(biases)))
            phi_pi = {}  # idx → array
            peak_labels = {0: L("peak_left"), 1: L("peak_center"), 2: L("peak_right")}
            colors_idx = {0: "tab:blue", 1: "tab:red", 2: "k"}
            for j in range(n_use):
                lams = np.array([tracked[b][j][0] for b in biases])
                d_lambda = lams - lams[ref_b_idx]
                d_phi_pi = 2 * d_lambda / fsr_for_phase  # ÷π already implicit
                phi_pi[j] = d_phi_pi
                ax.plot(biases, d_phi_pi,
                        color=colors_idx.get(j, "gray"),
                        ls="-." if j == 2 else "--",
                        lw=1.2,
                        label=peak_labels.get(j, f"Peak {j}"))
    ax.axhline(0, color="gray", lw=0.5)
    ax.set_xlabel(L("voltage"))
    ax.set_ylabel(L("phase_shift"))
    ax.set_title(L("phase_analysis"))
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)

    # --- (6) VpiL vs bias ---
    ax = fig.add_subplot(gs[1, 2])
    L_um = parse_phaseshifter_length_um(measurement.device_name)
    if fsr_for_phase is not None and np.isfinite(L_um) and tracked:
        # Use the leftmost notch only for VpiL
        n_use = min(len(tracked[b]) for b in biases) if all(tracked[b] for b in biases) else 0
        if n_use >= 1:
            lams = np.array([tracked[b][0][0] for b in biases])
            ref_b_idx = int(np.argmin(np.abs(biases)))
            d_lambda = lams - lams[ref_b_idx]
            d_phi_pi = 2 * d_lambda / fsr_for_phase  # in units of π
            # Vπ·L = V * π / Δφ * L  =  V / |Δφ_in_π| * L
            with np.errstate(divide="ignore", invalid="ignore"):
                vpi = np.where(np.abs(d_phi_pi) > 1e-3,
                               np.abs(biases) / np.abs(d_phi_pi),
                               np.nan)
            vpi_l = vpi * (L_um * 1e-4)  # µm → cm
            ax.plot(biases, vpi_l, "k-.", lw=1.2)
            # Highlight the SS markers at 0V, -1V, and -2V
            for V_target, col, lab in [(0.0, "red", "SS 0V"),
                                       (-1.0, "blue", "SS -1V"),
                                       (-2.0, "green", "SS -2V")]:
                idx = int(np.argmin(np.abs(biases - V_target)))
                if abs(biases[idx] - V_target) > 0.1:
                    continue
                if np.isfinite(vpi_l[idx]):
                    ax.scatter(biases[idx], vpi_l[idx], color=col, s=80,
                               zorder=10,
                               label=f"{lab} = {vpi_l[idx]:.2f} V·cm")
    ax.set_xlabel(L("voltage"))
    ax.set_ylabel(L("vpi_l_vcm"))
    ax.set_title(L("vpil_analysis"))
    ax.legend(loc="upper right", fontsize=8, title="Vπ·L (V·cm)")
    ax.grid(alpha=0.3)

    band_str = f"{measurement.band}-band " if measurement.band else ""
    fig.suptitle(
        f"{measurement.wafer}/{measurement.die}  {band_str}"
        f"{measurement.test_site}  {measurement.device_name}\n"
        f"Vπ·L analysis (small-signal) — picqa",
        fontsize=11, y=0.995,
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out
