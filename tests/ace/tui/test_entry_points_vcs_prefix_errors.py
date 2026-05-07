"""Tests for TUI-facing VCS prefix detection failures."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow import _entry_points
from sase.ace.tui.actions.agent_workflow._entry_points import EntryPointsMixin
from sase.ace.tui.modals import SelectionItem


class _App(EntryPointsMixin):
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.prompt_launches: list[dict[str, Any]] = []
        self.editor_launches: list[dict[str, Any]] = []
        self.changespecs: list[Any] = []
        self.current_idx = 0
        self._last_custom_agent_selection = None
        self._prompt_context = None

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _show_prompt_input_bar_for_home(self, **kwargs: Any) -> None:
        self.prompt_launches.append(kwargs)

    def _select_and_open_editor_for_home(self, **kwargs: Any) -> None:
        self.editor_launches.append(kwargs)


@pytest.fixture
def missing_workspace_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_project_file: str, _name: str) -> str:
        raise ValueError("No workspace plugin detected a workflow type")

    monkeypatch.setattr(_entry_points.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(_entry_points, "_vcs_prompt_prefix", _raise)


def test_repeat_last_selection_reports_vcs_detection_error_without_launching(
    missing_workspace_plugin: None,
) -> None:
    app = _App()
    app._last_custom_agent_selection = SelectionItem(
        display_name="Fix bug",
        item_type="cl",
        project_name="proj",
        cl_name="fix_bug",
    )

    app.action_start_agent_from_changespec()

    assert app.notifications == [
        (
            "Cannot start agent for fix_bug: "
            "No workspace plugin detected a workflow type",
            "error",
        )
    ]
    assert app.prompt_launches == []
    assert app.editor_launches == []


def test_repeat_last_selection_clears_stale_missing_project_without_launching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_calls: list[bool] = []
    persisted_selection = SelectionItem(
        display_name="branch",
        item_type="cl",
        project_name="project",
        cl_name="branch",
    )

    def _unexpected_prefix(_project_file: str, _name: str) -> str:
        raise AssertionError("stale selections should not detect workspace type")

    monkeypatch.setattr(
        "sase.ace.last_agent_selection.load_last_agent_selection",
        lambda: persisted_selection,
    )
    monkeypatch.setattr(
        "sase.ace.last_agent_selection.clear_last_agent_selection",
        lambda: clear_calls.append(True) or True,
    )
    monkeypatch.setattr(_entry_points.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(_entry_points, "_vcs_prompt_prefix", _unexpected_prefix)

    app = _App()

    app.action_start_agent_from_changespec()

    assert app.notifications == [
        (
            "Saved @/<space> selection is stale: "
            "project file not found for 'project'; cleared saved selection",
            "warning",
        )
    ]
    assert app.prompt_launches == []
    assert app.editor_launches == []
    assert app._last_custom_agent_selection is None
    assert clear_calls == [True]


def test_quick_current_changespec_reports_vcs_detection_error_without_saving(
    missing_workspace_plugin: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[SelectionItem] = []
    monkeypatch.setattr(
        "sase.ace.last_agent_selection.save_last_agent_selection", saved.append
    )
    app = _App()
    app.changespecs = [
        SimpleNamespace(
            name="fix_bug",
            file_path="/tmp/proj/proj.gp",
            project_basename="proj",
        )
    ]

    app._start_agent_from_changespec_quick()

    assert app.notifications == [
        (
            "Cannot start agent for fix_bug: "
            "No workspace plugin detected a workflow type",
            "error",
        )
    ]
    assert app.prompt_launches == []
    assert app.editor_launches == []
    assert app._last_custom_agent_selection is None
    assert saved == []
