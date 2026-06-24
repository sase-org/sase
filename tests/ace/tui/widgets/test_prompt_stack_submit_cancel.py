"""Widget-level tests for Phase 4 stack submit / cancel semantics.

Covers the Phase 4 deliverable of the multi-agent prompt stack:

- ``<enter>`` opens a submit chooser for non-empty multi-pane stacks.
- ``g<enter>`` submits only the selected pane and keeps the bar mounted
  while other panes remain, dropping an empty selected pane instead of launching
  it.
- ``<enter>`` on the final pane submits the whole bar (unmount path).
- ``<ctrl+s>`` stashes the active pane.
- ``<ctrl+c>`` cancels only the selected pane and keeps the bar mounted while
  other panes remain.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.modals.prompt_submit_choice_modal import PromptSubmitChoiceModal
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _CaptureApp(App[None]):
    """Hosts a prompt bar and records prompt-bar messages."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
        self.submitted: list[PromptInputBar.Submitted] = []
        self.cancelled: list[PromptInputBar.Cancelled] = []
        self.stashed: list[PromptInputBar.Stashed] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )

    def on_prompt_input_bar_submitted(self, event: PromptInputBar.Submitted) -> None:
        self.submitted.append(event)

    def on_prompt_input_bar_cancelled(self, event: PromptInputBar.Cancelled) -> None:
        self.cancelled.append(event)

    def on_prompt_input_bar_stashed(self, event: PromptInputBar.Stashed) -> None:
        self.stashed.append(event)


# --- <enter>: submit-choice modal ------------------------------------------


async def test_enter_on_multi_pane_pushes_submit_choice_modal() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, PromptSubmitChoiceModal)
        assert app.submitted == []
        assert app.query(PromptInputBar)


@pytest.mark.parametrize("choice_key", ["a", "ctrl+s"])
async def test_submit_choice_all_submits_whole_stack(choice_key: str) -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        await pilot.press(choice_key)
        await pilot.pause()

        assert len(app.submitted) == 1
        event = app.submitted[0]
        assert event.value == "first\n---\nsecond\n---\nthird"
        assert event.whole_stack is True
        assert event.keep_bar is False


async def test_submit_choice_current_submits_selected_pane() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        await pilot.pause()

        assert len(app.submitted) == 1
        event = app.submitted[0]
        assert event.value == "third"
        assert event.keep_bar is True
        assert event.whole_stack is False
        assert bar.all_prompt_texts() == ["first", "second"]


async def test_submit_choice_escape_cancels_without_mutating_stack() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert app.submitted == []
        assert app.cancelled == []
        assert bar.all_prompt_texts() == ["first", "second", "third"]
        assert app.query(PromptInputBar)


# --- g<enter>: single selected-pane submit ----------------------------------


async def test_g_enter_submits_selected_pane_and_keeps_bar() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 2  # bottom pane active

        await pilot.press("escape", "g", "enter")  # submit "third"
        await pilot.pause()
        await pilot.pause()

        assert len(app.submitted) == 1
        event = app.submitted[0]
        assert event.value == "third"
        assert event.keep_bar is True
        assert event.whole_stack is False

        # The submitted pane is gone; the bar stays mounted with the rest.
        assert bar.all_prompt_texts() == ["first", "second"]
        assert app.query(PromptInputBar)
        assert app.cancelled == []


async def test_ctrl_g_enter_submits_selected_pane_from_insert() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 2
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("ctrl+g", "enter")
        await pilot.pause()
        await pilot.pause()

        assert len(app.submitted) == 1
        event = app.submitted[0]
        assert event.value == "third"
        assert event.keep_bar is True
        assert event.whole_stack is False
        assert bar.all_prompt_texts() == ["first", "second"]
        assert bar.active_text_area()._vim_mode == "insert"


async def test_g_enter_reattaches_frontmatter_to_single_pane_submit() -> None:
    # Prompt-level YAML frontmatter is held on the stack, not as a pane; a lone
    # pane submit must carry it so referenced local xprompts still resolve.
    app = _CaptureApp("---\nmodel: opus\n---\nalpha\n---\nbeta")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar.all_prompt_texts() == ["alpha", "beta"]

        await pilot.press("escape", "g", "enter")  # submit bottom pane "beta"
        await pilot.pause()
        await pilot.pause()

        assert len(app.submitted) == 1
        event = app.submitted[0]
        assert event.value == "---\nmodel: opus\n---\nbeta"
        assert event.keep_bar is True
        # The remaining pane keeps the frontmatter for its own later submit.
        assert bar.current_prompt_text() == "---\nmodel: opus\n---\nalpha"


async def test_enter_on_empty_selected_pane_drops_it_without_submitting() -> None:
    app = _CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        # Add an empty bottom pane (NORMAL-mode ``g-``), then submit it.
        await pilot.press("escape")
        await pilot.press("g", "-")
        await pilot.pause()
        await pilot.pause()
        assert bar.all_prompt_texts() == ["first", "second", ""]

        await pilot.press("enter")  # empty selected pane
        await pilot.pause()
        await pilot.pause()

        # Nothing launched; the empty pane is dropped.
        assert app.submitted == []
        assert bar.all_prompt_texts() == ["first", "second"]


async def test_enter_on_final_pane_submits_whole_bar() -> None:
    app = _CaptureApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert len(app.submitted) == 1
        event = app.submitted[0]
        assert event.value == "only one"
        assert event.keep_bar is False
        assert event.whole_stack is False


async def test_g_enter_drains_stack_one_pane_at_a_time() -> None:
    app = _CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("escape", "g", "enter")  # submit "second", keep bar
        await pilot.pause()
        await pilot.pause()
        assert bar.all_prompt_texts() == ["first"]

        await pilot.press("escape", "g", "enter")  # final pane -> whole-bar submit
        await pilot.pause()

        assert [e.value for e in app.submitted] == ["second", "first"]
        assert [e.keep_bar for e in app.submitted] == [True, False]


async def test_g_enter_on_single_pane_bar_submits_normally() -> None:
    app = _CaptureApp("solo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape", "g", "enter")
        await pilot.pause()

        assert len(app.submitted) == 1
        assert app.submitted[0].value == "solo"
        assert app.submitted[0].keep_bar is False


async def test_ctrl_shift_s_no_longer_submits_selected_pane() -> None:
    app = _CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("ctrl+shift+s")
        await pilot.pause()

        assert app.submitted == []
        assert bar.all_prompt_texts() == ["first", "second"]


# --- <ctrl+s>: active-pane stash -------------------------------------------


async def test_ctrl_s_stashes_active_pane() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()

        assert app.submitted == []
        assert len(app.stashed) == 1
        event = app.stashed[0]
        assert event.source == "current"
        assert event.dismiss_bar is False
        assert [pane.text for pane in event.panes] == ["third"]
        assert event.panes[0].pane_index == 2
        assert bar.all_prompt_texts() == ["first", "second"]


async def test_ctrl_s_is_noop_in_feedback_mode() -> None:
    app = _CaptureApp("plan note", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()

        assert app.submitted == []
        assert app.stashed == []


# --- <ctrl+c>: per-pane cancel ---------------------------------------------


async def test_ctrl_c_cancels_only_selected_pane_and_keeps_bar() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("ctrl+c")  # cancel "third"
        await pilot.pause()
        await pilot.pause()

        assert len(app.cancelled) == 1
        event = app.cancelled[0]
        assert event.cancelled_text == "third"
        assert event.keep_bar is True

        assert bar.all_prompt_texts() == ["first", "second"]
        assert app.query(PromptInputBar)  # bar still mounted
        assert app.submitted == []


async def test_ctrl_c_on_final_pane_cancels_whole_bar() -> None:
    app = _CaptureApp("solo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+c")
        await pilot.pause()

        assert len(app.cancelled) == 1
        event = app.cancelled[0]
        assert event.cancelled_text == "solo"
        assert event.keep_bar is False


# --- subtitle discoverability ----------------------------------------------


async def test_multi_pane_subtitle_advertises_ctrl_s_stash() -> None:
    app = _CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert "[^S] stash" in bar.insert_mode_subtitle()
        assert "[^G Enter] this" in bar.insert_mode_subtitle()


async def test_single_pane_subtitle_omits_ctrl_s_stash() -> None:
    app = _CaptureApp("solo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert "[^S] stash" not in bar.insert_mode_subtitle()


async def test_multi_pane_insert_subtitle_points_to_nav() -> None:
    app = _CaptureApp("first\n---\nsecond")

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
    app = _CaptureApp("solo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar.insert_mode_subtitle() == "[Enter] send  [Esc] normal  [^C] cancel"


async def test_multi_pane_normal_subtitle_advertises_stack_keys() -> None:
    app = _CaptureApp("first\n---\nsecond")

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
    app = _CaptureApp("solo")

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
    app = _CaptureApp("plan note", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        # Feedback bars are not stashable, so they keep the original hints.
        assert bar.normal_mode_subtitle() == "[Esc] clear  [i] insert  [^C] cancel"


async def test_entering_normal_mode_applies_stack_subtitle() -> None:
    app = _CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.active_text_area()._enter_normal_mode()
        await pilot.pause()
        # The wired-up normal-mode subtitle reaches the live border subtitle.
        assert "[gj/gk] pane" in str(bar.border_subtitle)
