"""Commit finalizer project resolution and skip tests."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.controller import FinalizerControllerError, run_finalizers
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.types import InvokeResult


def test_forged_empty_plan_fails_closed_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A forged empty plan is not treated as a successful no-op."""
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260511_120000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.build_commit_details",
        MagicMock(return_value=(False, [], "", "")),
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "finalizer_plan.json").write_text(
        '{"schema_version": 1, "plan": {"entries": []}}\n',
        encoding="utf-8",
    )
    provider = MagicMock()

    with pytest.raises(FinalizerControllerError, match="authority"):
        run_finalizers(
            provider=provider,
            original_prompt="prompt",
            invoke_result=InvokeResult(content="response"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    provider.invoke.assert_not_called()
    result = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "failed"
    assert result["diagnostics"][0]["code"] == "plan_integrity_failed"


def test_finalizer_no_op_without_sase_agent_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-SASE invocations do not trigger finalization regardless of state."""
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    build = MagicMock(return_value=(True, ["a.py"], "commit", "details"))
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.build_commit_details",
        build,
    )
    provider = MagicMock()

    run_finalizers(
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

    assert resolve_finalizer_project_dir() == str(active_project)


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

    assert resolve_finalizer_project_dir() == str(workspace)


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

    assert resolve_finalizer_project_dir() == str(parent_project)
