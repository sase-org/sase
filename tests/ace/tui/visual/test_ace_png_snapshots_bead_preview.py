"""sase's TUI PNG visual snapshots for the bead preview card."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.bead_preview_modal import BeadPreviewModal
from sase.ace.tui.models.bead_preview import BeadPreview, BeadStoreRef
from sase.bead.model import BeadNote, BeadTier, Issue, IssueType, Status
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    patches,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_CREATED = "2026-06-25T12:00:00+00:00"
_UPDATED = "2026-07-06T10:00:00+00:00"


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "bead_preview_card_epic_dark_120x40",
            "ACE bead preview card - epic with phases, dark theme",
        ),
        (
            "textual-light",
            "bead_preview_card_epic_light_120x40",
            "ACE bead preview card - epic with phases, light theme",
        ),
    ],
)
async def test_bead_preview_epic_card_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(
            BeadPreviewModal(
                _visual_store(),
                "bob-cli-kx",
                preview=_visual_epic_preview(),
            )
        )
        await page.expect_modal("BeadPreviewModal")
        await wait_for_svg_contains(page, "PHASES")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_bead_preview_phase_card_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.push_screen(
            BeadPreviewModal(
                _visual_store(),
                "bob-cli-kx.2",
                preview=_visual_phase_preview(),
            )
        )
        await page.expect_modal("BeadPreviewModal")
        await wait_for_svg_contains(page, "Blocked by")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "bead_preview_card_phase_dark_120x40",
            title="ACE bead preview card - phase with lineage and dependencies",
        )


async def test_bead_preview_loading_card_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(BeadPreviewModal, "_start_load", lambda self: None)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.push_screen(BeadPreviewModal(_visual_store(), "bob-cli-kx"))
        await page.expect_modal("BeadPreviewModal")
        await wait_for_svg_contains(page, "Loading")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "bead_preview_card_loading_dark_120x40",
            title="ACE bead preview card - loading state",
        )


async def test_bead_preview_long_epic_large_terminal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"',
        size=(200, 60),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        page.app.push_screen(
            BeadPreviewModal(
                _visual_store(),
                "bob-cli-kx",
                preview=_visual_long_epic_preview(),
            )
        )
        await page.expect_modal("BeadPreviewModal")
        await wait_for_svg_contains(page, "PHASES")
        await wait_for_svg_contains(page, "Fourteen: wrap-up and verification")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "bead_preview_card_long_epic_dark_200x60",
            title="ACE bead preview card - long epic on a large terminal",
        )


def _visual_store() -> BeadStoreRef:
    home = Path.home()
    return BeadStoreRef(
        project_key="bob-cli",
        project_label="bob-cli",
        beads_dir=home / "beads",
        primary_workspace=home,
    )


def _visual_epic_preview() -> BeadPreview:
    epic = _issue(
        id="bob-cli-kx",
        title="Gmail archive on task close",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        description=(
            "bob gmail sync archives a bob-labelled thread's saved messages exactly "
            "once when every linking Obsidian task is closed, visibly, undoably, "
            "and without a second archive of the same thread."
        ),
        created_at=_CREATED,
        updated_at=_UPDATED,
        notes=[
            BeadNote(
                id="n1",
                timestamp="2026-07-01T12:00:00+00:00",
                author="bryan",
                text="First note.",
            ),
            BeadNote(
                id="n2",
                timestamp="2026-07-04T12:00:00+00:00",
                author="bryan",
                text="Second note.",
            ),
            BeadNote(
                id="n3",
                timestamp=_UPDATED,
                author="bryan",
                text="Phase 5 is waiting on the gated live run.",
            ),
        ],
    )
    children = (
        _issue(
            id="bob-cli-kx.1",
            title="Mutation-path spike",
            issue_type=IssueType.PHASE,
            parent_id="bob-cli-kx",
            status=Status.CLOSED,
            size="small",
        ),
        _issue(
            id="bob-cli-kx.2",
            title="Archive-on-close machinery in bob-cli",
            issue_type=IssueType.PHASE,
            parent_id="bob-cli-kx",
            status=Status.CLOSED,
            size="medium",
        ),
        _issue(
            id="bob-cli-kx.3",
            title="Obsidian task close wiring",
            issue_type=IssueType.PHASE,
            parent_id="bob-cli-kx",
            status=Status.CLOSED,
            size="medium",
        ),
        _issue(
            id="bob-cli-kx.4",
            title="Undo and idempotency",
            issue_type=IssueType.PHASE,
            parent_id="bob-cli-kx",
            status=Status.CLOSED,
            size="small",
        ),
        _issue(
            id="bob-cli-kx.5",
            title="Gated live enable and verification",
            issue_type=IssueType.PHASE,
            parent_id="bob-cli-kx",
            status=Status.IN_PROGRESS,
            size="medium",
        ),
    )
    return BeadPreview(
        issue=epic,
        ancestors=(),
        children=children,
        depends_on=(),
        blocks=(),
        store=_visual_store(),
        plan_reference="gmail_archive_on_task_close.md",
        plan_source="self",
        plan_path=str(Path.home() / "plans/202611/gmail_archive_on_task_close.md"),
    )


def _visual_long_epic_preview() -> BeadPreview:
    epic = _issue(
        id="bob-cli-kx",
        title="Gmail archive on task close",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        description=(
            "bob gmail sync archives a bob-labelled thread's saved messages exactly "
            "once when every linking Obsidian task is closed, visibly, undoably, "
            "and without a second archive of the same thread.\n\n"
            "The large card must show the full phase list on a 200x60 terminal, "
            "keep the footer pinned, and draw a full-width separator above the "
            "property grid.\n\n"
            "A third paragraph keeps the body tall enough that the 1fr scroll "
            "region is doing real work even after the frame grows."
        ),
        created_at=_CREATED,
        updated_at=_UPDATED,
        notes=[
            BeadNote(
                id="n1",
                timestamp="2026-07-01T12:00:00+00:00",
                author="bryan",
                text="First note.",
            ),
            BeadNote(
                id="n2",
                timestamp="2026-07-04T12:00:00+00:00",
                author="bryan",
                text="Second note.",
            ),
            BeadNote(
                id="n3",
                timestamp=_UPDATED,
                author="bryan",
                text="Phase 5 is waiting on the gated live run.",
            ),
        ],
    )
    children = tuple(
        _issue(
            id=f"bob-cli-kx.{index}",
            title=title,
            issue_type=IssueType.PHASE,
            parent_id="bob-cli-kx",
            status=status,
            size=size,
        )
        for index, (title, status, size) in enumerate(
            (
                ("Mutation-path spike", Status.CLOSED, "small"),
                ("Archive-on-close machinery in bob-cli", Status.CLOSED, "medium"),
                ("Obsidian task close wiring", Status.CLOSED, "medium"),
                ("Undo and idempotency", Status.CLOSED, "small"),
                ("Gated live enable and verification", Status.IN_PROGRESS, "medium"),
                ("Docs and help-modal copy", Status.OPEN, "small"),
                ("Notification on archive", Status.OPEN, "medium"),
                ("Undo confirmation gate", Status.READY, "small"),
                ("Idempotent second close", Status.CLAIMED, "large"),
                ("Thread-label probe", Status.SNOOZED, "xsmall"),
                ("Vault path mapping", Status.OPEN, "medium"),
                ("Error toasts", Status.OPEN, "small"),
                ("Metrics and traces", Status.OPEN, "large"),
                ("Fourteen: wrap-up and verification", Status.OPEN, "xlarge"),
            ),
            start=1,
        )
    )
    return BeadPreview(
        issue=epic,
        ancestors=(),
        children=children,
        depends_on=(),
        blocks=(),
        store=_visual_store(),
        plan_reference="gmail_archive_on_task_close.md",
        plan_source="self",
        plan_path=str(Path.home() / "plans/202611/gmail_archive_on_task_close.md"),
    )


def _visual_phase_preview() -> BeadPreview:
    epic = _issue(
        id="bob-cli-kx",
        title="Gmail archive on task close",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    phase = _issue(
        id="bob-cli-kx.2",
        title="Archive-on-close machinery in bob-cli",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.PHASE,
        parent_id="bob-cli-kx",
        size="medium",
        description="Archive a bob-labelled thread exactly once on task close.",
        created_at=_CREATED,
        updated_at=_UPDATED,
    )
    blocker = _issue(
        id="bob-cli-kx.1",
        title="Mutation-path spike",
        status=Status.CLOSED,
        issue_type=IssueType.PHASE,
        parent_id="bob-cli-kx",
        size="small",
    )
    blocked = _issue(
        id="bob-cli-kx.5",
        title="Gated live enable and verification",
        status=Status.OPEN,
        issue_type=IssueType.PHASE,
        parent_id="bob-cli-kx",
        size="medium",
    )
    return BeadPreview(
        issue=phase,
        ancestors=(epic,),
        children=(),
        depends_on=(blocker,),
        blocks=(blocked,),
        store=_visual_store(),
        plan_reference="gmail_archive_on_task_close.md",
        plan_source="parent",
        plan_path=str(Path.home() / "plans/202611/gmail_archive_on_task_close.md"),
    )


def _issue(**overrides: object) -> Issue:
    values: dict[str, object] = {
        "id": "bob-cli-kx",
        "title": "Bead title",
        "status": Status.OPEN,
        "issue_type": IssueType.TASK,
        "description": "",
        "created_at": _CREATED,
        "updated_at": _UPDATED,
    }
    values.update(overrides)
    return Issue(**values)  # type: ignore[arg-type]
