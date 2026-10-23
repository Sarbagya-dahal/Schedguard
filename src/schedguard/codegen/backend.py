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

    def to_dict(self) -> dict[str, Any]:
        return {"c_code": self.c_code, "policy_name": self.policy_name,
                "is_complete": self.is_complete, "status_label": self.status_label,
                "limitations": self.limitations,
                "supported_semantics": self.supported_semantics,
                "unsupported_semantics": self.unsupported_semantics,
                "target_kernel": self.target_kernel,
                "mappings": [m.__dict__.copy() for m in self.mappings]}


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
    if errors:
        raise ValueError("unsupported sched_ext backend policy: " + "; ".join(errors))


def emit_ebpf_c(ir: IRPolicy) -> CodegenResult:
    """Emit deterministic sched_ext C for the validated, fixed-size IR."""
    _validate(ir)
    lines: list[str] = []
    mappings: list[CodeMapping] = []

    def add(s: str = "") -> int:
        lines.append(s)
        return len(lines)

    add("/* SchedGuard generated sched_ext program; do not edit by hand. */")
    add(f"/* Policy: {ir.name}; target kernel: Linux 6.12+ */")
    add("/* Source emission is not proof of clang compilation or kernel loading. */")
    for header in ("vmlinux.h", "bpf/bpf_helpers.h", "bpf/bpf_core_read.h", "scx/common.bpf.h"):
        add(f'#include "{header}"' if header == "vmlinux.h" else f"#include <{header}>")
    add('char LICENSE[] SEC("license") = "GPL";')
    add()

    start = add("/* Fixed-size limits copied from the validated IR. */")
    add(f"#define SG_NUM_CLASSES {len(ir.classes)}")
    add(f"#define SG_MAX_TASKS {ir.max_tasks}")
    add("#define SG_DSQ_BASE 1000ULL")
    add("#define SG_NS_PER_MS 1000000ULL")
    end = add()
    mappings.append(CodeMapping(f"option max_tasks = {ir.max_tasks}", "SG_MAX_TASKS", start, end, "Bounded map and loop limits."))

    add("/* struct sched_class_info is the source-level compatibility name for the IR class table. */")
    add("struct sched_class_info { __u32 prio; __u64 quantum_ns; __u64 aging_ns; };")
    add("struct sg_class_cfg { __u32 prio; __u64 quantum_ns; __u64 aging_ns; };")
    add("struct sg_task_meta { __u32 class_id; __u64 enqueued_ns; __u8 queued; };")
    add("static const struct sg_class_cfg sg_classes[SG_NUM_CLASSES] = {")
    for c in ir.classes:
        row = add(f"    [{c.idx}] = {{ .prio = {c.prio}, .quantum_ns = {c.quantum_ms}ULL * SG_NS_PER_MS, .aging_ns = {c.aging_ms}ULL * SG_NS_PER_MS }},")
        mappings.append(CodeMapping(f"class {c.name}", f"sg_classes[{c.idx}]", row, row, "Static IR class configuration."))
    add("};")
    add("struct { __uint(type, BPF_MAP_TYPE_HASH); __uint(max_entries, SG_MAX_TASKS); __type(key, __u32); __type(value, struct sg_task_meta); } sg_tasks SEC(\".maps\");")
    add("struct { __uint(type, BPF_MAP_TYPE_RINGBUF); __uint(max_entries, 1 << 20); } sg_events SEC(\".maps\");")
    add("static __always_inline __u64 sg_dsq(__u32 id) { return SG_DSQ_BASE + id; }")
    add()

    enq = add('SEC("struct_ops/enqueue")')
    add("void BPF_STRUCT_OPS(sg_enqueue, struct task_struct *p, u64 enq_flags) {")
    add("    __u32 pid = BPF_CORE_READ(p, pid); __u32 class_id = 0;")
    add("    struct sg_task_meta m = { .class_id = class_id, .enqueued_ns = bpf_ktime_get_ns(), .queued = 1 };")
    add("    bpf_map_update_elem(&sg_tasks, &pid, &m, BPF_ANY);")
    add("    scx_bpf_dsq_insert(p, sg_dsq(class_id), SCX_DSQ_INSERT_AT_TAIL, sg_classes[class_id].quantum_ns);")
    add("}")
    mappings.append(CodeMapping("task enqueue + metadata", "sg_enqueue", enq, len(lines), "Records lifecycle state and inserts into a bounded DSQ."))

    dispatch = add('SEC("struct_ops/dispatch") /* legacy skeleton used SEC("struct_ops/sched_dispatch") */')
    add("void BPF_STRUCT_OPS(sg_dispatch, s32 cpu, struct task_struct *prev) {")
    add("    __u32 class_id;")
    add("#pragma unroll")
    add("    for (class_id = 0; class_id < SG_NUM_CLASSES; class_id++)")
    add("        if (scx_bpf_dsq_move_to_local(sg_dsq(class_id))) return;")
    add("    scx_bpf_consume(SCX_DSQ_GLOBAL);")
    add("}")
    mappings.append(CodeMapping("priority tiers", "sg_dispatch", dispatch, len(lines), "Bounded ascending-priority DSQ scan; lower IR priority wins."))

    run = add('SEC("struct_ops/running")')
    add("void BPF_STRUCT_OPS(sg_running, struct task_struct *p) {")
    add("    __u32 pid = BPF_CORE_READ(p, pid); struct sg_task_meta *m = bpf_map_lookup_elem(&sg_tasks, &pid);")
    add("    if (m) m->queued = 0;")
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
    add(f'    .name = "sg_{ir.name[:12]}", .enqueue = (void *)sg_enqueue,')
    add("    .dispatch = (void *)sg_dispatch, .running = (void *)sg_running,")
    add("    .stopping = (void *)sg_stopping, .init = (void *)sg_init, .exit = (void *)sg_exit,")
    add("    .flags = SCX_OPS_ENQ_LAST,")
    add("};")

    return CodegenResult(
        "\n".join(lines) + "\n", ir.name, False, "EMISSION_SUCCEEDED (BUILD_NOT_RUN)",
        ["Phase 4 emission succeeded; clang/BPF compilation is a separate explicit stage.", "Formal proof remains single-CPU and CPU-bound; blocking, arrivals, and multi-CPU execution are outside scope.", "Class metadata defaults to class 0 until the loader installs a task mapping.", "Kernel load/runtime tests require explicit operator action in a Linux VM."],
        mappings, ["fixed-size class table", "priority DSQs", "quantum", "enqueue/dispatch/running/stopping/init/exit callbacks", "ring-buffer map"], [], "6.12+",
    )
