"""Objectives for adversarial evaluation: candidate regression and dynamic scope violations."""
from dataclasses import dataclass, field
from typing import Any
from ..ir import IRPolicy
from ..sim.workload import Workload
from ..sim.simulator import simulate, SimResult


@dataclass
class RegressionResult:
    target_class: str
    metric_name: str
    incumbent_val: float
    candidate_val: float
    regression: float
    tolerance: float
    is_regression: bool
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "target_class": self.target_class,
            "metric_name": self.metric_name,
            "incumbent_val": round(self.incumbent_val, 2),
            "candidate_val": round(self.candidate_val, 2),
            "regression": round(self.regression, 2),
            "tolerance": self.tolerance,
            "is_regression": self.is_regression,
            "details": self.details,
        }


class RegressionObjective:
    """Measures performance regression of a candidate policy P1 relative to incumbent P0."""

    def __init__(self, target_class: str, metric_name: str = "p99_dispatch_latency", tolerance: float = 0.0):
        self.target_class = target_class
        self.metric_name = metric_name
        self.tolerance = tolerance

    def _extract_metric(self, sim_res: SimResult, cls: str) -> float:
        st = sim_res.per_class.get(cls)
        if st is None:
            return 0.0
        if self.metric_name in ("p99_dispatch_latency", "p99"):
            return float(st.p99_dispatch_latency_ms)
        elif self.metric_name in ("p50_dispatch_latency", "p50"):
            return float(st.p50_dispatch_latency_ms)
        elif self.metric_name in ("max_dispatch_latency", "max_latency"):
            return float(st.max_dispatch_latency_ms)
        elif self.metric_name in ("max_wait_ms", "max_wait"):
            return float(st.max_wait_ms)
        elif self.metric_name in ("share_pct", "share"):
            return float(st.share_pct)
        elif self.metric_name in ("cpu_ms", "cpu"):
            return float(st.cpu_ms)
        else:
            raise ValueError(f"Unknown metric name: {self.metric_name}")

    def evaluate(self, incumbent: IRPolicy, candidate: IRPolicy, workload: Workload, horizon_ms: int = 10_000) -> RegressionResult:
        res0 = simulate(incumbent, workload, horizon_ms=horizon_ms)
        res1 = simulate(candidate, workload, horizon_ms=horizon_ms)

        val0 = self._extract_metric(res0, self.target_class)
        val1 = self._extract_metric(res1, self.target_class)

        # For latency/wait metrics, higher in candidate is a regression: val1 - val0
        # For share/cpu metrics, lower in candidate is a regression: val0 - val1
        if self.metric_name in ("share_pct", "share", "cpu_ms", "cpu"):
            regression = val0 - val1
        else:
            regression = val1 - val0

        is_reg = regression > self.tolerance

        return RegressionResult(
            target_class=self.target_class,
            metric_name=self.metric_name,
            incumbent_val=val0,
            candidate_val=val1,
            regression=regression,
            tolerance=self.tolerance,
            is_regression=is_reg,
            details={
                "incumbent_dispatches": res0.per_class.get(self.target_class, None).dispatches if self.target_class in res0.per_class else 0,
                "candidate_dispatches": res1.per_class.get(self.target_class, None).dispatches if self.target_class in res1.per_class else 0,
            }
        )


@dataclass
class ScopeViolationResult:
    guarantee_str: str
    guarantee_kind: str
    target_class: str
    status: str          # "HELD" | "SCOPE_VIOLATION"
    observed_val: float
    guaranteed_val: float
    explanation: str

    def to_dict(self) -> dict:
        return {
            "guarantee": self.guarantee_str,
            "kind": self.guarantee_kind,
            "class": self.target_class,
            "status": self.status,
            "observed_val": round(self.observed_val, 2),
            "guaranteed_val": self.guaranteed_val,
            "explanation": self.explanation,
        }


class ScopeViolationObjective:
    """Evaluates whether dynamic/adversarial workloads violate guarantees that held statically.

    Reports dynamic failures as out-of-scope dynamic findings, clearly distinct
    from static formal verifier bugs.
    """

    def evaluate(self, policy: IRPolicy, workload: Workload, horizon_ms: int = 10_000) -> list[ScopeViolationResult]:
        res = simulate(policy, workload, horizon_ms=horizon_ms)
        results = []

        for g in policy.guarantees:
            st = res.per_class.get(g.cls_name)
            if st is None:
                continue

            if g.kind == "no_starvation":
                obs = float(st.max_wait_ms)
                if obs > g.value:
                    status = "SCOPE_VIOLATION"
                    exp = (
                        f"Dynamic workload caused max wait {obs:.1f}ms exceeding static bound {g.value}ms "
                        "(out-of-scope dynamic finding; not a verifier bug in static model)"
                    )
                else:
                    status = "HELD"
                    exp = f"Max wait {obs:.1f}ms within static bound {g.value}ms"
                results.append(ScopeViolationResult(
                    guarantee_str=g.pretty(),
                    guarantee_kind=g.kind,
                    target_class=g.cls_name,
                    status=status,
                    observed_val=obs,
                    guaranteed_val=float(g.value),
                    explanation=exp,
                ))

            elif g.kind == "min_share":
                obs = float(st.share_pct)
                if obs < g.value:
                    status = "SCOPE_VIOLATION"
                    exp = (
                        f"Dynamic workload achieved share {obs:.1f}% below static floor {g.value}% "
                        "(out-of-scope dynamic finding)"
                    )
                else:
                    status = "HELD"
                    exp = f"Share {obs:.1f}% satisfies floor {g.value}%"
                results.append(ScopeViolationResult(
                    guarantee_str=g.pretty(),
                    guarantee_kind=g.kind,
                    target_class=g.cls_name,
                    status=status,
                    observed_val=obs,
                    guaranteed_val=float(g.value),
                    explanation=exp,
                ))

        return results
