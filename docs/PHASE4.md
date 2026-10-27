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
Task class assignment is intentionally a loader responsibility, but the current
backend does not yet define the required control-plane mapping or prove that
`select_cpu` and `enqueue` apply it consistently. Therefore multi-class IRs are
rejected before C emission with a specific `UNSUPPORTED` diagnostic; they are
never emitted with a misleading global-FIFO fallback. A single-class, no-aging
IR can be emitted with its only class selected and its configured quantum used
on the class DSQ. It also defines `select_cpu` and applies that same quantum
when the kernel's default idle-CPU path would otherwise bypass `enqueue`; a
metadata-map failure uses the configured quantum on the global fallback path.
Policies with aging are also rejected until enqueue-age
promotion is implemented in runtime decision logic. PolicyLang guarantee claims
remain explicitly unsupported by this backend.

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
