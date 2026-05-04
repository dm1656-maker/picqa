# Changelog

## [1.5.0] — Cross-parameter efficiency analysis
- New `picqa.analysis.efficiency_map` module combines all measured
  parameters into one **EfficiencyScore** per die (0-1)
- Robust 5-95th percentile min-max normalisation per metric, configurable
  weights and directions via `EfficiencyConfig`
- **Sweet-spot detection**: identifies die positions that consistently
  appear in the top tier across multiple wafers (process-favoured locations)
- Position summary by region (center/edge), quadrant (NE/NW/SE/SW), and
  radius bin
- New CLI: `picqa efficiency <features.csv> --phase <phase.csv> -o <dir>`
  with --top-n, --threshold, --min-consistency, --normalise-per-wafer flags
- Two new visualisations: `efficiency_wafermap.png` (per-wafer score map)
  and `sweet_spots.png` (consistency + mean score across wafers)
- Auto-included in `picqa report`: 14 figures + 16 CSVs + 10 sections
- 12 new tests (52 total)
- Findings on HY202103: sweet spots at (0,3), (0,-3), (2,0) — top tier
  on 3 of 4 wafers (75% consistency); SW quadrant is weakest


## [1.4.0] — Detailed V-π·L analysis figure
- New `picqa/viz/vpi_analysis.py` reproduces the six-panel V-φ analysis
  figure used in production silicon photonic characterisation pipelines:
  measured + reference polynomial / normalised / focus-on-peak /
  IV / phase-vs-V / Vπ·L-vs-V
- Notch tracking by wavelength continuity (not depth) so multi-FSR
  spectra don't lose lock when normalisation flattens the envelope
- Sub-pm peak localisation via parabolic fit at every bias
- `plot_bias_shift` now auto-derives plot ranges from the measurement's
  design wavelength so it works for both O- and C-band devices (fixes
  empty bias_shift figure for D07)
- Integrated report's bias_shift target now prefers a die with ≥3 deep
  notches, ensuring the figure is informative
- New CLI: `picqa plot vpi_analysis <data-dir> -o file.png`
- Six-panel figure auto-included in `picqa report` output


## [1.3.1] — Device name in CSVs
- All feature CSVs now include `Device` and `TestSite` columns next to `Die`
  so it's obvious from a spreadsheet which device each row corresponds to
  (e.g. `MZMOTE_LULAB_380_500` for an O-band MZM with 380 µm phase shifter)
- Affects mzm_features.csv, pn_segments.csv, pn_length_fit.csv,
  phase_features.csv, and the photodetector CSV
- 9 new test assertions covering the new columns and ordering


## [1.3.0] — Multi-band support
- Band-agnostic parser auto-detects O / C / E / S / L / U from the XML's
  `WL` design parameter or test-site naming convention (LMZO/LMZC,
  PSLOTE/PSLCTE, MZMOTE/MZMCTE)
- New `picqa.io.bands` module with `band_from_wavelength`, `band_from_name`,
  `band_for_measurement`, `default_wavelength_for_band`
- `Measurement` and `PNMeasurement` gain `design_wavelength_nm` and `band`
  fields; extractors use them instead of a hardcoded 1310 nm
- `parse_directory` now accepts a list of test sites; `MZM_TEST_SITES` and
  `PN_TEST_SITES` constants drive multi-site scans
- Feature tables get `Band` and `DesignWavelength_nm` columns; legacy
  column `PeakIL_near_1310_dB` retained as alias of new `PeakIL_dB`
- 19 new tests for band detection (62 total)
- D07 wafer (C-band only) is now part of every analysis without code changes


## [1.2.0] — Projects 1 + 2
- Wafer-level uniformity analysis (center-vs-edge, radial trends, FSR-to-index, IV uniformity)
- V-phi extraction: Vπ, Vπ·L, ER from existing dλ/dV data
- New CLI: `picqa uniformity`, `picqa phase`
- New plot kinds: radial, center_vs_edge, vphi, vpi
- 14 new tests; integrated into unified report (now 11 figures + 11 CSVs)


All notable changes to this project will be documented in this file.

## [1.0.0] — Initial release

- Full module surface (io, extract, analysis, viz, report, cli)
- MZM feature extraction (FSR, tuning slope, peak IL, leakage)
- Photodetector dark current extraction
- Spec-based yield evaluation from YAML
- Failed-contact heuristic
- Five plot types: IV grid, spectra grid, bias-shift, wafer map, summary
- Markdown report generator
- 6 test modules, end-to-end CLI tests

## [0.5.0] — Reporting

- `report/markdown.py` — full Markdown report assembly
- `picqa report` CLI subcommand

## [0.4.0] — Analysis & visualisation

- `analysis/yield_calc.py` with YAML spec loading
- `analysis/statistics.py` robust grouped statistics
- `analysis/outlier.py` failed-contact heuristic
- All `viz/` plot modules

## [0.3.0] — Multi-device extraction

- `extract/photodetector.py`
- `extract/waveguide.py` (stub)

## [0.2.0] — MZM extraction

- `extract/mzm.py` with FSR / tuning slope / peak IL
- `picqa extract mzm` CLI

## [0.1.0] — Foundations

- `pyproject.toml`, CI workflow, license
- `io/schemas.py` data containers
- `io/xml_parser.py` parser + inventory
- `picqa inventory`, `picqa parse` CLI
