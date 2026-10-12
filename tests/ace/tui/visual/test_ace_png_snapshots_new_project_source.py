"""PNG snapshots for the test-pushed New Project Source stage."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.widgets import OptionList, Static

from sase import workspace_provider
from sase.ace.testing import AcePage
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.ace.tui.modals.new_project_source import NewProjectSource
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.project_onboarding import CandidateInputs, OwnerResult, Preferences
from sase.workspace_provider import ParsedRepoRef, WorkflowMetadata
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
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
    assert "Remote" in detail
    assert "push allowed" in detail
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


async def test_new_project_source_loading_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Source stage clearly signals cache loading while preserving its shell."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_modal(page, modal)
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _empty_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_modal(page, modal)
        assert (
            "no owners" in modal.query_one("#new-project-health", Static).render().plain
        )
        ace_png_visual.assert_page_png(
            page,
            "new_project_source_empty_no_owners_120x40",
            title="New Project wizard — no owners",
        )


async def test_new_project_source_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The modal remains legible at a narrow terminal size."""
    patch_startup_loaders(monkeypatch)
    _patch_deterministic_source(monkeypatch)

    async with AcePage(query='"visual"', size=(84, 28), patches=patches()) as page:
        modal = NewProjectModal(
            provider_metadata=(_provider(),),
            candidate_inputs={"gh": _populated_inputs()},
            preferences=Preferences(last_provider="gh"),
        )
        await _open_modal(page, modal)
        await _select_suggested_source(page, modal)
        ace_png_visual.assert_page_png(
            page,
            "new_project_source_populated_84x28",
            title="New Project wizard — narrow Source stage",
        )
