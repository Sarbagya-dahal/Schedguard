# Review 1: Q&A preparation

Rubric (10 marks): problem & objectives 2, literature survey 2, novelty 2, 25% implementation 2, presentation & Q&A 2.
Strategy: never overclaim. Examiners reward "we know exactly what we proved and what we didn't".

## Questions to expect, with answers

**1. "Isn't this just SchedCP?"**
No. SchedCP has LLM agents write raw eBPF schedulers, with static/dynamic safety verification plus runtime
canaries and circuit breakers. We (a) put the agent behind a DSL, (b) prove *scheduling-level* properties
(starvation, share), not just load-safety, (c) use AI on both sides of the verifier but never inside it.
SchedCP's own discussion lists regression/fairness/starvation trust and cross-workload generalisation as open.

**2. "Why is the novelty not just 'LLM + Z3'?"**
The contribution is the architecture and the checked interfaces: AI-proposed guarantees from a vetted
property library, a three-valued verdict with simulator replay, and (Phase 2) adversarial pre-deployment traces.
We state it as "to our knowledge, from our literature search".

**3. "If the AI picks the specification, who checks the specification?"**
Three layers: only properties from a fixed library are accepted (schema gate); every proposal is proved or
refuted against the actual policy; and the operator approves the final property set. Wrong specs cost an
iteration, never a safety failure, because acceptance is decided by the verifier.

**4. "How do you know your bound is correct?"**
It is derived in docs/MODEL.md and validated by a differential test: 2,000 random policies x workloads,
4,287 finite-class checks, zero cases where the simulator exceeded the bound; 1,069 starvation predictions
all reproduced. Also 496 random-workload attacks on VERIFIED guarantees found zero false accepts.
(Say: this is evidence, not a mechanised proof.)

**5. "What does UNKNOWN mean? Isn't that a failure?"**
The bound is an upper bound, so Z3 can find a workload where the *bound* exceeds the claim even though the
real behaviour doesn't. Replay shows it. We refuse to call that a violation or a proof. It's honest, and
shrinking the UNKNOWN rate is a measurable goal.

**6. "Your model assumes CPU-bound tasks and one CPU."**
Yes, stated up front (docs/MODEL.md limits). Phase 2 adds bursty/blocking workloads in the simulator and
uses adversarial search to probe outside the proof's scope. Multi-CPU is out of scope.

**7. "Where is eBPF / sched_ext?"**
Phase 4. The IR and safety limits are designed to be fixed-size so the backend is a lowering step. We
deliberately proved the idea in a simulator first because it is testable without a kernel.

**8. "Where is the AI result? The stub isn't AI."**
Correct. The stub is an offline stand-in for testing the pipeline and must not be read as LLM
performance. The real-LLM vs rule-table comparison is Phase 1b, with the harness spec in AGENTS.md.
(If you ran it before the review, present those numbers with variance over 3 runs.)

**9. "Why AI instead of a rule table?"**
Coverage. A rule table maps known workload types to fixed templates and returns nothing for novel
classes (see tests: untagged class gets zero proposals). We measure it against the baseline instead of
assuming; if AI does not win, we say so.

**10. "How does this relate to your course (Compiler Design)?"**
Lexer (Module 1), LL(1) recursive-descent parser (Module 2), syntax-directed lowering to IR (Module 3/4),
static analysis over a fixed-size IR (Module 5 dataflow-style bounds checks), DSL compilation (Module 7).
Only claim what's implemented: no SSA/optimisation passes yet.

**11. "What did you implement vs. design?"**
Implemented: everything in AGENTS.md "Status" Phase 1 items (812 non-blank source lines, 27 tests).
Designed: Phases 2-4 (ROADMAP.md).

**12. "Why not a formal proof assistant?"**
SMT over linear integer arithmetic is decidable and fast (about 3-7 ms per guarantee up to 16 classes),
which makes it usable inside an agent loop. A mechanised proof of the bound is future work.

**13. "Is 25% really done?"**
Phase 1 is weighted 25% in ROADMAP.md with measurable exit criteria; show the checklist.

## Demo plan (3 minutes, scripted)
1. `python -m schedguard check examples/strict_starves.sched`: VIOLATED, counterexample, replay.
2. `python -m schedguard analyze examples/aging_fix.sched`: provable worst-case wait/share.
3. `python -m schedguard check examples/three_tier.sched`: show an UNKNOWN and explain it.
4. `python -m schedguard infer examples/aging_fix.sched intents/web_batch.json`: proposals -> verdicts.
Fallback if the laptop misbehaves: show `experiments/results/phase1_metrics.json` and the slide screenshots.

## Delivery tips
- Open with the gap (one sentence), not the architecture.
- Say "to our knowledge" for every novelty statement; name SchedCP yourself before they do.
- Know three numbers cold: 0 bound violations, 0 false accepts, ~3-7 ms per proof.
- If asked something you haven't built, say which phase covers it and what measurement would answer it.
