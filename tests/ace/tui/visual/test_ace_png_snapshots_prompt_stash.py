"""ACE TUI PNG visual snapshot coverage for the prompt-stash surfaces.

Phase 4 visual polish: pin how the two user-facing chrome pieces of the prompt
stash render — the top-bar ``StashedPromptsIndicator`` badge (snowflake glyph +
green-teal accent, shown only when a stash exists) and the ``StashedPromptsModal``
restore picker (newest-first rows with numbered keycap gutter, relative age,
originating-project chip, truncated preview, and the ``✓`` pop / ``📌`` pin /
``✗`` delete markers).

Relative ages are frozen via the shared row-renderer ``format_relative_time`` so
the rows are deterministic regardless of when the suite runs.
"""

from __future__ import annotations

import pytest

import sase.ace.tui.modals.prompt_stash_row as prompt_stash_row
from sase.ace.testing import AcePage
from sase.ace.tui.modals import StashedPromptsModal, UpdatePinnedStashModal
from sase.ace.tui.widgets import StashedPromptsIndicator
from sase.core.prompt_stash_wire import PromptStashEntryWire
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


# Frozen relative ages keyed by each fixture entry's ``created_at`` so the
# modal rows render identically on every run.
_FROZEN_AGES = {
    "2026-06-16T12:00:00": "2m ago",
    "2026-06-16T11:30:00": "1h ago",
    "2026-06-16T09:00:00": "5h ago",
    "2026-06-15T12:00:00": "1d ago",
    "2026-06-13T12:00:00": "3d ago",
}


def _frozen_age(iso_timestamp: str) -> str:
    return _FROZEN_AGES.get(iso_timestamp, "just now")


def _stash_entries() -> list[PromptStashEntryWire]:
    """Entries spanning every row state the picker can show.

    Newest-first display order is ``recent → cleanup → longpreview → noproj →
    multiline``; the snapshot marks ``recent`` for restore+pop, ``cleanup`` as
    pinned, and ``longpreview`` for deletion so the marker and pin columns, the
    project chips, the placeholder, and the preview-truncation path are all
    exercised in one frame.
    """
    return [
        PromptStashEntryWire(
            id="recent",
            created_at="2026-06-16T12:00:00",
            text=(
                "%m:opus %wait:planner\n\n"
                "# Review Checklist\n\n"
                "Run #review(scope=diff) and then %{ship | hold}.\n\n"
                "```python\n#literal %wait:no\n```"
            ),
            frontmatter="---\nxprompts:\n  helper: Use local rules\n---",
            project="sase",
            source="current",
        ),
        PromptStashEntryWire(
            id="cleanup",
            created_at="2026-06-16T11:30:00",
            text="Throwaway scratch prompt to delete",
            project="sase-core",
            source="current",
        ),
        PromptStashEntryWire(
            id="longpreview",
            created_at="2026-06-16T09:00:00",
            text=(
                "Draft the release notes for the prompt stash feature and link "
                "the before/after screenshots plus the migration checklist so "
                "the reviewer has everything in one place"
            ),
            project="sase-telegram",
            source="all",
            pane_index=0,
        ),
        PromptStashEntryWire(
            id="noproj",
            created_at="2026-06-15T12:00:00",
            text="Home-scoped prompt with no originating project",
            project=None,
            source="current",
        ),
        PromptStashEntryWire(
            id="multiline",
            created_at="2026-06-13T12:00:00",
            text="\n\nRefactor the missing-checkout failure path\nsecond line",
            project="sase-nvim",
            source="all",
            pane_index=1,
        ),
    ]


async def test_stashed_prompts_indicator_badge_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")

        # Drive the badge as if three prompts are stashed on disk so the
        # snowflake + count chrome renders in the top bar.
        indicator = page.app.query_one(
            "#stashed-prompts-indicator", StashedPromptsIndicator
        )
        indicator.set_count(3)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "stashed_prompts_indicator_badge_120x40",
            title="ACE stashed-prompts top-bar badge",
        )


async def test_stashed_prompts_restore_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(prompt_stash_row, "format_relative_time", _frozen_age)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)

        modal = StashedPromptsModal(_stash_entries())
        page.app.push_screen(modal)
        await page.expect_modal("StashedPromptsModal")

        # Mark one row for pop (✓), one as pinned (📌), and one for deletion
        # (✗) so the marker/pin columns render alongside the plain rows.
        modal._pop = {"recent"}
        modal._pinned = {"cleanup"}
        modal._deleted = {"longpreview"}
        modal._refresh_rows()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "stashed_prompts_restore_modal_120x40",
            title="ACE stashed-prompts panel",
        )


async def test_stashed_prompts_bundle_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(prompt_stash_row, "format_relative_time", _frozen_age)
    bundle = PromptStashEntryWire(
        id="bundle",
        created_at="2026-06-16T12:00:00",
        text=(
            "# First prompt\n\nRun #review:diff.\n"
            "---\n"
            "# Second prompt\n\nChoose %{ship | hold}."
        ),
        project="sase",
        source="all",
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        page.app.push_screen(
            StashedPromptsModal(
                [
                    bundle,
                    PromptStashEntryWire(
                        id="single",
                        created_at="2026-06-16T11:30:00",
                        text="A single prompt below the selected bundle",
                        project="sase-core",
                        source="current",
                    ),
                ]
            )
        )
        await page.expect_modal("StashedPromptsModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "stashed_prompts_bundle_preview_120x40",
            title="ACE stashed-prompts bundle preview",
        )


async def test_stashed_prompts_narrow_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(prompt_stash_row, "format_relative_time", _frozen_age)

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(100, 40)
    ) as page:
        await wait_for_startup(page)
        page.app.push_screen(StashedPromptsModal(_stash_entries()))
        await page.expect_modal("StashedPromptsModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "stashed_prompts_narrow_modal_100x40",
            title="ACE stashed-prompts narrow panel",
        )


async def test_update_pinned_stash_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(prompt_stash_row, "format_relative_time", _frozen_age)
    pinned_entries = [
        PromptStashEntryWire(
            **{
                **entry.__dict__,
                "pinned": True,
            }
        )
        for entry in _stash_entries()[:3]
    ]

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        page.app.push_screen(UpdatePinnedStashModal(pinned_entries))
        await page.expect_modal("UpdatePinnedStashModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "update_pinned_stash_preview_120x40",
            title="ACE update-pinned prompt preview",
        )
