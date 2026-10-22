"""Tests for Phase 1b eval harness metrics and execution."""
import os
import pytest
from unittest.mock import patch, MagicMock
from schedguard.ir import IRGuarantee, IRPolicy, IRClass
from schedguard.verify.properties import Verdict
from schedguard.inference.pipeline import InferenceReport


def _dummy_ir():
    c0 = IRClass(0, "web", 0, 5, 0, "interactive")
    c1 = IRClass(1, "batch", 1, 20, 200, "batch")
    return IRPolicy("test_pol", (c0, c1), (), 8)


class TestEvalHarnessMetrics:
    def test_compute_metrics_basic(self):
        from experiments.eval_inference import compute_metrics
        ir = _dummy_ir()
        g1 = IRGuarantee("no_starvation", 0, "web", 50)
        g2 = IRGuarantee("min_share", 1, "batch", 10)
        v1 = Verdict(guarantee=g1, status="VERIFIED", elapsed_ms=5.0)
        v2 = Verdict(guarantee=g2, status="VIOLATED", elapsed_ms=5.0)
        facts = {
            "web": {"tightest_wait_ms": 25, "guaranteed_min_share_pct": 50},
            "batch": {"tightest_wait_ms": 200, "guaranteed_min_share_pct": 10},
        }

        rep = InferenceReport(
            source="test",
            facts=facts,
            proposed=[g1, g2],
            rejected=[],
            verdicts=[v1, v2],
        )

        m = compute_metrics([rep])
        assert m["classes_covered_count"] == 2
        assert set(m["classes_covered"]) == {"web", "batch"}
        assert m["total_proposed"] == 2
        assert m["schema_rejection_rate"] == 0.0
        assert m["verified_count"] == 1
        assert m["violated_count"] == 1
        assert m["unknown_count"] == 0
        assert m["verified_rate"] == 0.5
        assert m["violated_rate"] == 0.5
        # frontier distance: 50 / 25 = 2.0
        assert m["frontier_distance_mean"] == pytest.approx(2.0)

    def test_compute_metrics_no_proposals(self):
        from experiments.eval_inference import compute_metrics
        rep = InferenceReport(
            source="test",
            facts={"web": {"tightest_wait_ms": None}},
            proposed=[],
            rejected=[],
            verdicts=[],
        )
        m = compute_metrics([rep])
        assert m["classes_covered_count"] == 0
        assert m["total_proposed"] == 0
        assert m["schema_rejection_rate"] == 0.0
        assert m["verified_count"] == 0
        assert m["frontier_distance_mean"] is None

    def test_frontier_distance_unbounded(self):
        from experiments.eval_inference import compute_metrics
        g = IRGuarantee("no_starvation", 0, "web", 500)
        v = Verdict(guarantee=g, status="VIOLATED", elapsed_ms=5.0)
        rep = InferenceReport(
            source="test",
            facts={"web": {"tightest_wait_ms": None}},  # Unbounded class
            proposed=[g],
            rejected=[],
            verdicts=[v],
        )
        m = compute_metrics([rep])
        assert m["frontier_distance_mean"] is None
        assert m["unbounded_proposals_count"] == 1

    def test_schema_rejection_counted(self):
        from experiments.eval_inference import compute_metrics
        g = IRGuarantee("no_starvation", 0, "web", 50)
        v = Verdict(guarantee=g, status="VERIFIED", elapsed_ms=5.0)
        rep = InferenceReport(
            source="test",
            facts={"web": {"tightest_wait_ms": 50}},
            proposed=[g],
            rejected=[({"bad": "item"}, "unknown class")],
            verdicts=[v],
        )
        m = compute_metrics([rep])
        assert m["total_proposed"] == 1
        assert m["total_rejected"] == 1
        assert m["schema_rejection_rate"] == 0.5

    def test_not_run_when_no_key(self):
        from experiments.eval_inference import evaluate_provider
        env = {k: v for k, v in os.environ.items() if k not in ("OPENROUTER_API_KEY", "SCHEDGUARD_PROVIDER")}
        with patch.dict(os.environ, env, clear=True):
            res = evaluate_provider("openrouter", intents=[], repeats=1)
            assert res["status"] == "NOT_RUN"
            assert "key" in res["reason"].lower() or "missing" in res["reason"].lower()
