import pytest
from fastapi.testclient import TestClient
from schedguard.compiler import compile_source, compile_file
from schedguard.adapt import tune_policy
from schedguard.codegen import emit_ebpf_c
from schedguard.inference.policy_gen import propose_policy
from schedguard.sim import simulate, Workload
from schedguard.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_adapt_tuner_identifies_accepted_and_rejected_aging():
    ir = compile_file("examples/aging_fix.sched").ir
    res = tune_policy(ir, "batch", "aging", 50, 400, 6)
    assert res.target_class == "batch"
    assert res.param == "aging"
    assert len(res.candidates) >= 5
    # Lower aging is accepted under 400ms bound
    assert any(c.status == "ACCEPTED" for c in res.candidates)
    # Higher aging exceeding bound is rejected
    assert any(c.status == "REJECTED" for c in res.candidates)
    assert res.selected_value is not None
    assert "tightest verified wait bound" in res.selection_reason


def test_ebpf_codegen_emits_skeleton_and_mappings():
    ir = compile_file("examples/aging_fix.sched").ir
    cg = emit_ebpf_c(ir)
    assert not cg.is_complete
    assert "sched_ext" in cg.c_code
    assert "struct sched_class_info" in cg.c_code
    assert "SEC(\"struct_ops/dispatch\")" in cg.c_code
    assert len(cg.mappings) >= 2
    assert any("Phase 4" in lim for lim in cg.limitations)


def test_policy_gen_from_natural_language():
    prompt = ("Prioritize interactive web tasks, give batch tasks a longer time quantum, "
              "and prevent batch starvation with a maximum waiting-time requirement of 400 milliseconds.")
    prop = propose_policy(prompt, provider_name="rules")
    assert prop.status == "UNTRUSTED_PROPOSAL"
    assert "web" in prop.extracted_classes
    assert "batch" in prop.extracted_classes
    # Verify generated policy actually compiles through real compiler
    res = compile_source(prop.source_code)
    assert res.ok
    assert len(res.ir.classes) == 2
    assert any(g.kind == "no_starvation" for g in res.ir.guarantees)


def test_simulator_timeline_recording():
    ir = compile_file("examples/aging_fix.sched").ir
    wl = Workload.from_counts({"web": 2, "batch": 2})
    res = simulate(ir, wl, horizon_ms=5000, record_trace=True)
    assert len(res.timeline) > 0
    first_ev = res.timeline[0]
    assert "start_ms" in first_ev and "end_ms" in first_ev
    assert "class_name" in first_ev and "boosted" in first_ev
    assert "queue_sizes" in first_ev


def test_api_endpoints_compile_check_simulate(client):
    src = compile_file("examples/aging_fix.sched")
    with open("examples/aging_fix.sched", encoding="utf-8") as f:
        code = f.read()

    # 1. Compile
    r = client.post("/api/compile", json={"source": code})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert len(data["ir"]["classes"]) == 2

    # 2. Check
    r = client.post("/api/check", json={"source": code})
    assert r.status_code == 200
    cdata = r.json()
    assert cdata["all_verified"] is True
    assert len(cdata["verdicts"]) == 2

    # 3. Simulate
    r = client.post("/api/simulate", json={"source": code, "horizon_ms": 3000})
    assert r.status_code == 200
    sdata = r.json()
    assert sdata["ok"] is True
    assert len(sdata["timeline"]) > 0

    # 4. Adapt
    r = client.post("/api/adapt", json={"source": code, "range_min": 50, "range_max": 300})
    assert r.status_code == 200
    adata = r.json()
    assert adata["selected_value"] is not None

    # 5. Codegen
    r = client.post("/api/codegen", json={"source": code})
    assert r.status_code == 200
    assert "sg_dispatch" in r.json()["c_code"]

    # 6. Source file explorer
    r = client.get("/api/source_files")
    assert r.status_code == 200
    assert len(r.json()["files"]) >= 5

    r = client.get("/api/source_file?path=src/schedguard/verify/safety.py")
    assert r.status_code == 200
    assert "Diagnostic" in r.json()["content"]

    # 7. Progress & Metrics
    r = client.get("/api/progress")
    assert r.status_code == 200
    progress = r.json()
    assert progress["overall_completion_pct"] is None
    assert "not run" in progress["status_statement"].lower()


def test_run_snapshot_and_pdf_generation(client):
    with open("examples/aging_fix.sched", encoding="utf-8") as f:
        code = f.read()

    # 1. Execute run
    r = client.post("/api/run", json={"source": code})
    assert r.status_code == 200
    run_data = r.json()
    run_id = run_data["run_id"]
    assert run_id.startswith("run_")
    assert run_data["compile"]["ok"] is True
    assert len(run_data["compile"]["stages"]) == 4
    assert len(run_data["check"]["verdicts"]) == 2

    # 2. Verify run appears in history
    r_list = client.get("/api/runs")
    assert r_list.status_code == 200
    runs = r_list.json()["runs"]
    assert any(x["run_id"] == run_id for x in runs)

    # 3. Fetch exact historical run snapshot
    r_get = client.get(f"/api/run/{run_id}")
    assert r_get.status_code == 200
    assert r_get.json()["source_code"] == code

    # 4. Download generated PDF report
    r_pdf = client.get(f"/api/run/{run_id}/pdf")
    assert r_pdf.status_code == 200
    assert r_pdf.headers["content-type"] == "application/pdf"
    assert r_pdf.content.startswith(b"%PDF")
    assert len(r_pdf.content) > 1000
