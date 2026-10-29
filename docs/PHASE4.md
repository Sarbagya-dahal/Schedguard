# Phase 4 backend

Phase 4 is split into explicit stages: IR validation, C emission, clang BPF
compilation, kernel preflight, operator-authorized load, health monitoring, and
real telemetry collection. A successful earlier stage never implies success of
a later stage.

## Supported backend semantics

`codegen.backend.emit_ebpf_c` emits bounded Linux sched_ext source for the
validated fixed-size IR: class configuration, lower-number-is-more-urgent
priority tiers, quantum values, bounded DSQ creation/scan, task lifecycle
callbacks, and a ring-buffer map for telemetry. The source targets Linux 6.12+
with `vmlinux.h`, libbpf headers, `scx/common.bpf.h`, and
`clang -target bpf`.

The formal proof remains the single-CPU, CPU-bound model in `docs/MODEL.md`.
Linux blocking, arrivals, multiple CPUs, kernel preemption details, BPF
verifier acceptance, and runtime behavior are separate validation concerns.
Task class assignment is explicit in the generated control plane:
`option sched_ext_map = kind;` maps bounded task-`comm` prefixes to the
declared class names. For compatibility with the original two-class
`web_batch_sched` acceptance policy, the same mapping is inferred when both
classes declare `kind` and the policy contains exactly one 400 ms
`no_starvation` target. Other policies without the opt-in mapping remain
`UNSUPPORTED` rather than silently using a global-FIFO fallback. The supported
path applies mapping consistently in `select_cpu` and `enqueue`, creates one DSQ per
class, scans priority tiers, and promotes classes whose oldest queued task has
passed its declared aging threshold. A
single-class, no-aging IR continues to be emitted with its only class selected
and its configured quantum used on the class DSQ. PolicyLang guarantee claims
are reported as runtime limitations by this backend because the formal proof
model is separate from Linux multi-CPU runtime behavior; source emission does
not establish those guarantees.

The generated enqueue call follows the sched_ext ABI order
`(task, dsq_id, slice_ns, enqueue_flags)` and includes the sched_ext
compatibility header for version-sensitive helpers. The task metadata map has
an explicit runtime capacity (`SG_RUNTIME_MAX_TASKS=4096`) separate from the
formal model bound (`SG_MODEL_MAX_TASKS`); map insertion failures route to the
global FIFO. Ring-buffer reservations are checked before submitting lifecycle
events.

## Safe workflow

```text
PYTHONPATH=src python -m schedguard preflight --json
PYTHONPATH=src python -m schedguard emit examples/aging_fix.sched -o build/aging_fix.c
PYTHONPATH=src python -m schedguard build examples/aging_fix.sched \
  --source build/aging_fix.c --output build/aging_fix.bpf.o \
  --vmlinux /path/to/vmlinux.h --scx-header /path/to/include/scx/common.bpf.h
```

On Windows or without the Linux prerequisites, these commands report
`NOT_READY`/`NOT_RUN`; they do not install dependencies or load a scheduler.
Use a disposable Linux 6.12+ VM with sched_ext enabled for compilation and
load testing. Kernel load requires an explicit operator workflow and is not a
Studio startup action. Keep a known-good scheduler available and use the
kernel's normal scheduler as the deterministic emergency fallback.

The lifecycle module records `INSPECTION_ONLY`, `LOADED_AWAITING_HEALTH`,
`HEALTHY`, `LOAD_FAILED`, and `FALLBACK_REQUIRED`. A watchdog requires both a
healthy-startup signal and complete telemetry; it never delegates failure
decisions to an AI model.

## Real telemetry

Real traces use `schedguard.real_trace.v1` and `provenance=real_kernel_bpf`.
They must include a policy/run id, workload id and seed, kernel release,
dispatch events, dropped-event count, and a completeness status. Simulator or
mock traces must not be placed in the real-trace directory.
