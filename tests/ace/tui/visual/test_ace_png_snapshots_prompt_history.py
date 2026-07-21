"""ACE TUI PNG visual snapshot coverage for the prompt-history modal."""

from __future__ import annotations

import pytest

import sase.ace.tui.modals.prompt_history_modal as prompt_history_modal
import sase.history.prompt_metadata as prompt_metadata
import sase.xprompt._parsing as xprompt_parsing
from sase.ace.testing import AcePage
from sase.ace.tui.modals.prompt_history_modal import PromptHistoryModal
from sase.history.prompt_catalog import PromptHistoryPage, record_from_entry
from sase.history.prompt_store import PromptEntry
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


@pytest.fixture
def prompt_history_sources(monkeypatch: pytest.MonkeyPatch):
    """Patch prompt-history sources to deterministic visual fixtures."""
    monkeypatch.setattr(
        prompt_history_modal,
        "load_prompt_record_page",
        lambda **_kwargs: PromptHistoryPage(
            records=[record_from_entry(entry) for entry in _prompt_entries()],
            next_cursor=None,
            exhausted=True,
        ),
    )
    monkeypatch.setattr(
        "sase.workspace_provider.get_workflow_names",
        lambda: set(),
    )
    monkeypatch.setattr(
        "sase.workspace_provider._registry.get_workflow_names",
        lambda: set(),
    )
    _clear_prompt_metadata_caches()
    yield
    _clear_prompt_metadata_caches()


async def test_prompt_history_modal_redesign_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    prompt_history_sources: None,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        modal = PromptHistoryModal(show_cancelled=True)
        page.app.push_screen(modal)
        await page.expect_modal("PromptHistoryModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_history_modal_redesign_120x40",
            title="ACE prompt history modal redesign",
        )


def _prompt_entries() -> tuple[PromptEntry, ...]:
    return (
        _entry(
            "#gh:sase #fork %n Fix the parser bug so it handles edge cases in "
            "the prompt history table without shifting the preview column",
            last_used="260613_143000",
        ),
        _entry(
            "#git:home Refactor the workspace loader for clarity and make the "
            "failure state easier to scan during a long debugging session",
            last_used="260613_091500",
        ),
        _entry(
            "#gh:steveyegge/beads #research Investigate the failing CI on the "
            "beads branch and summarize the smallest reproducible case",
            last_used="260613_080200",
        ),
        _entry(
            "Quick note without any project tag at all here so the placeholder "
            "column and empty tag lane are visible",
            last_used="260613_074000",
        ),
        _entry(
            "%m:gpt-5 Try the experimental model on this one please, but keep "
            "the visible row focused on the cleaned prompt text",
            last_used="260612_221000",
        ),
        _entry(
            "#gh:sase #fork #research #cleanup #diagnose %n Audit the overflow "
            "tag rendering and make sure the compact suffix stays aligned",
            last_used="260612_191500",
        ),
        _entry(
            "#gh:sase %m Try the cancelled experiment again with a smaller "
            "prompt and keep it visually recessed",
            last_used="260612_184500",
            cancelled=True,
        ),
        _entry(
            "%n #gh:sase #fork",
            last_used="260612_173000",
        ),
    )


def _entry(
    text: str,
    *,
    last_used: str,
    cancelled: bool = False,
) -> PromptEntry:
    return PromptEntry(
        text=text,
        timestamp="260612_170000",
        last_used=last_used,
        cancelled=cancelled,
        branch_or_workspace="visual",
        workspace="sase",
    )


def _clear_prompt_metadata_caches() -> None:
    prompt_metadata._workflow_names.cache_clear()
    xprompt_parsing._VCS_TAG_PATTERN = None
    xprompt_parsing._VCS_TAG_EMBEDDED_PATTERN = None
