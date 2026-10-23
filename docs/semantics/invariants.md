# SchedGuard Semantic Invariants

This registry records stable safety boundaries. It describes the current implementation rather than promised future backend behavior.

| ID | Invariant | Enforced by | Protecting tests | Limitation |
| --- | --- | --- | --- | --- |
| SG-SEM-001 | A policy has bounded, uniquely named classes; references resolve before lowering. | `verify/safety.py` E001–E004, E009, E011 | `tests/test_verify_sim.py`, compiler tests | PolicyLang has no symbolic user-defined precedence syntax. |
| SG-SEM-002 | Quantum, priority, aging, task, adaptation, and guarantee values stay in the fixed declared limits. | `limits.py`, `verify/safety.py` E003, E005–E008, E010, E012–E013 | verifier/compiler tests | Backend runtime map capacity is a distinct, larger fixed limit. |
| SG-SEM-003 | Natural-language precedence must be acyclic before generation; explicit equal numeric priorities denote valid equal tiers. | `inference/policy_gen.py` | `tests/test_intent_parser_regression.py` | The recognised class vocabulary remains intentionally bounded. |
| SG-SEM-004 | Every generated source candidate passes parser, safety, intent-consistency, and formal verification gates before acceptance. | `compiler.py`, `policy_gen.py`, `synth/agent.py`, repair loop | synthesis and repair regression tests | A compiled candidate is not automatically a verified guarantee. |
| SG-SEM-005 | `VERIFIED`, `VIOLATED`, and `UNKNOWN` remain distinct; `VIOLATED` requires confirmed replay where the verifier contract requires it. | `verify/properties.py`, `report.aggregate_verdicts` | `tests/test_verify_sim.py`, verdict contract tests | The formal model is single-CPU and static CPU-bound. |
| SG-SEM-006 | AI/provider output is untrusted and offline rules/stub are never reported as a live LLM. | `inference/schema.py`, `pipeline.py`, provider metadata | provider/inference tests | Live provider availability needs independent configuration and request evidence. |
| SG-SEM-007 | Source emission, target compilation, preflight, kernel load, telemetry, predictor, watchdog, and hot-swap are separate evidence stages. | `codegen/*`, `runtime.py`, `report.py` | Phase 4 backend/report tests | No Linux VM runtime evidence exists in this Windows checkout. |
| SG-SEM-008 | The simulator and closed-form verifier share the documented dispatch semantics. | `verify/model.py`, `sim/simulator.py`, `docs/MODEL.md` | `experiments/soundness.py`, `tests/test_verify_sim.py` | Bursts, sleeps, and arrivals extend simulation only, not the proof scope. |
