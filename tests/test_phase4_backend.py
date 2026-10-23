from pathlib import Path

from schedguard.codegen import emit_ebpf_c
from schedguard.codegen.build import check_toolchain
from schedguard.predictor import ErrorPredictor, PairedObservation
from schedguard.runtime import LifecycleState, watchdog_check
from schedguard.telemetry import TelemetryTrace, load_trace
from schedguard.compiler import compile_file


def test_phase4_emitter_is_deterministic_and_bounded():
    ir = compile_file("examples/aging_fix.sched").ir
    one = emit_ebpf_c(ir)
    assert one.c_code == emit_ebpf_c(ir).c_code
    assert "#define SG_MODEL_MAX_TASKS 8" in one.c_code
    assert "#define SG_RUNTIME_MAX_TASKS 4096" in one.c_code
    assert "BPF_STRUCT_OPS(sg_dispatch" in one.c_code
    assert one.status == "UNSUPPORTED"
    assert any("exact aging promotion is not implemented" in item for item in one.unsupported_semantics)


def test_phase4_emitter_uses_real_dsq_argument_order_and_failure_paths():
    ir = compile_file("examples/balanced.sched").ir
    result = emit_ebpf_c(ir)
    assert "scx_bpf_dsq_insert(p, sg_dsq(class_id), sg_classes[class_id].quantum_ns, enq_flags)" in result.c_code
    assert "SCX_DSQ_INSERT_AT_TAIL" not in result.c_code
    assert "bpf_map_update_elem(&sg_tasks" in result.c_code
    assert "bpf_ringbuf_reserve(&sg_events" in result.c_code
    assert "scx_bpf_dsq_move_to_local(sg_dsq(class_id), 0)" in result.c_code


def test_phase4_emitter_does_not_invent_multiclass_task_mapping():
    ir = compile_file("examples/aging_fix.sched").ir
    result = emit_ebpf_c(ir)
    assert result.status == "UNSUPPORTED"
    assert any("runtime task-to-class mapping is undefined" in item for item in result.unsupported_semantics)
    assert "return SG_NUM_CLASSES == 1 ? 0 : -1;" in result.c_code


def test_phase4_preflight_is_inspection_only():
    report = check_toolchain()
    assert report.status in {"READY", "NOT_READY"}
    assert isinstance(report.diagnostics, list)


def test_predictor_grouped_training_and_conservative_prediction():
    rows = [PairedObservation(f"p{i}", f"w{i}", {"class_count": 2, "max_tasks": i + 1},
                              {"p99_dispatch_latency": 10.0}, {"p99_dispatch_latency": 12.0 + i / 10}) for i in range(8)]
    train, holdout = ErrorPredictor.grouped_split(rows)
    model = ErrorPredictor(min_samples=4)
    assert model.fit(train)["status"] == "TRAINED"
    pred = model.predict({"class_count": 2, "max_tasks": 4})
    assert pred.predicted_abs_error >= 0 and pred.uncertainty >= 0 and holdout


def test_watchdog_requires_telemetry_and_health():
    state = watchdog_check(LifecycleState(stage="LOADED_AWAITING_HEALTH"), False, False)
    assert state.stage == "FALLBACK_REQUIRED"
    assert state.fallback == "kernel_default_scheduler"


def test_real_trace_schema_roundtrip(tmp_path: Path):
    path = tmp_path / "real.json"
    TelemetryTrace("r1", "p1", "w1", 4, "6.12.1", status="COMPLETE").write(path)
    assert load_trace(path).to_dict()["schema"] == "schedguard.real_trace.v1"
