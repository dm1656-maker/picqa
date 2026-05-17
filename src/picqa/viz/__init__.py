"""Plotting utilities. Each function writes a PNG and returns the path."""

from picqa.viz.iv_plot import plot_iv_grid
from picqa.viz.pn_plot import plot_pn_length_dependence, plot_pn_summary
from picqa.viz.spectrum_plot import plot_bias_shift, plot_spectra_grid
from picqa.viz.summary_plot import plot_summary
from picqa.viz.uniformity_plot import (
    plot_center_vs_edge,
    plot_radial_dependence,
    plot_v_lambda,
    plot_vphi_curve,
    plot_vpi_distribution,
)
from picqa.viz.vpi_analysis import plot_vpi_analysis
from picqa.viz.wafer_map import (
    plot_all_metric_wafermaps,
    plot_metric_wafermap,
    plot_wafermap,
    plot_wafermap_grid,
)

__all__ = [
    "plot_iv_grid",
    "plot_spectra_grid",
    "plot_bias_shift",
    "plot_wafermap",
    "plot_wafermap_grid",
    "plot_metric_wafermap",
    "plot_all_metric_wafermaps",
    "plot_summary",
    "plot_pn_length_dependence",
    "plot_pn_summary",
    # project 1
    "plot_radial_dependence",
    "plot_center_vs_edge",
    # project 2
    "plot_v_lambda",
    "plot_vphi_curve",
    "plot_vpi_distribution",
    "plot_vpi_analysis",
]
