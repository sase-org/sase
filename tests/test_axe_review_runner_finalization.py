"""Regression tests for scheduler-launched review agent finalization."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from sase.axe import crs_runner, fix_hook_runner
from sase.env_contracts import WORKSPACE_PIN_ENV_VARS
from sase.llm_provider import AIMessage
from sase.llm_provider import commit_finalizer
from sase.llm_provider.commit_finalizer_types import (
    CommitFinalizerConfig,
    DirtyState,
)
from sase.llm_provider.types import InvokeResult
from sase.main.query_handler import EmbeddedWorkflowResult
from sase.workflows import crs as crs_workflow_module


def _clear_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        *WORKSPACE_PIN_ENV_VARS,
        "SASE_AGENT_TIMESTAMP",
        "SASE_ARTIFACTS_DIR",
        "SASE_COMMIT_METHOD",
        "SASE_AGENT_CL_NAME",
        "SASE_AGENT_PROJECT_FILE",
        "SASE_DISABLE_COMMIT_STOP_HOOK",
    ):
        monkeypatch.delenv(key, raising=False)


def _patch_runner_plumbing(
    monkeypatch: pytest.MonkeyPatch,
    runner: ModuleType,
) -> MagicMock:
    monkeypatch.setattr(runner, "init_telemetry", MagicMock())
    monkeypatch.setattr(runner, "register_push_on_exit", MagicMock())
    monkeypatch.setattr(
        runner, "detect_write_and_persist_review_agent_meta", MagicMock()
    )
    monkeypatch.setattr(runner, "find_chat_by_timestamp", MagicMock(return_value=None))
    monkeypatch.setattr(
        runner,
        "read_agent_meta",
        MagicMock(
            return_value={
                "model": "test-model",
                "llm_provider": "test-provider",
            }
        ),
    )
    monkeypatch.setattr(runner, "finalize_axe_runner", MagicMock())
    monkeypatch.setattr(runner, "WORKFLOW_EXECUTIONS", MagicMock())
    monkeypatch.setattr(runner, "WORKFLOW_DURATION", MagicMock())
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation",
        MagicMock(),
    )
    notify = MagicMock()
    monkeypatch.setattr(
        "sase.notifications.senders.notify_workflow_complete",
        notify,
    )
    return notify


def _install_clean_finalizer(
    monkeypatch: pytest.MonkeyPatch,
    observed_project_dirs: list[str],
) -> None:
    monkeypatch.setattr(
        commit_finalizer,
        "_load_finalizer_config",
        lambda: CommitFinalizerConfig(),
    )
    monkeypatch.setattr(
        commit_finalizer,
        "_auto_commit_separate_sdd_store_if_possible",
        lambda _project_dir, _artifact_root: False,
    )

    def collect_dirty_state(
        project_dir: str,
        *,
        artifact_root: Path | None = None,
    ) -> DirtyState:
        del artifact_root
        observed_project_dirs.append(project_dir)
        return DirtyState(project_dir=project_dir, repos=(), details="")

    monkeypatch.setattr(
        commit_finalizer,
        "_collect_dirty_state",
        collect_dirty_state,
    )


def _invoke_clean_finalizer(artifacts_dir: str) -> AIMessage:
    result = commit_finalizer.run_commit_finalizer(
        provider=MagicMock(),
        original_prompt="prompt",
        invoke_result=InvokeResult(content="agent response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=artifacts_dir,
    )
    return AIMessage(content=result.content)


def _assert_agent_env(
    *,
    artifacts_dir: Path,
    project_file: Path,
    cl_name: str,
) -> None:
    assert os.environ["SASE_ARTIFACTS_DIR"] == str(artifacts_dir)
    assert os.environ["SASE_AGENT_TIMESTAMP"] == artifacts_dir.name
    assert os.environ["SASE_COMMIT_METHOD"] == "create_proposal"
    assert os.environ["SASE_AGENT_CL_NAME"] == cl_name
    assert os.environ["SASE_AGENT_PROJECT_FILE"] == str(project_file)


def test_fix_hook_runner_publishes_env_and_reports_no_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_agent_env(monkeypatch)
    artifacts_dir = tmp_path / "artifacts" / "20260715120000"
    artifacts_dir.mkdir(parents=True)
    home_dir = tmp_path / "home"
    workspace_dir = tmp_path / "claimed-workspace"
    home_dir.mkdir()
    workspace_dir.mkdir()
    monkeypatch.chdir(home_dir)

    project_file = tmp_path / "sase.sase"
    observed_project_dirs: list[str] = []
    _install_clean_finalizer(monkeypatch, observed_project_dirs)
    notify = _patch_runner_plumbing(monkeypatch, fix_hook_runner)

    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda _project_file: "git",
    )
    monkeypatch.setattr(
        "sase.xprompt.tags.get_by_tag",
        lambda _tag: None,
    )
    monkeypatch.setattr(
        fix_hook_runner,
        "create_artifacts_directory",
        lambda *_args, **_kwargs: str(artifacts_dir),
    )
    monkeypatch.setattr(
        fix_hook_runner,
        "process_xprompt_references",
        lambda _prompt: "expanded fix-hook with #propose",
    )

    embedded = EmbeddedWorkflowResult(
        workflow_name="propose",
        pre_steps=[],
        post_steps=[],
    )

    def expand_embedded(
        _prompt: str,
        _artifacts_dir: str,
    ) -> tuple[str, list[EmbeddedWorkflowResult]]:
        os.environ["SASE_COMMIT_METHOD"] = "create_proposal"
        os.environ["SASE_ACTIVE_PROJECT_DIR"] = str(workspace_dir)
        return "expanded prompt", [embedded]

    monkeypatch.setattr(
        fix_hook_runner,
        "expand_embedded_workflows_in_query",
        expand_embedded,
    )

    def invoke_agent(_prompt: str, **kwargs: object) -> AIMessage:
        assert Path.cwd() == home_dir
        _assert_agent_env(
            artifacts_dir=artifacts_dir,
            project_file=project_file,
            cl_name="fix-hook-cl",
        )
        return _invoke_clean_finalizer(str(kwargs["artifacts_dir"]))

    monkeypatch.setattr(fix_hook_runner, "invoke_agent", invoke_agent)

    def execute_steps(
        _steps: object,
        context: dict[str, object],
        _workflow_name: str,
        _artifacts_dir: str,
    ) -> dict[str, object]:
        context["propose"] = {}
        return context

    monkeypatch.setattr(fix_hook_runner, "execute_standalone_steps", execute_steps)
    monkeypatch.setattr(fix_hook_runner, "parse_project_file", lambda _path: [])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fix_hook_runner.py",
            "fix-hook-cl",
            str(project_file),
            "just lint",
            str(tmp_path / "hook-output.txt"),
            str(tmp_path / "runner-output.txt"),
            "1",
            "260715_120000",
        ],
    )

    assert fix_hook_runner.main() == 1

    expected_error = (
        "Agent completed but no proposal was created — "
        "commit finalizer: clean (no_changes); propose step: skipped"
    )
    done = json.loads((artifacts_dir / "done.json").read_text(encoding="utf-8"))
    assert done["outcome"] == "failed"
    assert done["error"] == expected_error
    assert expected_error in (artifacts_dir / "error_report.md").read_text(
        encoding="utf-8"
    )
    assert observed_project_dirs == [str(workspace_dir)]
    assert "outside_sase_agent" not in (
        artifacts_dir / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")
    assert expected_error in notify.call_args.kwargs["notes"]


def test_crs_runner_publishes_env_and_reports_no_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_agent_env(monkeypatch)
    artifacts_dir = tmp_path / "artifacts" / "20260715130000"
    artifacts_dir.mkdir(parents=True)
    workspace_dir = tmp_path / "claimed-workspace"
    workspace_dir.mkdir()
    monkeypatch.chdir(workspace_dir)

    project_file = tmp_path / "sase.sase"
    comments_file = tmp_path / "comments.json"
    comments_file.write_text('{"comments": []}\n', encoding="utf-8")
    observed_project_dirs: list[str] = []
    _install_clean_finalizer(monkeypatch, observed_project_dirs)
    notify = _patch_runner_plumbing(monkeypatch, crs_runner)

    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda _project_file: "git",
    )
    monkeypatch.setattr(
        crs_runner,
        "create_artifacts_directory",
        lambda *_args, **_kwargs: str(artifacts_dir),
    )
    monkeypatch.setattr(
        crs_workflow_module,
        "create_artifacts_directory",
        lambda *_args, **_kwargs: str(artifacts_dir),
    )
    monkeypatch.setattr(
        crs_workflow_module,
        "generate_workflow_tag",
        lambda: "TEST",
    )
    monkeypatch.setattr(crs_workflow_module, "print_workflow_header", MagicMock())
    monkeypatch.setattr(crs_workflow_module, "print_status", MagicMock())
    monkeypatch.setattr(crs_workflow_module, "print_artifact_created", MagicMock())
    monkeypatch.setattr(crs_workflow_module, "initialize_sase_log", MagicMock())
    monkeypatch.setattr(crs_workflow_module, "finalize_sase_log", MagicMock())
    monkeypatch.setattr(
        crs_workflow_module,
        "_create_critique_comments_artifact",
        lambda _artifacts_dir, _comments_file: str(comments_file),
    )
    monkeypatch.setattr(
        crs_workflow_module,
        "_build_crs_prompt_invocation",
        lambda *_args, **_kwargs: "#crs(...) #propose",
    )
    monkeypatch.setattr(
        crs_workflow_module,
        "_build_crs_prompt",
        lambda *_args, **_kwargs: "expanded crs with #propose",
    )

    embedded = EmbeddedWorkflowResult(
        workflow_name="propose",
        pre_steps=[],
        post_steps=[],
    )

    def expand_embedded(
        _prompt: str,
        _artifacts_dir: str,
    ) -> tuple[str, list[EmbeddedWorkflowResult]]:
        os.environ["SASE_COMMIT_METHOD"] = "create_proposal"
        os.environ["SASE_ACTIVE_PROJECT_DIR"] = str(workspace_dir)
        return "expanded prompt", [embedded]

    monkeypatch.setattr(
        crs_workflow_module,
        "expand_embedded_workflows_in_query",
        expand_embedded,
    )

    def invoke_agent(_prompt: str, **kwargs: object) -> AIMessage:
        _assert_agent_env(
            artifacts_dir=artifacts_dir,
            project_file=project_file,
            cl_name="crs-cl",
        )
        return _invoke_clean_finalizer(str(kwargs["artifacts_dir"]))

    monkeypatch.setattr(crs_workflow_module, "invoke_agent", invoke_agent)

    def execute_steps(
        _steps: object,
        context: dict[str, object],
        _workflow_name: str,
        _artifacts_dir: str,
    ) -> dict[str, object]:
        context["propose"] = {"success": False}
        return context

    monkeypatch.setattr(crs_workflow_module, "execute_standalone_steps", execute_steps)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "crs_runner.py",
            "crs-cl",
            str(project_file),
            str(comments_file),
            "critique",
            "260715_130000",
        ],
    )

    assert crs_runner.main() == 1

    expected_error = (
        "Agent completed but no proposal was created — "
        "commit finalizer: clean (no_changes); propose step: failed"
    )
    done = json.loads((artifacts_dir / "done.json").read_text(encoding="utf-8"))
    assert done["outcome"] == "failed"
    assert done["error"] == expected_error
    assert expected_error in (artifacts_dir / "error_report.md").read_text(
        encoding="utf-8"
    )
    assert observed_project_dirs == [str(workspace_dir)]
    assert "outside_sase_agent" not in (
        artifacts_dir / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")
    assert expected_error in notify.call_args.kwargs["notes"]
