# Cross-parameter efficiency analysis (v1.5.0)

This page documents how picqa combines all measured parameters into one
per-die quality score and how that score is used to find die positions
that consistently produce the best devices.

## Why this matters

Each parameter we extract — FSR, dλ/dV, Vπ, ER, leakage, IL — describes
a different aspect of device quality. Looking at them one at a time gives
the picture for that one parameter, but the actual question is usually:

> *Which die positions on the wafer make the best devices overall?*

Answering that requires combining parameters, which means deciding two
things:

1. For each parameter, **what direction is "better"?** Lower Vπ is better,
   higher ER is better, less leakage is better, etc.
2. **How important is each parameter?** ER and Vπ are usually first-class;
   FSR is more informational.

## Score construction

Every parameter is scaled to a 0–1 score, then combined linearly:

```
EfficiencyScore = Σᵢ wᵢ · normalisedᵢ  /  Σᵢ wᵢ
```

The normalisation is **robust min-max** on the 5th–95th percentile range
so a single outlier can't compress the rest of the population. Direction
is configured per-metric:

| Metric | Direction | Reason |
|---|---|---|
| `Vpi_V` | `min` | Lower Vπ = stronger modulator |
| `ER_at_-2V_dB` | `max` | Higher ER = deeper modulation |
| `PeakIL_dB` | `max` | Less negative IL = lower loss |
| `I_at_-1V_pA` | `min_abs` | Less leakage = better contact / junction |
| `FSR_nm` | `max` | Larger FSR = more channel real-estate |

Default weights are `Vpi:2, ER:1.5, IL:1, leakage:1, FSR:0.5`. They can
be overridden via `EfficiencyConfig`.

## Per-wafer normalisation (optional)

When wafers come from different process runs or use different bands,
their absolute parameter scales differ. Use `--normalise-per-wafer` to
rank dies *within* each wafer-band group before combining. This focuses
the analysis on **position-relative** quality rather than absolute.

## Position analysis

Once each die has a score, three views of the wafer are computed:

* **Region** — center (radius ≤ 2.5 die units) vs edge
* **Quadrant** — NE / NW / SE / SW
* **Radius** — by integer-rounded radial bin

Reported as mean and median EfficiencyScore.

## Sweet spots — positions consistently in the top tier

Sweet spots are the most actionable output. A position (DieCol, DieRow)
is a **sweet spot** if its EfficiencyScore lands in the top
`threshold_pct` percentile (default 75 %) on at least `min_consistency`
wafers (default 2). This identifies positions that the process favours,
not positions that one wafer happened to be lucky in.

The sweet-spot map shows two views:

* **Number of wafers** where each position is in the top tier — high
  values mean reliable
* **Mean efficiency** across all wafers at each position — high values
  mean strong

Cross-referencing the two highlights positions that are *both* reliable
and strong.

## CLI

```bash
# Standalone — needs an MZM features CSV (and optionally a phase CSV)
picqa efficiency ./out/features.csv --phase ./out/phase.csv \
  -o ./out/efficiency \
  --top-n 10 \
  --threshold 75 \
  --min-consistency 2

# Optional: normalise per (Wafer, Band) so absolute differences don't dominate
picqa efficiency ./out/features.csv --phase ./out/phase.csv \
  --normalise-per-wafer -o ./out/efficiency_relative
```

The integrated `picqa report` runs efficiency analysis automatically and
includes the wafer map, sweet-spot map, top-N table, position summary,
and sweet-spot table in the Markdown output.

## Library

```python
from picqa.analysis.efficiency_map import (
    compute_efficiency_score,
    best_dies,
    position_summary,
    find_sweet_spots,
    plot_efficiency_wafermap,
    plot_sweet_spots,
)
import pandas as pd

features = pd.read_csv("out/features.csv")
phase = pd.read_csv("out/phase.csv")
keys = ["Wafer", "Session", "Die"]
merged = features.merge(
    phase[keys + ["Vpi_V", "ER_at_-2V_dB"]], on=keys, how="left"
)
working = merged[~merged["FailedContact"]]

scored = compute_efficiency_score(working)
print(best_dies(scored, n=10))
print(position_summary(scored))

sweet = find_sweet_spots(scored)
print(sweet[sweet["is_sweet_spot"]])

plot_efficiency_wafermap(scored, "out/efficiency_wafermap.png")
plot_sweet_spots(sweet, "out/sweet_spots.png")
```

## Findings on the HY202103 dataset

Running with the default config on the four wafers:

* **Top dies**: dominated by D07 (C-band) and D08 (both bands), with
  EfficiencyScores of 0.73–0.83. D23/D24 don't appear in the top-10.
* **Position summary**: SE quadrant scores highest on average (0.59),
  SW is the weakest (0.48). Center vs edge is roughly equal — not a
  strong radial trend on these wafers.
* **Sweet spots** identified at (0, 3), (0, -3), and (2, 0) — each
  appearing in the top-25% on 3 of 4 wafers (75 % consistency). These
  positions would be high-priority bins in a real production setting.
