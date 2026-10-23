# Final Overhaul Audit

## Initial evidence — 2026-10-24

- Checkpoint: `6484198ba2491f686b08ecae816e35c6207159fc` on `feature/phase4-sched-ext`.
- Baseline: `105 passed in 5.79s` using `.venv\\Scripts\\python.exe -m pytest -q` with `PYTHONPATH=src`.
- Live checkout—not the supplied stale ZIP—is canonical. The checkpoint tree had no tracked modifications; ignored caches, logs, virtual environment, and transient run records were retained.

## Architecture map

| Area | Live responsibility |
| --- | --- |
| DSL/compiler | `dsl/*`, `compiler.py`, `verify/safety.py`, `ir/*`: source to AST, static diagnostics, bounded IR. |
| Formal verification | `verify/model.py`, `verify/properties.py`: single-CPU, static CPU-bound Z3 checks and simulator replay. |
| Simulation/gate | `sim/*`, `adversary/*`, `gate.py`: richer bounded simulation and adversarial regression evaluation. |
| AI boundaries | `inference/*`, `synth/agent.py`, `repair/*`: untrusted proposal/repair input gated by compilation, schema validation, and verification. |
| Web workbench | `server.py`, `studio/*`: FastAPI API and vanilla browser Studio. |
| Backend | `codegen/*`, `runtime.py`, `telemetry.py`, `predictor.py`: bounded source emission and inspection-only Phase 4 scaffolding. |
| Evidence/reports | `report.py`, `experiments/*`: persisted runs, PDFs, reproducible metrics runners. |

## Initial findings

1. **High — provider failure contract is inconsistent.** `server.py:565` calls `get_provider()` without translating failures. With credentials absent, `/api/infer` produces an unhelpful generic HTTP 500, whereas `/api/generate` returns a 200 `PROVIDER_ERROR` and `/api/synthesize` returns an unsuccessful 200 result. Reproduction used no credential and made no live request.
2. **High — natural-language priority contradiction can be silently unsupported instead of rejected.** `extract_intent()` does not recognize `web has higher priority than batch and batch has higher priority than web`; it returns an unsupported prompt rather than a conflict diagnostic. It also currently marks two classes at the same numeric priority as conflicting despite valid equal-tier DSL semantics.
3. **High — PDF backend disclosure is hardcoded.** `report.py` uses a fixed Phase-4 skeleton narrative rather than reading run-level emission/build/preflight/load evidence.
4. **High — current backend is not a general deployable PolicyLang backend.** `codegen/backend.py` deliberately has no operating-system task classifier for multi-class policies and correctly falls back to global FIFO; runtime preflight is inspection-only. Generated source, build, and kernel load must remain separate statuses.
5. **Medium — workbench workflow remains fragmented.** Baseline browser inspection rendered ten top-level modes. At 1280px the overview run table clips the action column, despite the rest of the visual system being reasonably coherent.
6. **Medium — visible project-status API is stale.** `server.py`’s `api_progress` describes Phase 2 and Phase 3 as planned even though the live tree includes their implementations and tests.
7. **Medium — production deployment hardening is not visible in application code.** `server.py` uses wildcard CORS with credentials and exposes source-reading/build paths without an authentication boundary. This may be acceptable for local research use only; any network deployment needs a documented deployment profile with strict origins, host protection, and authentication/authorization.

## Environment limits

This audit host is Windows. A local API preflight/browser run is permitted; sched_ext building/loading, telemetry collection, and predictor validation need an explicitly authorized Linux 6.12+ disposable VM and real paired traces. No such load was attempted.

## Remediation evidence — 2026-10-24

| Task | Result | Evidence |
| --- | --- | --- |
| Intent semantics | Complete | `24f6055`: directed priority edges are cycle-checked before policy generation; equal numeric tiers remain valid. |
| Provider contract | Complete | `8453216`: missing configuration, malformed upstream responses, retryable failures, and safe API envelopes are regression-tested; no live provider was called. |
| Report evidence | Complete | `d6d333a`: legacy and emission-only records normalize unproven runtime stages to `NOT_RUN`; PDF stage text is record-backed. |
| Studio workflow | Complete | `17252c4`: grouped desktop navigation, sticky run actions, narrow icon navigation with accessible names, and structured provider-error display. |
| Status/security disclosure | Complete | Same-origin local API is the default; configured CORS is explicit and non-credentialed. Progress data reports implemented Phases 2/3 and `EXPERIMENTAL_NOT_RUN` Phase 4. |

### Validation performed

- Full regression suite after the Studio task: `117 passed`.
- Browser, local-only `127.0.0.1:8766`: desktop grouping and visible row actions; 390px narrow view; a real `Compile & Run` against `aging_fix`; and a missing-OpenRouter-key path. The browser displayed the sanitized operation, provider, `configuration` category, non-retryability, and correlation reference. The expected API response was HTTP 400; no live provider request was made.
- `experiments/soundness.py`: 400 randomized trials, 789 finite-class checks, zero bound violations, and zero share-floor violations. This is a fresh differential test, not a claim about kernel execution.
- `experiments/run_phase4_metrics.py`: regenerated `experiments/results/phase4_metrics.json` with `NOT_RUN` because no paired Linux sched_ext observations exist on this Windows host.

### Phase 4 evidence ledger

| Stage | Status | Basis |
| --- | --- | --- |
| Source emission | Implemented/inspectable | Bounded emitter and unit tests; this does not prove a compiler accepted output. |
| BPF build | NOT_RUN | No Linux BPF toolchain build recorded on this host. |
| Kernel preflight/load | NOT_RUN | No authorized Linux 6.12+ VM or kernel load. |
| Telemetry/watchdog/hot swap | NOT_RUN | No real kernel execution or complete telemetry. |
| Predictor validation | NOT_RUN | No paired simulator/real observations. |

### Remaining deployment risks

The local server still has no authentication/authorization model, so the documented CORS boundary is a local-development safeguard, not a production deployment profile. Multi-class backend dispatch remains unsupported without an operating-system task classifier. A real Linux VM validation must separately establish compilation, verifier acceptance, load behavior, telemetry completeness, watchdog fallback, and predictor accuracy.
