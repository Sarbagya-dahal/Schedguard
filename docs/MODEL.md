# Formal model (what is actually proven)

## Scheduler semantics (shared by the simulator and the verifier)
- One CPU. Tasks are CPU-bound (always runnable). Quanta are non-preemptive.
- Each class has `prio` (0 = most urgent tier), `quantum` Q (ms), optional `aging` A (ms).
- Dispatch rule: the *top queue* is a FIFO of (a) tasks in the highest populated tier, and
  (b) **boosted** tasks: a task in any lower tier whose class has aging and that has been ready for >= A ms
  enters the top queue at the instant it becomes eligible (its FIFO position is that instant).
  A task runs one quantum, then is re-enqueued at the back with ready_since = now.
- A task in a lower tier without aging never runs while a higher tier is populated (starvation).

## Quantities
n_j = runnable tasks in class j (symbolic in 0..max_tasks; n_i >= 1 for the class under test).
W_i = upper bound on the time from "task becomes ready" to "task is dispatched":
```
H  = sum_{prio_j <  prio_i} n_j Q_j
S  = sum_{prio_j == prio_i} n_j Q_j - Q_i
G  = sum_{aging_j, prio_j > prio_i} n_j Q_j
BA = sum_{aging_j, prio_j >= prio_i} n_j Q_j - Q_i
higher = exists j: prio_j < prio_i and n_j >= 1
W_i = INF               if higher and not aging_i
    = A_i + H + BA      if higher and aging_i
    = S + G             otherwise
```
**Why it is an upper bound (sketch).** The top queue is FIFO by entry time. Once a task is in it, only
tasks that entered earlier run before it, and each of them runs at most once (after running it re-enters
behind). Entry happens at ready_since (top tier) or ready_since + A (boosted). Tasks that could be ahead are
bounded by the sums above (counted conservatively: every possibly-present task contributes one quantum).

## Guarantees checked (property library)
- `no_starvation(C, B ms)`: for all workloads in the domain, W_C <= B. Z3 searches for n with W_C > B.
- `min_share(C, P %)`: each task is served >= one quantum per (W_C + Q_C), so share >= n_C Q_C / (W_C + Q_C).
  Checked in linear form: 100 * n_C * Q_C >= P * (W_C + Q_C).

## Verdicts (three-valued, deliberately)
- **VERIFIED**: no workload in the domain violates the claim under the model.
- **VIOLATED**: Z3 found a counterexample workload AND the simulator reproduced the violation.
- **UNKNOWN**: Z3 found a counterexample to the *bound*, but replay did not reproduce it: the analysis is
  conservative there (W is an upper bound, not exact). Never reported as a violation. Tightening the
  analysis for these cases is future work.

## Validation of the model
`experiments/soundness.py`: random policies x random workloads, simulator max wait must never exceed the
closed-form bound (and starvation predictions must be reproduced). Latest run: see
`experiments/results/phase1_metrics.json` (`soundness`, `verification_gate`).

## Known limits (be upfront about these)
1. Static, CPU-bound workload model (no blocking/sleep, no arrivals in the proof). Phase 2 extends the
   simulator to bursty tasks; the proof stays restricted to the static class unless extended.
2. Single CPU. Multi-CPU/NUMA is out of scope.
3. The model is *our* scheduler semantics, not Linux sched_ext. Phase 4 adds a real backend and measures the
   simulator-to-real gap.
4. `min_share` is a conservative lower bound (UNKNOWN cases exist).
5. Properties are chosen from a fixed library; the AI cannot invent new property types.
