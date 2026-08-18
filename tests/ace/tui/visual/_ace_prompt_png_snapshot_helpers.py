"""Prompt-bar mounting helpers for ACE prompt PNG visual snapshots.

Prompt bodies live in `_ace_prompt_png_snapshot_prompts`, and the deterministic
catalogs each snapshot patches in live in the sibling `*_fixtures` modules.
"""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    wait_for_state,
    wait_for_visual_idle,
)


async def mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    """Mount a prompt bar over the running app and wait for it to settle."""
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus and len(bar._stack) > 0,
        description="mounted prompt stack and active-pane focus",
    )
    await wait_for_visual_idle(page)
    # A background refresh can move focus after the initial mount predicate
    # succeeds. Re-request it after the initial settling, prove cursor
    # visibility, then make convergence the final await so the PNG helper can
    # verify and rasterize that exact focused frame.
    text_area = bar.active_text_area()
    text_area.focus()
    await wait_for_state(
        page,
        lambda: text_area.has_focus and text_area._draw_cursor,
        description="focused prompt caret ready for snapshot capture",
    )
    # Recompute against the final cursor position. Under CI contention the
    # mount-time debounce can otherwise leave a stale suggestion that was
    # calculated while the cursor was still at the start of the prompt.
    text_area._on_prompt_completion_context_changed()
    await wait_for_visual_idle(page)
    return bar


def compute_jinja_now(text_area: PromptTextArea) -> None:
    text_area._jinja_diagnostics_generation += 1
    generation = text_area._jinja_diagnostics_generation
    text_area._fire_jinja_diagnostics_timer(
        generation,
        text_area.text,
        text_area._absolute_offset(text_area.cursor_location),
    )
