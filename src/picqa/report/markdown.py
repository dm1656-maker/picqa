"""Generate a self-contained Markdown report.

The report bundles inventory, MZM features, statistics, yield (if a spec is
provided), and embedded PNG figures into a single Markdown file.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from picqa.analysis.outlier import flag_failed_contacts
from picqa.analysis.statistics import per_group_stats
from picqa.analysis.yield_calc import Spec, evaluate_yield, yield_summary
from picqa.extract.mzm import MZM_TEST_SITES, extract_mzm_features
from picqa.io.schemas import Measurement
from picqa.io.xml_parser import inventory, parse_directory
from picqa.viz.iv_plot import plot_iv_grid
from picqa.viz.spectrum_plot import plot_bias_shift, plot_spectra_grid
from picqa.viz.summary_plot import plot_summary
from picqa.viz.wafer_map import plot_wafermap_grid


METRICS_FOR_STATS = [
    "FSR_nm",
    "Notch_at_0V_nm",
    "dLambda_dV_pm_per_V",
    "PeakIL_dB",
    "I_at_-1V_pA",
]


def _df_to_md(df: pd.DataFrame, *, max_rows: int = 50) -> str:
    """Convert a DataFrame to a GitHub-flavoured Markdown table.

    Uses ``pandas.DataFrame.to_markdown`` if the ``tabulate`` dependency is
    available, otherwise falls back to a simple hand-rolled formatter so the
    library has no hard runtime dependency on tabulate.
    """
    if df.empty:
        return "_(empty)_"
    if len(df) > max_rows:
        df = df.head(max_rows)
    try:
        return df.to_markdown(index=False, floatfmt=".4g")
    except ImportError:
        return _df_to_md_fallback(df)


def _df_to_md_fallback(df: pd.DataFrame) -> str:
    """Minimal Markdown table renderer (no external deps)."""
    def _fmt(v):
        if isinstance(v, float):
            return f"{v:.4g}"
        return str(v)

    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |"]
    lines.append("|" + "|".join("---" for _ in cols) + "|")
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(_fmt(row[c]) for c in df.columns) + " |")
    return "\n".join(lines)


def generate_report(
    data_dir: str | Path,
    output_dir: str | Path,
    *,
    spec: Spec | None = None,
    measurements: list[Measurement] | None = None,
    title: str = "PICQA Analysis Report",
) -> Path:
    """Run the full analysis pipeline and write a Markdown report.

    Parameters
    ----------
    data_dir : str | Path
        Directory containing the raw XML measurement files.
    output_dir : str | Path
        Where to write the report and its figures.
    spec : Spec | None
        If provided, a yield evaluation section is added.
    measurements : list[Measurement] | None
        Pre-parsed measurements. If ``None``, parses ``data_dir`` directly.
    title : str
        Title for the report.

    Returns
    -------
    Path
        Path to ``report.md``.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(exist_ok=True)

    inv = inventory(data_dir)
    if measurements is None:
        measurements = parse_directory(data_dir, test_site=list(MZM_TEST_SITES))

    features = extract_mzm_features(measurements)
    features = flag_failed_contacts(features)
    features.to_csv(out_dir / "mzm_features.csv", index=False)

    # PN modulator analysis (independent parser/extractor)
    pn_seg_df = pd.DataFrame()
    pn_fit_df = pd.DataFrame()
    try:
        from picqa.extract.pn_modulator import (
            extract_pn_length_fit,
            extract_pn_segment_features,
        )
        from picqa.io.pn_parser import parse_pn_directory
        pn_measurements = parse_pn_directory(data_dir)
        if pn_measurements:
            pn_seg_df = extract_pn_segment_features(pn_measurements)
            pn_fit_df = extract_pn_length_fit(pn_seg_df)
            pn_seg_df.to_csv(out_dir / "pn_segments.csv", index=False)
            pn_fit_df.to_csv(out_dir / "pn_length_fit.csv", index=False)
    except Exception as exc:
        # PN data is optional; don't break the whole report
        import logging
        logging.getLogger(__name__).warning("PN analysis skipped: %s", exc)

    # Figures (skip gracefully if data missing)
    fig_paths: dict[str, Path | None] = {}
    try:
        fig_paths["iv"] = plot_iv_grid(measurements, fig_dir / "iv.png")
    except Exception:
        fig_paths["iv"] = None
    try:
        fig_paths["spectra"] = plot_spectra_grid(
            measurements, fig_dir / "spectra.png", mode="median_band",
        )
        # Also produce a clean per-session single-die view alongside
        try:
            fig_paths["spectra_single"] = plot_spectra_grid(
                measurements, fig_dir / "spectra_single.png", mode="single",
            )
        except Exception:
            fig_paths["spectra_single"] = None
    except Exception:
        fig_paths["spectra"] = None
    try:
        # bias-shift: prefer a working die where the 0V sweep has at least
        # 3 clear notches (prominence >= 8 dB), so the figure looks good.
        from scipy.signal import find_peaks
        good_dies = features[~features["FailedContact"]]
        target = None
        for _, row in good_dies.iterrows():
            cand = next(
                (m for m in measurements
                 if m.wafer == row["Wafer"]
                 and m.session == row["Session"]
                 and m.die == row["Die"]),
                None,
            )
            if cand is None:
                continue
            sw0 = cand.sweep_at_bias(0.0)
            if sw0 is None:
                continue
            peaks, _ = find_peaks(-sw0.insertion_loss_db, prominence=8.0)
            if peaks.size >= 3:
                target = cand
                break
        if target is None and not good_dies.empty:
            # Fall back to the first working die regardless of notches
            row = good_dies.iloc[0]
            target = next(
                (m for m in measurements
                 if m.wafer == row["Wafer"]
                 and m.session == row["Session"]
                 and m.die == row["Die"]),
                None,
            )
        if target is not None:
            fig_paths["bias"] = plot_bias_shift(target, fig_dir / "bias_shift.png")
        else:
            fig_paths["bias"] = None
    except Exception:
        fig_paths["bias"] = None
    try:
        fig_paths["wafermap"] = plot_wafermap_grid(
            features,
            metrics=["I_at_-1V_pA", "PeakIL_near_1310_dB"],
            output_path=fig_dir / "wafermaps.png",
        )
    except Exception:
        fig_paths["wafermap"] = None
    try:
        fig_paths["summary"] = plot_summary(features, fig_dir / "summary.png")
    except Exception:
        fig_paths["summary"] = None

    # PN figures
    if not pn_seg_df.empty:
        try:
            from picqa.viz.pn_plot import plot_pn_length_dependence, plot_pn_summary
            fig_paths["pn_length"] = plot_pn_length_dependence(
                pn_seg_df, fig_dir / "pn_length.png"
            )
            if not pn_fit_df.empty:
                fig_paths["pn_summary"] = plot_pn_summary(
                    pn_fit_df, fig_dir / "pn_summary.png"
                )
        except Exception:
            fig_paths["pn_length"] = None
            fig_paths["pn_summary"] = None

    # Project 1: wafer-level uniformity analysis
    uniformity_dfs = {}
    try:
        from picqa.analysis.wafer_uniformity import (
            center_vs_edge,
            fsr_to_index_variation,
            iv_uniformity,
        )
        from picqa.viz.uniformity_plot import (
            plot_center_vs_edge,
            plot_radial_dependence,
        )
        uniformity_dfs["cve_il"] = center_vs_edge(
            features, "PeakIL_near_1310_dB", group_by=["Wafer"]
        )
        uniformity_dfs["fsr_var"] = fsr_to_index_variation(
            features, group_by=["Wafer", "Session"]
        )
        uniformity_dfs["iv_uni"] = iv_uniformity(
            features, metric="I_at_-1V_pA", group_by=["Wafer", "Session"]
        )
        uniformity_dfs["cve_il"].to_csv(out_dir / "center_vs_edge_il.csv", index=False)
        uniformity_dfs["fsr_var"].to_csv(out_dir / "fsr_index_variation.csv", index=False)
        uniformity_dfs["iv_uni"].to_csv(out_dir / "iv_uniformity.csv", index=False)
        fig_paths["radial_il"] = plot_radial_dependence(
            features, "PeakIL_near_1310_dB", fig_dir / "radial_il.png",
            title="Grating coupler IL vs wafer radius",
        )
        fig_paths["center_vs_edge"] = plot_center_vs_edge(
            features,
            ["FSR_nm", "PeakIL_near_1310_dB", "I_at_-1V_pA"],
            fig_dir / "center_vs_edge.png",
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Uniformity analysis skipped: %s", exc)

    # Project 2: V-phi extraction (Vπ, Vπ·L, ER)
    phase_df = pd.DataFrame()
    try:
        from picqa.analysis.phase_extraction import extract_phase_features
        from picqa.viz.uniformity_plot import plot_vpi_distribution, plot_vphi_curve
        from picqa.viz.vpi_analysis import plot_vpi_analysis
        phase_df = extract_phase_features(measurements, features)
        phase_df.to_csv(out_dir / "phase_features.csv", index=False)
        # Pick a representative working die for the V-phi curve
        good = phase_df[~phase_df.get("FailedContact", pd.Series(False, index=phase_df.index))]
        if not good.empty:
            row0 = good.iloc[0]
            target = next(
                (m for m in measurements
                 if m.wafer == row0["Wafer"] and m.session == row0["Session"]
                 and m.die == row0["Die"]),
                None,
            )
            if target is not None:
                fig_paths["vphi"] = plot_vphi_curve(target, fig_dir / "vphi_curve.png")
                # Also produce the detailed six-panel V-phi analysis
                try:
                    fig_paths["vpi_analysis"] = plot_vpi_analysis(
                        target, fig_dir / "vpi_analysis.png",
                    )
                except Exception:
                    fig_paths["vpi_analysis"] = None
                # V-λ wavelength-modulation-efficiency plot
                try:
                    from picqa.viz.uniformity_plot import plot_v_lambda
                    fig_paths["v_lambda"] = plot_v_lambda(
                        target, fig_dir / "v_lambda.png",
                    )
                except Exception:
                    fig_paths["v_lambda"] = None
        fig_paths["vpi_dist"] = plot_vpi_distribution(
            phase_df, fig_dir / "vpi_distribution.png"
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Phase extraction skipped: %s", exc)

    # Per-wafer representative-die figures (default: closest to (0,0))
    try:
        per_wafer_summary = _build_per_wafer_figures(
            measurements, features, fig_dir,
        )
        fig_paths["per_wafer"] = per_wafer_summary
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Per-wafer figures skipped: %s", exc)
        fig_paths["per_wafer"] = {}

    # Cross-parameter efficiency analysis (combines MZM + phase metrics)
    efficiency_df = pd.DataFrame()
    sweet_df = pd.DataFrame()
    pos_df = pd.DataFrame()
    multi_sweet_df = pd.DataFrame()
    try:
        from picqa.analysis.efficiency_map import (
            compute_efficiency_score,
            find_combined_sweet_spots,
            find_sweet_spots,
            find_sweet_spots_multi_metric,
            plot_combined_sweet_spots,
            plot_efficiency_wafermap,
            plot_multi_metric_sweet_spots,
            plot_sweet_spots,
            position_summary,
        )
        # Merge phase columns into features for richer scoring
        scoring_input = features.copy()
        keys = ["Wafer", "Session", "Die"]
        if not phase_df.empty:
            extra_cols = [c for c in ["Vpi_V", "Vpi_L_V_cm",
                                      "ER_at_-2V_dB", "ER_at_0V_dB"]
                          if c in phase_df.columns]
            if extra_cols:
                scoring_input = scoring_input.merge(
                    phase_df[keys + extra_cols], on=keys, how="left",
                )
        # Skip failed-contact dies for fair scoring
        if "FailedContact" in scoring_input.columns:
            scoring_input = scoring_input[~scoring_input["FailedContact"]].copy()

        if not scoring_input.empty:
            efficiency_df = compute_efficiency_score(scoring_input)
            efficiency_df.to_csv(out_dir / "efficiency_scored.csv", index=False)
            pos_df = position_summary(efficiency_df)
            pos_df.to_csv(out_dir / "position_summary.csv", index=False)
            sweet_df = find_sweet_spots(efficiency_df)
            sweet_df.to_csv(out_dir / "sweet_spots.csv", index=False)
            fig_paths["efficiency_map"] = plot_efficiency_wafermap(
                efficiency_df, fig_dir / "efficiency_wafermap.png",
            )
            fig_paths["sweet_spots"] = plot_sweet_spots(
                sweet_df, fig_dir / "sweet_spots.png",
            )

            # Per-metric sweet spots (Q, Vπ separately)
            try:
                multi = find_sweet_spots_multi_metric(efficiency_df)
                if multi:
                    fig_paths["multi_sweet"] = plot_multi_metric_sweet_spots(
                        multi, fig_dir / "multi_metric_sweet_spots.png",
                    )
                    multi_sweet_df = find_combined_sweet_spots(
                        multi, min_axes_agreeing=2,
                    )
                    if not multi_sweet_df.empty:
                        multi_sweet_df.to_csv(
                            out_dir / "combined_sweet_spots.csv", index=False,
                        )
                    fig_paths["combined_sweet"] = plot_combined_sweet_spots(
                        multi_sweet_df,
                        fig_dir / "combined_sweet_spots.png",
                        all_die_positions=efficiency_df[["DieCol", "DieRow"]],
                    )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "Multi-metric sweet spot analysis skipped",
                    exc_info=True,
                )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Efficiency analysis skipped: %s", exc)

    # Statistics
    stats = per_group_stats(features, group_by=["Wafer", "Session"], metrics=METRICS_FOR_STATS)
    stats.to_csv(out_dir / "stats_per_session.csv", index=False)

    # Yield (optional)
    yield_section = ""
    if spec is not None:
        evaluated = evaluate_yield(features, spec)
        evaluated.to_csv(out_dir / "yield_per_die.csv", index=False)
        per_wafer = yield_summary(evaluated, group_by=["Wafer"])
        per_session = yield_summary(evaluated, group_by=["Wafer", "Session"])
        per_wafer.to_csv(out_dir / "yield_per_wafer.csv", index=False)
        per_session.to_csv(out_dir / "yield_per_session.csv", index=False)
        yield_section = (
            "## Yield evaluation\n\n"
            f"Spec: `{spec.name}` with rules: `{spec.rules}`\n\n"
            "### Per-wafer yield\n\n"
            f"{_df_to_md(per_wafer)}\n\n"
            "### Per-session yield\n\n"
            f"{_df_to_md(per_session)}\n"
        )

    # Compose Markdown
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"_Generated {timestamp} by picqa._")
    lines.append("")
    lines.append("## Inventory")
    lines.append("")
    lines.append(f"- Source directory: `{Path(data_dir).resolve()}`")
    lines.append(f"- Total XML files: **{inv['n_files']}** "
                 f"({inv['total_size_bytes']/1e6:.1f} MB)")
    lines.append("- Files per wafer: " + ", ".join(
        f"{k}={v}" for k, v in inv["by_wafer"].items()
    ))
    lines.append("")
    lines.append("### Test site distribution")
    lines.append("")
    lines.append("| Test site | Count |")
    lines.append("|---|---|")
    for k, v in inv["by_test_site"].items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    lines.append("## MZM feature extraction")
    lines.append("")
    lines.append(f"Extracted {len(features)} MZM measurements from "
                 f"`DCM_LMZO` (O-band) and `DCM_LMZC` (C-band). "
                 f"Failed-contact flag added via leakage + tuning-slope thresholds.")
    if "FailedContact" in features.columns:
        n_fail = int(features["FailedContact"].sum())
        lines.append(f"Flagged as failed-contact: **{n_fail} / {len(features)}**")
    if "Band" in features.columns and features["Band"].notna().any():
        band_counts = features.groupby(["Wafer", "Band"]).size().reset_index(name="n")
        lines.append("")
        lines.append("**Wafer × band breakdown:**")
        lines.append("")
        lines.append(_df_to_md(band_counts))
    lines.append("")
    lines.append("Sample of features (first 20 rows):")
    lines.append("")
    lines.append(_df_to_md(features.head(20)))
    lines.append("")

    lines.append("## Robust statistics per (wafer, session)")
    lines.append("")
    lines.append(_df_to_md(stats))
    lines.append("")

    if yield_section:
        lines.append(yield_section)

    # Project 1: wafer-level uniformity analysis
    if uniformity_dfs:
        lines.append("## Project 1 — Wafer-level process uniformity")
        lines.append("")
        if "cve_il" in uniformity_dfs and not uniformity_dfs["cve_il"].empty:
            lines.append("### Grating coupler IL: center vs edge dies")
            lines.append("")
            lines.append("Edge_radius threshold = 2.5 die-units (R ≤ 2.5 → center).")
            lines.append("")
            lines.append(_df_to_md(uniformity_dfs["cve_il"]))
            lines.append("")
        if "fsr_var" in uniformity_dfs and not uniformity_dfs["fsr_var"].empty:
            lines.append("### FSR variation → implied geometry / index variation")
            lines.append("")
            lines.append("`FSR_relative_variation_pct = σ(FSR) / mean(FSR) × 100`. "
                         "For an unbalanced MZI, this approximates Δn_g/n_g, which in turn "
                         "reflects waveguide width / thickness uniformity across the wafer.")
            lines.append("")
            lines.append(_df_to_md(uniformity_dfs["fsr_var"]))
            lines.append("")
        if "iv_uni" in uniformity_dfs and not uniformity_dfs["iv_uni"].empty:
            lines.append("### IV uniformity (leakage at -1 V)")
            lines.append("")
            lines.append("Per-session statistics including robust median + MAD-based σ "
                         "alongside parametric mean / std / CV. Sessions with failed contact "
                         "show extremely low absolute means (~100 pA) compared to working "
                         "ones (10⁴–10⁵ pA).")
            lines.append("")
            lines.append(_df_to_md(uniformity_dfs["iv_uni"]))
            lines.append("")

    # Project 2: V-phi
    if not phase_df.empty:
        lines.append("## Project 2 — Voltage-based phase modulator characterisation")
        lines.append("")
        n_with_vpi = int(phase_df["Vpi_V"].notna().sum())
        lines.append(f"Extracted Vπ, Vπ·L, and extinction ratio for {n_with_vpi}/{len(phase_df)} dies. "
                     f"Vπ = FSR / (2·|dλ/dV|). Phase-shifter length is parsed best-effort from "
                     f"the device name; if absent, Vπ·L is left as NaN.")
        lines.append("")
        per_wafer_vpi = (
            phase_df[~phase_df["FailedContact"]]
            .groupby("Wafer")[["Vpi_V", "Vpi_L_V_cm", "ER_at_-2V_dB"]]
            .agg(["count", "median", "std"])
            .round(3)
        )
        if not per_wafer_vpi.empty:
            lines.append("### Per-wafer Vπ summary (working dies)")
            lines.append("")
            # Flatten multi-index columns for prettier markdown
            flat = per_wafer_vpi.copy()
            flat.columns = [f"{a}_{b}" for a, b in flat.columns]
            flat = flat.reset_index()
            lines.append(_df_to_md(flat))
            lines.append("")

    # Cross-parameter efficiency
    if not efficiency_df.empty:
        lines.append("## Cross-parameter efficiency analysis")
        lines.append("")
        lines.append(
            "Each parameter is normalised to a 0–1 score (1 = best in this dataset) "
            "and combined with the default weights "
            "(Vπ ×2, ER ×1.5, IL ×1, leakage ×1, FSR ×0.5) into a single "
            "**EfficiencyScore** per die. Scoring is robust to a few outliers "
            "(uses the 5–95th percentile range), and dies with NaN metrics get "
            "the remaining weights re-distributed."
        )
        lines.append("")
        lines.append("### Top dies overall")
        lines.append("")
        top_n = efficiency_df.dropna(
            subset=["EfficiencyScore"]
        ).nlargest(10, "EfficiencyScore")
        cols_show = [c for c in ["Wafer", "Die", "Band", "Vpi_V",
                                 "ER_at_-2V_dB", "PeakIL_dB",
                                 "I_at_-1V_pA", "EfficiencyScore"]
                     if c in top_n.columns]
        lines.append(_df_to_md(top_n[cols_show]))
        lines.append("")
        if not pos_df.empty:
            lines.append("### Position summary (mean efficiency by region)")
            lines.append("")
            lines.append(_df_to_md(pos_df.round(3)))
            lines.append("")
        if not sweet_df.empty:
            sweet_only = sweet_df[sweet_df["is_sweet_spot"]]
            if not sweet_only.empty:
                lines.append(
                    "### Sweet spots — positions in the top tier on ≥ 2 wafers"
                )
                lines.append("")
                lines.append(
                    _df_to_md(sweet_only[["DieCol", "DieRow", "n_wafers_top",
                                          "n_wafers_total", "mean_score",
                                          "consistency_pct"]].round(3))
                )
                lines.append("")
                lines.append(
                    "**Interpretation:** these die positions consistently "
                    "produce devices in the upper quartile of efficiency "
                    "across multiple wafers, suggesting that the process "
                    "favours these locations. Keeping such dies preferentially "
                    "during binning would raise overall yield."
                )
                lines.append("")

        # Multi-axis sweet spots
        if not multi_sweet_df.empty:
            lines.append("### Combined sweet spots — strong on multiple metrics")
            lines.append("")
            lines.append(
                "Sweet-spot analysis was repeated separately for "
                "EfficiencyScore, Q-factor, and Vπ. The table below "
                "lists positions that landed in the top tier on **two or "
                "more axes** — these are the strongest multi-criteria "
                "candidates because no single metric is dominating the "
                "decision."
            )
            lines.append("")
            lines.append(_df_to_md(multi_sweet_df))
            lines.append("")
            lines.append(
                "**Interpretation:** positions tagged `Eff+Vπ` are good "
                "for variability AND modulation strength. Positions matching "
                "`Eff+Q` are the most robust binning candidates because "
                "they combine independent quality axes."
            )
            lines.append("")

    # PN modulator section
    if not pn_seg_df.empty:
        lines.append("## PN modulator (PCM_PSLOTE_P1N1) analysis")
        lines.append("")
        lines.append(f"Extracted {len(pn_seg_df)} segment rows over {len(pn_fit_df)} dies. "
                     f"Each die has three PN segments (typically 500 / 1500 / 2500 µm) plus a "
                     f"reference waveguide; per-µm doping loss and electroabsorption "
                     f"modulation efficiency are obtained by linear fits versus segment length.")
        lines.append("")
        lines.append("### Per-die length-fit results (first 20 rows)")
        lines.append("")
        lines.append(_df_to_md(pn_fit_df.head(20)))
        lines.append("")

    lines.append("## Figures")
    lines.append("")
    if fig_paths.get("iv"):
        lines.append("### IV characteristics (MZM)")
        lines.append(f"![IV]({fig_paths['iv'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("spectra"):
        lines.append("### Transmission spectra @ -2V (MZM)")
        lines.append(f"![Spectra]({fig_paths['spectra'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("bias"):
        lines.append("### Bias-dependent spectrum (representative MZM die)")
        lines.append(f"![Bias shift]({fig_paths['bias'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("wafermap"):
        lines.append("### MZM wafer maps")
        lines.append(f"![Wafer maps]({fig_paths['wafermap'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("summary"):
        lines.append("### MZM summary panels")
        lines.append(f"![Summary]({fig_paths['summary'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("pn_length"):
        lines.append("### PN modulator length dependence")
        lines.append(f"![PN length]({fig_paths['pn_length'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("pn_summary"):
        lines.append("### PN modulator summary panels")
        lines.append(f"![PN summary]({fig_paths['pn_summary'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("radial_il"):
        lines.append("### (Project 1) Grating coupler IL vs wafer radius")
        lines.append(f"![Radial IL]({fig_paths['radial_il'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("center_vs_edge"):
        lines.append("### (Project 1) Center vs edge boxplots")
        lines.append(f"![Center vs edge]({fig_paths['center_vs_edge'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("vphi"):
        lines.append("### (Project 2) Representative V-φ curve")
        lines.append(f"![V-phi curve]({fig_paths['vphi'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("vpi_analysis"):
        lines.append("### (Project 2) Detailed V-π·L analysis (six panels)")
        lines.append(f"![Vpi analysis]({fig_paths['vpi_analysis'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("vpi_dist"):
        lines.append("### (Project 2) Vπ distribution and Vπ·L figure of merit")
        lines.append(f"![Vπ distribution]({fig_paths['vpi_dist'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("efficiency_map"):
        lines.append("### Cross-parameter efficiency map")
        lines.append(f"![Efficiency map]({fig_paths['efficiency_map'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("sweet_spots"):
        lines.append("### Sweet-spot map")
        lines.append(f"![Sweet spots]({fig_paths['sweet_spots'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("multi_sweet"):
        lines.append("### Per-metric sweet-spot maps")
        lines.append(f"![Multi-metric sweet spots]({fig_paths['multi_sweet'].relative_to(out_dir)})")
        lines.append("")
    if fig_paths.get("combined_sweet"):
        lines.append("### Combined multi-axis sweet spots")
        lines.append(f"![Combined sweet spots]({fig_paths['combined_sweet'].relative_to(out_dir)})")
        lines.append("")

    # Per-wafer representative-die figures
    per_wafer = fig_paths.get("per_wafer", {})
    if per_wafer:
        lines.append("## Per-wafer representative-die figures")
        lines.append("")
        lines.append("Each wafer (and band, where applicable) gets its own subfolder "
                     "under `figures/` containing the full plot set for the die "
                     "closest to (0, 0) with a healthy contact. This gives a quick "
                     "side-by-side reference die per wafer.")
        lines.append("")
        for folder, info in sorted(per_wafer.items()):
            wafer = info.get("wafer", folder)
            band = info.get("band", "")
            die = info.get("die", "")
            device = info.get("device", "")
            band_label = f" ({band}-band)" if band else ""
            lines.append(f"### {wafer}{band_label}  -  대표 die {die}")
            if device:
                lines.append(f"디바이스: `{device}`")
                lines.append("")
            for fig_key, fig_label in [
                ("iv",            "IV (semilog)"),
                ("spectra",       "Transmission spectra"),
                ("bias_shift",    "Bias-shift spectra"),
                ("v_lambda",      "V-λ (변조 효율 nm/V)"),
                ("vphi",          "V-φ"),
                ("vpi_analysis",  "6패널 V-π·L 분석"),
            ]:
                fig_path = info.get(fig_key)
                if fig_path is None or not isinstance(fig_path, Path):
                    continue
                lines.append(f"**{fig_label}**")
                lines.append(f"![{fig_label}]({fig_path.relative_to(out_dir)})")
                lines.append("")

    md_path = out_dir / "report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


# --------------------------------------------------------------------- #
# Per-wafer representative-die figures
# --------------------------------------------------------------------- #
def _pick_representative_die(
    measurements: list[Measurement],
    wafer: str,
    band: str | None,
    *,
    prefer_die: tuple[int, int] = (0, 0),
):
    """Pick the best representative die for a given wafer/band.

    Strategy: prefer ``(prefer_die)`` (default (0,0)) if it exists and is a
    working contact; otherwise pick the working die nearest to that target.
    """
    import numpy as _np

    candidates = [
        m for m in measurements
        if m.wafer == wafer and (band is None or m.band == band)
        and m.iv is not None and m.sweeps
    ]
    if not candidates:
        return None

    # Prefer dies whose contact looks healthy (|I@-1V| > 1 nA)
    healthy = [m for m in candidates if abs(m.iv.at(-1.0)) > 1e-9]
    pool = healthy if healthy else candidates

    target_col, target_row = prefer_die
    pool.sort(key=lambda m: ((m.die_col - target_col) ** 2
                             + (m.die_row - target_row) ** 2))
    return pool[0]


def _plot_single_die_iv(measurement, output_path: Path) -> Path:
    """Single-die IV (semilog) for the per-wafer folder."""
    import matplotlib.pyplot as plt
    import numpy as _np
    from picqa.viz.labels import L

    if measurement.iv is None:
        raise ValueError("No IV data")
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    ax.semilogy(measurement.iv.voltage,
                _np.abs(measurement.iv.current) + 1e-13,
                "ko-", markersize=5, lw=0.9)
    ax.set_xlabel(L("voltage"))
    ax.set_ylabel(L("current_abs"))
    band_str = f" ({measurement.band}-band)" if measurement.band else ""
    ax.set_title(f"IV: {measurement.wafer}/{measurement.die}{band_str}")
    ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(output_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _plot_single_die_spectra(measurement, output_path: Path) -> Path:
    """Single-die overlay of all bias spectra (one panel)."""
    import matplotlib.pyplot as plt
    from picqa.viz.labels import L

    if not measurement.sweeps:
        raise ValueError("No spectra")
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    sweeps = sorted(measurement.sweeps, key=lambda s: s.dc_bias_v)
    for sw in sweeps:
        ax.plot(sw.wavelength_nm, sw.insertion_loss_db, lw=0.7,
                label=f"{sw.dc_bias_v:+.1f} V")
    ax.set_xlabel(L("wavelength"))
    ax.set_ylabel(L("il_db"))
    band_str = f" ({measurement.band}-band)" if measurement.band else ""
    ax.set_title(f"Spectra: {measurement.wafer}/{measurement.die}{band_str}")
    ax.legend(fontsize=8, ncol=2, loc="lower left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _build_per_wafer_figures(
    measurements: list[Measurement],
    features: pd.DataFrame,
    fig_dir: Path,
    *,
    prefer_die: tuple[int, int] = (0, 0),
) -> dict[str, dict[str, Path]]:
    """For each (wafer, band) make a folder under fig_dir and dump the
    standard set of plots for that wafer's representative die.

    Returns a nested mapping ``{ "D08_O": { "v_lambda": Path, ... } }``.
    The picked die is the one closest to ``prefer_die`` (default (0,0))
    that has a working contact.
    """
    from picqa.viz.spectrum_plot import plot_bias_shift
    from picqa.viz.uniformity_plot import plot_v_lambda, plot_vphi_curve
    from picqa.viz.vpi_analysis import plot_vpi_analysis

    summary: dict[str, dict[str, Path]] = {}

    if features.empty:
        return summary

    if "Band" in features.columns:
        groups = features.groupby(["Wafer", "Band"], dropna=False).size().index
    else:
        groups = [(w, "") for w in features["Wafer"].unique()]

    for key in groups:
        if isinstance(key, tuple):
            wafer, band = key
        else:
            wafer, band = key, ""
        band = band if isinstance(band, str) else ""

        target = _pick_representative_die(
            measurements, wafer, band if band else None,
            prefer_die=prefer_die,
        )
        if target is None:
            continue

        folder_name = f"{wafer}_{band}" if band else wafer
        wafer_dir = fig_dir / folder_name
        wafer_dir.mkdir(parents=True, exist_ok=True)

        wafer_figs: dict[str, Path] = {
            "wafer": wafer,
            "band": band,
            "die": target.die,
            "device": target.device_name,
        }

        for fig_name, fn in [
            ("iv",            lambda: _plot_single_die_iv(target, wafer_dir / "iv.png")),
            ("spectra",       lambda: _plot_single_die_spectra(target, wafer_dir / "spectra.png")),
            ("bias_shift",    lambda: plot_bias_shift(target, wafer_dir / "bias_shift.png")),
            ("v_lambda",      lambda: plot_v_lambda(target, wafer_dir / "v_lambda.png")),
            ("vphi",          lambda: plot_vphi_curve(target, wafer_dir / "vphi.png")),
            ("vpi_analysis",  lambda: plot_vpi_analysis(target, wafer_dir / "vpi_analysis.png")),
        ]:
            try:
                wafer_figs[fig_name] = fn()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "Per-wafer plot %s for %s/%s failed: %s",
                    fig_name, wafer, band, exc,
                )

        summary[folder_name] = wafer_figs

    return summary
