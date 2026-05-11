#!/usr/bin/env python3
"""End-to-end analysis runner for picqa.

Usage
-----
    python run.py                              # use defaults
    python run.py --data ./mydata --out ./res  # custom paths
    python run.py --quick                      # skip slow steps

One invocation produces every CSV, every figure, the integrated
Markdown report, and per-wafer subfolders. Use this for batch runs,
CI, or just "I want all results from a fresh dataset".

For step-by-step analysis with commentary, open the companion notebook
``picqa_analysis.ipynb`` instead.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run every picqa analysis end-to-end.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--data", type=Path, default=Path("data"),
                   help="Root directory containing wafer subfolders "
                        "(e.g. data/D07/...)")
    p.add_argument("--out", type=Path, default=Path("results"),
                   help="Output directory; will be created if missing")
    p.add_argument("--spec", type=Path,
                   default=None,
                   help="MZM spec YAML (default: configs/mzm_spec.yaml "
                        "relative to picqa package)")
    p.add_argument("--family", default="mzm",
                   help="spec family name in the YAML")
    p.add_argument("--quick", action="store_true",
                   help="Skip slow steps (full report, per-wafer figures). "
                        "Useful for development iteration.")
    p.add_argument("--verbose", "-v", action="count", default=0,
                   help="-v for INFO, -vv for DEBUG logging")
    return p.parse_args()


def setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(name)s : %(message)s",
        datefmt="%H:%M:%S",
    )


def step(name: str):
    """Decorator-like context that times each pipeline step."""
    class _Step:
        def __enter__(self):
            print(f"\n[{name}] …")
            self.t0 = time.time()
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            dt = time.time() - self.t0
            status = "FAILED" if exc_type else "done"
            print(f"[{name}] {status} ({dt:.1f}s)")
            return False  # propagate exceptions
    return _Step()


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)

    # Late imports so --help is fast and so import errors don't mask args parsing
    try:
        from picqa.analysis.efficiency_map import (
            compute_efficiency_score,
            find_combined_sweet_spots,
            find_sweet_spots,
            find_sweet_spots_multi_metric,
        )
        from picqa.analysis.fwhm import extract_fwhm_features
        from picqa.analysis.outlier import flag_failed_contacts
        from picqa.analysis.phase_extraction import extract_phase_features
        from picqa.extract.mzm import MZM_TEST_SITES, extract_mzm_features
        from picqa.io.xml_parser import parse_directory
        from picqa.report.markdown import generate_report
    except ImportError as e:
        print(f"ERROR: picqa is not importable ({e}).", file=sys.stderr)
        print("Run `pip install -e .` from the project root first.",
              file=sys.stderr)
        return 1

    # Defaults that depend on the package location
    if args.spec is None:
        import picqa
        pkg_root = Path(picqa.__file__).parent.parent.parent
        args.spec = pkg_root / "configs" / "mzm_spec.yaml"

    # Sanity-check inputs
    if not args.data.is_dir():
        print(f"\nERROR: data directory '{args.data}' does not exist.",
              file=sys.stderr)
        print("", file=sys.stderr)
        print("picqa needs a directory of measurement XML files to analyse.",
              file=sys.stderr)
        print("Expected layout:", file=sys.stderr)
        print("    <data-dir>/<WaferID>/<SessionID>/<TestSite>/*.xml",
              file=sys.stderr)
        print("e.g. data/D08/20190526_082853/DCM_LMZO/<files>.xml",
              file=sys.stderr)
        print("", file=sys.stderr)
        print("If you have the HY202103 dataset:", file=sys.stderr)
        print("    1. Unzip HY202103.zip into the project root", file=sys.stderr)
        print("    2. Rename the extracted folder to 'data' "
              "(or pass --data <your-folder>)", file=sys.stderr)
        print("    3. Re-run this script", file=sys.stderr)
        print("", file=sys.stderr)
        print("If you don't have the dataset yet, request it from your "
              "data source. picqa is a library — measurement data is",
              file=sys.stderr)
        print("distributed separately to keep the package small.",
              file=sys.stderr)
        return 1
    if not args.spec.is_file():
        print(f"WARNING: --spec file {args.spec} not found; yield analysis "
              f"will be skipped.", file=sys.stderr)
        args.spec = None

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"Data:    {args.data}")
    print(f"Output:  {args.out}")
    print(f"Spec:    {args.spec}")
    print(f"Family:  {args.family}")
    print(f"Quick:   {args.quick}")

    # ---------- The full pipeline ---------- #
    if args.quick:
        # Quick mode: just parse + extract MZM + FWHM + phase
        with step("Parse XML files"):
            measurements = parse_directory(args.data,
                                           test_site=list(MZM_TEST_SITES))
            print(f"  → {len(measurements)} measurements loaded")

        with step("Extract MZM features"):
            mzm_df = extract_mzm_features(measurements)
            mzm_df = flag_failed_contacts(mzm_df)
            mzm_df.to_csv(args.out / "mzm_features.csv", index=False)
            n_failed = int(mzm_df["FailedContact"].sum())
            print(f"  → {len(mzm_df)} rows, {n_failed} failed-contact dies")

        with step("Extract phase features (Vπ, Vπ·L, ER)"):
            phase_df = extract_phase_features(measurements, mzm_df)
            phase_df.to_csv(args.out / "phase_features.csv", index=False)
            print(f"  → {phase_df['Vpi_V'].notna().sum()} dies with valid Vπ")

        with step("Extract FWHM / Q-factor"):
            fwhm_df = extract_fwhm_features(measurements, feature="peak")
            fwhm_df.to_csv(args.out / "fwhm_features.csv", index=False)
            print(f"  → {fwhm_df['Q_factor'].notna().sum()} dies with valid Q")

        with step("Compute efficiency + sweet spots"):
            import pandas as pd
            keys = ["Wafer", "Session", "Die"]
            merged = mzm_df.merge(
                phase_df[keys + ["Vpi_V", "Vpi_L_V_cm", "ER_at_-2V_dB"]],
                on=keys, how="left",
            ).merge(
                fwhm_df[keys + ["FWHM_nm", "Q_factor"]],
                on=keys, how="left",
            )
            working = merged[~merged["FailedContact"]].copy()
            scored = compute_efficiency_score(working)
            scored.to_csv(args.out / "efficiency_scored.csv", index=False)
            sweet = find_sweet_spots(scored)
            sweet.to_csv(args.out / "sweet_spots.csv", index=False)
            multi = find_sweet_spots_multi_metric(scored)
            combined = find_combined_sweet_spots(multi, min_axes_agreeing=2)
            if not combined.empty:
                combined.to_csv(args.out / "combined_sweet_spots.csv",
                                index=False)
            n_sweet = int(sweet["is_sweet_spot"].sum())
            print(f"  → {len(scored)} scored, {n_sweet} sweet positions")
        return 0

    # Full mode: defer everything to the integrated report
    with step("Full integrated report (parse + extract + plot + report)"):
        spec_obj = None
        if args.spec is not None:
            from picqa.analysis.yield_calc import load_spec
            spec_obj = load_spec(args.spec, args.family)
        md = generate_report(args.data, args.out, spec=spec_obj)
        print(f"  → Markdown report: {md}")
        # Quick inventory of what landed
        figs = sorted((args.out / "figures").glob("**/*.png"))
        csvs = sorted(args.out.glob("*.csv"))
        print(f"  → {len(figs)} figures, {len(csvs)} CSV files")

    print("\nAll outputs in:")
    print(f"  {args.out.resolve()}")
    print("\nKey deliverables:")
    print(f"  - {args.out}/report.md            ← Markdown report")
    print(f"  - {args.out}/figures/             ← all plots")
    print(f"  - {args.out}/efficiency_scored.csv")
    print(f"  - {args.out}/combined_sweet_spots.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
