from schedguard.report import aggregate_verdicts, create_run_record, generate_run_pdf
from schedguard.compiler import compile_file
from schedguard.sim import Workload, simulate
from schedguard.compiler import compile_instrumented
from schedguard.server import _ast_to_dict, _ir_to_dict


def _v(status):
    return {"guarantee": "g", "status": status, "counterexample": None, "replay": ""}


def test_verdict_aggregation_states_and_breakdowns():
    assert aggregate_verdicts([], "COMPLETED")["status"] == "NO_GUARANTEES"
    assert aggregate_verdicts([_v("UNKNOWN")], "NOT_RUN")["status"] == "NOT_RUN"
    assert aggregate_verdicts([_v("VERIFIED"), _v("VERIFIED")], "COMPLETED")["status"] == "VERIFIED"
    assert aggregate_verdicts([_v("VERIFIED"), _v("VIOLATED")], "COMPLETED")["status"] == "VIOLATED"
    mixed = aggregate_verdicts([_v("VERIFIED"), _v("UNKNOWN"), _v("UNKNOWN")], "COMPLETED")
    assert mixed["status"] == "INCONCLUSIVE"
    assert mixed["summary"] == "1 verified, 2 unknown"
    assert aggregate_verdicts([_v("UNKNOWN"), _v("UNKNOWN")], "COMPLETED")["status"] == "INCONCLUSIVE"
    assert aggregate_verdicts([], "ERROR", "z3 unavailable")["status"] == "ERROR"


def test_run_history_and_pdf_use_same_aggregate():
    run = create_run_record(
        source_code="policy p { class web { quantum 5 ms; } }",
        policy_name="verdict_contract",
        compile_data={"ok": True, "stages": [], "ir": {"classes": []}},
        check_data={"verdicts": [_v("VERIFIED"), _v("UNKNOWN"), _v("UNKNOWN")], "analysis_status": "COMPLETED"},
    )
    assert run["check"]["aggregate"]["status"] == "INCONCLUSIVE"
    pdf = generate_run_pdf(run)
    assert pdf.startswith(b"%PDF")
    assert b"INCONCLUSIVE" in pdf
    assert b"1 verified, 2 unknown" in pdf


def test_simulator_reports_trace_truncation_and_all_configured_classes():
    ir = compile_file("examples/aging_fix.sched").ir
    result = simulate(ir, Workload.from_counts({"web": 4, "batch": 4}), horizon_ms=1000,
                      record_trace=True, max_trace_events=2)
    assert set(result.per_class) == {"web", "batch"}
    assert len(result.timeline) <= 2
    assert result.trace_truncated is True
    assert result.trace_limit == 2


def test_simulator_overview_is_full_horizon_and_trace_is_explicitly_bounded():
    ir = compile_file("examples/aging_fix.sched").ir
    result = simulate(ir, Workload.from_counts({"web": 4, "batch": 4}), horizon_ms=1000,
                      record_trace=True, max_trace_events=2)
    assert result.configured_horizon_ms == 1000
    assert result.end_ms <= result.configured_horizon_ms
    assert result.overview_buckets[0]["start_ms"] == 0
    assert result.overview_buckets[-1]["end_ms"] == 1000
    totals = {name: 0 for name in result.per_class}
    for bucket in result.overview_buckets:
        for name, cpu_ms in bucket["cpu_ms"].items():
            totals[name] += cpu_ms
    assert totals == {name: stats.cpu_ms for name, stats in result.per_class.items()}


def test_ast_and_ir_payloads_are_real_distinct_representations():
    source = open("examples/aging_fix.sched", encoding="utf-8").read()
    compiled = compile_instrumented(source)
    ast = _ast_to_dict(compiled.ast)
    ir = _ir_to_dict(compiled.ir)
    assert ast["node_type"] == "PolicyAST"
    assert ast["classes"][0]["node_type"] == "ClassDecl"
    assert ir["classes"][0]["idx"] == 0
    assert ir["classes"][0]["name"] == ast["classes"][0]["name"]
    assert "node_type" not in ir["classes"][0]
    assert ir["dump"] != str(ast)
