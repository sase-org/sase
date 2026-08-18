"""Current-project seeding and display for the Projects tab."""

from __future__ import annotations

from pathlib import Path
import threading

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import (
    AdminCenterSessionState,
    ProjectsSessionState,
)
from sase.ace.tui.modals.project_inventory_panes import (
    RepoInventoryPane,
    WorkspaceInventoryPane,
)
from sase.ace.tui.modals.projects_pane import (
    ProjectsPane,
    _resolve_current_project_snapshot,
)
from sase.ace.tui.project_styles import project_accent
from sase.current_project import CurrentProject

from tests.ace.tui.modals.project_management_modal_test_helpers import (
    make_project_record,
)
from tests.ace.tui.test_projects_pane import _patch_panes

_ACCENT = "#C5547D"


def _current_project(
    project_key: str,
    *,
    display_name: str | None = None,
    origin: str = "project",
    origin_ref: str | None = None,
) -> CurrentProject:
    return CurrentProject(
        project_key=project_key,
        display_name=display_name or project_key,
        origin=origin,  # type: ignore[arg-type]
        origin_ref=origin_ref or project_key,
        workflow_type="gh",
    )


async def test_seeds_inventory_filters_from_current_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda: _current_project("alpha"),
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        repo_pane = pane.query_one(RepoInventoryPane)
        workspace_pane = pane.query_one(WorkspaceInventoryPane)

        await page.wait_for(lambda _s: repo_pane.project_filter == "alpha")
        assert workspace_pane.project_filter == "alpha"
        assert pane._session_state.project_filter_seeded is True


async def test_seeded_session_state_is_not_reapplied_on_remount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    resolve_calls: list[int] = []

    def fake_resolve() -> CurrentProject | None:
        resolve_calls.append(1)
        return _current_project("alpha")

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project", fake_resolve
    )
    state = AdminCenterSessionState()

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects", session_state=state)
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        repo_pane = pane.query_one(RepoInventoryPane)
        await page.wait_for(lambda _s: repo_pane.project_filter == "alpha")

        # The user escapes the seeded filter, then closes Admin Center.
        pane._switch_to_subtab("repos")
        await page.press("escape")
        assert repo_pane.project_filter is None
        assert state.projects.repos_project_filter is None
        assert len(resolve_calls) == 1

        page.app.pop_screen()
        await page.pause()

        # Reopening Admin Center mounts a fresh ProjectsPane bound to the
        # same session state; the escaped filter must not be reseeded.
        modal2 = ConfigCenterModal(initial_tab="projects", session_state=state)
        page.app.push_screen(modal2)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal2.query("#projects")))
        pane2 = modal2.query_one("#projects", ProjectsPane)
        repo_pane2 = pane2.query_one(RepoInventoryPane)
        await page.pause()
        assert repo_pane2.project_filter is None
        assert len(resolve_calls) == 2


async def test_resolves_current_project_for_display_when_seeding_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda: _current_project("alpha"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.get_known_project_workspaces",
        lambda **_kwargs: {"alpha": Path("/tmp/alpha")},
    )

    async with AcePage() as page:
        page.app._current_project_settings = CurrentProjectSettings(seed_filters=False)
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        repo_pane = pane.query_one(RepoInventoryPane)

        await page.wait_for(lambda _s: pane._current_project_key == "alpha")
        assert repo_pane.project_filter is None
        assert pane._session_state.project_filter_seeded is True
        assert "current:+alpha" in pane._summary_text().plain
        assert pane._record_label(pane._records[0]).plain[5:9] == "+   "


async def test_display_marks_row_summary_and_detail_after_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda: _current_project("alpha"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.get_known_project_workspaces",
        lambda **_kwargs: {"alpha": Path("/tmp/alpha"), "beta": Path("/tmp/beta")},
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        await page.wait_for(lambda _s: pane._current_project_key == "alpha")

        accent = project_accent("alpha", among=("alpha", "beta"))
        assert pane._current_project_key == "alpha"
        assert pane._current_project_accent == accent
        assert "current:+alpha" in pane._summary_text().plain
        assert pane._record_label(pane._records[0]).plain[5:9] == "+   "
        assert pane._record_label(pane._records[1]).plain[5:9] == "    "
        detail = pane._detail_text(pane._records[0]).plain
        assert "+CURRENT" in detail
        assert "Current project: yes  ·  via #gh:alpha" in detail
        other = pane._detail_text(pane._records[1]).plain
        assert "press c to make beta current" in other


async def test_summary_renders_when_current_project_is_not_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda: _current_project("ghost"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.get_known_project_workspaces",
        lambda **_kwargs: {"ghost": Path("/tmp/ghost")},
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        await page.wait_for(lambda _s: pane._current_project_key == "ghost")

        assert "current:+ghost" in pane._summary_text().plain
        assert all(
            pane._record_label(record).plain[5:9] == "    " for record in pane._records
        )
        assert pane.query_one(RepoInventoryPane).project_filter is None


async def test_session_state_paints_cached_current_project_on_reopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    release = threading.Event()

    def fake_resolve() -> CurrentProject:
        release.wait(timeout=5)
        return _current_project("beta", display_name="beta")

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        fake_resolve,
    )
    state = AdminCenterSessionState()
    state.projects.current_project_key = "alpha"
    state.projects.current_project_name = "alpha"
    state.projects.current_project_accent = _ACCENT
    state.projects.project_filter_seeded = True

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects", session_state=state)
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)

        assert pane._current_project_loaded is True
        assert pane._current_project_key == "alpha"
        assert "current:+alpha" in pane._summary_text().plain
        assert pane._record_label(pane._records[0]).plain[5:9] == "+   "

        release.set()
        await page.wait_for(lambda _s: pane._current_project_key == "beta")
        assert state.projects.current_project_key == "beta"
        assert state.projects.current_project_name == "beta"
        assert "current:+beta" in pane._summary_text().plain


def test_unmounted_pane_shows_dim_current_ellipsis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [make_project_record("alpha")],
    )
    pane = ProjectsPane(projects_root=tmp_path)

    assert pane._current_project_loaded is False
    assert "current:…" in pane._summary_text().plain


def test_unmounted_pane_seeds_display_from_session_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [make_project_record("alpha")],
    )
    session = ProjectsSessionState(
        current_project_key="alpha",
        current_project_name="alpha",
        current_project_accent=_ACCENT,
    )
    pane = ProjectsPane(projects_root=tmp_path, session_state=session)

    assert pane._current_project_loaded is True
    assert "current:+alpha" in pane._summary_text().plain
    assert pane._record_label(pane._records[0]).plain[5:9] == "+   "


def test_resolve_snapshot_computes_accent_off_the_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _current_project("alpha")
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda **_kwargs: project,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.get_known_project_workspaces",
        lambda **_kwargs: {"alpha": Path("/tmp/alpha")},
    )

    snapshot = _resolve_current_project_snapshot()

    assert snapshot.project is project
    assert snapshot.accent == project_accent("alpha", among=("alpha",))


def test_resolve_snapshot_degrades_to_unknown_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**_kwargs: object) -> CurrentProject | None:
        raise RuntimeError("disk")

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        boom,
    )

    snapshot = _resolve_current_project_snapshot()

    assert snapshot.project is None
    assert snapshot.accent == ""


async def test_reload_reruns_current_project_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    resolve_calls: list[int] = []

    def fake_resolve() -> CurrentProject:
        resolve_calls.append(1)
        return _current_project("alpha")

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        fake_resolve,
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        await page.wait_for(lambda _s: pane._current_project_key == "alpha")
        assert len(resolve_calls) == 1

        pane.action_reload_projects()
        await page.wait_for(lambda _s: len(resolve_calls) == 2)
        option_list = pane.query_one("#projects-list", OptionList)
        assert option_list.option_count == 2
