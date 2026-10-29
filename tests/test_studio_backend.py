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
    ir = compile_source("""policy one {
      class web { prio 0; quantum 7 ms; kind interactive; }
    }""").ir
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
    assert r.status_code == 400
    assert "multi-class" in r.json()["detail"]

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


def test_codegen_api_enforces_backend_semantics_for_supported_and_unsupported_policies(client):
    single = """policy one {
      class web { prio 0; quantum 7 ms; kind interactive; }
    }"""
    two_class = open("examples/balanced.sched", encoding="utf-8").read()
    aging = open("examples/aging_fix.sched", encoding="utf-8").read()

    response = client.post("/api/codegen", json={"source": single})
    assert response.status_code == 200
    assert response.json()["c_code"]
    assert "SG_NUM_CLASSES 1" in response.json()["c_code"]

    response = client.post("/api/codegen", json={"source": two_class})
    assert response.status_code == 400
    two_data = response.json()
    assert two_data["status"] == "UNSUPPORTED"
    assert two_data["status_label"] == "UNSUPPORTED"
    assert two_data["c_code"] == ""
    assert "multi-class" in two_data["detail"]
    assert "global-FIFO fallback" in two_data["unsupported_semantics"][0]

    response = client.post("/api/codegen", json={"source": aging})
    assert response.status_code == 400
    aging_data = response.json()
    assert aging_data["status"] == "UNSUPPORTED"
    assert aging_data["c_code"] == ""
    assert "aging" in aging_data["detail"]
    assert "enqueue-age promotion" in aging_data["unsupported_semantics"][0]

    three_tier = open("examples/three_tier.sched", encoding="utf-8").read()
    response = client.post("/api/codegen", json={"source": three_tier})
    assert response.status_code == 400
    tier_data = response.json()
    assert tier_data["status"] == "UNSUPPORTED"
    assert tier_data["status_label"] == "UNSUPPORTED"
    assert tier_data["is_complete"] is False
    assert tier_data["c_code"] == ""
    assert tier_data["unsupported_semantics"]

    multiclass = open("examples/sched_ext_multiclass_aging.sched", encoding="utf-8").read()
    response = client.post("/api/codegen", json={"source": multiclass})
    assert response.status_code == 200
    multi_data = response.json()
    assert multi_data["status"] == "PASSED"
    assert multi_data["c_code"]
    assert "SG_NUM_CLASSES 2" in multi_data["c_code"]
    assert "sg_class_aged" in multi_data["c_code"]

    target = """policy web_batch_sched {
      option max_tasks = 8;
      class web { prio 0; quantum 5 ms; kind interactive; }
      class batch { prio 1; quantum 20 ms; aging 200 ms; kind batch; }
      guarantee no_starvation(batch, 400 ms);
    }"""
    response = client.post("/api/codegen", json={"source": target})
    assert response.status_code == 200
    target_data = response.json()
    assert target_data["status"] == "PASSED"
    assert target_data["c_code"]
    assert "implicit kind mapping" in target_data["c_code"]
    assert "sg_classes[class_id].quantum_ns" in target_data["c_code"]
    assert "sg_class_aged" in target_data["c_code"]
    assert "PolicyLang guarantees are not established" in target_data["limitations"]


def test_sched_ext_ui_clears_stale_source_when_emission_is_rejected():
    ui = open("src/schedguard/studio/app.js", encoding="utf-8").read()
    start = ui.index("async function emitPhase4Source()")
    end = ui.index("// ============================================================================", start)
    handler = ui[start:end]
    assert 'output.textContent = "";' in handler
    assert 'output.textContent = "No sched_ext C source emitted.";' in handler
    assert 'data.status === "UNSUPPORTED"' in handler
    assert 'data.status_label === "UNSUPPORTED"' in handler
    assert "unsupported_semantics" in handler
    assert "copyBtn.disabled = true" in handler
    assert "downloadBtn.disabled = true" in handler


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
    assert run_data["codegen"]["status"] == "UNSUPPORTED"
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

    # 5. Non-existent run ID returns 404
    r_bad = client.get("/api/run/run_nonexistent_xyz/pdf")
    assert r_bad.status_code == 404


def test_pdf_generation_for_failed_compile(client):
    bad_code = "policy broken_syntax { invalid"
    r = client.post("/api/run", json={"source": bad_code})
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    r_pdf = client.get(f"/api/run/{run_id}/pdf")
    assert r_pdf.status_code == 200
    assert r_pdf.headers["content-type"] == "application/pdf"
    assert r_pdf.content.startswith(b"%PDF")
    assert len(r_pdf.content) > 500


def test_simulation_workload_variations_and_trace_truncation(client):
    with open("examples/aging_fix.sched", encoding="utf-8") as f:
        code = f.read()

    # Default workload simulation
    r_def = client.post("/api/simulate", json={"source": code, "horizon_ms": 2000})
    assert r_def.status_code == 200
    data_def = r_def.json()
    assert data_def["ok"] is True
    assert len(data_def["timeline"]) > 0

    # Custom heavy web workload
    heavy_web = {
        "tasks": [
            {"class": "web", "count": 8, "work_ms": 20, "arrival_ms": 0},
            {"class": "batch", "count": 1, "work_ms": 50, "arrival_ms": 0},
        ]
    }
    r_heavy = client.post("/api/simulate", json={"source": code, "horizon_ms": 2000, "workload": heavy_web})
    assert r_heavy.status_code == 200
    data_heavy = r_heavy.json()
    assert data_heavy["ok"] is True
    # CPU share and dispatches should reflect workload change
    assert data_heavy["per_class"]["web"]["dispatches"] > 0
    assert data_heavy["per_class"]["batch"]["dispatches"] > 0

    # Truncated trace request
    r_trunc = client.post("/api/simulate", json={"source": code, "horizon_ms": 2000, "max_trace_events": 5})
    assert r_trunc.status_code == 200
    data_trunc = r_trunc.json()
    assert data_trunc["trace_truncated"] is True
    assert len(data_trunc["timeline"]) == 5
    assert data_trunc["trace_window"]["events"] == 5
    assert data_trunc["trace_window"]["complete"] is False
    # Ensure real event structure
    first_ev = data_trunc["timeline"][0]
    assert "start_ms" in first_ev and "end_ms" in first_ev
    assert "class_name" in first_ev


def test_verification_verdicts_payload_and_counterexample(client):
    # 1. aging_fix should have kind, class_name, value populated in verdicts
    with open("examples/aging_fix.sched", encoding="utf-8") as f:
        aging_code = f.read()
    r = client.post("/api/run", json={"source": aging_code})
    assert r.status_code == 200
    data = r.json()
    assert data["compile"]["ok"] is True
    check = data["check"]
    assert check["all_verified"] is True
    verdicts = check["verdicts"]
    assert len(verdicts) >= 1
    v0 = verdicts[0]
    assert "kind" in v0 and v0["kind"] is not None
    assert "class_name" in v0 and v0["class_name"] is not None
    assert "value" in v0 and v0["value"] is not None
    assert v0["status"] == "VERIFIED"

    # 2. strict_starves should report VIOLATED and produce real counterexample
    with open("examples/strict_starves.sched", encoding="utf-8") as f:
        starve_code = f.read()
    r_starve = client.post("/api/run", json={"source": starve_code})
    assert r_starve.status_code == 200
    starve_data = r_starve.json()
    assert starve_data["compile"]["ok"] is True
    starve_check = starve_data["check"]
    assert starve_check["all_verified"] is False
    assert starve_check["aggregate"]["status"] == "VIOLATED"
    starve_verdicts = starve_check["verdicts"]
    violated_v = [v for v in starve_verdicts if v["status"] == "VIOLATED"]
    assert len(violated_v) >= 1
    assert violated_v[0]["counterexample"] is not None
    assert "tasks" in violated_v[0]["counterexample"] or isinstance(violated_v[0]["counterexample"], dict)


def test_studio_html_has_no_raw_latex_and_valid_math_entities():
    with open("src/schedguard/studio/index.html", encoding="utf-8") as f:
        html = f.read()
    # No raw LaTeX dollar math delimiters
    assert "$0 <=" not in html
    assert "$0 \\le" not in html
    assert "W_i = A_i" not in html
    assert "\\sum" not in html
    # Proper accessible mathematical HTML entities
    assert "&le;" in html
    assert "&sum;" in html
    assert "&minus;" in html
    assert "<sub>" in html
