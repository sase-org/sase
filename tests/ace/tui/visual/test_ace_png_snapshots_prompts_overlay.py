"""sase's TUI PNG visual snapshot coverage for the Prompts overlay Stash/Trash tabs.

The overlay cutover retired the standalone ``StashedPromptsModal`` surface; these
cases pin the production ``PromptsModal`` with populated Stash and Trash at wide
and narrow widths, including tab counts, list/preview layout, footer verbs, and
the empty-Trash state.
"""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

import sase.ace.tui.modals.prompt_stash_row as prompt_stash_row
from sase.ace.testing import AcePage
from sase.ace.tui.modals.prompts_modal import (
    PromptsModal,
    PromptsOrigin,
    PromptsTab,
)
from sase.core.prompt_stash_wire import (
    PromptStashEntryWire,
    PromptStashTrashRecordWire,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


# Frozen relative ages keyed by each fixture entry's ``created_at``/``trashed_at``
# so stash and trash rows render identically on every run.
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
    """Populated Stash rows spanning chips, pins, and preview truncation."""
    return [
        PromptStashEntryWire(
            id="recent",
            created_at="2026-06-16T12:00:00",
            text=(
                "%m:opus %wait:planner\n\n"
                "# Review Checklist\n\n"
                "Run #review(scope=diff) and then %{ship | hold}."
            ),
            project="sase",
            source="current",
        ),
        PromptStashEntryWire(
            id="cleanup",
            created_at="2026-06-16T11:30:00",
            text="Throwaway scratch prompt to delete",
            project="sase-core",
            source="current",
            pinned=True,
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


def _trash_records() -> list[PromptStashTrashRecordWire]:
    """Populated Trash rows with distinct previews and deletion ages."""
    return [
        PromptStashTrashRecordWire(
            trashed_at="2026-06-16T12:00:00",
            entry=PromptStashEntryWire(
                id="t-recent",
                created_at="2026-06-16T09:00:00",
                text="Discarded release notes draft with screenshots",
                project="sase",
                source="current",
            ),
        ),
        PromptStashTrashRecordWire(
            trashed_at="2026-06-16T11:30:00",
            entry=PromptStashEntryWire(
                id="t-mid",
                created_at="2026-06-15T12:00:00",
                text="Old debugging scratch prompt, no project",
                project=None,
                source="current",
            ),
        ),
        PromptStashTrashRecordWire(
            trashed_at="2026-06-16T09:00:00",
            entry=PromptStashEntryWire(
                id="t-old",
                created_at="2026-06-13T12:00:00",
                text="Stale migration checklist from last week",
                project="sase-core",
                source="all",
                pane_index=1,
            ),
        ),
    ]


def _refuse_history_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any history disk read: Stash/Trash tabs must not trigger one."""

    def _refuse_catalog() -> object:
        raise AssertionError("history catalog must not load before activation")

    def _refuse_page(**kwargs: object) -> object:
        raise AssertionError("history pages must not load before activation")

    monkeypatch.setattr(
        "sase.history.prompt_history_project_filter.PromptHistoryProjectCatalog.load",
        staticmethod(_refuse_catalog),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.history_pane.load_prompt_record_page",
        _refuse_page,
    )


async def _wait_for_overlay_list(
    page: AcePage,
    *,
    list_id: str,
    option_count: int,
    sentinel: str,
) -> None:
    await wait_for_svg_contains(page, sentinel)
    option_list = page.app.screen.query_one(list_id, OptionList)
    await wait_for_state(
        page,
        lambda: option_list.has_focus and option_list.option_count == option_count,
        description=f"{list_id} focus and {option_count} rendered rows",
    )
    await wait_for_visual_idle(page)


async def _open_overlay(
    page: AcePage,
    *,
    initial_tab: PromptsTab,
    trash: list[PromptStashTrashRecordWire] | None = None,
    trash_limit: int = 20,
) -> None:
    page.app.push_screen(
        PromptsModal(
            _stash_entries(),
            origin=PromptsOrigin(),
            initial_tab=initial_tab,
            trash=trash if trash is not None else _trash_records(),
            trash_limit=trash_limit,
        )
    )
    await page.expect_modal("PromptsModal")


async def test_prompts_overlay_stash_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(prompt_stash_row, "format_relative_time", _frozen_age)
    _refuse_history_io(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await _open_overlay(page, initial_tab=PromptsTab.STASH)
        await _wait_for_overlay_list(
            page,
            list_id="#stashed-prompts-list",
            option_count=5,
            sentinel="Stash 5",
        )

        ace_png_visual.assert_page_png(
            page,
            "prompts_overlay_stash_120x40",
            title="ACE Prompts overlay Stash tab",
        )


async def test_prompts_overlay_trash_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(prompt_stash_row, "format_relative_time", _frozen_age)
    _refuse_history_io(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await _open_overlay(page, initial_tab=PromptsTab.TRASH)
        await _wait_for_overlay_list(
            page,
            list_id="#trash-list",
            option_count=3,
            sentinel="screenshots",
        )

        ace_png_visual.assert_page_png(
            page,
            "prompts_overlay_trash_120x40",
            title="ACE Prompts overlay Trash tab",
        )


async def test_prompts_overlay_stash_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(prompt_stash_row, "format_relative_time", _frozen_age)
    _refuse_history_io(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(100, 40)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await _open_overlay(page, initial_tab=PromptsTab.STASH)
        await _wait_for_overlay_list(
            page,
            list_id="#stashed-prompts-list",
            option_count=5,
            sentinel="Stash 5",
        )

        ace_png_visual.assert_page_png(
            page,
            "prompts_overlay_stash_narrow_100x40",
            title="ACE Prompts overlay Stash tab narrow",
        )


async def test_prompts_overlay_trash_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(prompt_stash_row, "format_relative_time", _frozen_age)
    _refuse_history_io(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await _open_overlay(page, initial_tab=PromptsTab.TRASH, trash=[])
        await wait_for_svg_contains(page, "Discarded drafts appear here")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompts_overlay_trash_empty_120x40",
            title="ACE Prompts overlay empty Trash tab",
        )
