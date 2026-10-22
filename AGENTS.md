# AGENTS.md: context for AI coding assistants (read this first)

## Project in one paragraph
SchedGuard makes AI-driven scheduler changes **safe by construction**. An operator (or an AI agent) writes
scheduling policies in a tiny DSL, **PolicyLang**. The compiler lowers them to a fixed-size IR, a safety pass
enforces eBPF-like bounds, and a Z3-based verifier proves or refutes *scheduling-level guarantees*
(no starvation, minimum CPU share) over **all** workloads up to a size bound. Counterexamples are replayed in
a simulator. AI is used to *propose* guarantees (Feature 1), *attack* candidate policies with adversarial
workloads (Feature 2), *explain/repair* violations (Feature 3) and *predict simulator error* (Feature 4).
**The AI never decides acceptance. The deterministic verifier does.**

## Novelty claim (keep wording careful)
Prior work (SchedCP/sched-agent) lets LLM agents synthesize eBPF schedulers with safety verification and
runtime canary/circuit breakers. Verified scheduler DSLs (older work) prove properties but have no AI.
BeePL verifies eBPF safety, not scheduling semantics. To the best of our literature search, nobody combines
(a) AI-proposed *formal scheduling guarantees*, (b) policy-level proofs/counterexamples, and
(c) pre-deployment adversarial/counterfactual evaluation. Never claim "first ever"; say "to our knowledge".

## Repository tree
```
schedguard/
├── AGENTS.md                  <- this file
├── README.md  ROADMAP.md  pyproject.toml  requirements.txt
├── docs/
│   ├── MODEL.md               formal semantics, bound derivation, verdict meaning, limits
│   └── QA_PREP.md             review Q&A preparation
├── src/schedguard/
│   ├── limits.py              hard limits (fixed-size/eBPF-like) + INF marker
│   ├── compiler.py            source -> AST -> safety pass -> IR driver
│   ├── dsl/                   lexer.py (regex tokens), parser.py (LL(1) recursive descent), ast_nodes.py
│   ├── ir/                    ir.py (IRClass/IRGuarantee/IRPolicy), lower.py (AST->IR)
│   ├── verify/
│   │   ├── safety.py          range/uniqueness/reference checks (codes E001..E010)
│   │   ├── model.py           closed-form wait bound, ONE definition with NUM and SMT backends
│   │   └── properties.py      Z3 checker, counterexample replay, tightest bound, guaranteed min share
│   ├── sim/                   simulator.py (Simulator v2, bursts/sleeps, latency p50/p99), workload.py
│   ├── inference/             Feature 1
│   │   ├── schema.py          property library + STRICT validation of untrusted AI output
│   │   ├── rules.py           rule-table baseline (keyed by `kind` hint)
│   │   ├── prompts.py         system/user prompt builder
│   │   ├── providers.py       StubProvider (offline, not an AI) + AnthropicProvider + OpenRouterProvider
│   │   └── pipeline.py        propose -> validate -> verify; rules fallback on failure
│   ├── adversary/             Feature 2
│   │   ├── space.py           bounded workload parameter space + strict spec validator
│   │   ├── objectives.py      regression & scope-violation objectives
│   │   └── attackers.py       RandomAttacker, HillClimbAttacker, LLMAttacker
│   ├── gate.py                pre-deployment regression gate (static + traces + adversarial search)
│   └── cli.py                 subcommands: ir | check | analyze | simulate | infer | attack | gate
├── examples/*.sched           balanced, strict_starves, aging_fix, three_tier, invalid_ranges
├── workloads/*.json  intents/*.json (13 intents)  traces/*.json (4 recorded traces)
├── tests/                     71 tests (frontend, verifier, simulator v2, space, attackers, gate, eval)
└── experiments/
    ├── soundness.py           bound-vs-simulator differential test
    ├── eval_inference.py      Phase 1b rule-vs-LLM evaluation harness
    ├── planted_regressions.py Phase 2 planted regression benchmark suite
    ├── run_phase2_metrics.py  Phase 2 multi-seed metrics runner
    ├── run_metrics.py         regenerates results/phase1_metrics.json (all numbers in the report)
    └── results/               phase1_metrics.json, eval_inference.json, planted_regressions.json, phase2_metrics.json
```

## Data flow
`*.sched` -> `dsl.parse` -> `verify.safety.check` -> `ir.lower` -> `IRPolicy`
-> `verify.properties.check_guarantee` (Z3; VERIFIED | VIOLATED | UNKNOWN) -> replay in `sim.simulate`.
Feature 1: `inference.pipeline.infer(ir, intent, provider)`: facts = `analyze(ir)` -> prompt -> provider
-> `schema.validate` -> `check_guarantee` per accepted proposal.
Feature 2: `gate.evaluate_candidate(incumbent, candidate, traces, budget, tolerance, attacker)`:
static checks -> recorded traces -> adversarial search -> ACCEPT | REJECT.

## Invariants (never break these)
1. **AI output is untrusted.** Every provider response goes through `schema.validate` (guarantees) or `validate_spec` (workloads). No exceptions.
2. **Only the verifier accepts/rejects.** No code path may mark a guarantee verified because an AI said so.
3. `model.py` is the single source of truth for the bound; the simulator must stay semantically identical
   to docs/MODEL.md. If you change one, change the other and rerun `experiments/soundness.py`.
4. `UNKNOWN` must never be reported as `VIOLATED` or `VERIFIED`.
5. `StubProvider` is an offline stand-in: never report its output as LLM performance.
6. Keep everything fixed-size/bounded (limits.py); a future eBPF backend depends on it.
7. Don't hard-code numbers in reports: regenerate them with `experiments/run_metrics.py`.

## Commands
```
export PYTHONPATH=src:experiments
python -m pytest -q
python -m schedguard check|analyze|simulate|infer|attack|gate|ir ...
python experiments/run_metrics.py
python experiments/eval_inference.py
python experiments/planted_regressions.py
python experiments/run_phase2_metrics.py
```

## Status
- [x] Phase 1 core: DSL, parser, safety pass, IR, Z3 verifier, simulator, replay, CLI, Studio, 34 initial tests
- [x] Feature 1 skeleton: property library, schema gate, rule baseline, stub + Anthropic providers, pipeline
- [x] **Phase 1b:** evaluation harness `experiments/eval_inference.py` comparing rule baseline vs
      LLM on >= 12 intents in `intents/` (includes untagged/novel class names, prompt injection).
      Metrics: classes covered, schema-reject rate, verified/violated/unknown rates, distance to provable frontier
      (proposed bound / tightest bound). Supports OpenRouter and Anthropic with offline fallback.
      53 tests total passing.
- [x] **Phase 2 (Feature 2):** Simulator v2 (bursts/sleeps, event queue, dispatch latency percentiles),
      bounded parameter space, regression & scope-violation objectives, Random / HillClimb / LLM attackers,
      pre-deployment regression gate (`gate.py`), planted-regression benchmark suite (`planted_regressions.py`),
      multi-seed metrics runner (`run_phase2_metrics.py`), CLI `attack` & `gate`. 71 tests passing.
- [ ] Phase 3 (Feature 3), Phase 4 (Feature 4 + real sched_ext backend): see ROADMAP.md

## Good first prompts for an assistant
- "Write experiments/eval_inference.py per the Phase 1b spec in AGENTS.md and add 12 diverse intents."
- "Add a `max_wait_p99` metric to the simulator output and a CLI flag to print it."
- "Add property type `max_wait_ratio(A, B, k)` to the library: schema.py, model/properties.py, tests."
- "Tighten the min_share analysis to reduce UNKNOWN verdicts without breaking the soundness test."

## Pitfalls
- Z3 terms: use `z3.Or(*xs)` with non-empty lists only (model.py handles the empty case).
- Heredoc/brace expansion in `sh` differs from bash; use bash when scripting directory creation.
- The replay horizon is capped (properties._replay_horizon) to keep verification fast.
