# Phase 3: violation classification and repair

Phase 3 uses the deterministic verifier as the acceptance authority. A
counterexample is classified into `NO_AGING`, `AGING_TOO_SLOW`,
`TIER_CONTENTION`, `QUANTUM_IMBALANCE`, `OVERPROMISED_BOUND`,
`SHARE_INFEASIBLE`, or conservative `UNKNOWN_CONSERVATIVE` only from IR and
analysis evidence.

`schedguard classify` reports the deterministic cause. `schedguard repair`
runs a bounded repair loop of at most five iterations. Every candidate is
parsed, safety-checked, and formally reverified. Original guarantees must be
retained with an equal or stricter value; a candidate that removes or weakens
one is rejected. `schedguard synth` composes the existing proposal path with
the same repair loop.

The benchmark in `experiments/run_phase3_metrics.py` evaluates raw,
template, deterministic heuristic, and AI-explained feedback over the
validated 32-policy corpus in `experiments/broken_policies/`. Results are
written to `experiments/results/phase3_metrics.json`. Without a configured
real provider, the AI condition is recorded as `NOT_RUN`; the offline rules
provider is not reported as LLM performance.

Reproduce with:

```text
PYTHONPATH=src python experiments/make_broken_policies.py
PYTHONPATH=src python experiments/run_phase3_metrics.py
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python experiments/soundness.py
```

The verifier remains scoped to its documented bounded static workload model.
Repair success is therefore reported from actual verification outcomes;
`UNKNOWN` is never treated as success.
