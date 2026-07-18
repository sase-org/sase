"""Shared fixtures for run-agent-runner notification tests."""

import pytest


@pytest.fixture
def base_kwargs(tmp_path):
    """Return minimal notification args for tests to customize."""
    return {
        "cl_name": "test-cl",
        "artifacts_timestamp": "20260425232621",
        "workflow_name": "nightly_docs",
        "success": True,
        "agent_hidden": False,
        "agent_name": None,
        "agent_model": "opus",
        "agent_llm_provider": "claude",
        "error_summary": None,
        "error_report_path": None,
        "saved_path": None,
        "diff_path": None,
        "current_artifacts_dir": str(tmp_path / "agent_artifacts"),
        "markdown_pdf_paths": [],
        "markdown_source_count": None,
        "image_paths": [],
        "video_paths": [],
        "output_path": str(tmp_path / "output.log"),
        "step_output": None,
        "prompt": "#gh:sase #!sase/nightly_docs %auto",
    }
