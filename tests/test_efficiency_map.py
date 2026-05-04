"""Tests for the efficiency-scoring module."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from picqa.analysis.efficiency_map import (
    EfficiencyConfig,
    best_dies,
    compute_efficiency_score,
    find_sweet_spots,
    position_summary,
)


@pytest.fixture
def sample_scored_input():
    """Synthetic 5-wafer × 5-die feature table with a clear gradient.

    Center positions are deliberately given better numbers so we can verify
    the efficiency score aligns with our hand-built ground truth.
    """
    rows = []
    for w in ["W1", "W2"]:
        for col in [-2, -1, 0, 1, 2]:
            for row in [-2, -1, 0, 1, 2]:
                r = math.hypot(col, row)
                rows.append({
                    "Wafer": w,
                    "Session": "S1",
                    "Die": f"({col},{row})",
                    "DieCol": col,
                    "DieRow": row,
                    "Vpi_V": 25.0 + 2.0 * r,           # center is best (lowest Vπ)
                    "ER_at_-2V_dB": 40.0 - 1.5 * r,    # center is best (highest ER)
                    "PeakIL_dB": -7.0 - 0.4 * r,       # center is best (least negative IL)
                    "I_at_-1V_pA": 1e4 + 1e3 * r,      # center is best (lowest leakage)
                    "FSR_nm": 9.85,
                })
    return pd.DataFrame(rows)


def test_compute_efficiency_score_adds_columns(sample_scored_input):
    out = compute_efficiency_score(sample_scored_input)
    assert "EfficiencyScore" in out.columns
    score_cols = [c for c in out.columns if c.startswith("Score_")]
    # Should have one Score_ column per metric in default weights
    assert len(score_cols) == 5
    # All scores in [0, 1]
    for c in score_cols:
        s = out[c].dropna()
        assert (s >= 0).all() and (s <= 1).all()


def test_efficiency_score_in_unit_range(sample_scored_input):
    out = compute_efficiency_score(sample_scored_input)
    s = out["EfficiencyScore"].dropna()
    assert s.min() >= 0
    assert s.max() <= 1


def test_center_dies_score_higher_than_edge(sample_scored_input):
    """With our synthetic gradient, center should win."""
    out = compute_efficiency_score(sample_scored_input)
    out["Radius"] = np.hypot(out["DieCol"], out["DieRow"])
    center_mean = out[out["Radius"] <= 1.5]["EfficiencyScore"].mean()
    edge_mean = out[out["Radius"] > 1.5]["EfficiencyScore"].mean()
    assert center_mean > edge_mean


def test_compute_efficiency_handles_empty():
    df = pd.DataFrame(columns=["Wafer", "Die", "DieCol", "DieRow", "Vpi_V"])
    out = compute_efficiency_score(df)
    assert out.empty
    assert "EfficiencyScore" in out.columns


def test_compute_efficiency_handles_missing_metrics():
    """A column not in DEFAULT_WEIGHTS shouldn't crash; missing
    columns should be silently skipped (not silently penalised)."""
    df = pd.DataFrame([
        {"Wafer": "W1", "Die": "(0,0)", "DieCol": 0, "DieRow": 0,
         "Vpi_V": 25.0},  # only one of the metrics
    ])
    out = compute_efficiency_score(df)
    # Single-metric scoring still produces a finite EfficiencyScore
    assert out["EfficiencyScore"].notna().all()


def test_custom_weights_are_used():
    """Heavily up-weighting Vπ should make Vπ-driven scores dominate."""
    df = pd.DataFrame([
        {"Wafer": "W1", "Die": f"({i},0)", "DieCol": i, "DieRow": 0,
         "Vpi_V": 25.0 if i == 0 else 35.0,
         "ER_at_-2V_dB": 40.0 if i != 0 else 25.0}
        for i in range(3)
    ])
    # Equal weights — die 0 wins because Vπ better
    cfg_equal = EfficiencyConfig(
        metrics=["Vpi_V", "ER_at_-2V_dB"],
        weights={"Vpi_V": 1.0, "ER_at_-2V_dB": 1.0},
    )
    out_eq = compute_efficiency_score(df, config=cfg_equal)
    # Heavy ER weight — non-zero die wins because ER better
    cfg_er = EfficiencyConfig(
        metrics=["Vpi_V", "ER_at_-2V_dB"],
        weights={"Vpi_V": 1.0, "ER_at_-2V_dB": 10.0},
    )
    out_er = compute_efficiency_score(df, config=cfg_er)
    # In ER-weighted case, die 1 or 2 should win (they have ER=40 vs die 0's 25)
    best_idx_eq = out_eq["EfficiencyScore"].idxmax()
    best_idx_er = out_er["EfficiencyScore"].idxmax()
    assert best_idx_eq != best_idx_er


def test_best_dies_returns_sorted_top_n(sample_scored_input):
    out = compute_efficiency_score(sample_scored_input)
    top = best_dies(out, n=5)
    assert len(top) == 5
    # Strictly non-increasing
    scores = top["EfficiencyScore"].values
    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


def test_best_dies_per_group(sample_scored_input):
    out = compute_efficiency_score(sample_scored_input)
    top = best_dies(out, n=3, group_by=["Wafer"])
    # 2 wafers × 3 each = 6 rows
    assert len(top) == 6
    # Each wafer represented exactly 3 times
    counts = top["Wafer"].value_counts()
    assert (counts == 3).all()


def test_position_summary_categorises(sample_scored_input):
    out = compute_efficiency_score(sample_scored_input)
    pos = position_summary(out)
    cats = set(pos["category"].unique())
    assert {"Region", "Quadrant", "Radius"}.issubset(cats)
    # Region should have exactly 2 levels
    region_rows = pos[pos["category"] == "Region"]
    assert len(region_rows) == 2
    assert set(region_rows["level"]) == {"center", "edge"}


def test_find_sweet_spots_flags_consistent_positions(sample_scored_input):
    out = compute_efficiency_score(sample_scored_input)
    sweet = find_sweet_spots(out, threshold_pct=75.0, min_consistency=2)
    # Center positions (radius 0–1) must be flagged as sweet spots
    # because they're the highest-scoring on every wafer
    center_pos = sweet[(sweet["DieCol"] == 0) & (sweet["DieRow"] == 0)]
    assert len(center_pos) == 1
    assert center_pos.iloc[0]["is_sweet_spot"]


def test_find_sweet_spots_threshold_can_be_relaxed():
    """Higher threshold → fewer sweet spots; lower → more."""
    df = pd.DataFrame([
        {"Wafer": "W1", "Die": f"({c},0)", "DieCol": c, "DieRow": 0,
         "Vpi_V": 25.0 + c, "ER_at_-2V_dB": 35.0 - c,
         "PeakIL_dB": -8.0, "I_at_-1V_pA": 1e4, "FSR_nm": 9.8}
        for c in range(5)
    ])
    out = compute_efficiency_score(df)
    high_threshold = find_sweet_spots(out, threshold_pct=99.0, min_consistency=1)
    low_threshold = find_sweet_spots(out, threshold_pct=10.0, min_consistency=1)
    n_sweet_high = high_threshold["is_sweet_spot"].sum()
    n_sweet_low = low_threshold["is_sweet_spot"].sum()
    assert n_sweet_low >= n_sweet_high


def test_normalise_per_wafer_groupby(sample_scored_input):
    """With group_by, each wafer should produce its own 0–1 range."""
    out = compute_efficiency_score(sample_scored_input, group_by=["Wafer"])
    for w in ["W1", "W2"]:
        sub = out[out["Wafer"] == w]
        # The best die in each wafer should score close to 1
        assert sub["EfficiencyScore"].max() > 0.95
        # The worst should be close to 0
        assert sub["EfficiencyScore"].min() < 0.1
