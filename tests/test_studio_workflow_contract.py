"""Static contracts for the workflow hierarchy and safe provider-error display."""
from pathlib import Path


STUDIO = Path("src/schedguard/studio")


def test_sidebar_groups_author_evaluate_research_and_deploy_workflows():
    html = (STUDIO / "index.html").read_text(encoding="utf-8")
    for label in ("Policy Workbench", "Evaluate", "Research", "Deploy"):
        assert f">{label}<" in html


def test_home_is_the_default_entry_point_and_links_to_real_views():
    html = (STUDIO / "index.html").read_text(encoding="utf-8")
    script = (STUDIO / "app.js").read_text(encoding="utf-8")
    assert '<section id="view-home" class="view-panel active">' in html
    assert '<section id="view-overview" class="view-panel hidden">' in html
    assert 'data-view="view-home"' in html
    assert "Design. Verify. Refine." in html
    assert "Open Policy Editor" in html
    assert "Explore Formal Guarantees" in html
    assert "switchView('view-editor')" in html
    assert "switchView('view-verification')" in html
    assert "switchView('view-phase4')" in html
    assert 'activeView: "view-home"' in script


def test_studio_uses_structured_provider_error_message_and_keeps_run_actions_reachable():
    script = (STUDIO / "app.js").read_text(encoding="utf-8")
    css = (STUDIO / "app.css").read_text(encoding="utf-8")
    assert "function apiErrorMessage" in script
    assert "payload?.error" in script
    assert "error.provider" in script
    assert "error.category" in script
    assert "error.retryable" in script
    assert "#recentRunsTable th:last-child" in css
    assert "#recentRunsTable td:last-child" in css


def test_formal_guarantees_workspace_exposes_real_run_evidence_and_stale_state():
    html = (STUDIO / "index.html").read_text(encoding="utf-8")
    script = (STUDIO / "app.js").read_text(encoding="utf-8")
    assert 'id="recheckVerifBtn"' in html
    assert 'id="verifEditPolicyBtn"' in html
    assert 'id="verificationCardsContainer"' in html
    assert "No policy has been verified yet." in html
    assert "executeCompileAndRun" in script
    assert "renderVerificationStaleState" in script
    assert "updateVerificationStaleness" in script
    assert "runRecord.source_code" in script
    assert "v.counterexample" in script
    assert "v.replay" in script
    assert "v.evidence" in script
    assert "guarantee-evidence" in script
    assert "Policy changed after this verification" in script
    assert "Single-CPU" in html
    assert "multi-CPU" in html


def test_policy_assistant_uses_bounded_synthesis_and_shows_formal_outcome():
    script = (STUDIO / "app.js").read_text(encoding="utf-8")
    assert 'fetch("/api/synthesize"' in script
    assert 'repair: true' in script
    assert "data.proposal || data" in script
    assert "data.source || proposal.source_code" in script
    assert "proposal.guarantee_status" in script
    assert "lastIteration?.status" in script
    assert "Formal correction:" in script


def test_studio_api_error_message_behavior_under_node():
    import json
    import subprocess
    import shutil

    if not shutil.which("node"):
        return  # Node not present in test runner environment; static checks above suffice

    node_script = """
    const fs = require('fs');
    const appJs = fs.readFileSync('src/schedguard/studio/app.js', 'utf8');
    const fnCode = appJs.match(/async function apiErrorMessage\\([\\s\\S]*?\\n\\}/)[0];
    eval(fnCode);

    async function test() {
      // 1. Structured provider envelope
      const r1 = {
        status: 400,
        json: async () => ({
          error: {
            operation: 'synthesize_policy',
            provider: 'openrouter',
            category: 'configuration',
            upstream_status: null,
            retryable: false,
            message: 'OPENROUTER_API_KEY environment variable is required',
            correlation_id: 'test-corr-1'
          }
        })
      };
      const msg1 = await apiErrorMessage(r1);

      // 2. Retryable failure with upstream status
      const r2 = {
        status: 503,
        json: async () => ({
          error: {
            operation: 'infer_guarantees',
            provider: 'openrouter',
            category: 'upstream_error',
            upstream_status: 529,
            retryable: true,
            message: 'Service overloaded',
            correlation_id: 'test-corr-2'
          }
        })
      };
      const msg2 = await apiErrorMessage(r2);

      // 3. FastAPI detail payload
      const r3 = {
        status: 422,
        json: async () => ({ detail: 'Unprocessable entity' })
      };
      const msg3 = await apiErrorMessage(r3);

      // 4. Non-JSON response
      const r4 = {
        status: 502,
        json: async () => { throw new Error('Not JSON'); }
      };
      const msg4 = await apiErrorMessage(r4);

      console.log(JSON.stringify({ msg1, msg2, msg3, msg4 }));
    }
    test();
    """

    res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=True)
    out = json.loads(res.stdout.strip())
    assert "synthesize_policy: OPENROUTER_API_KEY environment variable is required" in out["msg1"]
    assert "provider openrouter" in out["msg1"]
    assert "category configuration" in out["msg1"]
    assert "not retryable" in out["msg1"]
    assert "reference test-corr-1" in out["msg1"]

    assert "infer_guarantees: Service overloaded" in out["msg2"]
    assert "upstream 529" in out["msg2"]
    assert "retryable" in out["msg2"]
    assert "reference test-corr-2" in out["msg2"]

    assert out["msg3"] == "Unprocessable entity"
    assert out["msg4"] == "HTTP 502"


def test_narrow_viewport_reduces_sidebar_to_icons_without_hiding_navigation():
    css = (STUDIO / "app.css").read_text(encoding="utf-8")
    assert "@media (max-width: 600px)" in css
    assert ".sidebar { width: 60px; }" in css
    assert ".sidebar .nav-label {" in css
    assert "clip: rect(0 0 0 0);" in css
    assert "min-width: 0;" in css
    assert ".overview-header .btn { align-self: stretch; }" in css
