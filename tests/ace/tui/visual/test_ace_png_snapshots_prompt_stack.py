"""ACE TUI PNG visual snapshot coverage for the multi-agent prompt stack.

Phase 6 visual polish: pin how ``PromptInputBar`` renders a stacked, multi-agent
prompt in context — the accent-bordered active pane, the dimmer compacted
inactive panes, the quiet ``agent N`` separator rows, and the completion panel
scoped to the active pane. The bar is mounted directly over the ChangeSpecs tab
(``dock: bottom``) so the full ``styles.tcss`` styling applies exactly as it does
at runtime.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03

_TWO_PANE_PROMPT = (
    "Investigate the failing CI on the beads branch and\n"
    "summarize the smallest reproducible case for the team"
    "\n---\n"
    "Refactor the workspace loader for clarity and harden\n"
    "the missing-checkout failure path so it is easy to scan"
)

# The two upper panes carry more than ``_INACTIVE_PANE_MAX_ROWS`` lines so the
# inactive-pane cap visibly truncates them while the active bottom pane keeps
# its full body — the point of this snapshot.
_COMPACT_PROMPT = (
    "Audit the overflow tag rendering across the table\n"
    "and keep the compact suffix aligned in every lane\n"
    "so nothing shifts when a long project tag wraps\n"
    "and the preview column stays put under pressure\n"
    "with one more line to push past the compact cap\n"
    "and a final line that should be clipped away"
    "\n---\n"
    "Refactor the workspace loader for clarity\n"
    "and make the missing-checkout failure easy to scan\n"
    "during a long debugging session on a slow host\n"
    "with extra context lines for the reviewer\n"
    "and yet another line beyond the compact cap\n"
    "and a trailing line that should be clipped"
    "\n---\n"
    "Draft the release notes for the prompt stack feature\n"
    "and link the before/after screenshots"
)


async def _mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    """Mount a prompt bar over the running app and wait for it to settle."""
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_visual_idle(page)
    return bar


async def test_prompt_stack_two_panes_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await _mount_prompt_bar(page, _TWO_PANE_PROMPT)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_two_panes_120x40",
            title="ACE prompt stack — active lower pane",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_prompt_stack_active_upper_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _TWO_PANE_PROMPT)

        # Focus the top pane so the accent border moves up and the bottom pane
        # dims — the mirror image of the default active-lower snapshot.
        bar.focus_item(0)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_active_upper_120x40",
            title="ACE prompt stack — active upper pane",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_prompt_stack_compact_inactive_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(80, 30)
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await _mount_prompt_bar(page, _COMPACT_PROMPT)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_compact_inactive_80x30",
            title="ACE prompt stack — compact inactive panes",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_prompt_stack_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _TWO_PANE_PROMPT)

        # The completion panel is scoped to the active pane; render a
        # deterministic xprompt completion to pin its in-stack styling.
        bar.show_file_completions(
            "fo",
            _XPROMPT_COMPLETION_ROWS,
            selected_index=1,
            completion_kind="xprompt",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_completion_panel_120x40",
            title="ACE prompt stack — completion panel in active pane",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


def _xprompt_candidate(
    name: str,
    *,
    kind: str,
    description: str,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=f"#{name}",
        insertion=name,
        is_dir=False,
        name=name,
        metadata=XPromptAssistEntry(
            name=name,
            insertion=name,
            reference_prefix="#",
            kind=kind,
            input_signature=None,
            inputs=(),
            content_preview=None,
            description=description,
        ),
    )


_XPROMPT_COMPLETION_ROWS = [
    _xprompt_candidate("fork", kind="part", description="Strip SASE lingo and fork"),
    _xprompt_candidate(
        "format", kind="workflow", description="Run the formatter across the diff"
    ),
    _xprompt_candidate(
        "followup", kind="part", description="Draft a follow-up review pass"
    ),
]
