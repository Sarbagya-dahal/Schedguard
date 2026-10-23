# Roadmap: SchedGuard

Order of implementation is fixed: Feature 1 -> 2 -> 3 -> 4. Percentages = share of total implementation.

| Phase | Weight | Scope | Exit criteria (measurable) |
|---|---|---|---|
| **1. Foundation + Feature 1** (this repo) | 25% | PolicyLang compiler, safety pass, IR, Z3 verifier, simulator, replay; AI guarantee proposer with schema gate, OpenRouter/Anthropic providers, rule baseline | [x] COMPLETE: 53 tests pass; bound sound vs simulator (0 violations); 0 false accepts; **1b:** eval_inference.py harness run across 13 diverse intents |
| **2. Feature 2: adversarial workloads** | 25% | (a) simulator v2: bursty/blocking tasks, arrivals; (b) non-AI attackers: random + hill-climbing; (c) LLM attacker producing structured workload specs; (d) counterfactual gate: candidate must not regress incumbent on recorded + adversarial traces | [x] COMPLETE: LLM attacker vs random/hill-climb evaluated; gate catches 95.2% of planted regressions; 0.0% false alarm rate |
| **3. Feature 3: violation classification + repair** | 20% | cause taxonomy for counterexamples; AI explains + proposes policy edit; policy-synthesis agent loop; baselines: raw cex, template message, AI explanation | iterations-to-verified and success rate within budget, three conditions compared on >= 30 broken policies |
| **4. Feature 4 + real backend + final evaluation** | 30% | bounded sched_ext C emission, explicit clang/preflight workflow, lifecycle/watchdog state, versioned real-trace schema, predictor interface and conservative gate integration; Linux VM load/telemetry and learned-model evaluation remain environment-dependent | measured sim-vs-real gap; predictor error vs constant-threshold baseline; end-to-end demo |

## Phase 1 detail (what the first review shows)
Done: items in AGENTS.md "Status". For the review: demo `check` on strict_starves (counterexample + replay),
`analyze` on aging_fix, `infer` with the stub, plus the metrics slide. State clearly that the LLM comparison
(Phase 1b) is pending.

## Phase 2 notes
- Why adversarial traces: the proof covers only the static CPU-bound class. Real workloads block, burst and
  arrive. Adversarial search finds where a candidate policy regresses an incumbent outside the proof's scope.
- Honest design: always include random and hill-climbing baselines; the claim is "LLM attacker finds
  regressions faster/cheaper", not "LLM is magic".

## Phase 3 notes
- Prior art nearby: bpfix (explains raw eBPF verifier rejections). Ours explains *policy-level* semantic
  counterexamples. Keep this distinction in the writing.

## Phase 4 notes
- Needs root + Linux 6.12+ (sched_ext). Develop in a VM. The BPF emitter lowers the IR class table and the
  dispatch rule in docs/MODEL.md; the safety pass limits already mirror fixed-size eBPF tables.
- Feature 4 requires real telemetry, hence the backend lives in this phase.

## Risks
| Risk | Mitigation |
|---|---|
| LLM adds no measurable value over rule table | The harness reports it honestly; novelty also rests on the verification architecture |
| Too many UNKNOWN verdicts | Tighten analysis; report UNKNOWN rate as a metric |
| sched_ext backend slips | Phase 1-3 stand alone as a complete simulated system |
| Scope | Cut order: Feature 4 predictor -> Feature 3 synthesis loop -> keep 1+2 |
