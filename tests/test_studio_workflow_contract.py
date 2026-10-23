"""Static contracts for the workflow hierarchy and safe provider-error display."""
from pathlib import Path


STUDIO = Path("src/schedguard/studio")


def test_sidebar_groups_author_evaluate_research_and_deploy_workflows():
    html = (STUDIO / "index.html").read_text(encoding="utf-8")
    for label in ("Policy Workbench", "Evaluate", "Research", "Deploy"):
        assert f">{label}<" in html


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


def test_narrow_viewport_reduces_sidebar_to_icons_without_hiding_navigation():
    css = (STUDIO / "app.css").read_text(encoding="utf-8")
    assert "@media (max-width: 600px)" in css
    assert ".sidebar { width: 60px; }" in css
    assert ".sidebar .nav-label {" in css
    assert "clip: rect(0 0 0 0);" in css
    assert "min-width: 0;" in css
    assert ".overview-header .btn { align-self: stretch; }" in css
