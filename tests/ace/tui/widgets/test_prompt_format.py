"""Explicit prompt Markdown formatting behavior."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from threading import Event, Lock

import pytest
from textual.app import App, ComposeResult
from textual.document._document import Selection
from textual.pilot import Pilot

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _PromptFormatApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str, *, mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )


async def _wait_until(
    pilot: Pilot[None],
    predicate: Callable[[], bool],
    *,
    attempts: int = 100,
) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await pilot.pause(0.01)
    raise AssertionError("condition did not become true")


async def test_normal_gf_formats_once_preserves_mode_and_is_one_undo_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "alpha beta gamma"
    formatted = "alpha\nbeta gamma\n"
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_format.format_agent_prompt_markdown",
        lambda text: formatted if text == source else text,
    )
    app = _PromptFormatApp(source)

    async with app.run_test(size=(80, 24)) as pilot:
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape", "g", "f")
        await _wait_until(pilot, lambda: text_area.text == formatted)

        assert text_area._vim_mode == "normal"
        assert text_area.read_only is True
        assert text_area._last_mutation_keys == []

        await pilot.press("u")
        await pilot.pause()
        assert text_area.text == source

        # The whole-buffer replacement is isolated in one undo batch.
        await pilot.press("u")
        await pilot.pause()
        assert text_area.text == source


async def test_insert_ctrl_g_f_formats_and_maps_live_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "alpha beta gamma"
    formatted = "alpha\nbeta gamma\n"
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_format.format_agent_prompt_markdown",
        lambda _text: formatted,
    )
    app = _PromptFormatApp(source)

    async with app.run_test(size=(80, 24)) as pilot:
        text_area = app.query_one(PromptTextArea)
        text_area.selection = Selection((0, 6), (0, 10))

        await pilot.press("ctrl+g", "f")
        await _wait_until(pilot, lambda: text_area.text == formatted)

        assert text_area._vim_mode == "insert"
        assert text_area.read_only is False
        assert text_area.selection == Selection((1, 0), (1, 4))


async def test_cursor_and_mode_changes_during_worker_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()

    def slow_formatter(_text: str) -> str:
        started.set()
        release.wait(timeout=2)
        return "alpha\nbeta gamma\n"

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_format.format_agent_prompt_markdown",
        slow_formatter,
    )
    app = _PromptFormatApp("alpha beta gamma")

    async with app.run_test(size=(80, 24)) as pilot:
        text_area = app.query_one(PromptTextArea)
        await pilot.press("ctrl+g", "f")
        assert await asyncio.to_thread(started.wait, 1.0)

        await pilot.press("escape")
        text_area.cursor_location = (0, 6)
        release.set()
        await _wait_until(pilot, lambda: text_area.text == "alpha\nbeta gamma\n")

        assert text_area._vim_mode == "normal"
        assert text_area.read_only is True
        assert text_area.cursor_location == (1, 0)


async def test_formatting_does_not_enter_insert_dot_repeat_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_format.format_agent_prompt_markdown",
        lambda text: text.replace("alpha beta", "alpha\nbeta"),
    )
    app = _PromptFormatApp("alpha beta")

    async with app.run_test(size=(80, 24)) as pilot:
        text_area = app.query_one(PromptTextArea)
        await pilot.press("escape", "0", "i", "X")
        assert text_area._dot_insert_capture_offset == 0

        await pilot.press("ctrl+g", "f")
        await _wait_until(pilot, lambda: text_area.text == "Xalpha\nbeta")
        await pilot.press("escape")

        assert text_area._last_mutation_keys == ["i"]
        assert text_area._last_mutation_insert == "X"


async def test_focus_change_does_not_retarget_multi_pane_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    finished = Event()

    def slow_formatter(text: str) -> str:
        started.set()
        release.wait(timeout=2)
        finished.set()
        return f"formatted {text}"

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_format.format_agent_prompt_markdown",
        slow_formatter,
    )
    markdown = "---\nname: demo\n---\nfirst pane\n---\nsecond pane"
    app = _PromptFormatApp(markdown)

    async with app.run_test(size=(80, 30)) as pilot:
        bar = app.query_one(PromptInputBar)
        original_frontmatter = bar._stack.frontmatter
        target = bar.active_text_area()
        assert target.text == "second pane"

        await pilot.press("ctrl+g", "f")
        assert await asyncio.to_thread(started.wait, 1.0)

        await pilot.press("ctrl+g", "k")
        await pilot.pause()
        assert bar.active_text_area() is not target
        assert bar.active_text_area().text == "first pane"

        release.set()
        assert await asyncio.to_thread(finished.wait, 1.0)
        await _wait_until(
            pilot,
            lambda: (
                target.text == "formatted second pane"
                and bar._stack.texts == ["first pane", "formatted second pane"]
            ),
        )

        assert bar.active_text_area().text == "first pane"
        assert bar._stack.frontmatter == original_frontmatter
        assert bar._stack.texts == ["first pane", "formatted second pane"]


@pytest.mark.parametrize("mode", ["feedback", "approve_prompt"])
async def test_single_pane_auxiliary_bars_can_format(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_format.format_agent_prompt_markdown",
        lambda text: text.upper(),
    )
    app = _PromptFormatApp("format me", mode=mode)

    async with app.run_test(size=(80, 24)) as pilot:
        text_area = app.query_one(PromptTextArea)
        await pilot.press("ctrl+g", "f")
        await _wait_until(pilot, lambda: text_area.text == "FORMAT ME")
        assert text_area._vim_mode == "insert"


async def test_unchanged_format_result_creates_no_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_format.format_agent_prompt_markdown",
        lambda text: text,
    )
    app = _PromptFormatApp("already formatted")

    async with app.run_test(size=(80, 24)) as pilot:
        text_area = app.query_one(PromptTextArea)
        before_batches = len(text_area.history._undo_stack)
        await pilot.press("ctrl+g", "f")
        await pilot.pause(0.05)

        assert text_area.text == "already formatted"
        assert len(text_area.history._undo_stack) == before_batches


async def test_edit_while_formatter_runs_is_responsive_and_discards_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    finished = Event()

    def slow_formatter(_text: str) -> str:
        started.set()
        release.wait(timeout=2)
        finished.set()
        return "stale formatted result"

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_format.format_agent_prompt_markdown",
        slow_formatter,
    )
    app = _PromptFormatApp("draft")

    async with app.run_test(size=(80, 24)) as pilot:
        text_area = app.query_one(PromptTextArea)
        await pilot.press("ctrl+g", "f")
        assert await asyncio.to_thread(started.wait, 1.0)

        # This key is processed while the formatter thread is blocked.
        await pilot.press("x")
        await _wait_until(pilot, lambda: text_area.text == "draftx")

        release.set()
        assert await asyncio.to_thread(finished.wait, 1.0)
        await pilot.pause(0.05)
        assert text_area.text == "draftx"


async def test_newer_format_request_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    first_started = Event()
    release_first = Event()
    first_finished = Event()
    lock = Lock()
    calls = 0

    def formatter(text: str) -> str:
        nonlocal calls
        with lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_started.set()
            release_first.wait(timeout=2)
            first_finished.set()
            return "old result"
        return f"new {text}"

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_format.format_agent_prompt_markdown",
        formatter,
    )
    app = _PromptFormatApp("draft")

    async with app.run_test(size=(80, 24)) as pilot:
        text_area = app.query_one(PromptTextArea)
        await pilot.press("ctrl+g", "f")
        assert await asyncio.to_thread(first_started.wait, 1.0)

        await pilot.press("ctrl+g", "f")
        await _wait_until(pilot, lambda: text_area.text == "new draft")

        release_first.set()
        assert await asyncio.to_thread(first_finished.wait, 1.0)
        await pilot.pause(0.05)
        assert text_area.text == "new draft"


async def test_rebuilt_pane_discards_old_widget_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    finished = Event()

    def slow_formatter(_text: str) -> str:
        started.set()
        release.wait(timeout=2)
        finished.set()
        return "stale result"

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_format.format_agent_prompt_markdown",
        slow_formatter,
    )
    app = _PromptFormatApp("first\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        bar = app.query_one(PromptInputBar)
        old_target = bar.active_text_area()
        await pilot.press("ctrl+g", "f")
        assert await asyncio.to_thread(started.wait, 1.0)

        bar._sync_state_from_widgets()
        bar._rebuild_stack(enter_mode="insert")
        await pilot.pause()
        assert bar.active_text_area() is not old_target

        release.set()
        assert await asyncio.to_thread(finished.wait, 1.0)
        await pilot.pause(0.05)
        assert bar._stack.texts == ["first", "second"]
        assert all(area.text != "stale result" for area in bar.query(PromptTextArea))


async def test_formatter_error_and_ordinary_typing_leave_formatting_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def failing_formatter(_text: str) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_format.format_agent_prompt_markdown",
        failing_formatter,
    )
    app = _PromptFormatApp("draft")

    async with app.run_test(size=(80, 24)) as pilot:
        text_area = app.query_one(PromptTextArea)
        await pilot.press("x")
        await pilot.pause()
        assert text_area.text == "draftx"
        assert calls == 0

        await pilot.press("ctrl+g", "f")
        await _wait_until(pilot, lambda: calls == 1)
        await pilot.pause(0.05)
        assert text_area.text == "draftx"
