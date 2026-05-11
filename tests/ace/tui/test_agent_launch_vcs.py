"""Tests that ``_run_agent_launch_body`` resolves VCS refs correctly.

Covers ``#cd`` directory targeting, default git-home fallback when no
ref is present, known-project ref resolution without a provider, and
the launchable/non-launchable branching for saving the resolved ref as
the "last custom agent selection".

The non-blocking event-loop guarantees live in
``test_agent_launch_non_blocking.py``; the dispatch routing paths live
in ``test_agent_launch_dispatch.py``.
"""

from __future__ import annotations

import re
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workspace_provider._hookspec import ResolvedRef
from tests.ace.tui._agent_launch_helpers import (
    _LaunchBodyApp,
    _cd_git_metadata,
    _cd_metadata,
    _fake_context,
)


def test_run_agent_launch_body_cd_keeps_home_mode_and_uses_target_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()

    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: resolve_ref_from_prompt(
            prompt, wf_name, skip_workspace=skip_workspace
        )
    )

    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _cd_metadata)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )
        stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        app._run_agent_launch_body(f"#cd:{tmp_path} do work")

    assert len(app.launched) == 1
    launch = app.launched[0]
    assert launch["workspace_dir"] == str(tmp_path.resolve())
    assert launch["workspace_num"] == 0
    assert launch["is_home_mode"] is True
    assert launch["update_target"] == ""
    assert launch["vcs_ref"] == ("cd", str(tmp_path))


def test_run_agent_launch_body_no_ref_defaults_home_mode_to_git_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    primary_workspace = tmp_path / "home"
    allocated_workspace = tmp_path / "home_101"
    project_file = str(tmp_path / "home.gp")

    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: resolve_ref_from_prompt(
            prompt, wf_name, skip_workspace=skip_workspace
        )
    )

    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _cd_git_metadata)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.resolve_ref",
                return_value=ResolvedRef(
                    project_file=project_file,
                    project_name="home",
                    primary_workspace_dir=str(primary_workspace),
                    checkout_target="main",
                ),
            )
        )
        first_ws = stack.enter_context(
            patch(
                "sase.running_field.get_first_available_axe_workspace",
                return_value=101,
            )
        )
        provider_ws_dir = stack.enter_context(
            patch(
                "sase.workspace_provider.get_workspace_directory",
                return_value=str(allocated_workspace),
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=True,
            )
        )
        stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
        )
        stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        app._run_agent_launch_body("do work")

    assert len(app.launched) == 1
    launch = app.launched[0]
    assert launch["prompt"] == "#git:home do work"
    assert launch["project_name"] == "home"
    assert launch["project_file"] == project_file
    assert launch["workspace_dir"] == str(allocated_workspace)
    assert launch["workspace_num"] == 101
    assert launch["is_home_mode"] is False
    assert launch["update_target"] == ""
    assert launch["vcs_ref"] == ("git", "home")
    first_ws.assert_called_once_with(project_file)
    provider_ws_dir.assert_called_once_with(
        "git",
        101,
        "home",
        str(primary_workspace),
    )


def test_run_agent_launch_body_known_project_ref_without_provider_targets_project(
    tmp_path: Path,
) -> None:
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    workspace = tmp_path / "sase"
    workspace.mkdir()
    allocated_workspace = tmp_path / "sase_101"
    allocated_workspace.mkdir()
    project_file = str(Path.home() / ".sase" / "projects" / "sase" / "sase.gp")

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_ref_patterns", return_value={})
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value=set())
        )
        stack.enter_context(
            patch(
                "sase.xprompt.loader.get_known_project_workspaces",
                return_value={"sase": workspace},
            )
        )
        first_ws = stack.enter_context(
            patch(
                "sase.running_field.claim_next_axe_workspace",
                return_value=101,
            )
        )
        ws_dir = stack.enter_context(
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(allocated_workspace), None),
            )
        )
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )
        stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        app._run_agent_launch_body("#gh:sase #!sase/fix_just")

    assert len(app.launched) == 1
    launch = app.launched[0]
    assert launch["prompt"] == "#gh:sase #!sase/fix_just"
    assert launch["project_name"] == "sase"
    assert launch["project_file"] == project_file
    assert launch["workspace_dir"] == str(allocated_workspace)
    assert launch["workspace_num"] == 101
    assert launch["is_home_mode"] is False
    assert launch["update_target"] == VCS_DEFAULT_REVISION
    assert launch["vcs_ref"] == ("gh", "sase")
    first_ws.assert_called_once()
    assert first_ws.call_args.args[0] == project_file
    ws_dir.assert_called_once_with(101, "sase")


def test_run_agent_launch_body_does_not_save_non_launchable_resolved_vcs_ref() -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    previous_selection = object()
    app._last_custom_agent_selection = previous_selection  # type: ignore[assignment]
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/project/project.gp",
            "project",
            "/tmp/project_1",
            1,
            "project",
        )
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.get_ref_patterns",
                return_value={
                    "gh": re.compile(r"(?:^|(?<=\s))#gh(?:[_:]([^\s]+)|\(([^)]*)\))")
                },
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"gh"})
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=False,
            )
        )
        save = stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        record_mru = stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
        )
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )

        app._run_agent_launch_body("#gh:project fix stale replay")

    assert len(app.launched) == 1
    save.assert_not_called()
    record_mru.assert_not_called()
    assert app._last_custom_agent_selection is previous_selection


def test_run_agent_launch_body_saves_launchable_resolved_vcs_ref() -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/sase/sase.gp",
            "sase",
            "/tmp/sase_1",
            1,
            "fix_branch",
        )
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.get_ref_patterns",
                return_value={
                    "gh": re.compile(r"(?:^|(?<=\s))#gh(?:[_:]([^\s]+)|\(([^)]*)\))")
                },
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"gh"})
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=True,
            )
        )
        save = stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        record_mru = stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
        )
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )

        app._run_agent_launch_body("#gh:fix_branch implement")

    assert len(app.launched) == 1
    saved = app._last_custom_agent_selection
    assert saved is not None
    assert saved.item_type == "cl"
    assert saved.project_name == "sase"
    assert saved.cl_name == "fix_branch"
    save.assert_called_once_with(saved)
    record_mru.assert_called_once_with("#gh:fix_branch")
