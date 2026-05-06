"""Command-line interface for picqa.

Subcommands::

    picqa inventory <data-dir>
    picqa parse <data-dir> [--test-site SITE] [--output FILE.pkl]
    picqa extract mzm <data-dir> [--output FILE.csv]
    picqa extract pd  <data-dir> [--output FILE.csv]
    picqa plot iv       <data-dir> --output FILE.png
    picqa plot spectra  <data-dir> --output FILE.png [--bias V]
    picqa plot wafermap <features.csv> --metric NAME --output FILE.png
    picqa plot summary  <features.csv> --output FILE.png
    picqa yield <features.csv> --spec FILE.yaml --family NAME --output FILE.csv
    picqa report <data-dir> --output-dir DIR [--spec FILE.yaml --family NAME]
"""

from __future__ import annotations

import argparse
import logging
import pickle
import sys
from pathlib import Path

import pandas as pd

from picqa import __version__
from picqa.analysis.outlier import flag_failed_contacts
from picqa.analysis.yield_calc import evaluate_yield, load_spec, yield_summary
from picqa.extract.mzm import MZM_TEST_SITES, extract_mzm_features
from picqa.extract.photodetector import extract_pd_features
from picqa.io.xml_parser import inventory, parse_directory
from picqa.report.markdown import generate_report
from picqa.viz.iv_plot import plot_iv_grid
from picqa.viz.spectrum_plot import plot_spectra_grid
from picqa.viz.summary_plot import plot_summary
from picqa.viz.wafer_map import plot_wafermap

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# Subcommand handlers
# --------------------------------------------------------------------- #
def cmd_inventory(args: argparse.Namespace) -> int:
    inv = inventory(args.data_dir)
    print(f"Total files: {inv['n_files']}, {inv['total_size_bytes']/1e6:.1f} MB")
    print("Wafers:")
    for k, v in inv["by_wafer"].items():
        print(f"  {k}: {v} files")
    print("Test sites:")
    for k, v in inv["by_test_site"].items():
        print(f"  {k}: {v}")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    measurements = parse_directory(args.data_dir, test_site=args.test_site)
    print(f"Parsed {len(measurements)} measurements")
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("wb") as f:
            pickle.dump(measurements, f)
        print(f"Saved → {out}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    if args.device == "pn":
        # PN modulator uses a different parser/extractor pair because its XML
        # layout (multiple PortCombo segments) doesn't fit the generic
        # Measurement schema.
        from picqa.extract.pn_modulator import (
            extract_pn_length_fit,
            extract_pn_segment_features,
        )
        from picqa.io.pn_parser import parse_pn_directory

        measurements = parse_pn_directory(args.data_dir)
        seg_df = extract_pn_segment_features(measurements)
        fit_df = extract_pn_length_fit(seg_df)

        print(f"Extracted {len(seg_df)} segment rows over {len(fit_df)} dies")
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            seg_df.to_csv(out, index=False)
            fit_path = out.with_name(out.stem + "_lengthfit.csv")
            fit_df.to_csv(fit_path, index=False)
            print(f"Per-segment → {out}")
            print(f"Length fit  → {fit_path}")
        else:
            print(seg_df.head().to_string(index=False))
        return 0

    if args.device == "mzm":
        # Pull both O- and C-band MZ modulator sites in one pass.
        from picqa.extract.mzm import MZM_TEST_SITES
        measurements = parse_directory(args.data_dir, test_site=list(MZM_TEST_SITES))
        df = extract_mzm_features(measurements)
        df = flag_failed_contacts(df)
    elif args.device == "pd":
        measurements = parse_directory(args.data_dir, test_site="DCM_GPDO")
        df = extract_pd_features(measurements)
    else:
        print(f"Unknown device: {args.device}", file=sys.stderr)
        return 2

    print(f"Extracted {len(df)} rows")
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        print(f"Saved → {out}")
    else:
        print(df.head().to_string(index=False))
    return 0


def cmd_plot(args: argparse.Namespace) -> int:
    out = Path(args.output)

    if args.kind == "iv":
        measurements = parse_directory(args.input, test_site=list(MZM_TEST_SITES))
        plot_iv_grid(measurements, out)
    elif args.kind == "spectra":
        measurements = parse_directory(args.input, test_site=list(MZM_TEST_SITES))
        plot_spectra_grid(measurements, out, bias_v=args.bias,
                          mode=args.spectra_mode)
    elif args.kind == "wafermap":
        df = pd.read_csv(args.input)
        plot_wafermap(df, args.metric, out)
    elif args.kind == "summary":
        df = pd.read_csv(args.input)
        plot_summary(df, out)
    elif args.kind == "pn_length":
        from picqa.viz.pn_plot import plot_pn_length_dependence
        df = pd.read_csv(args.input)
        plot_pn_length_dependence(df, out)
    elif args.kind == "pn_summary":
        from picqa.viz.pn_plot import plot_pn_summary
        df = pd.read_csv(args.input)
        plot_pn_summary(df, out)
    elif args.kind == "radial":
        from picqa.viz.uniformity_plot import plot_radial_dependence
        df = pd.read_csv(args.input)
        if not args.metric:
            print("--metric required for radial plot", file=sys.stderr)
            return 2
        plot_radial_dependence(df, args.metric, out)
    elif args.kind == "center_vs_edge":
        from picqa.viz.uniformity_plot import plot_center_vs_edge
        df = pd.read_csv(args.input)
        # metric is comma-separated list of columns
        metrics = [args.metric] if args.metric else \
            ["FSR_nm", "PeakIL_near_1310_dB", "I_at_-1V_pA"]
        if args.metric and "," in args.metric:
            metrics = [m.strip() for m in args.metric.split(",")]
        plot_center_vs_edge(df, metrics, out)
    elif args.kind == "vpi":
        from picqa.viz.uniformity_plot import plot_vpi_distribution
        df = pd.read_csv(args.input)
        plot_vpi_distribution(df, out)
    elif args.kind == "vphi":
        # Need raw measurement, not CSV
        from picqa.viz.uniformity_plot import plot_vphi_curve
        measurements = parse_directory(args.input, test_site=list(MZM_TEST_SITES))
        # Pick a representative working die: first one with valid IV
        target = None
        for m in measurements:
            if m.iv is not None and m.sweeps:
                # Sanity check: leakage at -1V should be > 1nA (working contact)
                if abs(m.iv.at(-1.0)) > 1e-9:
                    target = m
                    break
        if target is None:
            print("No working die found for V-phi plot", file=sys.stderr)
            return 2
        plot_vphi_curve(target, out)
    elif args.kind == "vpi_analysis":
        # Six-panel detailed analysis (project 2, full version)
        from picqa.viz.vpi_analysis import plot_vpi_analysis
        measurements = parse_directory(args.input, test_site=list(MZM_TEST_SITES))
        target = None
        # Prefer working contact + clear notches (deeper than 10 dB)
        for m in measurements:
            if m.iv is None or not m.sweeps:
                continue
            if abs(m.iv.at(-1.0)) < 1e-9:
                continue  # failed contact
            sw0 = m.sweep_at_bias(0.0)
            if sw0 is None:
                continue
            from scipy.signal import find_peaks
            peaks, _ = find_peaks(-sw0.insertion_loss_db, prominence=10.0)
            if peaks.size >= 3:
                target = m
                break
        if target is None:
            print("No working die with clear notches found", file=sys.stderr)
            return 2
        plot_vpi_analysis(target, out)
    elif args.kind == "fwhm_wafermap":
        # FWHM (and Q-factor) wafer maps per (Wafer, Band)
        # Input is either a CSV from `picqa fwhm` or a data directory
        from picqa.viz.wafer_map import plot_fwhm_wafermap
        in_path = Path(args.input)
        if in_path.is_file() and in_path.suffix.lower() == ".csv":
            df = pd.read_csv(args.input)
        else:
            from picqa.analysis.fwhm import extract_fwhm_features
            measurements = parse_directory(args.input, test_site=list(MZM_TEST_SITES))
            df = extract_fwhm_features(measurements,
                                       bias_v=args.bias, feature="peak")
        plot_fwhm_wafermap(df, out)
    else:
        print(f"Unknown plot kind: {args.kind}", file=sys.stderr)
        return 2

    print(f"Saved → {out}")
    return 0


def _resolve_die(
    measurements: list,
    wafer: str,
    die: str,
    *,
    band: str | None = None,
    session: str | None = None,
) -> object | None:
    """Find a single measurement matching wafer/die (and optional band/session).

    Returns the matching Measurement, or prints disambiguation hints and
    returns None if zero or multiple matches are found.
    """
    # Normalise die spec: accept "(0,0)", "0,0", "0 0"
    die_norm = die.strip().lstrip("(").rstrip(")").replace(" ", "").replace(",", ",")

    candidates = [
        m for m in measurements
        if m.wafer == wafer and m.die.lstrip("(").rstrip(")") == die_norm
    ]
    if band:
        band_upper = band.upper()
        candidates = [m for m in candidates if m.band == band_upper]
    if session:
        candidates = [m for m in candidates if session in m.session]

    if not candidates:
        print(f"No measurement found for {wafer}/({die_norm})", file=sys.stderr)
        if band:
            print(f"  (filtered by band={band})", file=sys.stderr)
        return None

    if len(candidates) > 1:
        print(f"Multiple matches for {wafer}/({die_norm}):", file=sys.stderr)
        for c in candidates:
            print(f"  - band={c.band or '?'}  session={c.session}  "
                  f"test_site={c.test_site}  device={c.device_name}",
                  file=sys.stderr)
        print("Disambiguate with --band O|C or --session <substring>",
              file=sys.stderr)
        return None

    return candidates[0]


def cmd_show(args: argparse.Namespace) -> int:
    """Show one die's data or one of its plots.

    Examples
    --------
    picqa show <data-dir> D08 "(0,0)"
    picqa show <data-dir> D08 "(0,0)" --plot vpi_analysis
    picqa show <data-dir> D08 "(0,0)" --band C --plot bias_shift
    """
    # Parse all MZM sites by default; user can narrow with --test-site
    if args.test_site:
        test_sites = [args.test_site]
    else:
        test_sites = list(MZM_TEST_SITES)

    measurements = parse_directory(args.data_dir, test_site=test_sites)
    target = _resolve_die(
        measurements, args.wafer, args.die,
        band=args.band, session=args.session,
    )
    if target is None:
        return 1

    # Print metadata table
    print()
    print(f"  Wafer:               {target.wafer}")
    print(f"  Die:                 {target.die}")
    print(f"  Band:                {target.band or 'unknown'}")
    print(f"  Design wavelength:   {target.design_wavelength_nm} nm")
    print(f"  Test site:           {target.test_site}")
    print(f"  Device:              {target.device_name}")
    print(f"  Session:             {target.session}")
    print(f"  Source file:         {target.source_path}")
    print(f"  IV present:          {'yes' if target.iv else 'no'}")
    print(f"  # wavelength sweeps: {len(target.sweeps)}")
    if target.sweeps:
        biases = sorted(s.dc_bias_v for s in target.sweeps)
        print(f"  Bias points:         {biases}")
        sw0 = target.sweeps[0]
        print(f"  Wavelength range:    "
              f"{sw0.wavelength_nm.min():.2f}–{sw0.wavelength_nm.max():.2f} nm "
              f"({sw0.wavelength_nm.size} pts)")
    if target.iv is not None:
        v = target.iv.voltage
        i = target.iv.current
        print(f"  IV voltage range:    {v.min():.2f} to {v.max():.2f} V "
              f"({v.size} pts)")
        print(f"  |I| at -1 V:         {abs(target.iv.at(-1.0))*1e12:.2f} pA")
        print(f"  |I| at -2 V:         {abs(target.iv.at(-2.0))*1e12:.2f} pA")
    print()

    # Extracted features for this die (if MZM-shaped)
    if target.test_site in MZM_TEST_SITES:
        from picqa.extract.mzm import extract_one
        feat = extract_one(target)
        if feat is not None:
            print("  Extracted MZM features:")
            print(f"    FSR:                 {feat.fsr_nm:.3f} nm")
            print(f"    Notch @ 0V:          {feat.notch_at_0v_nm:.3f} nm")
            print(f"    dλ/dV:               {feat.dlambda_dv_pm_per_v:.2f} pm/V")
            print(f"    Peak IL:             {feat.peak_il_db:.2f} dB")
        # V-pi if extractable
        try:
            from picqa.analysis.phase_extraction import (
                parse_phaseshifter_length_um,
                vpi_from_slope,
            )
            slope_nm = (feat.dlambda_dv_pm_per_v / 1000.0) if feat else float("nan")
            vpi = vpi_from_slope(slope_nm, feat.fsr_nm) if feat else float("nan")
            L_um = parse_phaseshifter_length_um(target.device_name)
            if not (vpi != vpi):  # not NaN
                print(f"    Vπ:                  {vpi:.2f} V")
            if not (L_um != L_um) and not (vpi != vpi):
                print(f"    Vπ·L:                {vpi * L_um * 1e-4:.3f} V·cm  "
                      f"(L = {L_um:.0f} µm)")
        except Exception:
            pass
        print()

    # Optional plot
    if args.plot:
        if not args.output:
            args.output = f"{target.wafer}_{target.die}_{args.plot}.png".replace(
                "(", "").replace(")", "").replace(",", "_")
        out = Path(args.output)

        if args.plot == "bias_shift":
            from picqa.viz.spectrum_plot import plot_bias_shift
            plot_bias_shift(target, out)
        elif args.plot == "vpi_analysis":
            from picqa.viz.vpi_analysis import plot_vpi_analysis
            plot_vpi_analysis(target, out)
        elif args.plot == "vphi":
            from picqa.viz.uniformity_plot import plot_vphi_curve
            plot_vphi_curve(target, out)
        elif args.plot == "iv":
            import matplotlib.pyplot as plt
            import numpy as np
            if target.iv is None:
                print("No IV data for this die", file=sys.stderr)
                return 1
            fig, ax = plt.subplots(figsize=(7, 4.5))
            ax.semilogy(target.iv.voltage,
                        np.abs(target.iv.current) + 1e-13,
                        "ko-", markersize=5, lw=0.8)
            ax.set_xlabel("Voltage (V)")
            ax.set_ylabel("|Current| (A)")
            ax.set_title(f"IV: {target.wafer}/{target.die} ({target.band}-band)")
            ax.grid(alpha=0.3, which="both")
            fig.tight_layout()
            fig.savefig(out, dpi=130, bbox_inches="tight")
            plt.close(fig)
        elif args.plot == "spectrum":
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(9, 5))
            for sw in sorted(target.sweeps, key=lambda s: s.dc_bias_v):
                ax.plot(sw.wavelength_nm, sw.insertion_loss_db, lw=0.8,
                        label=f"{sw.dc_bias_v:+.1f} V")
            ax.set_xlabel("Wavelength (nm)")
            ax.set_ylabel("IL (dB)")
            ax.set_title(f"Spectra: {target.wafer}/{target.die}")
            ax.legend(fontsize=8, ncol=2)
            ax.grid(alpha=0.3)
            fig.tight_layout()
            fig.savefig(out, dpi=130, bbox_inches="tight")
            plt.close(fig)
        else:
            print(f"Unknown plot kind: {args.plot}", file=sys.stderr)
            return 2

        print(f"Plot saved → {out}")

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List dies in the dataset, optionally filtered.

    Examples
    --------
    picqa list <data-dir>                  # all MZM measurements
    picqa list <data-dir> D07              # only D07 dies
    picqa list <data-dir> --working-only   # skip failed-contact dies
    picqa list <data-dir> --band C
    """
    measurements = parse_directory(args.data_dir, test_site=list(MZM_TEST_SITES))

    if args.wafer:
        measurements = [m for m in measurements if m.wafer == args.wafer]
    if args.band:
        measurements = [m for m in measurements if m.band == args.band.upper()]

    if args.working_only:
        # Quick test: leakage at -1V > 1 nA
        measurements = [
            m for m in measurements
            if m.iv is not None and abs(m.iv.at(-1.0)) > 1e-9
        ]

    if not measurements:
        print("No measurements match those filters.")
        return 0

    # Pretty table
    print(f"{'Wafer':<6} {'Die':<10} {'Band':<5} {'Session':<22} "
          f"{'Device':<24} {'|I@-1V|':>12}")
    print("-" * 88)
    for m in measurements:
        leak_pa = abs(m.iv.at(-1.0)) * 1e12 if m.iv else float("nan")
        leak_str = f"{leak_pa:>10.1f} pA" if leak_pa == leak_pa else "        n/a"
        print(f"{m.wafer:<6} {m.die:<10} {m.band or '?':<5} "
              f"{m.session:<22} {m.device_name[:24]:<24} {leak_str:>12}")

    print(f"\n{len(measurements)} measurements")
    return 0


def cmd_fwhm(args: argparse.Namespace) -> int:
    """Extract FWHM and Q-factor for every die.

    Writes:
    * fwhm_features.csv         — die-level table (FWHM, Q, centre wavelength)
    * fwhm_annotated.png        — single-die illustrative plot
    * q_factor_distribution.png — population-level summary
    """
    from picqa.analysis.fwhm import extract_fwhm_features
    from picqa.viz.fwhm_plot import plot_fwhm_annotated, plot_q_factor_distribution

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    measurements = parse_directory(args.data_dir, test_site=list(MZM_TEST_SITES))
    df = extract_fwhm_features(measurements,
                               bias_v=args.bias, feature=args.feature,
                               drop_db=args.drop_db, flatten=not args.no_flatten)
    df.to_csv(out_dir / "fwhm_features.csv", index=False)

    n_valid = int(df["Q_factor"].notna().sum())
    print(f"\nExtracted {n_valid} / {len(df)} valid FWHM measurements")
    if n_valid:
        print(f"\nPer-wafer Q summary ({args.feature}):")
        per_wafer = (df.dropna(subset=["Q_factor"])
                       .groupby("Wafer")[["FWHM_nm", "Q_factor"]]
                       .agg(["count", "median", "std"]).round(2))
        print(per_wafer.to_string())

    # Pick a representative die for the annotated plot — use (0,0) closest
    target = None
    for m in measurements:
        if m.die_col == 0 and m.die_row == 0 and m.iv is not None \
                and abs(m.iv.at(-1.0)) > 1e-9:
            target = m
            break
    if target is None and measurements:
        # fallback to first working die
        for m in measurements:
            if m.iv is not None and abs(m.iv.at(-1.0)) > 1e-9:
                target = m
                break
    if target is not None:
        plot_fwhm_annotated(
            target, out_dir / "fwhm_annotated.png",
            bias_v=args.bias, feature=args.feature,
            drop_db=args.drop_db, flatten=not args.no_flatten,
        )
        print(f"\nAnnotated plot saved → {out_dir/'fwhm_annotated.png'}")

    if n_valid:
        plot_q_factor_distribution(
            df.dropna(subset=["Q_factor"]),
            out_dir / "q_factor_distribution.png",
        )
        print(f"Distribution plot saved → {out_dir/'q_factor_distribution.png'}")

        from picqa.viz.wafer_map import plot_fwhm_wafermap
        plot_fwhm_wafermap(
            df.dropna(subset=["Q_factor"]),
            out_dir / "fwhm_wafermap.png",
            show_q=True, per_band_scale=True,
        )
        print(f"Wafer map saved → {out_dir/'fwhm_wafermap.png'}")

    print(f"\nAll outputs saved to {out_dir}")
    return 0


def cmd_yield(args: argparse.Namespace) -> int:
    df = pd.read_csv(args.features)
    spec = load_spec(args.spec, args.family)
    evaluated = evaluate_yield(df, spec)
    summary = yield_summary(evaluated, group_by=["Wafer"])

    print(summary.to_string(index=False))
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        evaluated.to_csv(out, index=False)
        summary_path = out.with_name(out.stem + "_summary.csv")
        summary.to_csv(summary_path, index=False)
        print(f"Per-die → {out}")
        print(f"Summary → {summary_path}")
    return 0


def cmd_efficiency(args: argparse.Namespace) -> int:
    """Combine multiple parameters into a per-die efficiency score and
    identify wafer positions that consistently produce best devices.

    The default workflow merges MZM features with Vπ / ER from the phase
    extractor (when available) and writes:

    * efficiency_scored.csv      — every die with score columns
    * top_dies.csv               — top-N dies overall
    * position_summary.csv       — by-region / quadrant / radius stats
    * sweet_spots.csv            — positions consistently in the top tier
    * efficiency_wafermap.png    — colour map of EfficiencyScore per wafer
    * sweet_spots.png            — sweet-spot positions across wafers
    """
    from picqa.analysis.efficiency_map import (
        EfficiencyConfig,
        best_dies,
        compute_efficiency_score,
        find_sweet_spots,
        plot_efficiency_wafermap,
        plot_sweet_spots,
        position_summary,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    features = pd.read_csv(args.features)
    if "FailedContact" in features.columns and not args.include_failed:
        features = features[~features["FailedContact"]].copy()

    # Try to merge phase features for richer scoring
    if args.phase:
        try:
            phase = pd.read_csv(args.phase)
            keys = ["Wafer", "Session", "Die"]
            extra_cols = [c for c in ["Vpi_V", "Vpi_L_V_cm",
                                      "ER_at_-2V_dB", "ER_at_0V_dB"]
                          if c in phase.columns]
            if extra_cols:
                phase_subset = phase[keys + extra_cols]
                features = features.merge(phase_subset, on=keys, how="left")
                print(f"Merged phase columns: {extra_cols}")
        except FileNotFoundError:
            print(f"Warning: phase file not found at {args.phase}, "
                  f"continuing without Vπ/ER", file=sys.stderr)

    # Build config (allow per-wafer normalisation via flag)
    config = EfficiencyConfig()
    group_by = ["Wafer", "Band"] if args.normalise_per_wafer and "Band" in features.columns else None
    scored = compute_efficiency_score(features, config=config, group_by=group_by)

    # Save outputs
    scored.to_csv(out_dir / "efficiency_scored.csv", index=False)
    top = best_dies(scored, n=args.top_n)
    top.to_csv(out_dir / "top_dies.csv", index=False)
    pos = position_summary(scored)
    pos.to_csv(out_dir / "position_summary.csv", index=False)
    sweet = find_sweet_spots(scored, threshold_pct=args.threshold,
                             min_consistency=args.min_consistency)
    sweet.to_csv(out_dir / "sweet_spots.csv", index=False)

    plot_efficiency_wafermap(scored, out_dir / "efficiency_wafermap.png")
    plot_sweet_spots(sweet, out_dir / "sweet_spots.png")

    # Print headline info
    print(f"\n=== Efficiency analysis ===")
    print(f"Scored {len(scored)} dies")
    print(f"\nTop {args.top_n} dies:")
    cols = [c for c in ["Wafer", "Die", "Band", "Vpi_V",
                        "ER_at_-2V_dB", "PeakIL_dB",
                        "I_at_-1V_pA", "EfficiencyScore"]
            if c in top.columns]
    print(top[cols].to_string(index=False))

    print(f"\nPosition summary:")
    print(pos.to_string(index=False))

    print(f"\nSweet spots (top {len(sweet[sweet['is_sweet_spot']])} consistent positions):")
    sweet_only = sweet[sweet["is_sweet_spot"]]
    if not sweet_only.empty:
        print(sweet_only[["DieCol", "DieRow", "n_wafers_top",
                          "n_wafers_total", "mean_score",
                          "consistency_pct"]].to_string(index=False))
    else:
        print("(none — try lowering --threshold or --min-consistency)")

    print(f"\nAll outputs saved to {out_dir}")
    return 0


def cmd_uniformity(args: argparse.Namespace) -> int:
    """Project 1: wafer-level uniformity report."""
    from picqa.analysis.wafer_uniformity import (
        center_vs_edge,
        fsr_to_index_variation,
        iv_uniformity,
        per_radius_stats,
    )

    df = pd.read_csv(args.features)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Center vs edge for grating coupler IL (project 1, item 1)
    cve_il = center_vs_edge(df, "PeakIL_near_1310_dB",
                            group_by=["Wafer"])
    cve_il.to_csv(out_dir / "center_vs_edge_il.csv", index=False)

    # 2. FSR variation (project 1, item 2)
    fsr_var = fsr_to_index_variation(df, group_by=["Wafer", "Session"])
    fsr_var.to_csv(out_dir / "fsr_index_variation.csv", index=False)

    # 3. IV uniformity (project 1, item 3)
    iv_uni = iv_uniformity(df, metric="I_at_-1V_pA",
                           group_by=["Wafer", "Session"])
    iv_uni.to_csv(out_dir / "iv_uniformity.csv", index=False)

    # 4. Per-radius FSR stats
    rad_stats = per_radius_stats(df, "FSR_nm", group_by=["Wafer"])
    rad_stats.to_csv(out_dir / "fsr_per_radius.csv", index=False)

    print("Center vs edge IL:")
    print(cve_il.to_string(index=False))
    print("\nFSR / index variation:")
    print(fsr_var.to_string(index=False))
    print("\nIV uniformity (per session):")
    print(iv_uni.to_string(index=False))
    print(f"\nAll CSVs saved to {out_dir}")
    return 0


def cmd_phase(args: argparse.Namespace) -> int:
    """Project 2: extract V-phi metrics (Vπ, Vπ·L, ER)."""
    from picqa.analysis.phase_extraction import extract_phase_features
    from picqa.extract.mzm import extract_mzm_features
    from picqa.analysis.outlier import flag_failed_contacts

    measurements = parse_directory(args.data_dir, test_site=list(MZM_TEST_SITES))
    base = extract_mzm_features(measurements)
    base = flag_failed_contacts(base)
    augmented = extract_phase_features(measurements, base)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        augmented.to_csv(out, index=False)
        print(f"Saved {len(augmented)} rows → {out}")
        # Quick console summary
        working = augmented[~augmented["FailedContact"]]
        if not working.empty:
            print(f"\nVπ summary (working dies, n={len(working)}):")
            print(working.groupby("Wafer")["Vpi_V"].describe()
                  [["count", "mean", "50%", "std"]].to_string())
    else:
        print(augmented.head(15).to_string(index=False))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    spec = None
    if args.spec and args.family:
        spec = load_spec(args.spec, args.family)
    md = generate_report(args.data_dir, args.output_dir, spec=spec)
    print(f"Report → {md}")
    return 0


# --------------------------------------------------------------------- #
# Argparse setup
# --------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="picqa",
        description="Photonic IC Quality Analyzer",
    )
    p.add_argument("-V", "--version", action="version", version=f"picqa {__version__}")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="enable INFO logging")
    sub = p.add_subparsers(dest="command", required=True)

    # inventory
    sp = sub.add_parser("inventory", help="summarise files under a data directory")
    sp.add_argument("data_dir")
    sp.set_defaults(func=cmd_inventory)

    # parse
    sp = sub.add_parser("parse", help="parse XMLs to a pickle of Measurements")
    sp.add_argument("data_dir")
    sp.add_argument("--test-site", default=None,
                    help="filter by test site (e.g. DCM_LMZO)")
    sp.add_argument("--output", "-o", default=None)
    sp.set_defaults(func=cmd_parse)

    # extract
    sp = sub.add_parser("extract", help="extract device features to CSV")
    sp.add_argument("device", choices=["mzm", "pd", "pn"])
    sp.add_argument("data_dir")
    sp.add_argument("--output", "-o", default=None)
    sp.set_defaults(func=cmd_extract)

    # plot
    sp = sub.add_parser("plot", help="generate a figure")
    sp.add_argument("kind",
                    choices=["iv", "spectra", "wafermap", "summary",
                             "pn_length", "pn_summary",
                             "radial", "center_vs_edge", "vpi", "vphi",
                             "vpi_analysis", "fwhm_wafermap"])
    sp.add_argument("input", help="data directory or features CSV depending on kind")
    sp.add_argument("--output", "-o", required=True)
    sp.add_argument("--bias", type=float, default=-2.0,
                    help="DC bias for spectra plot (default: -2.0 V)")
    sp.add_argument("--spectra-mode", default="median_band",
                    choices=["median_band", "overlay", "single"],
                    help="how to display multi-die spectra: median_band "
                         "(default, median + 5-95%% range), overlay (all "
                         "dies in distinct colours + median bold), or "
                         "single (one die per session)")
    sp.add_argument("--metric", default=None,
                    help="metric column for wafermap/radial/center_vs_edge plots")
    sp.set_defaults(func=cmd_plot)

    # yield
    sp = sub.add_parser("yield", help="apply spec and compute yield")
    sp.add_argument("features", help="features CSV from `picqa extract`")
    sp.add_argument("--spec", required=True)
    sp.add_argument("--family", required=True, help="spec family name (e.g. mzm)")
    sp.add_argument("--output", "-o", default=None)
    sp.set_defaults(func=cmd_yield)

    # report
    sp = sub.add_parser("report", help="generate a Markdown report")
    sp.add_argument("data_dir")
    sp.add_argument("--output-dir", "-o", required=True)
    sp.add_argument("--spec", default=None,
                    help="optional spec YAML for yield evaluation")
    sp.add_argument("--family", default=None,
                    help="spec family name (required if --spec given)")
    sp.set_defaults(func=cmd_report)

    # uniformity (project 1)
    sp = sub.add_parser("uniformity",
                        help="wafer-level uniformity analysis (project 1)")
    sp.add_argument("features", help="MZM features CSV from `picqa extract mzm`")
    sp.add_argument("--output-dir", "-o", required=True)
    sp.set_defaults(func=cmd_uniformity)

    # phase (project 2)
    sp = sub.add_parser("phase",
                        help="V-phi extraction: Vπ, Vπ·L, ER (project 2)")
    sp.add_argument("data_dir")
    sp.add_argument("--output", "-o", default=None)
    sp.set_defaults(func=cmd_phase)

    # FWHM and Q-factor
    sp = sub.add_parser("fwhm",
                        help="FWHM and Q-factor extraction from spectra")
    sp.add_argument("data_dir")
    sp.add_argument("--output-dir", "-o", required=True)
    sp.add_argument("--bias", type=float, default=-2.0,
                    help="DC bias at which to measure FWHM (default -2.0 V)")
    sp.add_argument("--feature", default="peak", choices=["peak", "notch"],
                    help="measure the FWHM of a transmission peak (default) "
                         "or a notch (dip)")
    sp.add_argument("--drop-db", type=float, default=3.0,
                    help="dB level for the FWHM measurement (default 3.0 = -3 dB)")
    sp.add_argument("--no-flatten", action="store_true",
                    help="skip the grating-coupler envelope subtraction")
    sp.set_defaults(func=cmd_fwhm)

    # efficiency (cross-parameter scoring + sweet-spot map)
    sp = sub.add_parser("efficiency",
                        help="combine all parameters into one die-quality score")
    sp.add_argument("features",
                    help="MZM features CSV from `picqa extract mzm`")
    sp.add_argument("--phase", default=None,
                    help="optional phase features CSV (adds Vπ, ER to the score)")
    sp.add_argument("--output-dir", "-o", required=True)
    sp.add_argument("--top-n", type=int, default=10,
                    help="how many top dies to list (default 10)")
    sp.add_argument("--threshold", type=float, default=75.0,
                    help="percentile threshold for sweet-spot detection (default 75)")
    sp.add_argument("--min-consistency", type=int, default=2,
                    help="number of wafers a position must be in the top tier "
                         "to count as a sweet spot (default 2)")
    sp.add_argument("--normalise-per-wafer", action="store_true",
                    help="normalise each metric within (Wafer, Band) groups so "
                         "absolute differences between wafers don't dominate")
    sp.add_argument("--include-failed", action="store_true",
                    help="include FailedContact dies in the scoring")
    sp.set_defaults(func=cmd_efficiency)

    # show (per-die inspection)
    sp = sub.add_parser("show",
                        help="show one die's data and optionally plot it")
    sp.add_argument("data_dir")
    sp.add_argument("wafer", help="wafer ID, e.g. D08")
    sp.add_argument("die", help="die coordinate, e.g. (0,0) or 0,0")
    sp.add_argument("--band", default=None, choices=["O", "C", "L", "S", "E", "U"],
                    help="disambiguate when a die exists in multiple bands")
    sp.add_argument("--session", default=None,
                    help="filter by session substring")
    sp.add_argument("--test-site", default=None,
                    help="restrict to one test site (default: all MZM sites)")
    sp.add_argument("--plot", default=None,
                    choices=["bias_shift", "vpi_analysis", "vphi", "iv", "spectrum"],
                    help="also save a plot of this kind")
    sp.add_argument("--output", "-o", default=None,
                    help="output PNG path (auto-named if omitted)")
    sp.set_defaults(func=cmd_show)

    # list (browse / filter dies)
    sp = sub.add_parser("list",
                        help="list MZM dies, optionally filtered")
    sp.add_argument("data_dir")
    sp.add_argument("wafer", nargs="?", default=None,
                    help="optional wafer ID to filter by")
    sp.add_argument("--band", default=None, choices=["O", "C", "L", "S", "E", "U"])
    sp.add_argument("--working-only", action="store_true",
                    help="skip dies whose contact was bad (|I@-1V| < 1 nA)")
    sp.set_defaults(func=cmd_list)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
