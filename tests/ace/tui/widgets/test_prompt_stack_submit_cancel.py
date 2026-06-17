"""Widget-level tests for Phase 4 stack submit / cancel semantics.

Covers the Phase 4 deliverable of the multi-agent prompt stack:

- ``<enter>`` opens a submit chooser for non-empty multi-pane stacks.
- ``<ctrl+shift+s>`` submits only the selected pane and keeps the bar mounted
  while other panes remain, dropping an empty selected pane instead of launching
  it.
- ``<enter>`` on the final pane submits the whole bar (unmount path).
- ``<ctrl+s>`` submits the whole stack as one multi-prompt.
- ``<ctrl+c>`` cancels only the selected pane and keeps the bar mounted while
  other panes remain.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.modals.prompt_submit_choice_modal import PromptSubmitChoiceModal
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _CaptureApp(App[None]):
    """Hosts a prompt bar and records its Submitted / Cancelled messages."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
        self.submitted: list[PromptInputBar.Submitted] = []
        self.cancelled: list[PromptInputBar.Cancelled] = []

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


@pytest.mark.parametrize("choice_key", ["c", "ctrl+shift+s"])
async def test_submit_choice_current_submits_selected_pane(choice_key: str) -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("enter")
        await pilot.pause()
        await pilot.press(choice_key)
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


# --- <ctrl+shift+s>: single selected-pane submit ---------------------------


async def test_ctrl_shift_s_submits_selected_pane_and_keeps_bar() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 2  # bottom pane active

        await pilot.press("ctrl+shift+s")  # submit "third"
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


async def test_ctrl_shift_s_reattaches_frontmatter_to_single_pane_submit() -> None:
    # Prompt-level YAML frontmatter is held on the stack, not as a pane; a lone
    # pane submit must carry it so referenced local xprompts still resolve.
    app = _CaptureApp("---\nmodel: opus\n---\nalpha\n---\nbeta")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar.all_prompt_texts() == ["alpha", "beta"]

        await pilot.press("ctrl+shift+s")  # submit bottom pane "beta"
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
        # Add an empty bottom pane, then submit it.
        await pilot.press("escape")
        await pilot.press("ctrl+minus")
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


async def test_ctrl_shift_s_drains_stack_one_pane_at_a_time() -> None:
    app = _CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("ctrl+shift+s")  # submit "second", keep bar
        await pilot.pause()
        await pilot.pause()
        assert bar.all_prompt_texts() == ["first"]

        await pilot.press("enter")  # final pane -> whole-bar submit
        await pilot.pause()

        assert [e.value for e in app.submitted] == ["second", "first"]
        assert [e.keep_bar for e in app.submitted] == [True, False]


async def test_ctrl_shift_s_is_noop_in_single_pane_bar() -> None:
    app = _CaptureApp("solo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+shift+s")
        await pilot.pause()
        assert app.submitted == []

        await pilot.press("enter")
        await pilot.pause()

        assert len(app.submitted) == 1
        assert app.submitted[0].value == "solo"


# --- <ctrl+s>: whole-stack submit ------------------------------------------


async def test_ctrl_s_submits_whole_stack_as_multi_prompt() -> None:
    app = _CaptureApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()

        assert len(app.submitted) == 1
        event = app.submitted[0]
        assert event.value == "first\n---\nsecond\n---\nthird"
        assert event.whole_stack is True
        assert event.keep_bar is False


async def test_ctrl_s_is_noop_in_feedback_mode() -> None:
    app = _CaptureApp("plan note", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()

        assert app.submitted == []


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


async def test_multi_pane_subtitle_advertises_send_all() -> None:
    app = _CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert "[^S] all" in bar.insert_mode_subtitle()
        assert "[^⇧S] this" in bar.insert_mode_subtitle()


async def test_single_pane_subtitle_omits_send_all() -> None:
    app = _CaptureApp("solo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert "[^S] all" not in bar.insert_mode_subtitle()


async def test_multi_pane_insert_subtitle_points_to_nav() -> None:
    app = _CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        subtitle = bar.insert_mode_subtitle()
        assert "[Enter] submit…" in subtitle
        # Esc drops into normal mode where the stash / add-pane keys live.
        assert "[Esc] nav" in subtitle
        assert "[Esc] normal" not in subtitle
        # Pane focus navigation and reorder are advertised in insert mode too.
        assert "[^H/L] pane" in subtitle
        assert "[^⇧H/L] move" in subtitle


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
        # Pane focus lives on the unshifted Ctrl+H/L axis; reorder on the
        # adjacent Ctrl+Shift chords.
        assert "[^H/L] pane" in subtitle
        assert "[^⇧H/L] move" in subtitle
        # The retired comma-leader reorder hint is gone.
        assert ",J" not in subtitle and ",K" not in subtitle
        assert "[^-] add" in subtitle


async def test_single_pane_normal_subtitle_advertises_stash() -> None:
    app = _CaptureApp("solo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        # A single-pane prompt bar still advertises ,s so stashing the lone
        # draft is discoverable, plus ,f for the frontmatter panel.
        subtitle = bar.normal_mode_subtitle()
        assert subtitle == "[Esc] clear  [i] insert  [,s] stash  [,f] fm  [^C] cancel"


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
        assert "[^H/L] pane" in str(bar.border_subtitle)
