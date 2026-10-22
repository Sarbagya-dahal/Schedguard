"""Tests for planted regressions benchmark and phase 2 metrics calculation."""
import pytest
from experiments.planted_regressions import build_benchmark_pairs, establish_ground_truth


class TestPhase2Benchmarks:
    def test_benchmark_pairs_structure(self):
        pairs = build_benchmark_pairs()
        assert len(pairs) >= 30
        planted = [p for p in pairs if p["type"] == "planted_regression"]
        clean = [p for p in pairs if p["type"] == "clean"]
        assert len(planted) >= 20
        assert len(clean) >= 10

    def test_ground_truth_sweep_labeling(self):
        pairs = build_benchmark_pairs()[:5]
        gt = establish_ground_truth(pairs, sweep_trials=5, tolerance=5.0)
        assert len(gt) == 5
        assert all(isinstance(val, bool) for val in gt)
