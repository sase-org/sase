"""Widget tests for cycle-edit coalescing (``ctrl+n`` / ``ctrl+p``).

A cycle edit must pay for at most one full highlight-map build: the edit,
cursor move, hint refresh, and context refresh run inside
``_highlight_batch()``, and the queued ``Changed`` / ``SelectionChanged``
echoes are no-ops when nothing changed since the direct refresh.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import TextArea

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _CoalesceApp(App):
    # Mirror AceApp: the prompt subsystem owns ctrl+n/ctrl+p, so the
    # command palette (default ctrl+p) must not intercept them.
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, *, bar: bool = False) -> None:
        super().__init__()
        self._bar = bar

    def compose(self) -> ComposeResult:
        if self._bar:
            yield PromptInputBar(mode="prompt")
        else:
            yield PromptTextArea()


def _terminal_build_counter() -> tuple[Any, list[int]]:
    """Count full highlight-chain runs at Textual's terminal override."""
    calls: list[int] = []
    original = TextArea._build_highlight_map

    def counting(self: TextArea) -> None:
        calls.append(1)
        original(self)

    return patch.object(TextArea, "_build_highlight_map", counting), calls


def _patched_mru(mru: list[str]) -> Any:
    return patch(
        "sase.history.vcs_macro_mru.load_launchable_vcs_macro_mru",
        return_value=mru,
    )


async def test_cycle_press_builds_highlight_map_once() -> None:
    """One ``ctrl+p`` pays for a single synchronous highlight build."""
    app = _CoalesceApp(bar=True)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#git:foo")
        ta.move_cursor(ta._location_from_absolute(len("#git:foo")))
        ta.focus()
        await pilot.pause()
        patcher, calls = _terminal_build_counter()
        with (
            patcher,
            patch.object(
                PromptTextArea,
                "_schedule_jinja_diagnostics_refresh",
                lambda self: None,
            ),
            _patched_mru(["#git:foo", "#git:bar"]),
        ):
            await pilot.press("ctrl+p")
            await pilot.pause()
        assert ta.text == "#git:bar "
        assert len(calls) <= 1


async def test_cycle_highlight_spans_match_fresh_rebuild() -> None:
    """The batched build produces the same spans as an unbatched rebuild."""
    app = _CoalesceApp(bar=True)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#git:foo")
        ta.move_cursor(ta._location_from_absolute(len("#git:foo")))
        ta.focus()
        await pilot.pause()
        with _patched_mru(["#git:foo", "#git:bar"]):
            await pilot.press("ctrl+p")
            await pilot.pause()
        assert ta.text == "#git:bar "
        batched = {row: tuple(spans) for row, spans in ta._highlights.items() if spans}
        assert batched, "expected overlay spans for the cycled tag"
        ta._build_highlight_map()
        fresh = {row: tuple(spans) for row, spans in ta._highlights.items() if spans}
        assert batched == fresh


async def test_repeated_context_refresh_without_changes_is_noop() -> None:
    """Queued echoes after a cycle skip the expensive context refreshers."""
    app = _CoalesceApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#git:foo")
        ta.move_cursor(ta._location_from_absolute(len("#git:foo")))
        ta.focus()
        await pilot.pause()
        with (
            patch.object(
                PromptTextArea,
                "_refresh_prompt_glossary_context",
                autospec=True,
                side_effect=lambda self, **kwargs: None,
            ) as gloss,
            patch.object(
                PromptTextArea,
                "_refresh_prompt_repo_mention_context",
                autospec=True,
                side_effect=lambda self, **kwargs: None,
            ) as repo,
        ):
            ta._on_prompt_completion_context_changed()
            await pilot.pause()
            first = (gloss.call_count, repo.call_count)
            assert first == (1, 1)
            # Same text and cursor: the echo does no highlight/context work.
            ta._on_prompt_completion_context_changed()
            await pilot.pause()
            assert (gloss.call_count, repo.call_count) == first
            # New text re-arms the refreshers.
            ta.load_text("#git:foo fix")
            await pilot.pause()
            ta._on_prompt_completion_context_changed()
            await pilot.pause()
            assert gloss.call_count == 2
            assert repo.call_count == 2


async def test_highlight_batch_coalesces_nested_builds() -> None:
    """Nested ``_highlight_batch`` blocks flush a single build at exit."""
    app = _CoalesceApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#git:foo")
        await pilot.pause()
        patcher, calls = _terminal_build_counter()
        with patcher:
            with ta._highlight_batch():
                ta._build_highlight_map()
                with ta._highlight_batch():
                    ta._build_highlight_map()
                ta._build_highlight_map()
                assert not calls
            assert len(calls) == 1


async def test_jinja_diagnostics_inspect_runs_off_pump() -> None:
    """The diagnostics timer fire inspects in a pump-free task."""
    from ._completion_helpers import CompletionTestApp

    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Hello {{ name }")
        ta.cursor_location = (0, len(ta.text))
        await pilot.pause()
        ta._jinja_diagnostics_generation += 1
        generation = ta._jinja_diagnostics_generation
        ta._fire_jinja_diagnostics_timer(
            generation,
            ta.text,
            ta._absolute_offset(ta.cursor_location),
        )
        task = ta._jinja_diagnostics_task
        assert task is not None
        # Nothing is applied synchronously on the pump.
        assert not ta._jinja_diagnostics.has_jinja
        await task
        assert ta._jinja_diagnostics.has_jinja
        assert not ta._jinja_diagnostics.ok
        assert ta._jinja_error_span is not None


async def test_jinja_diagnostics_drops_stale_result() -> None:
    """An inspect that lands after an edit never overwrites fresh state."""
    from ._completion_helpers import CompletionTestApp

    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Hello {{ name }")
        ta.cursor_location = (0, len(ta.text))
        await pilot.pause()
        ta._jinja_diagnostics_generation += 1
        generation = ta._jinja_diagnostics_generation
        ta._fire_jinja_diagnostics_timer(
            generation,
            ta.text,
            ta._absolute_offset(ta.cursor_location),
        )
        task = ta._jinja_diagnostics_task
        assert task is not None
        ta.load_text("plain text, no jinja")
        try:
            await task
        except asyncio.CancelledError:
            # The load's echo rescheduled and superseded the in-flight task.
            pass
        assert not ta._jinja_diagnostics.has_jinja


async def test_cycle_highlight_reuses_wire_memo() -> None:
    """Repeated highlight builds convert warm entries to wire format once."""
    from sase.macro import highlight as macro_highlight

    from sase.ace.tui.widgets.macro_arg_assist import MacroAssistEntry

    entries = [
        MacroAssistEntry(
            name="deploy",
            insertion="#deploy",
            reference_prefix="#",
            kind="xprompt",
            input_signature=None,
            inputs=(),
            content_preview=None,
        )
    ]
    app = _CoalesceApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#deploy:prod")
        await pilot.pause()
        with (
            patch.object(
                PromptTextArea,
                "_get_exact_warm_macro_arg_assist_entries",
                return_value=entries,
            ),
            patch.object(
                macro_highlight,
                "macro_arg_assist_entries_to_wire",
                wraps=macro_highlight.macro_arg_assist_entries_to_wire,
            ) as to_wire,
        ):
            ta._build_highlight_map()
            ta._build_highlight_map()
        assert to_wire.call_count == 1


async def test_cursor_may_need_arg_hint() -> None:
    """The cheap arg-hint pre-check mirrors detection's text scan."""
    # Plain text and bare refs never need a detect pass.
    cases = [
        ("fix the bug", 11, False),
        ("", 0, False),
        ("+sase fix the bug", 5, False),
        # A provider ref still takes the detect path (which finds no entry).
        ("#git:foo", 8, True),
        # A colon or paren after the last ``#`` may open an argument list.
        ("#deploy:prod ", 13, True),
        ("#run(arg", 8, True),
        ("fix #run(arg", 11, True),
        # The marker must precede the cursor.
        ("#:arg after", 0, False),
    ]
    app = _CoalesceApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        for text, cursor, expected in cases:
            ta.load_text(text)
            ta.move_cursor(ta._location_from_absolute(cursor))
            assert ta._cursor_may_need_arg_hint() is expected, (
                f"text={text!r} cursor={cursor}"
            )
