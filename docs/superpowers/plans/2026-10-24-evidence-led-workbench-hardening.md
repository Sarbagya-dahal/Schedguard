# Evidence-Led Workbench Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live SchedGuard workbench reject contradictory scheduling intent, expose provider failures safely and consistently, and report only backend evidence that actually exists.

**Architecture:** Preserve the existing PolicyLang compiler, verifier, simulator, and vanilla HTML/CSS/JS Studio. Add a small typed provider-error boundary shared by provider callers, strengthen intent extraction before any candidate source is accepted, normalize persisted run evidence before rendering reports, and use the existing API rather than synthetic browser data.

**Tech Stack:** Python 3, FastAPI, Pydantic, urllib, Z3, fpdf2, vanilla HTML/CSS/JavaScript, pytest, Playwright CLI.

**Spec:** `C:/Users/Sarbagya/.codex/attachments/35949ad3-9960-4398-933e-db4a0a40cb03/Pasted text.txt`

## Global Constraints

- Preserve the deterministic verifier as the sole acceptance authority; `UNKNOWN` is never success or violation.
- Treat provider responses and provider diagnostics as untrusted; never expose keys, bearer tokens, or large upstream payloads.
- Keep offline rules/stub explicitly labelled as non-LLM provenance.
- Do not perform kernel loading; on this Windows host, backend runtime remains `NOT_RUN` or `UNSUPPORTED` based on recorded evidence.
- Do not fabricate metrics, timeline events, or backend evidence.
- Keep the current HTML/CSS/JS stack; no framework migration.

## Review Focus

- Natural-language priority cycles joined by punctuation or conjunctions must fail before policy generation; Task 1 covers it.
- Equal numeric DSL tiers must remain valid while conflicting precedence intent fails; Task 1 covers it.
- Missing credentials, upstream HTTP responses, malformed success payloads, and network timeouts must be distinguishable without secret leakage; Task 2 covers it.
- Old run JSON without backend evidence must render as `NOT_RUN`, not a successful backend; Task 3 covers it.
- The Studio must not mark an API error as a successful proposal or let narrow viewports hide its primary run action; Task 4 covers it.

### Task 1: Intent and semantic invariant registry

**Files:**
- Create: `docs/semantics/invariants.md`
- Modify: `src/schedguard/inference/policy_gen.py`
- Modify: `tests/test_intent_parser_regression.py`
- Modify: `tests/test_verify_sim.py`

**Interfaces:**
- Consumes: `extract_intent(prompt_text: str) -> SchedulingIntent`.
- Produces: `SchedulingIntent.conflicts` populated for all directed precedence cycles; numeric equal tiers retained as valid policy semantics.

- [ ] **Step 1: Write failing intent regression tests** for conjunctive two-node priority contradictions, three-node cycles, and equal explicit tiers.
- [ ] **Step 2: Run the focused tests** and confirm the former two are not rejected while equal tiers are incorrectly rejected.
- [ ] **Step 3: Implement normalized precedence-edge extraction plus cycle detection** in `policy_gen.py`; preserve only semantic contradictions as conflicts.
- [ ] **Step 4: Write the invariant registry** mapping IDs to the safety pass, intent extraction, verifier verdict contracts, tests, and documented proof scope.
- [ ] **Step 5: Run focused and full semantic tests**, then commit the isolated change.

### Task 2: Provider error contract and OpenRouter hardening

**Files:**
- Modify: `src/schedguard/inference/providers.py`
- Modify: `src/schedguard/inference/policy_gen.py`
- Modify: `src/schedguard/server.py`
- Modify: `tests/test_providers.py`
- Modify: `tests/test_openrouter_policy_synthesis.py`
- Create: `tests/test_provider_api_errors.py`

**Interfaces:**
- Consumes: `OpenRouterProvider.complete(Prompt) -> str` and API provider selections.
- Produces: a safe provider-failure envelope with operation, provider, category, optional upstream status, retryability, correlation ID, and sanitized message.

- [ ] **Step 1: Write failing unit and API tests** for missing credentials, 400/401/402/403/404/429/500, timeout/network errors, malformed/empty choices, fenced JSON, cache failure, retry exhaustion, and explicit fallback provenance.
- [ ] **Step 2: Run the focused tests** and confirm the current route divergence (`/api/infer` generic 500; synthesis/generation nonuniform outcomes).
- [ ] **Step 3: Implement typed provider failures and a central API translation helper**; honour environment-configured model, timeout, and bounded retry settings; redact sensitive values in both logs and response payloads.
- [ ] **Step 4: Make all provider-facing routes return the same envelope/status semantics** while retaining an explicit successful offline fallback only when requested by policy.
- [ ] **Step 5: Add a default-disabled live smoke test** gated by both opt-in environment variable and credentials, then run the mocked suite and full suite.

### Task 3: Run evidence and data-driven reports

**Files:**
- Modify: `src/schedguard/report.py`
- Modify: `src/schedguard/server.py`
- Modify: `src/schedguard/codegen/backend.py`
- Modify: `tests/test_phase4_backend.py`
- Create: `tests/test_report_evidence.py`

**Interfaces:**
- Consumes: run snapshots whose `codegen`, build, preflight, and runtime evidence may be absent or from older schemas.
- Produces: normalized evidence fields for emission, build, preflight, load, telemetry, predictor, watchdog, and hot-swap, with `NOT_RUN` as the backward-compatible default.

- [ ] **Step 1: Write failing report tests** for a legacy run, an emitted-only run, and a genuinely successful recorded build/runtime evidence case.
- [ ] **Step 2: Run them** and confirm the current report emits its fixed Phase-4 wording regardless of input evidence.
- [ ] **Step 3: Implement evidence normalization and data-driven PDF sections**; retain formal-model and simulation provenance/limits.
- [ ] **Step 4: Keep emitter statuses honest**—multi-class policies without a task classifier are unsupported; generated source is not a build or load.
- [ ] **Step 5: Extract PDF text and render a sample page for layout inspection**, then run report/backend tests.

### Task 4: Workbench workflow and responsive data UI

**Files:**
- Modify: `src/schedguard/studio/index.html`
- Modify: `src/schedguard/studio/app.css`
- Modify: `src/schedguard/studio/app.js`
- Modify: `tests/test_frontend.py`
- Modify: `tests/test_studio_run_contract.py`

**Interfaces:**
- Consumes: compile, verification, simulation, provider envelope, and run evidence API payloads.
- Produces: one authoritative current policy state, coherent workflow navigation, rendered AST/IR and real workload timeline/comparison states, plus safe provider/error presentation.

- [ ] **Step 1: Write failing frontend/API contract tests** for provider error display, current-policy handoff, comparable simulator runs, and narrow-width table/action behavior.
- [ ] **Step 2: Run focused tests** and record the existing fragmented navigation and clipped action column baseline.
- [ ] **Step 3: Refactor the current Studio state/navigation and rendering without replacing the stack**; combine overlapping entry points into a Policy Workbench while retaining distinct draft, guarantee inference, synthesis, repair, simulation, gate, and backend operations.
- [ ] **Step 4: Render timelines and per-class metrics solely from simulator response data**, including empty/loading/error and comparability states.
- [ ] **Step 5: Validate desktop and narrow workflows through Playwright**, inspect screenshots, and run frontend/API suites.

### Task 5: Evidence audit, reproducibility, and integration verification

**Files:**
- Create: `docs/FINAL_OVERHAUL_AUDIT.md`
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Modify: `AGENTS.md`
- Modify: applicable experiment result metadata only when a documented runner regenerated it.

**Interfaces:**
- Consumes: exact test, soundness, experiment, browser, PDF, and backend evidence from Tasks 1–4.
- Produces: an evidence-backed architecture map, claim/status matrix, Windows run instructions, and honest experimental/future-scope boundaries.

- [ ] **Step 1: Record the live architecture and pre-change audit facts** (baseline SHA, test count, provider root cause, backend limitations, report/UI mismatches).
- [ ] **Step 2: Run only reproducible documented experiments affected by the changes**, recording seed, source, date, and status rather than inventing results.
- [ ] **Step 3: Update documentation and visible status labels from the recorded evidence**; do not modify the supplied review PDF.
- [ ] **Step 4: Run the full test suite, soundness, selected metrics, PDF render check, and browser workflow**, then inspect Git diff/status/secrets.
- [ ] **Step 5: Obtain an independent final code review, fix critical/important findings test-first, and create the final non-pushed commit.**

## Self-Review

The plan covers the required highest-risk semantic regression, the observed OpenRouter API root cause, report/runtime-status integrity, the existing Studio’s workflow and responsive rendering, and evidence-based documentation. A fully validated real Linux sched_ext runtime cannot be claimed from this Windows host; the plan therefore makes its unsupported/not-run boundary explicit rather than simulating completion.
