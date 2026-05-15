"""Codex commit-stop fallback project resolution and skip tests."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.codex import CodexProvider
from tests.llm_provider._codex_fallback_helpers import (
    isolate_fallback_markers,
    set_sase_session,
)


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_skips_when_worktree_clean(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean worktree means only the original invocation runs."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    set_sase_session(monkeypatch)
    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (False, [], "", ""),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 1


def test_codex_fallback_uses_active_project_dir_when_parent_project_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback inspects the workflow-assigned project dir when cwd differs."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    set_sase_session(monkeypatch, "260511_120100")
    cwd = tmp_path / "cwd"
    active_project = tmp_path / "active-project"
    cwd.mkdir()
    active_project.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(active_project))

    captured: dict[str, str] = {}
    logs: list[tuple[str, dict[str, object]]] = []

    def fake_build(project_dir: str) -> tuple[bool, list[str], str, str]:
        captured["project_dir"] = project_dir
        return (False, [], "", "")

    monkeypatch.setattr("sase.llm_provider.codex.build_commit_details", fake_build)
    monkeypatch.setattr(
        "sase.llm_provider.codex.jlog",
        lambda event, **kwargs: logs.append((event, kwargs)),
    )

    provider = CodexProvider()
    assert (
        provider._maybe_run_commit_fallback_turn(
            base_args=["codex"],
            original_prompt="prompt",
            accumulated_response="response",
            suppress_output=True,
        )
        is None
    )

    assert captured["project_dir"] == str(active_project)
    assert logs[-1][0] == "codex_fallback_skip"
    assert logs[-1][1]["reason"] == "no_changes"
    assert logs[-1][1]["project_dir"] == str(active_project)


def test_codex_fallback_uses_workspace_env_when_cwd_diverges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workspace env vars cover the phase-agent subprocess case."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    set_sase_session(monkeypatch, "260512_120000")
    cwd = tmp_path / "cwd"
    workspace = tmp_path / "workspace"
    cwd.mkdir()
    workspace.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", str(workspace))

    captured: dict[str, str] = {}

    def fake_build(project_dir: str) -> tuple[bool, list[str], str, str]:
        captured["project_dir"] = project_dir
        return (False, [], "", "")

    monkeypatch.setattr("sase.llm_provider.codex.build_commit_details", fake_build)

    provider = CodexProvider()
    assert (
        provider._maybe_run_commit_fallback_turn(
            base_args=["codex"],
            original_prompt="prompt",
            accumulated_response="response",
            suppress_output=True,
        )
        is None
    )

    assert captured["project_dir"] == str(workspace)


def test_codex_fallback_skip_log_includes_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`no_changes` skip log records project_dir, cwd, and workspace_env."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    set_sase_session(monkeypatch, "260512_120100")
    cwd = tmp_path / "cwd"
    workspace = tmp_path / "workspace"
    cwd.mkdir()
    workspace.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", str(workspace))

    logs: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (False, [], "", ""),
    )
    monkeypatch.setattr(
        "sase.llm_provider.codex.jlog",
        lambda event, **kwargs: logs.append((event, kwargs)),
    )

    provider = CodexProvider()
    provider._maybe_run_commit_fallback_turn(
        base_args=["codex"],
        original_prompt="prompt",
        accumulated_response="response",
        suppress_output=True,
    )

    skip_logs = [entry for entry in logs if entry[0] == "codex_fallback_skip"]
    assert skip_logs, "expected a codex_fallback_skip log entry"
    payload = skip_logs[-1][1]
    assert payload["reason"] == "no_changes"
    assert payload["project_dir"] == str(workspace)
    assert payload["cwd"] == str(cwd)
    assert payload["workspace_env"] == str(workspace)


def test_codex_fallback_parent_project_dir_overrides_active_project_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit CODEX_PROJECT_DIR remains authoritative."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    set_sase_session(monkeypatch, "260511_120200")
    cwd = tmp_path / "cwd"
    active_project = tmp_path / "active-project"
    parent_project = tmp_path / "parent-project"
    cwd.mkdir()
    active_project.mkdir()
    parent_project.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(parent_project))
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(active_project))

    captured: dict[str, str] = {}

    def fake_build(project_dir: str) -> tuple[bool, list[str], str, str]:
        captured["project_dir"] = project_dir
        return (False, [], "", "")

    monkeypatch.setattr("sase.llm_provider.codex.build_commit_details", fake_build)

    provider = CodexProvider()
    assert (
        provider._maybe_run_commit_fallback_turn(
            base_args=["codex"],
            original_prompt="prompt",
            accumulated_response="response",
            suppress_output=True,
        )
        is None
    )

    assert captured["project_dir"] == str(parent_project)


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_no_op_without_sase_agent_timestamp(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-SASE invocations do not trigger the fallback regardless of state."""
    isolate_fallback_markers(monkeypatch, tmp_path)
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (True, ["a.py"], "commit", "details"),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 1
