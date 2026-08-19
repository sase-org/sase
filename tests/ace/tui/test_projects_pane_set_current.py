"""Set-current keypress on the Admin Center Projects tab."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from textual.widgets import OptionList
from textual.worker import WorkerState

from sase.ace.testing import AcePage
from sase.ace.tui.modals import project_management_actions as actions_module
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.project_management_actions import _CURRENT_PROJECT_SET_GROUP
from sase.ace.tui.modals.projects_pane import ProjectCountsLoadResult, ProjectsPane
from sase.ace.tui.widgets.current_project_indicator import CurrentProjectIndicator
from sase.current_project import CurrentProject, SetCurrentProjectOutcome

from tests.ace.tui.modals.project_management_modal_test_helpers import (
    ProjectsPaneTestApp,
    make_project_record,
)
from tests.ace.tui.test_projects_pane import _patch_panes


class _FakeWorker:
    def __init__(self, result: object, error: object | None = None) -> None:
        self.result = result
        self.error = error


class _FakeStateChanged:
    def __init__(self, worker: _FakeWorker, state: WorkerState) -> None:
        self.worker = worker
        self.state = state


def _current_project(
    project_key: str,
    *,
    display_name: str | None = None,
) -> CurrentProject:
    return CurrentProject(
        project_key=project_key,
        display_name=display_name or project_key,
        origin="project",
        origin_ref=project_key,
        workflow_type="gh",
    )


def _outcome(
    status: str,
    *,
    project: CurrentProject | None = None,
    message: str = "",
) -> SetCurrentProjectOutcome:
    return SetCurrentProjectOutcome(
        status=status,  # type: ignore[arg-type]
        project=project,
        message=message,
    )


def _install_records(
    monkeypatch: pytest.MonkeyPatch,
    records: list[Any],
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: list(records),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.collect_project_inventory_counts",
        lambda *_args, **_kwargs: ProjectCountsLoadResult({}),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda **_kwargs: None,
    )


def _stub_set(
    monkeypatch: pytest.MonkeyPatch,
    outcome: SetCurrentProjectOutcome | None = None,
) -> list[tuple[str, Path | None]]:
    calls: list[tuple[str, Path | None]] = []

    def fake_set(
        project_key: str, *, projects_dir: Path | None = None
    ) -> SetCurrentProjectOutcome:
        calls.append((project_key, projects_dir))
        if outcome is not None:
            return outcome
        project = _current_project(project_key)
        return _outcome(
            "set",
            project=project,
            message=f"{project_key} is now the current project.",
        )

    monkeypatch.setattr(actions_module, "set_current_project", fake_set)
    return calls


async def test_no_selection_sets_status_and_starts_no_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_records(monkeypatch, [])
    set_calls = _stub_set(monkeypatch)
    started: list[object] = []

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        monkeypatch.setattr(pane, "run_worker", lambda *a, **k: started.append((a, k)))
        monkeypatch.setattr(pane, "notify", MagicMock())

        pane.action_set_current_project()

        assert pane._status_message == "No project selected"
        assert started == []
        assert set_calls == []
        pane.notify.assert_not_called()


async def test_disabled_precheck_warns_and_starts_no_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_records(
        monkeypatch,
        [make_project_record("alpha", state="disabled", launchable=False)],
    )
    set_calls = _stub_set(monkeypatch)
    started: list[object] = []

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        monkeypatch.setattr(pane, "run_worker", lambda *a, **k: started.append((a, k)))
        monkeypatch.setattr(pane, "notify", MagicMock())

        await pilot.press("c")

        message = "alpha is disabled; enable it first (a)"
        assert pane._status_message == message
        pane.notify.assert_called_once_with(message, severity="warning")
        assert started == []
        assert set_calls == []


async def test_non_launchable_precheck_warns_and_starts_no_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_records(
        monkeypatch,
        [make_project_record("widgets", state="enabled", launchable=False)],
    )
    set_calls = _stub_set(monkeypatch)
    started: list[object] = []

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        monkeypatch.setattr(pane, "run_worker", lambda *a, **k: started.append((a, k)))
        monkeypatch.setattr(pane, "notify", MagicMock())

        await pilot.press("c")

        message = "widgets has no launchable ProjectSpec"
        assert pane._status_message == message
        pane.notify.assert_called_once_with(message, severity="warning")
        assert started == []
        assert set_calls == []


async def test_already_current_precheck_starts_no_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_records(monkeypatch, [make_project_record("alpha")])
    set_calls = _stub_set(monkeypatch)
    started: list[object] = []

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        pane._current_project = _current_project("alpha")
        monkeypatch.setattr(pane, "run_worker", lambda *a, **k: started.append((a, k)))
        monkeypatch.setattr(pane, "notify", MagicMock())

        await pilot.press("c")

        assert pane._status_message == "alpha is already current"
        assert started == []
        assert set_calls == []
        pane.notify.assert_not_called()


async def test_eligible_press_starts_thread_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_records(
        monkeypatch,
        [make_project_record("alpha"), make_project_record("beta")],
    )
    outcome = _outcome(
        "set",
        project=_current_project("beta"),
        message="beta is now the current project.",
    )
    set_calls = _stub_set(monkeypatch, outcome)
    captured: list[dict[str, Any]] = []

    def fake_run_worker(task: Any, **kwargs: Any) -> MagicMock:
        captured.append({"task": task, **kwargs})
        return MagicMock()

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        option_list = pane.query_one("#projects-list", OptionList)
        option_list.highlighted = 1
        monkeypatch.setattr(pane, "run_worker", fake_run_worker)

        pane.action_set_current_project()

        assert pane._status_message == "Making beta current…"
        assert len(captured) == 1
        assert captured[0]["thread"] is True
        assert captured[0]["exclusive"] is False
        assert captured[0]["group"] == _CURRENT_PROJECT_SET_GROUP
        assert captured[0]["task"]() == outcome
        assert set_calls == [("beta", tmp_path)]


@pytest.mark.parametrize(
    ("status", "severity", "restarts"),
    [
        ("set", "information", True),
        ("unchanged", "information", False),
        ("ineligible", "warning", False),
        ("unverified", "error", False),
    ],
)
async def test_outcomes_drive_status_notify_and_refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
    severity: str,
    restarts: bool,
) -> None:
    _install_records(monkeypatch, [make_project_record("beta")])
    project = _current_project("beta")
    message = f"outcome:{status}"
    outcome = _outcome(status, project=project, message=message)

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        monkeypatch.setattr(pane, "notify", MagicMock())
        resolve = MagicMock()
        invalidate = MagicMock()
        monkeypatch.setattr(pane, "_start_current_project_resolve", resolve)
        monkeypatch.setattr(pane, "_invalidate_current_project_indicator", invalidate)

        pane._apply_set_current_project_outcome(
            _FakeStateChanged(_FakeWorker(outcome), WorkerState.SUCCESS)
        )

        assert pane._status_message == message
        pane.notify.assert_called_once_with(message, severity=severity)
        if restarts:
            resolve.assert_called_once_with()
            invalidate.assert_called_once_with()
        else:
            resolve.assert_not_called()
            invalidate.assert_not_called()


async def test_set_survives_missing_indicator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_records(monkeypatch, [make_project_record("beta")])
    outcome = _outcome(
        "set",
        project=_current_project("beta"),
        message="beta is now the current project.",
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        monkeypatch.setattr(pane, "notify", MagicMock())
        resolve = MagicMock()
        monkeypatch.setattr(pane, "_start_current_project_resolve", resolve)

        pane._apply_set_current_project_outcome(
            _FakeStateChanged(_FakeWorker(outcome), WorkerState.SUCCESS)
        )

        assert pane._status_message == "beta is now the current project."
        pane.notify.assert_called_once_with(
            "beta is now the current project.", severity="information"
        )
        resolve.assert_called_once_with()
        assert list(app.query(CurrentProjectIndicator)) == []


async def test_set_updates_row_summary_detail_and_invalidates_chip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    current = {"key": "alpha"}

    def fake_resolve(**_kwargs: object) -> CurrentProject:
        return _current_project(str(current["key"]))

    def fake_set(
        project_key: str, *, projects_dir: Path | None = None
    ) -> SetCurrentProjectOutcome:
        current["key"] = project_key
        project = _current_project(project_key)
        return _outcome(
            "set",
            project=project,
            message=f"{project_key} is now the current project.",
        )

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        fake_resolve,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.get_known_project_workspaces",
        lambda **_kwargs: {
            "alpha": Path("/tmp/alpha"),
            "beta": Path("/tmp/beta"),
        },
    )
    monkeypatch.setattr(actions_module, "set_current_project", fake_set)

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        await page.wait_for(lambda _s: pane._current_project_key == "alpha")

        indicator = page.query_one_widget(
            "#current-project-indicator", CurrentProjectIndicator
        )
        invalidate_calls: list[int] = []
        original_invalidate = indicator.invalidate

        def spy_invalidate() -> None:
            invalidate_calls.append(1)
            original_invalidate()

        monkeypatch.setattr(indicator, "invalidate", spy_invalidate)

        option_list = pane.query_one("#projects-list", OptionList)
        option_list.highlighted = 1
        pane.action_set_current_project()

        await page.wait_for(
            lambda _s: pane._status_message == "beta is now the current project."
        )
        await page.wait_for(lambda _s: pane._current_project_key == "beta")

        assert "current:+beta" in pane._summary_text().plain
        assert pane._record_label(pane._records[1]).plain[5:9] == "+   "
        assert pane._record_label(pane._records[0]).plain[5:9] == "    "
        detail = pane._detail_text(pane._records[1]).plain
        assert "+CURRENT" in detail
        assert "Current project: yes  ·  via #gh:beta" in detail
        assert invalidate_calls == [1]
