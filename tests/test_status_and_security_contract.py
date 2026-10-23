"""Truthful Studio status and local-only API defaults."""

from schedguard.server import api_progress, cors_origins


def test_progress_reports_implemented_research_features_and_unrun_kernel_evidence():
    phases = {str(item["phase"]): item for item in api_progress()["phases"]}
    assert phases["2"]["status"] == "COMPLETED"
    assert phases["3"]["status"] == "COMPLETED"
    assert phases["4"]["status"] == "EXPERIMENTAL_NOT_RUN"
    assert "not run" in phases["4"]["verified_exit_criteria"].lower()


def test_cors_is_opt_in_and_never_uses_wildcard_credentials():
    assert cors_origins("") == []
    assert cors_origins("http://localhost:8766, https://studio.example") == [
        "http://localhost:8766",
        "https://studio.example",
    ]
