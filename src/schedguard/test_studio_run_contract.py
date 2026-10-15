"""Regression coverage for the Studio run-record API contract."""

from schedguard.server import api_get_run, api_run_pdf, api_runs
from schedguard.report import create_run_record


def test_run_history_historical_and_pdf_share_one_snapshot():
    source = """policy contract_regression {
  option max_tasks = 4;
  class web { prio 0; quantum 5 ms; kind interactive; }
}
"""

    run = create_run_record(
        source_code=source,
        policy_name="contract_regression",
        compile_data={
            "ok": True,
            "total_duration_ms": 1.0,
            "stages": [{"name": "IR Lowering", "status": "COMPLETED", "duration_ms": 1.0}],
            "diagnostics": [],
            "ir": {"guarantees": []},
        },
        check_data={"verdicts": [], "all_verified": False, "has_violation": False, "has_unknown": False},
        analyze_data={"facts": {}},
        sim_data={"decisions": 0},
        codegen_data={"c_code": "// regression"},
    )
    run_id = run["run_id"]

    # The full run response is the persisted report schema consumed by Studio.
    assert run["source_code"] == source
    assert run["compile"]["ok"] is True
    assert run["compile"]["stages"]

    history_entry = next(item for item in api_runs()["runs"] if item["run_id"] == run_id)
    assert history_entry["run_id"] == run_id
    assert history_entry["compile_ok"] == run["compile"]["ok"]
    assert history_entry["guarantees_count"] == len(run["check"]["verdicts"])

    historical = api_get_run(run_id)
    assert historical["run_id"] == run_id
    assert historical["source_code"] == run["source_code"]
    assert historical["compile"] == run["compile"]
    assert historical["check"] == run["check"]
    assert historical["simulate"] == run["simulate"]
    assert historical["codegen"] == run["codegen"]

    pdf_response = api_run_pdf(run_id)
    assert pdf_response.media_type == "application/pdf"
    assert pdf_response.body.startswith(b"%PDF")
    assert run_id in pdf_response.headers["content-disposition"]

