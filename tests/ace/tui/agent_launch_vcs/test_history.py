"""VCS launch MRU and replay-selection history behavior."""

from __future__ import annotations

import re
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.ace.tui._agent_launch_helpers import _LaunchBodyApp, _fake_context


def test_run_agent_launch_body_does_not_save_non_launchable_resolved_vcs_ref() -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    previous_selection = object()
    app._last_custom_agent_selection = previous_selection  # type: ignore[assignment]
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/project/project.sase",
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
        stack.enter_context(
            patch(
                "sase.running_field.claim_next_axe_workspace",
                return_value=101,
            )
        )
        stack.enter_context(
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=("/tmp/project_101", None),
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
            "/tmp/sase/sase.sase",
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
        stack.enter_context(
            patch(
                "sase.running_field.claim_next_axe_workspace",
                return_value=101,
            )
        )
        stack.enter_context(
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=("/tmp/sase_101", None),
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


def test_run_agent_launch_body_records_home_multi_prompt_vcs_ref_mru() -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/sase/sase.sase",
            "sase",
            "/tmp/sase",
            0,
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
                "sase.agent.launch_projects.enable_known_project_vcs_refs_for_launch_prompt",
                return_value=(),
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=True,
            )
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

        app._run_agent_launch_body("#gh:fix_branch first\n---\nsecond")

    assert app.launched == []
    multi_prompt_calls = [
        (fn, args)
        for fn, args in app.scheduled
        if fn == app._launch_multi_prompt_agents
    ]
    assert len(multi_prompt_calls) == 1
    _, args = multi_prompt_calls[0]
    assert args[2] == ("gh", "fix_branch")
    record_mru.assert_called_once_with("#gh:fix_branch")


def test_run_agent_launch_body_skips_home_multi_prompt_non_launchable_vcs_ref_mru() -> (
    None
):
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/project/project.sase",
            "project",
            "/tmp/project",
            0,
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
                "sase.agent.launch_projects.enable_known_project_vcs_refs_for_launch_prompt",
                return_value=(),
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.modals.project_discovery.is_launchable_project",
                return_value=False,
            )
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

        app._run_agent_launch_body("#gh:project first\n---\nsecond")

    multi_prompt_calls = [
        (fn, args)
        for fn, args in app.scheduled
        if fn == app._launch_multi_prompt_agents
    ]
    assert len(multi_prompt_calls) == 1
    record_mru.assert_not_called()


def test_run_agent_launch_body_records_non_home_detected_vcs_ref_mru() -> None:
    app = _LaunchBodyApp()
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/sase/sase.sase",
            "sase",
            "/tmp/sase",
            0,
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
        stack.enter_context(
            patch(
                "sase.running_field.claim_next_axe_workspace",
                return_value=101,
            )
        )
        stack.enter_context(
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=("/tmp/test_101", None),
            )
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
    assert app.launched[0]["vcs_ref"] == ("gh", "fix_branch")
    record_mru.assert_called_once_with("#gh:fix_branch")


def test_run_agent_launch_body_skips_non_home_non_launchable_vcs_ref_mru() -> None:
    app = _LaunchBodyApp()
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: (
            "/tmp/project/project.sase",
            "project",
            "/tmp/project",
            0,
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
        stack.enter_context(
            patch(
                "sase.running_field.claim_next_axe_workspace",
                return_value=101,
            )
        )
        stack.enter_context(
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=("/tmp/test_101", None),
            )
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

        app._run_agent_launch_body("#gh:project implement")

    assert len(app.launched) == 1
    record_mru.assert_not_called()
