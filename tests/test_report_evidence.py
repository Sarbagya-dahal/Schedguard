"""Evidence-state regressions for persisted runs and their PDF reports."""
from schedguard.report import generate_run_pdf, normalize_backend_evidence


def _run(codegen=None):
    return {
        "run_id": "run_test_evidence", "timestamp": "2026-10-24 10:00:00", "policy_name": "p",
        "source_code": "policy p { class a { quantum 1 ms; } }",
        "compile": {"ok": True, "stages": [], "ir": {"classes": []}},
        "check": {"verdicts": [], "analysis_status": "NOT_RUN"}, "analyze": {"facts": {}},
        "simulate": {}, "codegen": codegen or {}, "tuner": {},
    }


def test_legacy_run_defaults_each_backend_stage_to_not_run():
    evidence = normalize_backend_evidence(_run())
    assert set(evidence) == {"emission", "build", "preflight", "load", "telemetry", "predictor", "watchdog", "hot_swap"}
    assert set(evidence.values()) == {"NOT_RUN"}


def test_report_distinguishes_emission_only_from_runtime_evidence():
    emitted_pdf = generate_run_pdf(_run({"status": "PASSED", "status_label": "EMISSION_SUCCEEDED (BUILD_NOT_RUN)"}))
    runtime_pdf = generate_run_pdf(_run({"status": "PASSED", "runtime_evidence": {"load": "PASSED", "telemetry": "PASSED"}}))

    assert b"Emission: PASSED" in emitted_pdf
    assert b"Load: NOT_RUN" in emitted_pdf
    assert b"Load: PASSED" in runtime_pdf
    assert b"Telemetry: PASSED" in runtime_pdf
