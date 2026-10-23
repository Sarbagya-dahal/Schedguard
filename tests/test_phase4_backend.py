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
    assert "#define SG_MAX_TASKS" in one.c_code
    assert "BPF_STRUCT_OPS(sg_dispatch" in one.c_code
    assert one.status_label == "EMISSION_SUCCEEDED (BUILD_NOT_RUN)"


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
