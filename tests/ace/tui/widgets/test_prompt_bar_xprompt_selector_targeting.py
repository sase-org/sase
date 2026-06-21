"""Widget tests for ``#@`` selector-origin targeting (Phase 1).

These cover the two halves of the plumbing:

- the ``#@`` trigger posts a ``SnippetRequested`` carrying the originating bar,
  text area, pane id, and the trigger range covering the literal ``#``; and
- ``PromptInputBar.insert_snippet_at_target`` inserts into the captured pane
  (preserving surrounding text and other panes) and refuses to touch anything
  when the captured pane is stale.
"""

from __future__ import annotations

from textual.message import Message

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


async def test_hash_at_posts_snippet_requested_with_origin() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        captured: list[PromptInputBar.SnippetRequested] = []
        original_post = bar.post_message

        def _capture(message: Message) -> bool:
            if isinstance(message, PromptInputBar.SnippetRequested):
                captured.append(message)
                return True
            return original_post(message)

        bar.post_message = _capture  # type: ignore[method-assign]

        ta.load_text("before #")
        ta.cursor_location = (0, len("before #"))
        await pilot.press("@")

        assert len(captured) == 1
        message = captured[0]
        assert message.origin_bar is bar
        assert message.origin_text_area is ta
        assert message.origin_pane_id == ta.id
        # Trigger range covers the literal '#'; the '@' was prevented.
        assert message.trigger_range == ((0, 7), (0, 8))


async def test_hash_at_in_feedback_mode_does_not_request_selector() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        bar._mode = "feedback"
        ta = app.query_one(PromptTextArea)

        captured: list[PromptInputBar.SnippetRequested] = []
        original_post = bar.post_message

        def _capture(message: Message) -> bool:
            if isinstance(message, PromptInputBar.SnippetRequested):
                captured.append(message)
                return True
            return original_post(message)

        bar.post_message = _capture  # type: ignore[method-assign]

        ta.load_text("#")
        ta.cursor_location = (0, 1)
        await pilot.press("@")

        assert captured == []


async def test_insert_at_target_empty_pane_inserts_reference() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        # The '#' from the '#@' trigger is already present ('@' was prevented).
        ta.load_text("#")
        ta.cursor_location = (0, 1)

        inserted = bar.insert_snippet_at_target(
            ta, ta.id or "", ((0, 0), (0, 1)), "review"
        )
        await pilot.pause()

        assert inserted is True
        assert ta.text == "#review"


async def test_insert_at_target_preserves_surrounding_text() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        ta.load_text("before # after")
        ta.cursor_location = (0, len("before #"))

        inserted = bar.insert_snippet_at_target(
            ta, ta.id or "", ((0, 7), (0, 8)), "review"
        )
        await pilot.pause()

        assert inserted is True
        assert ta.text == "before #review after"


async def test_insert_at_target_multi_pane_targets_origin_only() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        bar.load_stack_from_text("#\n---\nsecond")
        await pilot.pause()

        upper, lower = list(bar.query(PromptTextArea))
        # Make the *other* pane active to prove targeting follows the captured
        # origin pane rather than whatever pane is active when the modal closes.
        bar.focus_item(1)
        await pilot.pause()
        assert bar.active_text_area() is lower

        inserted = bar.insert_snippet_at_target(
            upper, upper.id or "", ((0, 0), (0, 1)), "review"
        )
        await pilot.pause()

        assert inserted is True
        assert upper.text == "#review"  # the captured origin pane
        assert lower.text == "second"  # untouched, even though it was active


async def test_insert_at_target_stale_pane_returns_false_without_mutation() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        stale_pane = ta
        stale_id = ta.id or ""

        # A whole-stack rebuild bumps the generation and remounts panes under a
        # fresh id, leaving the captured reference orphaned.
        bar.load_stack_from_text("other")
        await pilot.pause()

        inserted = bar.insert_snippet_at_target(
            stale_pane, stale_id, ((0, 0), (0, 1)), "review"
        )
        await pilot.pause()

        assert inserted is False
        # The live pane was left byte-for-byte unchanged.
        assert bar.active_text_area().text == "other"
