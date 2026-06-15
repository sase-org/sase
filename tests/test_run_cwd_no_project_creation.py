"""Regression tests: ``sase run`` must not register the CWD as a project.

A plain launch from a git checkout whose basename happens to be a valid SASE
project name must not silently create ``~/.sase/projects/<cwd-project>/``.
Bare prompts fall back to ``home``; explicit refs resolve their real project.
Both background (``launch_agents_from_cwd``) and foreground (``run_query``)
paths are covered.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider._hookspec import ResolvedRef
from tests._cd_launch_resolution_helpers import (
    patch_cd_git_metadata,
    patch_cd_metadata,
)

_INFERRED_PROJECT = "myrepo"


def _fake_resolve_ref(ref: str, workflow_type: str, *, base: Path) -> ResolvedRef:
    return ResolvedRef(
        project_file=str(base / f"{ref}.sase"),
        project_name=ref,
        primary_workspace_dir=str(base / ref),
        checkout_target="main",
    )


def test_daemon_bare_prompt_falls_back_to_home_without_creating_cwd_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A bare daemon launch from an inferred (spec-less) git project → home."""
    patch_cd_git_metadata(monkeypatch)
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))

    from sase.agent.launcher import launch_agent_from_cwd
    from sase.main import utils as main_utils

    # The CWD infers a valid-but-unregistered project name.
    monkeypatch.setattr(
        main_utils, "get_workspace_name", lambda _cwd: _INFERRED_PROJECT
    )

    primary_workspace = tmp_path / "home"
    allocated_workspace = tmp_path / "home_101"
    project_file = str(tmp_path / "home.sase")
    spawn_result = MagicMock(
        pid=123, workspace_dir=str(allocated_workspace), workspace_num=101
    )
    with (
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch(
            "sase.workspace_provider.resolve_ref",
            return_value=ResolvedRef(
                project_file=project_file,
                project_name="home",
                primary_workspace_dir=str(primary_workspace),
                checkout_target="main",
            ),
        ),
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ),
    ):
        result = launch_agent_from_cwd("do work")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["prompt"] == "#git:home do work"
    assert kwargs["project_name"] == "home"
    assert kwargs["vcs_ref"] == ("git", "home")
    # The inferred CWD project must never have been registered on disk.
    assert not (sase_home / "projects" / _INFERRED_PROJECT).exists()


def test_daemon_explicit_ref_resolves_referenced_project_not_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An explicit ``#git:sase`` launch resolves ``sase`` and never ``myrepo``."""
    patch_cd_git_metadata(monkeypatch)
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))

    from sase.agent.launcher import launch_agent_from_cwd
    from sase.main import utils as main_utils

    monkeypatch.setattr(
        main_utils, "get_workspace_name", lambda _cwd: _INFERRED_PROJECT
    )

    allocated_workspace = tmp_path / "sase_101"
    spawn_result = MagicMock(
        pid=123, workspace_dir=str(allocated_workspace), workspace_num=101
    )
    with (
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["260501_120000"],
        ),
        patch(
            "sase.agent.launcher.spawn_agent_subprocess",
            return_value=spawn_result,
        ) as spawn,
        patch(
            "sase.workspace_provider.resolve_ref",
            side_effect=lambda ref, wf: _fake_resolve_ref(ref, wf, base=tmp_path),
        ),
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=101,
        ),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=(str(allocated_workspace), None),
        ),
    ):
        result = launch_agent_from_cwd("#git:sase do work")

    assert result is spawn_result
    kwargs = spawn.call_args.kwargs
    assert kwargs["project_name"] == "sase"
    assert kwargs["vcs_ref"] == ("git", "sase")
    # The inferred CWD project must never have been registered on disk.
    assert not (sase_home / "projects" / _INFERRED_PROJECT).exists()


def test_run_query_bare_prompt_skips_claim_without_creating_cwd_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Foreground ``run_query`` from a spec-less checkout creates no project."""
    patch_cd_metadata(monkeypatch)
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))

    from sase.main import utils as main_utils

    monkeypatch.setattr(
        main_utils, "get_workspace_name", lambda _cwd: _INFERRED_PROJECT
    )

    workflow_result = MagicMock(response_text="ok")
    anon_workflow = MagicMock(name="anon", xprompts=None)

    with (
        patch("sase.xprompt.resolve_xprompt_aliases", side_effect=lambda q: q),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.main.query_handler._query.claim_workspace",
        ) as claim_workspace,
        patch("sase.main.query_handler._query.release_workspace"),
        patch(
            "sase.main.query_handler._query.create_artifacts_directory",
        ) as create_artifacts,
        patch(
            "sase.xprompt.models.create_anonymous_workflow",
            return_value=anon_workflow,
        ),
        patch(
            "sase.xprompt.workflow_runner.execute_workflow",
            return_value=workflow_result,
        ) as execute_workflow,
        patch(
            "sase.main.query_handler._query.save_chat_history",
            return_value="/tmp/chat.md",
        ),
    ):
        from sase.main.query_handler._query import run_query

        run_query("hello")

    execute_workflow.assert_called_once()
    # No project resolved → no workspace claim and no CWD-derived artifacts.
    claim_workspace.assert_not_called()
    create_artifacts.assert_not_called()
    assert not (sase_home / "projects" / _INFERRED_PROJECT).exists()


def test_run_query_anchors_artifacts_to_resolved_home_not_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When a bare prompt resolves to ``home``, artifacts anchor to ``home``."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    artifacts_dir = str(tmp_path / "20260501120000")
    Path(artifacts_dir).mkdir(parents=True)

    mock_directives = MagicMock(model=None)
    anon_workflow = MagicMock(name="anon", xprompts=None)
    workflow_result = MagicMock(response_text="ok")

    with (
        patch(
            "sase.main.query_handler._query._resolve_vcs_cwd",
            return_value=("home", "home"),
        ),
        patch(
            "sase.main.query_handler._query.ensure_project_file_and_get_workspace_num",
            return_value=(None, None, None),
        ),
        patch(
            "sase.main.query_handler._query.create_artifacts_directory",
            return_value=artifacts_dir,
        ) as create_artifacts,
        patch("sase.xprompt.resolve_xprompt_aliases", side_effect=lambda q: q),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.xprompt.directives.extract_prompt_directives",
            return_value=("hello", mock_directives),
        ),
        patch(
            "sase.llm_provider.temporary_override.resolve_effective_default_provider_model",
            return_value=("anthropic", "test-model"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch(
            "sase.main.query_handler._query.update_agent_artifact_index_for_marker_mutation"
        ),
        patch("sase.main.query_handler._query.claim_workspace") as claim_workspace,
        patch("sase.main.query_handler._query.release_workspace"),
        patch(
            "sase.xprompt.models.create_anonymous_workflow",
            return_value=anon_workflow,
        ),
        patch(
            "sase.xprompt.workflow_runner.execute_workflow",
            return_value=workflow_result,
        ),
        patch(
            "sase.main.query_handler._query.save_chat_history",
            return_value="/tmp/chat.md",
        ),
    ):
        from sase.main.query_handler._query import run_query

        run_query("hello")

    create_artifacts.assert_called_once_with("run", project_name="home")
    # project_file resolved to None → workspace claiming is skipped.
    claim_workspace.assert_not_called()
