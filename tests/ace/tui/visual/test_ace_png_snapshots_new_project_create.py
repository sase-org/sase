"""Focused visual snapshots for the create Configure stage."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from textual.widgets import Button, Input, Static

from sase import workspace_provider
from sase.ace.testing import AcePage
from sase.ace.tui.modals.new_project_create import NewProjectCreateConfigure
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.ace.tui.modals.new_project_review import NewProjectReview
from sase.project_onboarding import Preferences
from sase.workspace_provider._hookspec import (
    ParsedRepoRef,
    RepoCreationField,
    RepoCreationForm,
    WorkflowMetadata,
)
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
    monkeypatch: pytest.MonkeyPatch,
    *,
    probe_status: str,
    form: RepoCreationForm | None = None,
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
        lambda workflow_type, namespace: form or _create_form(),
    )


async def _open_create(
    page: AcePage,
    modal: NewProjectModal,
    raw_name: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    workflow_type: str = "gh",
    owners: tuple[str, ...] = ("sase-org",),
) -> NewProjectCreateConfigure:
    """Open create Configure with the wall-clock debounce neutered.

    AcePage settle barriers do not advance wall-clock time, so the 0.3 s
    availability debounce can never elapse there. The debounce itself is
    covered by real-time interaction tests; snapshots drive the same
    off-thread check entry directly and wait for the settled stage.
    """
    monkeypatch.setattr(NewProjectCreateConfigure, "request_check", lambda self: None)
    await _open_modal(page, modal)
    modal.enter_create_configure(workflow_type=workflow_type, owners=owners, account="")

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


async def test_new_project_bare_git_create_and_review_hide_visibility_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare git's create and Review stages contain no visibility affordance."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    bare_form = RepoCreationForm(
        workflow_type="git",
        namespace="",
        fields=(
            RepoCreationField(
                name="bare_dir",
                label="Bare repository path",
                kind="line",
                group="advanced",
            ),
        ),
        can_create=True,
    )
    _patch_create_provider(monkeypatch, probe_status="not_found", form=bare_form)

    def parse_git(workflow_type: str, text: str) -> ParsedRepoRef | None:
        if workflow_type != "git":
            return None
        name = text.removeprefix("git:")
        if name != "tools":
            return None
        return ParsedRepoRef(
            workflow_type="git",
            ref="tools",
            identity_key="git:/home/visual/.sase/repos/tools.git",
            display="tools",
            name="tools",
            project_key_base="tools",
            project_name_base="tools",
            checkout_dir="~/projects/git/tools/",
        )

    monkeypatch.setattr(workspace_provider, "parse_repo_ref", parse_git)
    monkeypatch.setattr(
        NewProjectModal, "_start_provider_load", lambda self, _type: None
    )
    metadata = WorkflowMetadata(
        workflow_type="git",
        ref_pattern=r"^$",
        display_name="Bare git",
        pre_allocated_env_prefix="SASE_GIT",
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(metadata,),
            candidate_inputs={},
            preferences=Preferences(last_provider="git"),
        )
        widget = await _open_create(
            page,
            modal,
            "tools",
            monkeypatch,
            workflow_type="git",
            owners=(),
        )
        assert not widget.query_one("#new-project-create-visibility-row").display
        ace_png_visual.assert_page_png(
            page,
            "new_project_create_bare_git_120x40",
            title="New Project wizard — bare git create Configure",
        )

        modal._state.to_review()
        modal._show_stage("review")
        review = modal.query_one(NewProjectReview)
        review.show_document(modal._create_plan)
        await wait_for_visual_idle(page)
        heading = review.query_one("#new-project-review-card-heading", Static)
        confirm = review.query_one("#new-project-review-confirm", Button)
        assert heading.render().plain.strip() == "! CREATE tools"
        assert "PRIVATE" not in str(confirm.label)
        ace_png_visual.assert_page_png(
            page,
            "new_project_review_create_bare_git_120x40",
            title="New Project wizard — bare git Review create",
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


def _create_review_document(*, visibility: str) -> dict[str, Any]:
    vis = visibility
    warnings = (
        [{"message": "PUBLIC visibility is visible to everyone."}]
        if vis == "public"
        else []
    )
    return {
        "schema_version": 1,
        "kind": "project_onboarding_plan",
        "mode": "create",
        "status": "ready",
        "intent_fingerprint": "c" * 64,
        "provider": {"workflow_type": "gh", "display": "GitHub"},
        "target": {
            "ref": "sase-org/new",
            "display": "sase-org/new",
            "identity_key": "github.com/sase-org/new",
            "host": "github.com",
            "owner": "sase-org",
            "web_url": "https://github.com/sase-org/new",
            "visibility": vis,
            "checkout_dir": "~/projects/github/sase-org/new/",
        },
        "project": {
            "key": "gh_sase-org__new",
            "name": "new",
            "aliases": [],
            "accent": "#B9589C",
            "state": "enabled",
            "existing": False,
        },
        "creation": {
            "visibility": vis,
            "summary": ["GitHub repository"],
        },
        "setup": {
            "enabled": True,
            "code": "unmanaged_can_push",
            "reason": "Recommended: mark this checkout SASE-managed.",
        },
        "steps": [
            {
                "id": "checkout",
                "operation": "create",
                "label": "Clone and register",
                "detail": "~/projects/github/sase-org/new/",
                "state": "pending",
            }
        ],
        "warnings": warnings,
        "blockers": [],
        "apply_argv": [
            "sase",
            "project",
            "create",
            "sase-org/new",
            "--visibility",
            vis,
            "--yes",
            "--json",
        ],
    }


async def _open_create_review(
    page: AcePage,
    modal: NewProjectModal,
    monkeypatch: pytest.MonkeyPatch,
    *,
    visibility: str,
) -> NewProjectReview:
    await _open_create(page, modal, "new", monkeypatch)
    document = _create_review_document(visibility=visibility)
    monkeypatch.setattr(
        NewProjectReview,
        "start_check",
        lambda self, _document: self.show_document(document),
    )
    modal._state.to_review()
    modal._show_stage("review")
    review = modal.query_one(NewProjectReview)
    review.show_document(document)
    await wait_for_visual_idle(page)
    assert review.has_class("danger")
    heading = (
        review.query_one("#new-project-review-card-heading", Static).render().plain
    )
    assert "CREATE" in heading
    assert visibility.upper() in heading
    return review


async def test_new_project_review_create_private_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create Review uses DANGER styling and keeps the CREATE PRIVATE heading."""
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
        review = await _open_create_review(
            page, modal, monkeypatch, visibility="private"
        )
        assert (
            "keeps the created repository"
            in review.query_one("#new-project-review-state", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_review_create_private_120x40",
            title="New Project wizard — Review create private",
        )


async def test_new_project_review_create_public_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create Review highlights PUBLIC visibility on the DANGER heading."""
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
        review = await _open_create_review(
            page, modal, monkeypatch, visibility="public"
        )
        assert (
            "PUBLIC"
            in review.query_one("#new-project-review-warnings", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_review_create_public_120x40",
            title="New Project wizard — Review create public",
        )


async def test_new_project_review_create_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create Review keeps the DANGER heading visible at 80 by 24 cells."""
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
        review = await _open_create_review(
            page, modal, monkeypatch, visibility="private"
        )
        assert review.has_class("compact")
        heading = (
            review.query_one("#new-project-review-card-heading", Static).render().plain
        )
        assert "CREATE" in heading
        ace_png_visual.assert_page_png(
            page,
            "new_project_review_create_private_80x24",
            title="New Project wizard — narrow Review create private",
        )
