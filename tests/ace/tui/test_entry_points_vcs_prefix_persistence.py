"""Tests for VCS-prefix mount behavior in quick-launch/edit-relaunch entry points."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow import _entry_points

from ._entry_points_vcs_prefix_helpers import _App


def test_quick_patch_mounts_prompt_bar_for_non_launchable_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bogus project_basename still mounts the prompt bar with its prefix."""
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        lambda _name, projects_dir=None: False,
    )

    app = _App()
    app.patches = [
        SimpleNamespace(
            name="branch",
            file_path="/tmp/project/project.sase",
            project_basename="project",
        )
    ]

    app._start_agent_from_patch_quick()

    assert len(app.prompt_launches) == 1
    assert app.prompt_launches[0]["initial_text"] == "#gh:branch "


def test_quick_agent_mounts_prompt_bar_for_non_launchable_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale agent.project_file still mounts the prompt bar with its prefix."""
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        lambda _name, projects_dir=None: False,
    )

    agent = SimpleNamespace(
        project_file="/tmp/project/project.sase",
        cl_name="branch",
        is_project_agent=False,
    )

    class _AppWithAgent(_App):
        def _get_selected_agent(self) -> Any:
            return agent

    app = _AppWithAgent()

    app._start_agent_from_agent_quick()

    assert len(app.prompt_launches) == 1


def test_quick_agent_uses_cl_name_not_agent_display_name_for_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workflow display labels must not replace the launchable CL/ref name."""
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        lambda _name, projects_dir=None: True,
    )

    agent = SimpleNamespace(
        project_file="/tmp/project/project.sase",
        cl_name="branch",
        display_name="workflow_label",
        is_project_agent=False,
    )

    class _AppWithAgent(_App):
        def _get_selected_agent(self) -> Any:
            return agent

    app = _AppWithAgent()

    app._start_agent_from_agent_quick()

    assert app.prompt_launches[0]["initial_text"] == "#gh:branch "
    assert app.prompt_launches[0]["display_name"] == "branch"


def test_edit_and_relaunch_mounts_prompt_bar_for_non_launchable_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale project_file in edit-and-relaunch still mounts the prompt bar."""
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        lambda _name, projects_dir=None: False,
    )

    class _AppEdit(_App):
        def __init__(self) -> None:
            super().__init__()
            self.mounted: list[Any] = []

        def _unmount_prompt_bar(self) -> None:
            return None

        def mount(self, widget: Any) -> None:
            self.mounted.append(widget)

    app = _AppEdit()

    app._edit_and_relaunch_agent(
        raw_prompt="Do work",
        project_file="/tmp/project/project.sase",
        cl_name="branch",
        is_project_agent=False,
    )

    assert len(app.mounted) == 1
