"""Focused visual snapshots for the create Configure stage."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from textual.widgets import Input, Static

from sase import workspace_provider
from sase.ace.testing import AcePage
from sase.ace.tui.modals.new_project_create import NewProjectCreateConfigure
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.project_onboarding import Preferences
from sase.workspace_provider._hookspec import RepoCreationField, RepoCreationForm
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.visual.test_ace_png_snapshots_new_project_source import (
    _open_modal,
    _patch_deterministic_source,
    _populated_inputs,
    _provider,
)

pytestmark = pytest.mark.visual


def _create_form() -> RepoCreationForm:
    return RepoCreationForm(
        workflow_type="gh",
        namespace="sase-org",
        fields=(
            RepoCreationField(
                name="description",
                label="Description",
                kind="line",
                default="",
            ),
            RepoCreationField(
                name="readme", label="Add README", kind="bool", default="true"
            ),
            RepoCreationField(
                name="template",
                label="Template repository",
                kind="line",
                group="advanced",
                excludes=("readme",),
            ),
        ),
        can_create=True,
    )


def _patch_create_provider(
    monkeypatch: pytest.MonkeyPatch, *, probe_status: str
) -> None:
    def _probe_repo(workflow_type: str, ref: str) -> Any:
        return SimpleNamespace(
            status=probe_status,
            visibility="",
            is_empty=None,
            is_archived=None,
            can_push=None,
            sase_managed=None,
            repo_id="",
            default_branch="",
            message="",
            web_url="",
            error_kind=None,
        )

    monkeypatch.setattr(workspace_provider, "probe_repo", _probe_repo)
    monkeypatch.setattr(
        workspace_provider,
        "describe_repo_creation",
        lambda workflow_type, namespace: _create_form(),
    )


async def _open_create(
    page: AcePage,
    modal: NewProjectModal,
    raw_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> NewProjectCreateConfigure:
    """Open create Configure with the wall-clock debounce neutered.

    AcePage settle barriers do not advance wall-clock time, so the 0.3 s
    availability debounce can never elapse there. The debounce itself is
    covered by real-time interaction tests; snapshots drive the same
    off-thread check entry directly and wait for the settled stage.
    """
    monkeypatch.setattr(NewProjectCreateConfigure, "request_check", lambda self: None)
    await _open_modal(page, modal)
    modal.enter_create_configure(workflow_type="gh", owners=["sase-org"], account="")

    def _form_ready() -> bool:
        return modal._create_form_status == "ready"

    await wait_for_state(page, _form_ready, description="create form ready")
    modal.query_one("#new-project-create-name", Input).value = raw_name

    def _draft_caught_up() -> bool:
        draft = modal._state.create_draft
        return draft is not None and draft.raw_name == raw_name

    await wait_for_state(page, _draft_caught_up, description="create draft caught up")
    modal._schedule_create_check()

    def _settled() -> bool:
        availability = (
            modal.query_one("#new-project-create-availability", Static).render().plain
        )
        return "Checking" not in availability and bool(modal._create_plan)

    await wait_for_state(page, _settled, description="create check settled")
    await wait_for_visual_idle(page)
    return modal.query_one(NewProjectCreateConfigure)


async def test_new_project_create_configure_basics_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create Configure shows owner, name, options, and project preview."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_create_provider(monkeypatch, probe_status="not_found")
    monkeypatch.setattr(
        NewProjectModal, "_start_provider_load", lambda self, _type: None
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        widget = await _open_create(page, modal, "new", monkeypatch)
        assert "available" in modal._create_availability.reason
        assert widget._confirmable
        ace_png_visual.assert_page_png(
            page,
            "new_project_create_configure_basics_120x40",
            title="New Project wizard — create Configure basics",
        )


async def test_new_project_create_name_taken_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A taken remote name surfaces the explicit add-instead action."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_create_provider(monkeypatch, probe_status="found")
    monkeypatch.setattr(
        NewProjectModal, "_start_provider_load", lambda self, _type: None
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_create(page, modal, "taken", monkeypatch)
        assert modal._create_availability.status == "taken"
        assert modal.query_one("#new-project-create-add-instead").display
        ace_png_visual.assert_page_png(
            page,
            "new_project_create_name_taken_120x40",
            title="New Project wizard — create name taken",
        )


async def test_new_project_create_configure_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create Configure remains scrollable and legible at 80x24."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_create_provider(monkeypatch, probe_status="not_found")
    monkeypatch.setattr(
        NewProjectModal, "_start_provider_load", lambda self, _type: None
    )
    async with AcePage(query='"visual"', size=(80, 24), patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_create(page, modal, "new", monkeypatch)
        assert "available" in modal._create_availability.reason
        ace_png_visual.assert_page_png(
            page,
            "new_project_create_configure_basics_80x24",
            title="New Project wizard — create Configure narrow",
        )
