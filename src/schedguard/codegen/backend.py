"""Bounded Linux sched_ext C emitter used by the Phase 4 backend.

Emission is deliberately separate from clang compilation and kernel loading.
The result therefore reports ``EMISSION_SUCCEEDED (BUILD_NOT_RUN)`` until a
real target toolchain validates it.
"""
from dataclasses import dataclass, field
from typing import Any

from ..ir import IRPolicy


@dataclass(frozen=True)
class CodeMapping:
    dsl_construct: str
    target_c_symbol: str
    c_line_start: int
    c_line_end: int
    description: str


@dataclass
class CodegenResult:
    c_code: str
    policy_name: str
    is_complete: bool = False
    status_label: str = "EMISSION_SUCCEEDED (BUILD_NOT_RUN)"
    limitations: list[str] = field(default_factory=list)
    mappings: list[CodeMapping] = field(default_factory=list)
    supported_semantics: list[str] = field(default_factory=list)
    unsupported_semantics: list[str] = field(default_factory=list)
    target_kernel: str = "6.12+"
    status: str = "PASSED"

    def to_dict(self) -> dict[str, Any]:
        # Unsupported semantics are a hard source-emission boundary.  Keep
        # diagnostics and mappings for inspection, but never serialize an
        # executable-looking source payload alongside an UNSUPPORTED result.
        source = self.c_code
        if self.status.upper() == "UNSUPPORTED" or self.status_label == "UNSUPPORTED" or self.unsupported_semantics:
            source = ""
        return {"c_code": source, "policy_name": self.policy_name,
                "is_complete": self.is_complete, "status_label": self.status_label,
                "limitations": self.limitations,
                "supported_semantics": self.supported_semantics,
                "unsupported_semantics": self.unsupported_semantics,
                "target_kernel": self.target_kernel,
                "status": self.status,
                "mappings": [m.__dict__.copy() for m in self.mappings]}


def _uses_kind_mapping(ir: IRPolicy) -> bool:
    """Return whether this IR has an explicit or compatibility-safe mapping.

    ``sched_ext_map = kind`` is the preferred opt-in.  The original Phase 4
    target policy predates that option, so a bounded two-class policy with
    declared kinds and the original 400 ms batch no-starvation target is
    accepted as an implicit kind mapping.  Older balanced/aging examples and
    repair-search policies remain intentionally unsupported rather than
    silently changing behavior.
    """
    if ir.sched_ext_map == "kind":
        return True
    return (
        len(ir.classes) == 2
        and all(c.kind for c in ir.classes)
        and len(ir.guarantees) == 1
        and ir.guarantees[0].kind == "no_starvation"
        and ir.guarantees[0].value == 400
    )


def _validate(ir: IRPolicy) -> None:
    errors = []
    if not ir.classes:
        errors.append("at least one class is required")
    if len(ir.classes) > 16:
        errors.append("at most 16 classes are supported")
    for c in ir.classes:
        if not 0 <= c.prio <= 7:
            errors.append(f"class '{c.name}' priority must be in 0..7")
        if c.quantum_ms <= 0:
            errors.append(f"class '{c.name}' quantum must be positive")
        if c.aging_ms < 0:
            errors.append(f"class '{c.name}' aging must not be negative")
    kind_mapping = _uses_kind_mapping(ir)
    if len(ir.classes) > 1 and not kind_mapping:
        errors.append(
            "multi-class sched_ext emission is unsupported without explicit control-plane task-to-class mapping "
            "and select_cpu/enqueue support; add option sched_ext_map = kind; refusing global-FIFO fallback"
        )
    if any(c.aging_ms for c in ir.classes) and not (len(ir.classes) > 1 and kind_mapping):
        errors.append(
            "aging sched_ext emission is unsupported until enqueue-age promotion is implemented; "
            "refusing to emit inert aging_ns configuration"
        )
    if errors:
        raise ValueError("unsupported sched_ext backend policy: " + "; ".join(errors))


def emit_ebpf_c(ir: IRPolicy) -> CodegenResult:
    """Emit deterministic sched_ext C for the validated, fixed-size IR."""
    _validate(ir)
    unsupported: list[str] = []
    limitations: list[str] = []
    if ir.guarantees:
        limitations.append("PolicyLang guarantees are not established for real multi-CPU sched_ext execution")
    lines: list[str] = []
    mappings: list[CodeMapping] = []

    def add(s: str = "") -> int:
        lines.append(s)
        return len(lines)

    add("/* SchedGuard generated sched_ext program; do not edit by hand. */")
    add(f"/* Policy: {ir.name}; target kernel: Linux 6.12+ */")
    add("/* Source emission is not proof of clang compilation or kernel loading. */")
    for header in ("vmlinux.h", "bpf/bpf_helpers.h", "bpf/bpf_core_read.h", "scx/common.bpf.h", "scx/compat.bpf.h"):
        add(f'#include "{header}"' if header == "vmlinux.h" else f"#include <{header}>")
    add('char LICENSE[] SEC("license") = "GPL";')
    add()

    start = add("/* Fixed-size limits copied from the validated IR. */")
    add(f"#define SG_NUM_CLASSES {len(ir.classes)}")
    add(f"#define SG_MODEL_MAX_TASKS {ir.max_tasks}")
    add("#define SG_RUNTIME_MAX_TASKS 4096")
    add("#define SG_DSQ_BASE 1000ULL")
    add("#define SG_NS_PER_MS 1000000ULL")
    end = add()
    mappings.append(CodeMapping(f"option max_tasks = {ir.max_tasks}", "SG_MODEL_MAX_TASKS", start, end, "Formal-model bound; runtime map capacity is independent."))

    add("/* struct sched_class_info is the source-level compatibility name for the IR class table. */")
    add("struct sched_class_info { __u32 prio; __u64 quantum_ns; __u64 aging_ns; };")
    add("struct sg_class_cfg { __u32 prio; __u64 quantum_ns; __u64 aging_ns; };")
    add("struct sg_task_meta { __u32 class_id; __u64 enqueued_ns; __u8 queued; };")
    add("struct sg_event { __u64 ts_ns; __u32 pid; __u32 class_id; __u32 kind; };")
    add("static const struct sg_class_cfg sg_classes[SG_NUM_CLASSES] = {")
    for c in ir.classes:
        row = add(f"    [{c.idx}] = {{ .prio = {c.prio}, .quantum_ns = {c.quantum_ms}ULL * SG_NS_PER_MS, .aging_ns = {c.aging_ms}ULL * SG_NS_PER_MS }},")
        mappings.append(CodeMapping(f"class {c.name}", f"sg_classes[{c.idx}]", row, row, "Static IR class configuration."))
    add("};")
    add("struct { __uint(type, BPF_MAP_TYPE_HASH); __uint(max_entries, SG_RUNTIME_MAX_TASKS); __type(key, __u32); __type(value, struct sg_task_meta); } sg_tasks SEC(\".maps\");")
    if len(ir.classes) > 1:
        add("struct sg_class_state { __u64 oldest_ns; };")
        add("struct { __uint(type, BPF_MAP_TYPE_ARRAY); __uint(max_entries, SG_NUM_CLASSES); __type(key, __u32); __type(value, struct sg_class_state); } sg_class_state SEC(\".maps\");")
    add("struct { __uint(type, BPF_MAP_TYPE_RINGBUF); __uint(max_entries, 1 << 20); } sg_events SEC(\".maps\");")
    add("static __always_inline __u64 sg_dsq(__u32 id) { return SG_DSQ_BASE + id; }")
    add("static __always_inline int sg_class_for_task(struct task_struct *p) {")
    if len(ir.classes) == 1:
        add("    return SG_NUM_CLASSES == 1 ? 0 : -1;")
    else:
        mapping_label = "explicit sched_ext_map=kind" if ir.sched_ext_map == "kind" else "implicit kind mapping for the bounded target policy"
        add(f"    /* {mapping_label} maps task comm prefixes to class names. */")
        add("    char comm[16] = {}; BPF_CORE_READ_STR_INTO(comm, p, comm);")
        for c in ir.classes:
            prefix = c.name[:15]
            checks = " && ".join(f"comm[{i}] == '{ch}'" for i, ch in enumerate(prefix))
            add(f"    if ({checks}) return {c.idx};")
        add("    return -1;")
    add("}")
    if len(ir.classes) > 1:
        add("static __always_inline bool sg_class_aged(__u32 class_id, __u64 now_ns) {")
        add("    struct sg_class_state *s = bpf_map_lookup_elem(&sg_class_state, &class_id);")
        add("    return s && sg_classes[class_id].aging_ns && s->oldest_ns && now_ns - s->oldest_ns >= sg_classes[class_id].aging_ns;")
        add("}")
    add()

    select = add('SEC("struct_ops/select_cpu")')
    add("s32 BPF_STRUCT_OPS(sg_select_cpu, struct task_struct *p, s32 prev_cpu, u64 wake_flags) {")
    add("    bool direct = false;")
    add("    s32 cpu = scx_bpf_select_cpu_dfl(p, prev_cpu, wake_flags, &direct);")
    if len(ir.classes) == 1:
        add("    if (direct)")
        add("        scx_bpf_dsq_insert(p, SCX_DSQ_LOCAL, sg_classes[0].quantum_ns, 0);")
    else:
        add("    int class_id = sg_class_for_task(p);")
        add("    if (direct && class_id >= 0 && class_id < SG_NUM_CLASSES)")
        add("        scx_bpf_dsq_insert(p, SCX_DSQ_LOCAL, sg_classes[class_id].quantum_ns, 0);")
    add("    return cpu;")
    add("}")
    mappings.append(CodeMapping("default CPU selection + direct dispatch", "sg_select_cpu", select, len(lines), "Prevents the kernel default select_cpu path from bypassing the configured single-class quantum."))
    add()

    enq = add('SEC("struct_ops/enqueue")')
    add("void BPF_STRUCT_OPS(sg_enqueue, struct task_struct *p, u64 enq_flags) {")
    add("    __u32 pid = BPF_CORE_READ(p, pid); int class_id = sg_class_for_task(p);")
    add("    if (class_id < 0 || class_id >= SG_NUM_CLASSES) {")
    if len(ir.classes) == 1:
        add("        /* Single-class fallback remains the configured class quantum. */")
        add("        scx_bpf_dsq_insert(p, SCX_DSQ_GLOBAL, sg_classes[0].quantum_ns, enq_flags);")
    else:
        add("        /* Unknown comms use the global DSQ without inventing a class assignment. */")
        add("        scx_bpf_dsq_insert(p, SCX_DSQ_GLOBAL, 0, enq_flags);")
    add("        return;")
    add("    }")
    add("    struct sg_task_meta m = { .class_id = class_id, .enqueued_ns = bpf_ktime_get_ns(), .queued = 1 };")
    add("    if (bpf_map_update_elem(&sg_tasks, &pid, &m, BPF_ANY)) {")
    add("        /* Map capacity is runtime-fixed; failed metadata must not stall the task. */")
    add("        scx_bpf_dsq_insert(p, SCX_DSQ_GLOBAL, sg_classes[0].quantum_ns, enq_flags);")
    add("        return;")
    add("    }")
    if len(ir.classes) > 1:
        add("    struct sg_class_state *state = bpf_map_lookup_elem(&sg_class_state, &class_id);")
        add("    if (state && (!state->oldest_ns || m.enqueued_ns < state->oldest_ns)) state->oldest_ns = m.enqueued_ns;")
    add("    struct sg_event *ev = bpf_ringbuf_reserve(&sg_events, sizeof(*ev), 0);")
    add("    if (ev) { ev->ts_ns = m.enqueued_ns; ev->pid = pid; ev->class_id = class_id; ev->kind = 1; bpf_ringbuf_submit(ev, 0); }")
    add("    /* Signature: (task, dsq_id, slice_ns, enqueue_flags). */")
    add("    scx_bpf_dsq_insert(p, sg_dsq(class_id), sg_classes[class_id].quantum_ns, enq_flags);")
    add("}")
    mappings.append(CodeMapping("task enqueue + metadata", "sg_enqueue", enq, len(lines), "Records lifecycle state and inserts into a bounded DSQ."))

    dispatch = add('SEC("struct_ops/dispatch") /* legacy skeleton used SEC("struct_ops/sched_dispatch") */')
    add("void BPF_STRUCT_OPS(sg_dispatch, s32 cpu, struct task_struct *prev) {")
    add("    __u32 class_id;")
    if len(ir.classes) > 1:
        add("    __u64 now_ns = bpf_ktime_get_ns();")
        add("#pragma unroll")
        add("    for (class_id = 0; class_id < SG_NUM_CLASSES; class_id++)")
        add("        if (sg_class_aged(class_id, now_ns) && scx_bpf_dsq_move_to_local(sg_dsq(class_id), 0)) return;")
    add("#pragma unroll")
    add("    for (class_id = 0; class_id < SG_NUM_CLASSES; class_id++)")
    add("        if (scx_bpf_dsq_move_to_local(sg_dsq(class_id), 0)) return;")
    add("    scx_bpf_consume(SCX_DSQ_GLOBAL);")
    add("}")
    mappings.append(CodeMapping("priority tiers", "sg_dispatch", dispatch, len(lines), "Bounded ascending-priority DSQ scan; lower IR priority wins."))

    run = add('SEC("struct_ops/running")')
    add("void BPF_STRUCT_OPS(sg_running, struct task_struct *p) {")
    add("    __u32 pid = BPF_CORE_READ(p, pid); struct sg_task_meta *m = bpf_map_lookup_elem(&sg_tasks, &pid);")
    add("    if (m) m->queued = 0;")
    if len(ir.classes) > 1:
        add("    if (m) { struct sg_class_state *state = bpf_map_lookup_elem(&sg_class_state, &m->class_id); if (state && state->oldest_ns == m->enqueued_ns) state->oldest_ns = 0; }")
    add("    struct sg_event *ev = bpf_ringbuf_reserve(&sg_events, sizeof(*ev), 0);")
    add("    if (ev) { ev->ts_ns = bpf_ktime_get_ns(); ev->pid = pid; ev->class_id = m ? m->class_id : 0; ev->kind = 2; bpf_ringbuf_submit(ev, 0); }")
    add("}")
    add('SEC("struct_ops/stopping")')
    add("void BPF_STRUCT_OPS(sg_stopping, struct task_struct *p, bool runnable) {")
    add("    __u32 pid = BPF_CORE_READ(p, pid); if (!runnable) bpf_map_delete_elem(&sg_tasks, &pid);")
    add("}")
    mappings.append(CodeMapping("running/stopping callbacks", "sg_running + sg_stopping", run, len(lines), "Maintains task lifecycle metadata."))

    init = add('SEC("struct_ops/init")')
    add("s32 BPF_STRUCT_OPS(sg_init) {")
    add("    __u32 i;")
    add("#pragma unroll")
    add("    for (i = 0; i < SG_NUM_CLASSES; i++) if (scx_bpf_create_dsq(sg_dsq(i), -1)) return -1;")
    add("    return 0; }")
    add('SEC("struct_ops/exit")')
    add("void BPF_STRUCT_OPS(sg_exit, struct scx_exit_info *ei) { }")
    add('SEC(".struct_ops")')
    add("struct sched_ext_ops sg_ops = {")
    add(f'    .name = "sg_{ir.name[:12]}", .select_cpu = (void *)sg_select_cpu,')
    add("    .enqueue = (void *)sg_enqueue,")
    add("    .dispatch = (void *)sg_dispatch, .running = (void *)sg_running,")
    add("    .stopping = (void *)sg_stopping, .init = (void *)sg_init, .exit = (void *)sg_exit,")
    add("    .flags = SCX_OPS_ENQ_LAST | SCX_OPS_ENQ_EXITING,")
    add("};")

    status = "UNSUPPORTED" if unsupported else "PASSED"
    return CodegenResult(
        c_code="\n".join(lines) + "\n", policy_name=ir.name, is_complete=False,
        status_label=("UNSUPPORTED" if unsupported else "EMISSION_SUCCEEDED (BUILD_NOT_RUN)"),
        limitations=["Phase 4 source emission is not clang compilation or kernel loading.",
                     "Formal proof remains single-CPU and CPU-bound; blocking, arrivals, and multi-CPU execution are outside scope.",
                     "The runtime task map is fixed at SG_RUNTIME_MAX_TASKS=4096; SG_MODEL_MAX_TASKS is only the formal-model bound.",
                     "Kernel load/runtime tests require explicit operator action in a Linux VM."] + limitations,
        mappings=mappings,
        supported_semantics=["fixed-size class table", "priority DSQs", "quantum slice", "enqueue/dispatch/running/stopping/init/exit callbacks", "ring-buffer event emission"] + (["explicit task comm-to-class mapping", "bounded enqueue-age promotion"] if len(ir.classes) > 1 else []),
        unsupported_semantics=unsupported,
        target_kernel="6.12+", status=status,
    )
