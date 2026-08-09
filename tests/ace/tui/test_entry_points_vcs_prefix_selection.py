"""Tests for selection-driven VCS prefix entry points."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.agent_workflow import _entry_points
from sase.ace.tui.modals import ProjectSelectModal, SelectionItem
from sase.ace.tui.modals.project_select_modal import _ProjectSelectData
from sase.project_display_names import ProjectDisplayProjection, ProjectDisplaySnapshot

from ._entry_points_vcs_prefix_helpers import (
    _App,
    _patch_missing_workspace_plugin,
)


def test_repeat_last_selection_reports_vcs_detection_error_without_launching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_missing_workspace_plugin(monkeypatch)
    app = _App()
    app._last_custom_agent_selection = SelectionItem(
        display_name="Fix bug",
        item_type="cl",
        project_name="proj",
        cl_name="fix_bug",
    )

    app.action_start_agent_from_patch()

    assert app.notifications == [
        (
            "Cannot start agent for fix_bug: "
            "No workspace plugin detected a workflow type",
            "error",
        )
    ]
    assert app.prompt_launches == []
    assert app.editor_launches == []


def test_home_project_selection_launches_with_vcs_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#git:{name} "
    )
    app = _App()

    app._start_custom_agent_from_selection(
        SelectionItem(
            display_name="[P] home",
            item_type="project",
            project_name="home",
            cl_name=None,
        )
    )

    assert app.prompt_launches == [
        {
            "initial_text": "#git:home ",
            "display_name": "home",
            "history_sort_key": "home",
        }
    ]
    assert app.editor_launches == []


def test_project_selection_prefills_configured_project_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A project with a ``PROJECT_NAME`` prefills the configured name, not the key.

    The bar label is humanized too, while the history grouping key stays the
    canonical directory key.
    """
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda key, *_a, **_k: {"gh_acme__widgets": "widgets"}.get(key, key),
    )
    app = _App()

    app._start_custom_agent_from_selection(
        SelectionItem(
            display_name="[P] gh_acme__widgets",
            item_type="project",
            project_name="gh_acme__widgets",
            cl_name=None,
        )
    )

    assert app.prompt_launches == [
        {
            "initial_text": "#gh:widgets ",
            "display_name": "widgets",
            "history_sort_key": "gh_acme__widgets",
        }
    ]
    assert app.editor_launches == []


def test_project_selection_without_project_name_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A project without a ``PROJECT_NAME`` still prefills its directory key."""
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda key, *_a, **_k: key,
    )
    app = _App()

    app._start_custom_agent_from_selection(
        SelectionItem(
            display_name="[P] sase",
            item_type="project",
            project_name="sase",
            cl_name=None,
        )
    )

    assert app.prompt_launches == [
        {
            "initial_text": "#gh:sase ",
            "display_name": "sase",
            "history_sort_key": "sase",
        }
    ]


def test_cl_selection_keeps_patch_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PR branch is untouched: it prefills the patch name verbatim."""
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda key, *_a, **_k: {"gh_acme__widgets": "widgets"}.get(key, key),
    )
    app = _App()

    app._start_custom_agent_from_selection(
        SelectionItem(
            display_name="fix bug",
            item_type="cl",
            project_name="gh_acme__widgets",
            cl_name="fix_bug",
        )
    )

    assert app.prompt_launches == [
        {
            "initial_text": "#gh:fix_bug ",
            "display_name": "fix_bug",
            "history_sort_key": "fix_bug",
        }
    ]


def test_start_custom_agent_selector_hides_home_project_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_select_modal._load_project_select_data",
        lambda: _ProjectSelectData(
            projects=(
                ProjectDisplayProjection("home", "home"),
                ProjectDisplayProjection("sase", "sase"),
            ),
            patches=(),
            project_display_snapshot=ProjectDisplaySnapshot(
                {"home": "home", "sase": "sase"}
            ),
        ),
    )
    app = _App()

    app.action_start_custom_agent()

    assert len(app.pushed_screens) == 1
    modal, callback = app.pushed_screens[0]
    assert isinstance(modal, ProjectSelectModal)
    assert callback is not None
    assert [item.display_name for item in modal.all_items] == ["[P] sase"]


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
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: False)
    monkeypatch.setattr(_entry_points, "_vcs_prompt_prefix", _unexpected_prefix)

    app = _App()

    app.action_start_agent_from_patch()

    assert app.notifications == [
        (
            "Saved +/Ctrl+Space selection is stale: "
            "project 'project' is not launchable; cleared saved selection",
            "warning",
        )
    ]
    assert app.prompt_launches == []
    assert app.editor_launches == []
    assert app._last_custom_agent_selection is None
    assert clear_calls == [True]


def test_repeat_last_selection_clears_stale_default_home_without_launching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale project-``home`` selection clears instead of launching default home."""
    clear_calls: list[bool] = []
    persisted_selection = SelectionItem(
        display_name="[P] home",
        item_type="project",
        project_name="home",
        cl_name=None,
    )

    monkeypatch.setattr(
        "sase.ace.last_agent_selection.load_last_agent_selection",
        lambda: persisted_selection,
    )
    monkeypatch.setattr(
        "sase.ace.last_agent_selection.clear_last_agent_selection",
        lambda: clear_calls.append(True) or True,
    )
    # ``home`` is a launchable project, so the stale-launchability guard does
    # not fire; the default-prefix guard must.
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#git:{name} "
    )

    app = _App()

    app.action_start_agent_from_patch()

    assert app.notifications == [
        (
            "Saved +/Ctrl+Space selection was the implicit #git:home default; "
            "cleared it (use the home keymap to start a home-mode agent)",
            "warning",
        )
    ]
    assert app.prompt_launches == []
    assert app.editor_launches == []
    assert app._last_custom_agent_selection is None
    assert clear_calls == [True]


def test_repeat_last_selection_replays_non_default_launchable_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A launchable project with a non-default prefix is replayed normally."""
    monkeypatch.setattr(
        "sase.ace.last_agent_selection.load_last_agent_selection",
        lambda: SelectionItem(
            display_name="[P] sase",
            item_type="project",
            project_name="sase",
            cl_name=None,
        ),
    )
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: True)
    monkeypatch.setattr(
        _entry_points, "_vcs_prompt_prefix", lambda _pf, name: f"#gh:{name} "
    )

    app = _App()

    app.action_start_agent_from_patch()

    assert app.prompt_launches == [
        {
            "initial_text": "#gh:sase ",
            "display_name": "sase",
            "history_sort_key": "sase",
        }
    ]
    assert app.notifications == []
    assert app.editor_launches == []
    assert app._last_custom_agent_selection is not None


def test_quick_current_patch_reports_vcs_detection_error_without_saving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_missing_workspace_plugin(monkeypatch)
    saved: list[SelectionItem] = []
    monkeypatch.setattr(
        "sase.ace.last_agent_selection._save_last_agent_selection", saved.append
    )
    app = _App()
    app.patches = [
        SimpleNamespace(
            name="fix_bug",
            file_path="/tmp/proj/proj.sase",
            project_basename="proj",
        )
    ]

    app._start_agent_from_patch_quick()

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
