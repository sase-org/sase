"""Tests for CodexProvider commit-stop fallback behavior."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.codex import CodexProvider


def _isolate_fallback_markers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point fallback/native marker files into a tmp dir for the test."""
    marker_dir = tmp_path / "markers"
    marker_dir.mkdir()
    monkeypatch.setenv("SASE_TMPDIR", str(marker_dir))


def _set_sase_session(
    monkeypatch: pytest.MonkeyPatch, ts: str = "260511_120000"
) -> str:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", ts)
    return ts


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
    _isolate_fallback_markers(monkeypatch, tmp_path)
    _set_sase_session(monkeypatch)
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
    _isolate_fallback_markers(monkeypatch, tmp_path)
    _set_sase_session(monkeypatch, "260511_120100")
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


def test_codex_fallback_parent_project_dir_overrides_active_project_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit CODEX_PROJECT_DIR remains authoritative."""
    _isolate_fallback_markers(monkeypatch, tmp_path)
    _set_sase_session(monkeypatch, "260511_120200")
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
def test_codex_fallback_runs_when_dirty_and_no_native_marker(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dirty worktree without native marker triggers one follow-up turn."""
    _isolate_fallback_markers(monkeypatch, tmp_path)
    session_id = _set_sase_session(monkeypatch, "260511_130000")
    details = (
        "Uncommitted changes detected:\n"
        "src/foo.py\n\n"
        "A post-completion hook has detected uncommitted changes. "
        "commit using /sase_git_commit"
    )
    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (True, ["src/foo.py"], "commit", details),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("second-turn-response", "", 0)

    provider = CodexProvider()
    result = provider.invoke("primary-prompt", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 2
    second_call_stdin = mock_popen.return_value.stdin.write.call_args_list[-1].args[0]
    assert "src/foo.py" in second_call_stdin
    assert "/sase_git_commit" in second_call_stdin
    assert "--- Work So Far ---" in second_call_stdin
    assert "--- Commit Stop Hook ---" in second_call_stdin

    native_marker = (
        Path(os.environ["SASE_TMPDIR"]) / f"sase_commit_hook_done_{session_id}"
    )
    fallback_marker = (
        Path(os.environ["SASE_TMPDIR"])
        / f"sase_codex_commit_fallback_done_{session_id}"
    )
    assert native_marker.exists()
    assert fallback_marker.exists()
    assert "second-turn-response" in result.content


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_runs_even_when_native_marker_present(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final worktree state dictates fallback; native marker is informational."""
    _isolate_fallback_markers(monkeypatch, tmp_path)
    session_id = _set_sase_session(monkeypatch, "260511_140000")
    native_marker = (
        Path(os.environ["SASE_TMPDIR"]) / f"sase_commit_hook_done_{session_id}"
    )
    native_marker.touch()

    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (True, ["a.py"], "commit", "details body"),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 2


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_skipped_when_fallback_marker_already_present(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One-shot: don't fire again once the fallback marker exists."""
    _isolate_fallback_markers(monkeypatch, tmp_path)
    session_id = _set_sase_session(monkeypatch, "260511_150000")
    fallback_marker = (
        Path(os.environ["SASE_TMPDIR"])
        / f"sase_codex_commit_fallback_done_{session_id}"
    )
    fallback_marker.touch()

    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (True, ["a.py"], "commit", "details"),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 1


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_disabled_by_env(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SASE_DISABLE_COMMIT_STOP_HOOK=1 keeps the provider to a single invocation."""
    _isolate_fallback_markers(monkeypatch, tmp_path)
    _set_sase_session(monkeypatch, "260511_160000")
    monkeypatch.setenv("SASE_DISABLE_COMMIT_STOP_HOOK", "1")
    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (True, ["a.py"], "commit", "details"),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 1


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_includes_bead_close_when_bead_id_set(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bead-close instruction propagates from the shared helper to the prompt."""
    _isolate_fallback_markers(monkeypatch, tmp_path)
    _set_sase_session(monkeypatch, "260511_170000")
    monkeypatch.setenv("SASE_BEAD_ID", "sase-31.2")

    captured: dict[str, str] = {}

    def fake_build(project_dir: str) -> tuple[bool, list[str], str, str]:
        from sase.scripts.sase_commit_stop_hook import (
            _build_commit_instruction_message,
        )

        instr = _build_commit_instruction_message(
            "/sase_git_commit", "create_commit", "sase-31.2"
        )
        details = "Uncommitted changes detected:\nsrc/foo.py\n\n" + instr
        captured["details"] = details
        return (True, ["src/foo.py"], instr, details)

    monkeypatch.setattr("sase.llm_provider.codex.build_commit_details", fake_build)

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    second_call_stdin = mock_popen.return_value.stdin.write.call_args_list[-1].args[0]
    assert "sase bead close sase-31.2" in second_call_stdin


@patch("sase.llm_provider.codex.stream_and_parse_codex_json_output")
@patch("sase.llm_provider.codex.subprocess.Popen")
@patch("sase.llm_provider.codex.gemini_timer")
def test_codex_fallback_is_one_shot_when_second_turn_leaves_dirty(
    mock_timer: MagicMock,
    mock_popen: MagicMock,
    mock_stream: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider returns after exactly two invocations even if still dirty."""
    _isolate_fallback_markers(monkeypatch, tmp_path)
    _set_sase_session(monkeypatch, "260511_180000")
    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (True, ["a.py"], "commit", "still dirty"),
    )

    mock_popen.return_value = MagicMock()
    mock_stream.return_value = ("response", "", 0)

    provider = CodexProvider()
    provider.invoke("test", model_tier="large", suppress_output=True)

    assert mock_popen.call_count == 2


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
    _isolate_fallback_markers(monkeypatch, tmp_path)
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
