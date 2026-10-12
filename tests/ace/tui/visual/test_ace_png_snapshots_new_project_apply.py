"""PNG snapshots for New Project Progress, Ready, and Failed stages."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.new_project_failed import NewProjectFailed
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.ace.tui.modals.new_project_progress import NewProjectProgress
from sase.ace.tui.modals.new_project_progress_model import reduce_lines
from sase.ace.tui.modals.new_project_ready import NewProjectReady
from sase.project_onboarding import Preferences
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.visual.test_ace_png_snapshots_new_project_source import (
    _open_modal,
    _patch_deterministic_source,
    _patch_local_add_plan,
    _populated_inputs,
    _provider,
)

pytestmark = pytest.mark.visual


def _progress_view():
    return reduce_lines(
        [
            '{"event":"plan","plan":{"steps":['
            '{"id":"checkout","label":"Clone and register","state":"pending"},'
            '{"id":"manage","label":"Mark as SASE-managed","state":"pending"}]}}',
            '{"event":"step","id":"checkout","status":"running"}',
        ]
    )


def _failed_view():
    return reduce_lines(
        [
            '{"event":"plan","plan":{"steps":['
            '{"id":"checkout","label":"Clone and register","state":"pending"},'
            '{"id":"manage","label":"Mark as SASE-managed","state":"pending"}]}}',
            '{"event":"step","id":"checkout","status":"failed",'
            '"message":"Could not clone the repository",'
            '"hint":"The repository was kept. Re-run the same command to retry."}',
            '{"event":"result","status":"failed",'
            '"project":{"key":"gh_sase-org__new","name":"new"},'
            '"message":"Could not clone the repository"}',
        ]
    )


async def _open_apply_shell(
    page: AcePage,
    modal: NewProjectModal,
) -> None:
    await _open_modal(page, modal)
    modal._state.to_progress()
    modal._show_stage("progress")
    await wait_for_visual_idle(page)


async def test_new_project_progress_mid_run_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Progress shows one running step and one pending step."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_local_add_plan(monkeypatch, can_push=True)
    monkeypatch.setattr(
        NewProjectModal, "_start_provider_load", lambda self, _type: None
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_apply_shell(page, modal)
        progress = modal.query_one(NewProjectProgress)
        progress.show_preview(_progress_view(), running_glyph="⠋", elapsed="3s")
        await wait_for_visual_idle(page)
        assert (
            "Clone and register"
            in progress.query_one("#new-project-progress-checklist", Static)
            .render()
            .plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_progress_mid_run_120x40",
            title="New Project wizard — Progress mid-run",
        )


async def test_new_project_failed_kept_repo_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed keeps the checklist and the kept-repository hint."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_local_add_plan(monkeypatch, can_push=True)
    monkeypatch.setattr(
        NewProjectModal, "_start_provider_load", lambda self, _type: None
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_apply_shell(page, modal)
        modal._state.finish_failed()
        modal._show_stage("failed")
        failed = modal.query_one(NewProjectFailed)
        failed.show_failure(_failed_view(), message="Could not clone the repository")
        await wait_for_visual_idle(page)
        assert (
            "repository was kept"
            in failed.query_one("#new-project-failed-message", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_failed_kept_repo_120x40",
            title="New Project wizard — Failed with kept-repository hint",
        )


async def test_new_project_ready_accent_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ready paints the project name in the plan accent."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_local_add_plan(monkeypatch, can_push=True)
    monkeypatch.setattr(
        NewProjectModal, "_start_provider_load", lambda self, _type: None
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_apply_shell(page, modal)
        modal._ready_key = "gh_sase-org__new"
        modal._ready_name = "new"
        modal._needs_init = False
        modal._state.finish_ready()
        modal._show_stage("ready")
        ready = modal.query_one(NewProjectReady)
        ready.show_project(
            name="new",
            key="gh_sase-org__new",
            accent="#B9589C",
            needs_init=False,
        )
        modal._apply_ready_accent("#B9589C")
        await wait_for_visual_idle(page)
        assert (
            "new" in ready.query_one("#new-project-ready-name", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_ready_accent_120x40",
            title="New Project wizard — Ready in project accent",
        )


async def test_new_project_ready_not_initialized_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ready shows the amber not-initialized line when init was cancelled."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_local_add_plan(monkeypatch, can_push=True)
    monkeypatch.setattr(
        NewProjectModal, "_start_provider_load", lambda self, _type: None
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_apply_shell(page, modal)
        modal._ready_key = "gh_sase-org__new"
        modal._ready_name = "new"
        modal._needs_init = True
        modal._state.finish_ready()
        modal._show_stage("ready")
        ready = modal.query_one(NewProjectReady)
        ready.show_project(
            name="new",
            key="gh_sase-org__new",
            accent="#B9589C",
            needs_init=True,
        )
        modal._apply_ready_accent("#B9589C")
        await wait_for_visual_idle(page)
        assert (
            "Not initialized"
            in ready.query_one("#new-project-ready-init", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_ready_not_initialized_120x40",
            title="New Project wizard — Ready not initialized",
        )
