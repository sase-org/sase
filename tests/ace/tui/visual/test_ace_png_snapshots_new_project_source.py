"""PNG snapshots for the test-pushed New Project Source stage."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.widgets import OptionList, Static

from sase import workspace_provider
from sase.ace.testing import AcePage
from sase.ace.tui.modals.new_project_configure import NewProjectConfigure
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.ace.tui.modals.new_project_review import NewProjectReview
from sase.ace.tui.modals.new_project_source import NewProjectSource
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.project_onboarding import CandidateInputs, OwnerResult, Preferences
from sase.workspace_provider import ParsedRepoRef, WorkflowMetadata
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _provider() -> WorkflowMetadata:
    return WorkflowMetadata(
        workflow_type="gh",
        ref_pattern=r"^$",
        display_name="GitHub",
        pre_allocated_env_prefix="SASE_GH",
    )


def _parsed(workflow_type: str, ref: str) -> ParsedRepoRef:
    owner, name = ref.split("/", 1)
    return ParsedRepoRef(
        workflow_type=workflow_type,
        ref=ref,
        identity_key=f"github.com/{ref}".casefold(),
        display=ref,
        host="github.com",
        owner=owner,
        name=name,
        project_key_base=f"gh_{owner}__{name}",
        project_name_base=name,
        checkout_dir=f"~/projects/github/{owner}/{name}/",
    )


def _populated_inputs() -> CandidateInputs:
    return CandidateInputs(
        workflow_type="gh",
        display="GitHub",
        account="bbugyi200",
        owners=[OwnerResult(name="sase-org")],
        remote=[
            {
                "identity_key": "github.com/sase-org/new",
                "ref": "sase-org/new",
                "display": "sase-org/new",
                "owner": "sase-org",
                "name": "new",
                "description": "A suggested repository",
                "visibility": "public",
                "pushed_at": "2026-10-11T14:00:00Z",
                "is_fork": False,
            },
            {
                "identity_key": "github.com/sase-org/fork",
                "ref": "sase-org/fork",
                "display": "sase-org/fork",
                "owner": "sase-org",
                "name": "fork",
                "description": "",
                "visibility": "public",
                "is_fork": True,
            },
            {
                "identity_key": "github.com/sase-org/already-added",
                "ref": "sase-org/already-added",
                "display": "sase-org/already-added",
                "owner": "sase-org",
                "name": "already-added",
                "description": "Already registered",
                "visibility": "private",
                "is_fork": False,
            },
        ],
        local=[
            {
                "identity_key": "github.com/sase-org/clone",
                "ref": "sase-org/clone",
                "display": "sase-org/clone",
                "owner": "sase-org",
                "name": "clone",
                "path": "/tmp/clone",
                "numbered_copy": False,
            }
        ],
        projects=[
            {
                "key": "old-project",
                "name": "old-project",
                "aliases": [],
                "state": "disabled",
                "identity_keys": [],
            },
            {
                "key": "existing-project",
                "name": "existing-project",
                "aliases": [],
                "state": "enabled",
                "identity_keys": ["github.com/sase-org/already-added"],
            },
        ],
        inventory=[
            {
                "identity_key": "github.com/sase-org/sase--plans",
                "kind": "sidecar",
                "project_key": "sase",
            }
        ],
        journals=[
            {
                "identity_key": "github.com/sase-org/forge",
                "ref": "sase-org/forge",
                "display": "sase-org/forge",
                "status": "failed",
                "stopped_at": "2026-10-11T14:00:00Z",
            }
        ],
        owned_namespaces=["sase-org", "bbugyi200"],
        sidecar_roles=["plans", "beads", "agents", "attachments", "research", "sdd"],
    )


def _owner_error_inputs() -> CandidateInputs:
    return CandidateInputs(
        workflow_type="gh",
        display="GitHub",
        account="bbugyi200",
        owners=[
            OwnerResult(
                name="sase-org",
                status="error",
                error_kind="auth",
                message="GitHub authentication expired",
                remedy_argv=["gh", "auth", "login"],
            )
        ],
        owned_namespaces=["sase-org"],
    )


def _empty_inputs() -> CandidateInputs:
    return CandidateInputs(workflow_type="gh", display="GitHub", account="")


async def _open_modal(page: AcePage, modal: NewProjectModal) -> None:
    await wait_for_startup(page)
    await page.press(page.artifacts_digit("patches"))
    await page.expect_state("artifacts_subtab", "patches")
    page.app.push_screen(modal)
    await page.expect_modal("NewProjectModal")
    await wait_for_visual_idle(page)
    assert modal.query_one("#new-project-health", Static).region.width > 0


async def _wait_for_create_row(page: AcePage, modal: NewProjectModal) -> None:
    """Wait until create-support discovery pins the Source Create row."""
    source = modal.query_one(NewProjectSource)

    def _pinned() -> bool:
        return source.create_row is not None

    await wait_for_state(page, _pinned, description="Create row pinned")
    await wait_for_visual_idle(page)


async def _select_suggested_source(page: AcePage, modal: NewProjectModal) -> None:
    source = modal.query_one(NewProjectSource)
    row = next(row for row in source._rows.values() if row.group == "suggested")
    options = source.query_one(OptionList)
    for index in range(options.option_count):
        if options.get_option_at_index(index).id == row.row_id:
            options.highlighted = index
            break
    source._probe_cache[("gh", row.ref)] = SimpleNamespace(
        visibility="public",
        default_branch="main",
        sase_managed=False,
        can_push=True,
        message="",
    )
    source._select_detail(row, schedule_probe=False)
    detail = modal.query_one("#new-project-source-detail", Static).render().plain
    if "\n" in detail:
        assert "Remote" in detail
        assert "push allowed" in detail
    else:
        # Short terminals collapse the card to one summary line.
        assert row.display in detail
    await wait_for_visual_idle(page)


def _patch_deterministic_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: (
            _parsed(workflow_type, text) if "/" in text else None
        ),
    )
    monkeypatch.setattr(DetailPanelDebouncer, "schedule", lambda self, callback: None)


def _patch_create_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the Source Create row: provider form discovery finds a form."""
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: object()
    )


def _patch_create_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave the add-only Source list: provider form discovery finds nothing."""
    monkeypatch.setattr(
        workspace_provider, "describe_repo_creation", lambda _wt, _ns: None
    )


async def test_new_project_source_loading_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Source stage clearly signals cache loading while preserving its shell."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_create_unsupported(monkeypatch)
    monkeypatch.setattr(
        NewProjectModal, "_start_provider_load", lambda self, _type: None
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            preferences=Preferences(last_provider="gh"),
        )
        await _open_modal(page, modal)
        assert (
            "loading cached candidates"
            in modal.query_one("#new-project-health", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_source_loading_120x40",
            title="New Project wizard — loading Source candidates",
        )


async def test_new_project_source_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Source stage shows candidate groups, hidden counts, and a live detail card."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_create_supported(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_modal(page, modal)
        await _wait_for_create_row(page, modal)
        await _select_suggested_source(page, modal)
        assert (
            "bbugyi200" in modal.query_one("#new-project-health", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_source_populated_120x40",
            title="New Project wizard — populated Source candidates",
        )


async def test_new_project_source_owner_error_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An owner failure remains visible with its recovery action."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_create_unsupported(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _owner_error_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_modal(page, modal)
        assert (
            "owner issue"
            in modal.query_one("#new-project-health", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_source_owner_error_120x40",
            title="New Project wizard — owner error",
        )


async def test_new_project_source_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The empty state explains that a repository can be pasted without owners."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_create_supported(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _empty_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_modal(page, modal)
        await _wait_for_create_row(page, modal)
        assert (
            "no owners" in modal.query_one("#new-project-health", Static).render().plain
        )
        detail = modal.query_one("#new-project-source-detail", Static).render().plain
        assert "No GitHub owners yet" in detail
        assert "github_orgs" in detail
        ace_png_visual.assert_page_png(
            page,
            "new_project_source_empty_no_owners_120x40",
            title="New Project wizard — no owners",
        )


async def test_new_project_source_compact_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At 80x24 the detail card collapses to one summary line."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_create_supported(monkeypatch)

    async with AcePage(query='"visual"', size=(80, 24), patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_modal(page, modal)
        await _wait_for_create_row(page, modal)
        source = modal.query_one(NewProjectSource)
        row = next(row for row in source._rows.values() if row.group == "suggested")
        options = source.query_one(OptionList)
        for index in range(options.option_count):
            if options.get_option_at_index(index).id == row.row_id:
                options.highlighted = index
                break
        source._probe_cache[("gh", row.ref)] = SimpleNamespace(
            visibility="public",
            default_branch="main",
            sase_managed=False,
            can_push=True,
            message="",
        )
        source._select_detail(row, schedule_probe=False)
        detail = modal.query_one("#new-project-source-detail", Static).render().plain
        assert "\n" not in detail
        assert "○ will be set up" in detail
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "new_project_source_populated_80x24",
            title="New Project wizard — compact Source stage",
        )


async def test_new_project_source_create_compact_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At 80x24 the highlighted Create card also collapses to one line."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_create_supported(monkeypatch)

    async with AcePage(query='"visual"', size=(80, 24), patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_modal(page, modal)
        await _wait_for_create_row(page, modal)
        source = modal.query_one(NewProjectSource)
        row = next(row for row in source._rows.values() if row.group == "create")
        options = source.query_one(OptionList)
        for index in range(options.option_count):
            if options.get_option_at_index(index).id == row.row_id:
                options.highlighted = index
                break
        source._select_detail(row, schedule_probe=False)
        detail = modal.query_one("#new-project-source-detail", Static).render().plain
        assert "\n" not in detail
        assert "Create a new GitHub repository" in detail
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "new_project_source_create_80x24",
            title="New Project wizard — compact Source Create row",
        )


def _configure_document(*, can_push: bool) -> dict[str, object]:
    setup_enabled = can_push
    return {
        "schema_version": 1,
        "kind": "project_onboarding_plan",
        "mode": "add",
        "status": "ready",
        "intent_fingerprint": "a" * 64,
        "provider": {"workflow_type": "gh", "display": "GitHub"},
        "target": {
            "ref": "sase-org/new",
            "display": "sase-org/new",
            "identity_key": "github.com/sase-org/new",
            "checkout_dir": "~/projects/github/sase-org/new/",
            "can_push": can_push,
            "sase_managed": False,
            "visibility": "public",
        },
        "project": {
            "key": "gh_sase-org__new",
            "name": "new",
            "aliases": [],
            "accent": "#B9589C",
            "state": "enabled",
            "existing": False,
        },
        "setup": {
            "enabled": setup_enabled,
            "code": "unmanaged_can_push" if can_push else "no_push",
            "reason": (
                "Recommended: mark this checkout SASE-managed."
                if can_push
                else "No push rights. Use `sase init -M` in a terminal."
            ),
        },
        "steps": [
            {
                "id": "checkout",
                "operation": "create",
                "label": "Clone and register",
                "detail": "~/projects/github/sase-org/new/",
                "state": "pending",
            },
            {
                "id": "manage",
                "operation": "create",
                "label": "Mark the repository as SASE-managed",
                "detail": "Commit and push sase/sase.yml is_sase_managed",
                "state": "pending",
            },
            {
                "id": "init",
                "operation": "validate",
                "label": "Initialize SASE",
                "detail": "Review sidecar setup on first launch",
                "state": "pending",
            },
        ],
        "warnings": [],
        "blockers": [],
        "apply_argv": [
            "sase",
            "project",
            "add",
            "sase-org/new",
            "--name",
            "new",
            "--yes",
            "--json",
        ],
        "next_argv": ["sase", "init", "-p", "gh_sase-org__new"],
    }


def _patch_local_add_plan(monkeypatch: pytest.MonkeyPatch, *, can_push: bool) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_configure_flow.plan_configure_display",
        lambda _target, _draft, _facts: _configure_document(can_push=can_push),
    )


async def _open_configure_for_visual(
    page: AcePage,
    modal: NewProjectModal,
) -> None:
    await _open_modal(page, modal)
    await _select_suggested_source(page, modal)
    modal.query_one(NewProjectSource).choose_highlighted()
    await wait_for_visual_idle(page)
    assert modal.query_one(NewProjectConfigure).is_mounted


async def test_new_project_configure_recommended_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configure shows the recommended setup and planner-derived project identity."""
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
        await _open_configure_for_visual(page, modal)
        assert (
            "Identity  UNIQUE"
            in modal.query_one("#new-project-configure-identity", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_configure_recommended_120x40",
            title="New Project wizard — Configure with recommended setup",
        )


async def test_new_project_configure_no_push_amber_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configure leaves setup off and calls out the human-only no-push follow-up."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_local_add_plan(monkeypatch, can_push=False)
    monkeypatch.setattr(
        NewProjectModal, "_start_provider_load", lambda self, _type: None
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_configure_for_visual(page, modal)
        assert (
            "sase init -M"
            in modal.query_one("#new-project-configure-setup-reason", Static)
            .render()
            .plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_configure_no_push_amber_120x40",
            title="New Project wizard — Configure without push rights",
        )


async def _open_review_for_visual(
    page: AcePage,
    modal: NewProjectModal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _open_configure_for_visual(page, modal)
    review_doc = _configure_document(can_push=True)
    review_doc["warnings"] = [{"message": "PUBLIC visibility is visible to everyone."}]
    monkeypatch.setattr(
        NewProjectReview,
        "start_check",
        lambda self, _document: self.show_document(review_doc),
    )
    modal._enter_review()
    await wait_for_visual_idle(page)
    assert modal.query_one(NewProjectReview).is_mounted


async def test_new_project_review_add_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review shows the exact add argv, operation rows, and public warning."""
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
        await _open_review_for_visual(page, modal, monkeypatch)
        assert (
            "$ sase project add"
            in modal.query_one("#new-project-review-argv", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_review_add_120x40",
            title="New Project wizard — Review add plan",
        )


async def test_new_project_review_add_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review remains usable at 80 by 24 cells."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
    _patch_local_add_plan(monkeypatch, can_push=True)
    monkeypatch.setattr(
        NewProjectModal, "_start_provider_load", lambda self, _type: None
    )
    async with AcePage(query='"visual"', size=(80, 24), patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_review_for_visual(page, modal, monkeypatch)
        review = modal.query_one(NewProjectReview)
        assert (
            "PUBLIC visibility"
            in review.query_one("#new-project-review-warnings", Static).render().plain
        )
        assert (
            "$ sase project add"
            in review.query_one("#new-project-review-argv", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_review_add_80x24",
            title="New Project wizard — narrow Review add plan",
        )
