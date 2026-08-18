"""Tests for selection-driven VCS prefix entry points."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow import _entry_points
from sase.ace.tui.modals import ProjectSelectModal, SelectionItem
from sase.ace.tui.modals.project_select_modal import _ProjectSelectData
from sase.project_display_names import ProjectDisplayProjection, ProjectDisplaySnapshot

from ._entry_points_vcs_prefix_helpers import (
    _App,
    _patch_missing_workspace_plugin,
)


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
        lambda **_kwargs: _ProjectSelectData(
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


def test_start_custom_agent_reads_seed_filters_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.current_project_settings import CurrentProjectSettings

    captured: list[bool] = []

    def fake_load(**kwargs: Any) -> _ProjectSelectData:
        captured.append(kwargs["seed_from_current_project"])
        return _ProjectSelectData(
            projects=(),
            patches=(),
            project_display_snapshot=ProjectDisplaySnapshot({}),
        )

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_select_modal._load_project_select_data",
        fake_load,
    )
    app = _App()
    app._current_project_settings = CurrentProjectSettings(seed_filters=False)

    app.action_start_custom_agent()

    assert captured == [False]


def test_selecting_non_launchable_project_notifies_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a stale/non-launchable project just notifies; nothing is saved."""
    monkeypatch.setattr(_entry_points, "is_launchable_project", lambda _project: False)
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda key, *_a, **_k: key,
    )

    app = _App()

    app._start_custom_agent_from_selection(
        SelectionItem(
            display_name="branch",
            item_type="cl",
            project_name="project",
            cl_name="branch",
        )
    )

    assert app.notifications == [
        ("Project 'project' is not launchable", "warning"),
    ]
    assert app.prompt_launches == []
    assert app.editor_launches == []


def test_ctrl_space_mounts_bar_from_mru_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``<ctrl+space>`` pre-fills from the VCS xprompt MRU head.

    Regression coverage for the headline defect: ``<ctrl+space>`` must read
    the same store that every launch surface writes, not a separate
    selection-time store. The display half seeds the bar text/label; the
    canonical half seeds ``history_sort_key``.
    """
    from sase.history import vcs_xprompt_mru

    monkeypatch.setattr(
        vcs_xprompt_mru,
        "load_launchable_vcs_xprompt_mru_pairs",
        lambda *a, **k: [("#gh:gh_acme__widgets", "#gh:widgets")],
    )
    app = _App()

    app.action_start_agent_from_patch()

    assert app.prompt_launches == [
        {
            "initial_text": "#gh:widgets ",
            "display_name": "widgets",
            "history_sort_key": "gh_acme__widgets",
        }
    ]
    assert app.notifications == []


def test_ctrl_space_offers_most_recently_launched_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After launching ref A then ref B, ``<ctrl+space>`` offers B, not A.

    Reduces the "open the bar on A, cycle to B, launch" headline bug to its
    MRU-head effect: the most recently *launched* ref wins, regardless of
    what an earlier selection or cycle left behind.
    """
    from sase.history import vcs_xprompt_mru

    monkeypatch.setattr(
        vcs_xprompt_mru,
        "load_launchable_vcs_xprompt_mru_pairs",
        lambda *a, **k: [("#gh:projB", "#gh:projB"), ("#gh:projA", "#gh:projA")],
    )
    app = _App()

    app.action_start_agent_from_patch()

    assert app.prompt_launches == [
        {
            "initial_text": "#gh:projB ",
            "display_name": "projB",
            "history_sort_key": "projB",
        }
    ]


def test_ctrl_space_warns_when_mru_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.history import vcs_xprompt_mru

    monkeypatch.setattr(
        vcs_xprompt_mru,
        "load_launchable_vcs_xprompt_mru_pairs",
        lambda *a, **k: [],
    )
    app = _App()

    app.action_start_agent_from_patch()

    assert app.notifications == [
        ("No previously launched VCS xprompt", "warning"),
    ]
    assert app.prompt_launches == []
    assert app.editor_launches == []


def test_quick_current_patch_reports_vcs_detection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_missing_workspace_plugin(monkeypatch)
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
