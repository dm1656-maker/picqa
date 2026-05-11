# picqa — Photonic IC Quality Analyzer

[![CI](https://github.com/USER/picqa/actions/workflows/ci.yml/badge.svg)](https://github.com/USER/picqa/actions)

A modular Python library and CLI for analyzing wafer-level test data from
silicon photonic process runs. Designed around the HY202103 dataset format
(LION1 maskset, 1310 nm O-band devices).

## Features

- **Pluggable XML parser** for OIO measurement files (MZM and PN modulator
  variants supported)
- **Band-agnostic extraction** — O/E/S/C/L/U bands are detected automatically
  from the XML's `WL` design parameter or from test-site naming, so the same
  pipeline handles 1310 nm and 1550 nm devices side by side
- **Per-device feature extractors** (MZM, PN modulator, photodetector;
  waveguide stub)
- **Length-dependent analysis** for PN modulators: per-µm doping loss and
  electroabsorption modulation efficiency by linear fit across three
  segment lengths
- **Wafer-level uniformity (project 1)**: center-vs-edge comparison,
  radial dependence, FSR-to-index-variation mapping, IV uniformity
- **V-phi extraction (project 2)**: Vπ, Vπ·L, and extinction ratio derived
  from the bias-dependent notch shift; six-panel detailed analysis figure
- **Cross-parameter efficiency analysis**: combines all measured parameters
  into a single per-die EfficiencyScore (0–1), identifies sweet-spot
  positions consistently producing best devices across wafers
- **Spec-based yield calculation** from a YAML rule file
- **Automatic failed-contact detection** via leakage + tuning-slope thresholds
- **Publication-quality plots**: IV curves, transmission spectra, bias-shift
  comparisons, wafer maps, six-panel MZM summary, PN length-dependence,
  PN trade-off summary, radial-IL trend, center-vs-edge boxplots, V-φ curves,
  Vπ distribution, six-panel V-π·L analysis, **efficiency wafer map**,
  **sweet-spot map**
- **Markdown report generator** that bundles inventory, statistics,
  yield results, MZM features, PN features, project-1 uniformity, project-2
  V-phi, **efficiency analysis**, and figures into one file (14 figures + 16 CSVs)
- **Per-die inspection commands**: `picqa show` and `picqa list` for
  fast terminal-based browsing of measurements
- **CLI** for every operation — no GUI, no notebook required

## Installation

```bash
git clone <repo-url>
cd picqa
pip install -e ".[dev]"
```

## Quickstart

The fastest way to get every result for a fresh dataset is the bundled
one-shot script:

```bash
# Run the entire pipeline (≈ 70 s on the HY202103 dataset)
python run.py --data ./HY202103 --out ./results
# → ./results/report.md          ← integrated Markdown report
# → ./results/figures/           ← 51 plots (per-wafer subfolders included)
# → ./results/efficiency_scored.csv, combined_sweet_spots.csv, …
```

For a step-by-step walkthrough with commentary, open the bundled
notebook:

```bash
jupyter notebook picqa_analysis.ipynb
```

It runs the same analysis in 8 sections, explains each step, and
displays the figures inline. The notebook is tolerant of missing
IPython (e.g. when executed as a plain Python script) — it falls back
to printing image paths.

### CLI individual commands

```bash
# 1) See what's in the dataset
picqa inventory ./HY202103

# 2) Extract MZM features into a CSV
picqa extract mzm ./HY202103 -o ./out/features.csv

# 3) Extract PN modulator features (per-segment + per-die length fit)
picqa extract pn ./HY202103 -o ./out/pn_segments.csv

# 4) Plot a six-panel MZM summary
picqa plot summary ./out/features.csv -o ./out/summary.png

# 5) Plot PN length dependence and trade-off summary
picqa plot pn_length ./out/pn_segments.csv -o ./out/pn_length.png
picqa plot pn_summary ./out/pn_segments_lengthfit.csv -o ./out/pn_summary.png

# 6) Compute MZM yield against a spec
picqa yield ./out/features.csv \
    --spec configs/mzm_spec.yaml \
    --family mzm \
    -o ./out/yield.csv

# 7) Generate a one-shot Markdown report with all figures (MZM + PN)
picqa report ./HY202103 -o ./out/report \
    --spec configs/mzm_spec.yaml --family mzm
```

## Library usage

```python
from picqa.io.xml_parser import parse_directory
from picqa.extract.mzm import extract_mzm_features
from picqa.analysis.yield_calc import load_spec, evaluate_yield

measurements = parse_directory("./HY202103", test_site="DCM_LMZO")
features = extract_mzm_features(measurements)

spec = load_spec("configs/mzm_spec.yaml", "mzm")
evaluated = evaluate_yield(features, spec)
print(evaluated["Pass"].mean())  # overall yield as a fraction
```

## Project layout

```
src/picqa/
    io/         XML parsing + typed data containers
    extract/    Per-device feature extraction
    analysis/   Statistics, yield, outlier detection
    viz/        Plotting (matplotlib, file output only)
    report/     Markdown report generation
    cli.py      Entry point exposed as `picqa`
tests/          pytest unit + integration tests
examples/       Usage scripts
configs/        YAML spec files
docs/           Architecture and data-format notes
```

See `docs/architecture.md` for the design rationale and module
responsibilities.

## Development

```bash
# Tests with coverage
pytest --cov=picqa

# Lint
ruff check src/ tests/

# Build a wheel
python -m build
```

## Verified on the HY202103 dataset

The full pipeline has been exercised end-to-end on the HY202103 process run
(4 wafers × up to 14 dies × 13 test sites, 709 XML files, 484.8 MB):

- **MZM extraction (multi-band)**: 98 measurements (D07 C-band 14 + D08 O+C 28
  + D23 O 28 + D24 O 28). The same call now picks up D07 (which is C-band
  only) and the C-band MZMs that exist on D08. FSR scales 1.46× from O-band
  (9.83 nm) to C-band (14.3 nm) — consistent with group-index theory.
- **Failed contact**: 28 / 98 dies automatically flagged, matching the two
  re-test sessions where the probe lost electrical contact.
- **PN modulator (PCM_PSLOTE_P1N1 + PCM_PSLCTE_P1N1)**: 84 dies × 3 segment
  lengths (500/1500/2500 µm) = 252 segment rows. D07 C-band PN shows ~1.4×
  larger electroabsorption than D08 O-band, in line with carrier-absorption
  scaling as λ².
- **Wafer uniformity (project 1)**: grating-coupler IL is consistently
  better at the wafer center than at the edge by ~1.6 dB, with significantly
  smaller die-to-die spread.
- **V-phi extraction (project 2)**: Vπ ≈ 27 V on D08, ≈ 29 V on D07,
  36–39 V on D23/D24; extinction ratio ≈ 37 dB on all wafers.
- **MZM yield against the bundled spec**: D08 = 100 % (14/14, O-band only),
  D23 = 50 % (14/28), D24 = 50 % (14/28).
- **One-shot reporting**: 11+ figures + 11 CSVs + 1 Markdown report
  generated by a single `picqa report` call.
- **Tests**: 62 unit and integration tests pass (31 automated + 31 manual).

## License

MIT
