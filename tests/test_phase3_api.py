"""API contracts for the Phase 3 Studio workbench."""
from fastapi.testclient import TestClient
from concurrent.futures import ThreadPoolExecutor

from schedguard.server import app, api_classify, api_repair, SourceRequest, RepairRequest


POLICY = """policy api_phase3 {
  option max_tasks = 8;
  class web { prio 0; quantum 6 ms; kind interactive; }
  class batch { prio 1; quantum 20 ms; kind batch; }
  guarantee no_starvation(batch, 350 ms);
}"""


def test_phase3_classify_and_repair_endpoints():
    client = TestClient(app)
    classified = client.post("/api/classify", json={"source": POLICY})
    assert classified.status_code == 200
    assert classified.json()["status"] == "VIOLATED"
    assert classified.json()["classifications"][0]["cause"] == "NO_AGING"

    repaired = client.post("/api/repair", json={"source": POLICY, "feedback": "heuristic"})
    assert repaired.status_code == 200
    body = repaired.json()
    assert body["success"] is True
    assert body["iterations"][-1]["status"] == "VERIFIED"


def test_phase3_synthesis_and_metrics_endpoints():
    client = TestClient(app)
    synthesis = client.post("/api/synthesize", json={
        "prompt": "Prioritize interactive over batch; batch must not wait longer than 350 ms.",
        "provider": "stub", "repair": False,
    })
    assert synthesis.status_code == 200
    assert synthesis.json()["proposal"]["extracted_guarantees"]
    assert synthesis.json()["proposal"]["is_live_llm"] is False

    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["phase"] in {"phase1", "phase2", "phase3", None}


def test_concurrent_classify_and_repair_are_serialized_safely():
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(api_classify, SourceRequest(source=POLICY)),
            executor.submit(api_repair, RepairRequest(source=POLICY, feedback="heuristic")),
        ]
        classify_result, repair_result = [future.result() for future in futures]
    assert classify_result["status"] == "VIOLATED"
    assert repair_result["success"] is True


def test_invalid_policy_returns_structured_json_error():
    response = TestClient(app, raise_server_exceptions=False).post("/api/classify", json={"source": "not PolicyLang"})
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert "detail" in response.json()
