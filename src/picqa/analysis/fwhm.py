"""FWHM and Q-factor extraction from MZM transmission spectra.

Two complementary measurements:

1. **Peak FWHM** — width of the spectral peak (the local *maximum* of the
   flattened transmission, i.e. the top of an MZI fringe). Uses the
   classic -3 dB definition: width measured 3 dB below the peak's
   amplitude.

2. **Notch FWHM** — width of a notch (local *minimum*). Defined as the
   width measured 3 dB above the minimum, which is the equivalent
   measurement for a transmission dip rather than a peak.

Both produce the same quality figure of merit:

    Q = λ_centre / FWHM

Q is dimensionless and quantifies how spectrally selective the resonance
is. Higher Q means the device picks out wavelengths more precisely.

The "flattened transmission" trick (subtract a polynomial envelope from
the raw spectrum) is borrowed from the V-π·L analysis: it makes peaks
appear as clean local maxima around 0 dB, which is the convention shown
in standard textbooks.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from picqa.io.schemas import Measurement


@dataclass
class FWHMResult:
    """Result of one FWHM measurement on one (peak or notch) feature."""

    wafer: str
    session: str
    die: str
    band: str | None
    bias_v: float
    feature: str           # "peak" or "notch"
    centre_wavelength_nm: float
    fwhm_nm: float
    q_factor: float
    peak_il_db: float      # IL value at the centre (peak amplitude or notch depth)
    left_edge_nm: float    # x position where IL crosses the half-max threshold
    right_edge_nm: float


# --------------------------------------------------------------------- #
# Single-spectrum FWHM
# --------------------------------------------------------------------- #
def _flatten_envelope(
    wavelength_nm: np.ndarray,
    il_db: np.ndarray,
    *,
    poly_order: int = 3,
    notch_depth_db: float = 5.0,
) -> np.ndarray:
    """Return ``il_db`` with the slow grating-coupler envelope removed.

    A polynomial is fit to the upper envelope of the spectrum (notch
    samples excluded), then subtracted. The result has flat baseline
    near 0 dB so peaks and notches stand out cleanly.
    """
    win = max(50, len(il_db) // 30)
    rolling_max = np.array([
        np.max(il_db[max(0, i - win):min(len(il_db), i + win)])
        for i in range(len(il_db))
    ])
    keep = il_db >= (rolling_max - notch_depth_db)
    coeffs = np.polyfit(wavelength_nm[keep], il_db[keep], poly_order)
    envelope = np.polyval(coeffs, wavelength_nm)
    return il_db - envelope


def _interp_crossing(
    x: np.ndarray, y: np.ndarray, threshold: float, idx_centre: int,
    *, direction: str,
) -> float | None:
    """Linearly interpolate where ``y`` crosses ``threshold`` next to
    ``idx_centre`` in the given ``direction`` ('left' or 'right').

    For peaks: ``y`` decreases as we move away from the centre, so we
    look for the first sample where ``y < threshold``.

    Returns the interpolated x value, or None if no crossing is found
    within the array.
    """
    if direction == "right":
        for i in range(idx_centre, len(y) - 1):
            if (y[i] - threshold) * (y[i + 1] - threshold) <= 0:
                # Linear interpolation between i and i+1
                if y[i + 1] != y[i]:
                    frac = (threshold - y[i]) / (y[i + 1] - y[i])
                else:
                    frac = 0.0
                return float(x[i] + frac * (x[i + 1] - x[i]))
        return None
    elif direction == "left":
        for i in range(idx_centre, 0, -1):
            if (y[i] - threshold) * (y[i - 1] - threshold) <= 0:
                if y[i - 1] != y[i]:
                    frac = (threshold - y[i]) / (y[i - 1] - y[i])
                else:
                    frac = 0.0
                return float(x[i] + frac * (x[i - 1] - x[i]))
        return None
    else:
        raise ValueError(f"direction must be 'left' or 'right', got {direction!r}")


def fwhm_of_peak(
    wavelength_nm: np.ndarray,
    il_db: np.ndarray,
    *,
    feature: str = "peak",
    flatten: bool = True,
    target_wavelength_nm: float | None = None,
    drop_db: float = 3.0,
    prominence_db: float = 3.0,
) -> tuple[float, float, float, float, float] | None:
    """Measure FWHM at the strongest peak (or notch) of a spectrum.

    Parameters
    ----------
    feature : {"peak", "notch"}
        ``"peak"`` finds the strongest local maximum (transmission peak,
        appropriate for the flat region between MZI notches).
        ``"notch"`` finds the deepest local minimum (dip).
    flatten : bool
        If True, subtract the grating-coupler envelope first so the
        peaks/notches are clean. Recommended for MZM spectra.
    target_wavelength_nm : float | None
        If given, prefer the feature closest to this wavelength rather
        than the strongest one in the whole spectrum. Useful for
        focusing on the design wavelength.
    drop_db : float
        How far below the peak (or above the notch) to measure the
        width. The classical FWHM uses 3.0 dB (= 50 % linear intensity).

    Returns
    -------
    tuple (centre_nm, fwhm_nm, peak_value_db, left_edge_nm, right_edge_nm)
    or ``None`` if no suitable feature is found.
    """
    if feature not in ("peak", "notch"):
        raise ValueError(f"feature must be 'peak' or 'notch', got {feature!r}")

    if flatten:
        y = _flatten_envelope(wavelength_nm, il_db)
    else:
        y = il_db.copy()

    # For peaks: search for local maxima in y. For notches: search for
    # local minima (i.e. peaks in -y).
    search_signal = y if feature == "peak" else -y
    peaks, _ = find_peaks(search_signal, prominence=prominence_db)
    if peaks.size == 0:
        return None

    # Pick the right one
    if target_wavelength_nm is not None:
        idx = peaks[np.argmin(np.abs(wavelength_nm[peaks] - target_wavelength_nm))]
    else:
        # Strongest = largest absolute value of the (signed) feature
        idx = peaks[np.argmax(search_signal[peaks])]

    centre_wl = float(wavelength_nm[idx])
    centre_amp = float(y[idx])

    # For peaks, threshold is centre_amp - drop_db; for notches it's
    # centre_amp + drop_db. The direction of crossing is then symmetric.
    if feature == "peak":
        threshold = centre_amp - drop_db
    else:
        threshold = centre_amp + drop_db

    left = _interp_crossing(wavelength_nm, y, threshold, idx, direction="left")
    right = _interp_crossing(wavelength_nm, y, threshold, idx, direction="right")
    if left is None or right is None:
        return None

    return centre_wl, float(right - left), centre_amp, left, right


def extract_fwhm_features(
    measurements: list[Measurement],
    *,
    bias_v: float = -2.0,
    feature: str = "peak",
    drop_db: float = 3.0,
    flatten: bool = True,
    use_design_wavelength: bool = True,
) -> pd.DataFrame:
    """Apply :func:`fwhm_of_peak` to every measurement and return a table.

    One row per (Wafer, Session, Die). Dies where no feature is found
    or the spectrum is missing get NaN for FWHM and Q.
    """
    rows: list[dict] = []
    for m in measurements:
        sw = m.sweep_at_bias(bias_v)
        if sw is None:
            continue
        target = m.design_wavelength_nm if use_design_wavelength else None
        result = fwhm_of_peak(
            sw.wavelength_nm, sw.insertion_loss_db,
            feature=feature, flatten=flatten,
            target_wavelength_nm=target, drop_db=drop_db,
        )
        if result is None:
            centre, fwhm, amp, left, right = (np.nan,) * 5
        else:
            centre, fwhm, amp, left, right = result
        q = (centre / fwhm) if (np.isfinite(fwhm) and fwhm > 0) else np.nan
        rows.append({
            "Wafer": m.wafer,
            "Session": m.session,
            "Die": m.die,
            "DieCol": m.die_col,
            "DieRow": m.die_row,
            "Device": m.device_name,
            "TestSite": m.test_site,
            "Band": m.band,
            "Bias_V": bias_v,
            "Feature": feature,
            "Centre_nm": centre,
            "FWHM_nm": fwhm,
            "Q_factor": q,
            "PeakAmp_dB": amp,
            "LeftEdge_nm": left,
            "RightEdge_nm": right,
        })
    return pd.DataFrame(rows)
