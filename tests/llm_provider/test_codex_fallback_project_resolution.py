"""Commit finalizer project resolution and skip tests."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider.commit_finalizer import (
    _resolve_finalizer_project_dir,
    run_commit_finalizer,
)
from sase.llm_provider.types import InvokeResult


def test_finalizer_skips_when_worktree_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean worktree means no follow-up provider turn."""
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260511_120000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        MagicMock(return_value=(False, [], "", "")),
    )
    provider = MagicMock()

    result = run_commit_finalizer(
        provider=provider,
        original_prompt="prompt",
        invoke_result=InvokeResult(content="response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path / "artifacts"),
    )

    provider.invoke.assert_not_called()
    assert result.content == "response"


def test_finalizer_no_op_without_sase_agent_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-SASE invocations do not trigger finalization regardless of state."""
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    build = MagicMock(return_value=(True, ["a.py"], "commit", "details"))
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        build,
    )
    provider = MagicMock()

    run_commit_finalizer(
        provider=provider,
        original_prompt="prompt",
        invoke_result=InvokeResult(content="response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path / "artifacts"),
    )

    build.assert_not_called()
    provider.invoke.assert_not_called()


def test_finalizer_disabled_by_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SASE_DISABLE_COMMIT_STOP_HOOK remains a compatibility disable switch."""
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260511_160000")
    monkeypatch.setenv("SASE_DISABLE_COMMIT_STOP_HOOK", "1")
    build = MagicMock(return_value=(True, ["a.py"], "commit", "details"))
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        build,
    )
    provider = MagicMock()

    run_commit_finalizer(
        provider=provider,
        original_prompt="prompt",
        invoke_result=InvokeResult(content="response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(tmp_path / "artifacts"),
    )

    build.assert_not_called()
    provider.invoke.assert_not_called()
    assert '"reason": "disabled_by_env"' in (
        tmp_path / "artifacts" / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")


def test_finalizer_uses_active_project_dir_when_parent_project_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The finalizer inspects the workflow-assigned project dir when cwd differs."""
    cwd = tmp_path / "cwd"
    active_project = tmp_path / "active-project"
    cwd.mkdir()
    active_project.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(active_project))

    assert _resolve_finalizer_project_dir() == str(active_project)


def test_finalizer_uses_workspace_env_when_cwd_diverges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workspace env vars cover phase-agent subprocesses for all providers."""
    cwd = tmp_path / "cwd"
    workspace = tmp_path / "workspace"
    cwd.mkdir()
    workspace.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("CODEX_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", str(workspace))

    assert _resolve_finalizer_project_dir() == str(workspace)


def test_finalizer_parent_project_dir_overrides_active_project_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit provider project dir remains authoritative."""
    active_project = tmp_path / "active-project"
    parent_project = tmp_path / "parent-project"
    active_project.mkdir()
    parent_project.mkdir()
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(parent_project))
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(active_project))

    assert _resolve_finalizer_project_dir() == str(parent_project)
