# Phase 4 evaluation

`experiments/run_phase4_metrics.py` writes a versioned report with explicit
`NOT_RUN` states until paired simulator and real-kernel observations exist.
The current Windows development environment has no Linux sched_ext VM, so no
kernel compilation, load, telemetry, or predictor validation result is
claimed.

The predictor target is absolute error per supported metric, currently
`p99_dispatch_latency` when both simulator and real observations are present.
Rows with incomplete telemetry are excluded. Splits are grouped by
`(policy_id, workload_id)` to avoid repeated-policy leakage. The learned model
is a small non-negative linear regression; the conservative baseline is the
maximum observed training error. With insufficient data the predictor returns
`INSUFFICIENT_DATA`, and the gate uses a stricter threshold rather than
accepting on missing evidence.

Required ablations after genuine traces are collected:

1. Existing static/recorded/adversarial gate.
2. Constant-error baseline.
3. Grouped learned predictor.
4. Full gate with predictor, recorded traces, and adversarial search.

Report sample provenance, grouped splits, seed, MAE, RMSE, underprediction
rate, telemetry completeness, fallback/abort events, and false accept/reject
behavior only where ground truth supports it. Never label simulated or
hand-authored values as real measurements.
