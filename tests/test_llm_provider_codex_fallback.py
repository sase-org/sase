"""Tests for CodexProvider commit-stop fallback behavior."""

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.codex import CodexProvider

SIBLING_HOOK = (
    Path(__file__).resolve().parents[1] / "tools" / "sase_sibling_commit_stop_hook"
)


def _isolate_fallback_markers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point fallback/native marker files into a tmp dir for the test."""
    marker_dir = tmp_path / "markers"
    project_dir = tmp_path / "project"
    marker_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("SASE_TMPDIR", str(marker_dir))
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))


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


def test_codex_fallback_uses_workspace_env_when_cwd_diverges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workspace env vars cover the phase-agent subprocess case."""
    _isolate_fallback_markers(monkeypatch, tmp_path)
    _set_sase_session(monkeypatch, "260512_120000")
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
    _isolate_fallback_markers(monkeypatch, tmp_path)
    _set_sase_session(monkeypatch, "260512_120100")
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


def test_codex_fallback_runs_when_sibling_hook_blocks_clean_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex exec fallback also surfaces dirty sibling repos."""
    _isolate_fallback_markers(monkeypatch, tmp_path)
    session_id = _set_sase_session(monkeypatch, "260513_220000")
    project_dir = tmp_path / "sase"
    tools_dir = project_dir / "tools"
    sibling_dir = tmp_path / "sase-telegram"
    tools_dir.mkdir(parents=True)
    sibling_dir.mkdir()
    (tools_dir / "sase_sibling_commit_stop_hook").symlink_to(SIBLING_HOOK)
    subprocess.run(["git", "init", "-q"], cwd=sibling_dir, check=True)
    (sibling_dir / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))
    monkeypatch.setattr(
        "sase.llm_provider.codex.build_commit_details",
        lambda project_dir: (False, [], "", ""),
    )

    emitted: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "sase.llm_provider.codex.jlog",
        lambda event, **kwargs: emitted.append((event, kwargs)),
    )

    prompts: list[str] = []
    provider = CodexProvider()

    def fake_run_subprocess(
        args: list[str], prompt: str, suppress_output: bool
    ) -> tuple[str, str, int]:
        prompts.append(prompt)
        return "sibling-follow-up", "", 0

    monkeypatch.setattr(provider, "_run_subprocess", fake_run_subprocess)

    result = provider._maybe_run_commit_fallback_turn(
        base_args=["codex"],
        original_prompt="prompt",
        accumulated_response="response",
        suppress_output=True,
    )

    assert result == "sibling-follow-up"
    assert len(prompts) == 1
    assert "../sase-telegram" in prompts[0]
    assert "/sase_git_commit" in prompts[0]
    fallback_marker = (
        Path(os.environ["SASE_TMPDIR"])
        / f"sase_codex_commit_fallback_done_{session_id}"
    )
    sibling_marker = (
        Path(os.environ["SASE_TMPDIR"]) / f"sase_sibling_hook_done_{session_id}"
    )
    assert fallback_marker.exists()
    assert sibling_marker.exists()
    assert emitted[-1][0] == "codex_fallback_block_emitted"
    assert emitted[-1][1]["sibling_blocked"] is True


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


def test_codex_fallback_inspects_spawn_workspace_when_parent_env_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end regression: stale parent env must not redirect the fallback.

    Mirrors the sase-39.1 bug: parent's leaked SASE_ACTIVE_PROJECT_DIR pointed
    at a clean repo, so the child's commit-stop fallback skipped with
    no_changes. After the spawn-boundary rewrite, the child's env reflects the
    child's actual workspace; the fallback inspects that workspace and emits a
    commit block when it's dirty.
    """
    from tests._cd_launch_resolution_helpers import patch_cd_git_metadata
    from sase.running_field import ClaimResult

    patch_cd_git_metadata(monkeypatch)

    clean_parent = tmp_path / "parent-clean"
    dirty_workspace = tmp_path / "child-dirty"
    clean_parent.mkdir()
    dirty_workspace.mkdir()
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(clean_parent))
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(clean_parent))

    captured_env: dict[str, str] = {}

    def fake_spawn(
        _prepared: object,
        *,
        env: dict[str, str],
        claim_callback: Callable[[int], bool] | None = None,
    ) -> int:
        captured_env.update(env)
        if claim_callback is not None:
            claim_callback(12345)
        return 12345

    from sase.agent.launcher import spawn_agent_subprocess

    with (
        patch(
            "sase.core.paths.sharded_path",
            return_value=str(tmp_path / "agent.log"),
        ),
        patch(
            "sase.core.agent_launch_facade.spawn_prepared_agent_process",
            side_effect=fake_spawn,
        ),
        patch(
            "sase.running_field.claim_workspace",
            return_value=ClaimResult(success=True),
        ),
        patch(
            "sase.running_field.transfer_workspace_claim",
            return_value=ClaimResult(success=True),
        ),
        patch("sase.axe.chop_agents.record_chop_agent_launch_from_env"),
    ):
        spawn_agent_subprocess(
            cl_name="home",
            project_file=str(tmp_path / "home.sase"),
            workspace_dir=str(dirty_workspace),
            workspace_num=101,
            workflow_name="ace(run)-ts",
            prompt="#git:home do work",
            timestamp="20260512190000",
            project_name="home",
            is_home_mode=False,
            vcs_ref=("git", "home"),
        )

    # Simulate the spawned child by applying the captured env. The child's
    # resolver should consult its own env, not the parent's.
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)
    if "SASE_ACTIVE_PROJECT_DIR" in captured_env:
        monkeypatch.setenv(
            "SASE_ACTIVE_PROJECT_DIR", captured_env["SASE_ACTIVE_PROJECT_DIR"]
        )
    assert "CODEX_PROJECT_DIR" not in captured_env

    _isolate_fallback_markers(monkeypatch, tmp_path)
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    if "SASE_ACTIVE_PROJECT_DIR" in captured_env:
        monkeypatch.setenv(
            "SASE_ACTIVE_PROJECT_DIR", captured_env["SASE_ACTIVE_PROJECT_DIR"]
        )
    _set_sase_session(monkeypatch, "260512_183950")

    inspected: dict[str, str] = {}

    def fake_build(project_dir: str) -> tuple[bool, list[str], str, str]:
        inspected["project_dir"] = project_dir
        return (True, ["src/foo.py"], "commit", "details body")

    monkeypatch.setattr("sase.llm_provider.codex.build_commit_details", fake_build)

    emitted: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "sase.llm_provider.codex.jlog",
        lambda event, **kwargs: emitted.append((event, kwargs)),
    )

    popen_mock = MagicMock(return_value=MagicMock())
    monkeypatch.setattr("sase.llm_provider.codex.subprocess.Popen", popen_mock)
    monkeypatch.setattr(
        "sase.llm_provider.codex.stream_and_parse_codex_json_output",
        lambda *a, **k: ("follow-up", "", 0),
    )

    provider = CodexProvider()
    result = provider._maybe_run_commit_fallback_turn(
        base_args=["codex"],
        original_prompt="prompt",
        accumulated_response="response",
        suppress_output=True,
    )

    assert inspected["project_dir"] == str(dirty_workspace)
    assert result is not None
    assert any(event == "codex_fallback_block_emitted" for event, _ in emitted)
