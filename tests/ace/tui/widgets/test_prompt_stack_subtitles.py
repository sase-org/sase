"""Widget tests for prompt-stack key discoverability in subtitles."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.ace.tui.widgets.prompt_stack_submit_cancel_test_support import CaptureApp


async def test_multi_pane_subtitle_advertises_ctrl_s_stash() -> None:
    app = CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert "[^S] stash" in bar.insert_mode_subtitle()
        assert "[^G Enter] this" in bar.insert_mode_subtitle()


async def test_single_pane_subtitle_omits_ctrl_s_stash() -> None:
    app = CaptureApp("solo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert "[^S] stash" not in bar.insert_mode_subtitle()


async def test_multi_pane_insert_subtitle_points_to_nav() -> None:
    app = CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        subtitle = bar.insert_mode_subtitle()
        assert "[Enter] submit…" in subtitle
        # Esc drops into normal mode where the pane-focus / reorder / stash keys
        # live.
        assert "[Esc] nav" in subtitle
        assert "[Esc] normal" not in subtitle
        # Pane focus and reorder are NORMAL-mode-only now, so they are NOT
        # advertised in insert mode -- the subtitle just points to nav.
        assert "[K/J] pane" not in subtitle
        assert "[↑/↓] move" not in subtitle


async def test_single_pane_insert_subtitle_keeps_normal_hint() -> None:
    app = CaptureApp("solo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar.insert_mode_subtitle() == "[Enter] send  [Esc] normal  [^C] cancel"


async def test_multi_pane_normal_subtitle_advertises_stack_keys() -> None:
    app = CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        subtitle = bar.normal_mode_subtitle()
        # Every stack keymap the active pane exposes is discoverable here.
        # Pane focus / reorder / add migrated onto the `g` prefix.
        assert "[g<enter>] launch" in subtitle
        assert "[gj/gk] pane" in subtitle
        assert "[gJ/gK] move" in subtitle
        assert "[^S/gs] stash" in subtitle
        # The retired comma-leader hints are gone.
        assert "," not in subtitle


async def test_single_pane_normal_subtitle_advertises_stash() -> None:
    app = CaptureApp("solo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        # A single-pane prompt bar advertises Ctrl+S so stashing the lone
        # draft is discoverable.
        subtitle = bar.normal_mode_subtitle()
        assert subtitle == (
            "[Esc] clear  [i] insert  [g<enter>] send  [^S] stash  [^C] cancel"
        )


async def test_feedback_normal_subtitle_omits_stash() -> None:
    app = CaptureApp("plan note", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        # Feedback bars are not stashable, so they keep the original hints.
        assert bar.normal_mode_subtitle() == "[Esc] clear  [i] insert  [^C] cancel"


async def test_entering_normal_mode_applies_stack_subtitle() -> None:
    app = CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.active_text_area()._enter_normal_mode()
        await pilot.pause()
        # The wired-up normal-mode subtitle reaches the live border subtitle.
        assert "[gj/gk] pane" in str(bar.border_subtitle)
