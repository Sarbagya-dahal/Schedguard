"""Small, interpretable simulator-vs-real error predictor.

The model is deliberately dependency-free.  It trains only from paired,
real-kernel observations and returns a conservative fallback when data or
telemetry quality is insufficient.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math
from typing import Any, Iterable


@dataclass(frozen=True)
class PairedObservation:
    policy_id: str
    workload_id: str
    features: dict[str, float]
    simulator: dict[str, float]
    real: dict[str, float]
    telemetry_complete: bool = True


@dataclass
class Prediction:
    status: str
    metric: str
    predicted_abs_error: float
    uncertainty: float
    sample_count: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _error(obs: PairedObservation, metric: str) -> float:
    if metric not in obs.simulator or metric not in obs.real:
        raise ValueError(f"missing paired metric '{metric}'")
    return abs(float(obs.real[metric]) - float(obs.simulator[metric]))


def _quality(rows: Iterable[float]) -> dict[str, float | None]:
    values = list(rows)
    if not values:
        return {"mae": None, "rmse": None, "underprediction_rate": None}
    return {"mae": sum(values) / len(values),
            "rmse": math.sqrt(sum(v * v for v in values) / len(values)),
            "underprediction_rate": None}


class ErrorPredictor:
    def __init__(self, metric: str = "p99_dispatch_latency", min_samples: int = 8, seed: int = 0):
        self.metric = metric
        self.min_samples = min_samples
        self.seed = seed
        self.feature_names: list[str] = []
        self.weights: list[float] = []
        self.constant_error: float | None = None
        self.train_groups: set[tuple[str, str]] = set()

    def fit(self, observations: Iterable[PairedObservation]) -> dict[str, Any]:
        rows = [o for o in observations if o.telemetry_complete]
        errors = [_error(o, self.metric) for o in rows]
        self.constant_error = max(errors) if errors else None
        self.train_groups = {(o.policy_id, o.workload_id) for o in rows}
        names = sorted({k for o in rows for k in o.features})
        self.feature_names = names
        if len(rows) < self.min_samples:
            self.weights = []
            return {"status": "INSUFFICIENT_DATA", "samples": len(rows), "metric": self.metric,
                    "groups": len(self.train_groups), "quality": _quality(errors)}
        # A bounded one-pass gradient descent fit with an intercept.  Features
        # are assumed to be pre-evaluation policy/workload descriptors.
        weights = [sum(errors) / len(errors)] + [0.0] * len(names)
        scales = [max(1.0, max(abs(float(o.features.get(n, 0))) for o in rows)) for n in names]
        for _ in range(1200):
            grads = [0.0] * len(weights)
            for o, y in zip(rows, errors):
                x = [1.0] + [float(o.features.get(n, 0)) / s for n, s in zip(names, scales)]
                pred = max(0.0, sum(a * b for a, b in zip(weights, x)))
                err = pred - y
                for i, value in enumerate(x):
                    grads[i] += err * value / len(rows)
            for i in range(len(weights)):
                weights[i] = max(0.0, weights[i] - 0.03 * grads[i])
        self.weights = weights
        self._scales = scales
        preds = [self._predict_row(o) for o in rows]
        quality = _quality([abs(p - y) for p, y in zip(preds, errors)])
        under = sum(p < y for p, y in zip(preds, errors)) / len(errors)
        quality["underprediction_rate"] = under
        return {"status": "TRAINED", "samples": len(rows), "metric": self.metric,
                "groups": len(self.train_groups), "quality": quality, "seed": self.seed}

    def _predict_row(self, obs: PairedObservation) -> float:
        if not self.weights:
            return float(self.constant_error or 0.0)
        x = [1.0] + [float(obs.features.get(n, 0)) / s for n, s in zip(self.feature_names, self._scales)]
        return max(0.0, sum(a * b for a, b in zip(self.weights, x)))

    def predict(self, features: dict[str, float], uncertainty: float = 0.0) -> Prediction:
        if self.constant_error is None:
            return Prediction("INSUFFICIENT_DATA", self.metric, 0.0, float("inf"), 0,
                              "no complete real-kernel pairs are available")
        obs = PairedObservation("candidate", "candidate", features, {self.metric: 0.0}, {self.metric: 0.0})
        value = self._predict_row(obs)
        # The fallback is intentionally the maximum observed error, and
        # uncertainty only increases the conservative threshold.
        return Prediction("PREDICTED" if self.weights else "CONSTANT_FALLBACK", self.metric,
                          value, max(float(uncertainty), value * 0.25),
                          len(self.train_groups), "trained model" if self.weights else "constant-error fallback")

    @staticmethod
    def grouped_split(observations: list[PairedObservation], holdout_fraction: float = 0.25) -> tuple[list[PairedObservation], list[PairedObservation]]:
        groups = sorted({(o.policy_id, o.workload_id) for o in observations})
        cut = max(1, int(len(groups) * (1 - holdout_fraction))) if groups else 0
        train_groups = set(groups[:cut])
        return ([o for o in observations if (o.policy_id, o.workload_id) in train_groups],
                [o for o in observations if (o.policy_id, o.workload_id) not in train_groups])
