# Roadmap: SchedGuard

Order of implementation is fixed: Feature 1 -> 2 -> 3 -> 4. Percentages = share of total implementation.

| Phase | Weight | Scope | Exit criteria (measurable) |
|---|---|---|---|
| **1. Foundation + Feature 1** | 25% | PolicyLang compiler, safety pass, IR, Z3 verifier, simulator, replay; AI guarantee proposer with schema gate, provider interfaces, rule baseline | [x] Implemented. Offline and mock/provider paths are explicitly distinct; run the documented soundness/evaluation commands for provenance. |
| **2. Feature 2: adversarial workloads** | 25% | Simulator v2, bounded random/hill-climbing attackers, structured attacker interface, and counterfactual gate | [x] Implemented with recorded offline experiment artifacts. A stub attacker is not reported as a live LLM result. |
| **3. Feature 3: violation classification + repair** | 20% | Cause taxonomy, bounded repair loop, synthesis integration, benchmark corpus, and offline comparative baselines | [x] Implemented and benchmarked offline. Live-provider evaluation remains opt-in and is not inferred from stub results. |
| **4. Feature 4 + real backend + final evaluation** | 30% | Bounded sched_ext C emission, explicit build/preflight API, lifecycle/watchdog state, real-trace schema, predictor interface, conservative gate integration | [~] Experimental scaffolding. Linux VM compilation/load/telemetry and learned-predictor validation are `NOT_RUN`; no sim-vs-real or end-to-end deployment claim is made. |

## Phase 1 detail (what the first review shows)
Done: items in AGENTS.md "Status". For the review: demo `check` on strict_starves (counterexample + replay),
`analyze` on aging_fix, `infer` with the stub, plus the metrics slide. State clearly that an offline/stub
run is not a live LLM comparison.

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
