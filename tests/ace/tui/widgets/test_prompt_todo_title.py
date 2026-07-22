"""Whole-stack TODO title capsule and prompt lifecycle coverage."""

from __future__ import annotations

from rich.color import Color
from rich.console import Console
from rich.markup import render as render_markup
from rich.style import Style
from textual.theme import Theme

from sase.ace.tui.models.agent_status import RUNNING_COLOR
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_stack import XPromptBinding
from sase.xprompt import jinja_inspect

from ._prompt_input_bar_stack_helpers import _PromptBarApp, _XPromptMarkdownApp


def _plain_title(bar: PromptInputBar) -> str:
    return render_markup(str(bar.border_title)).plain


def _rendered_todo_title_style(bar: PromptInputBar) -> Style:
    title = render_markup(str(bar.border_title))
    segments = Console(color_system="truecolor", force_terminal=True).render(title)
    return next(
        segment.style
        for segment in segments
        if "TODO" in segment.text and isinstance(segment.style, Style)
    )


def _compute_jinja_now(bar: PromptInputBar) -> None:
    text_area = bar.active_text_area()
    text_area._jinja_diagnostics_generation += 1
    generation = text_area._jinja_diagnostics_generation
    text_area._fire_jinja_diagnostics_timer(
        generation,
        text_area.text,
        text_area._absolute_offset(text_area.cursor_location),
    )


async def test_todo_title_tracks_initial_offscreen_text_and_live_edits() -> None:
    initial = "TODO: above viewport\n" + "ordinary line\n" * 30 + "finish here"
    app = _PromptBarApp(initial)

    async with app.run_test(size=(80, 16)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()

        assert text_area.cursor_location[0] == text_area.document.line_count - 1
        assert "TODO 1" in _plain_title(bar)

        text_area.load_text("done")
        await pilot.pause()
        assert text_area.todo_annotation_count == 0
        assert not any(
            name.startswith("todo.")
            for row in text_area._highlights.values()
            for *_range, name in row
        )
        assert "TODO" not in _plain_title(bar)

        text_area.load_text("TODO(owner): restored")
        await pilot.pause()
        assert text_area.todo_annotation_count == 1
        assert any(
            name == "todo.header"
            for row in text_area._highlights.values()
            for *_range, name in row
        )
        assert "TODO 1" in _plain_title(bar)


async def test_todo_title_aggregates_reorders_and_removes_panes() -> None:
    app = _PromptBarApp("TODO: upper\n---\nTODO: lower and TODO(dev): second")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert "TODO 3" in _plain_title(bar)

        assert bar.move_active_pane(-1, target_mode="insert")
        await pilot.pause()
        await pilot.pause()
        assert "TODO 3" in _plain_title(bar)

        bar.stash_active_pane()
        await pilot.pause()
        await pilot.pause()
        assert len(bar._stack) == 1
        assert "TODO 1" in _plain_title(bar)


async def test_todo_title_updates_for_append_and_fresh_stash_restore_paths() -> None:
    app = _PromptBarApp("TODO: existing")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.restore_stashed_entries([("plain restored", ""), ("TODO: restored", "")])
        await pilot.pause()
        await pilot.pause()

        assert len(bar._stack) == 3
        assert "TODO 2" in _plain_title(bar)
        assert bar.active_text() == "TODO: restored"

    fresh = _XPromptMarkdownApp("TODO: restored one\n---\nTODO(dev): restored two")
    async with fresh.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = fresh.query_one(PromptInputBar)
        assert len(bar._stack) == 2
        assert "TODO 2" in _plain_title(bar)
        assert bar.active_text() == "TODO(dev): restored two"


async def test_todo_title_updates_through_history_and_editor_rebuilds() -> None:
    app = _PromptBarApp("plain draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.update_active_pane("TODO: returned from the pane editor")
        await pilot.pause()
        await pilot.pause()
        assert "TODO 1" in _plain_title(bar)

        bar.load_stack_from_xprompt_markdown(
            "TODO(owner): returned from the whole-stack editor\n---\nplain second pane"
        )
        await pilot.pause()
        await pilot.pause()
        assert "TODO 1" in _plain_title(bar)

        target = bar.active_text_area()
        assert target.id is not None
        assert bar.load_prompt_into_pane(
            target,
            target.id,
            "TODO: history one and TODO(dev): history two",
        )
        await pilot.pause()
        await pilot.pause()
        assert "TODO 3" in _plain_title(bar)


async def test_todo_title_keeps_binding_mode_agent_and_jinja_adornments(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(jinja_inspect, "known_toplevel_context", lambda: {"root"})
    source = tmp_path / "review.md"
    source.write_text("TODO: saved", encoding="utf-8")
    app = _PromptBarApp("TODO: upper\n---\nTODO: {{ root }}")

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar._stack.bind(XPromptBinding.for_file(source))
        bar._refresh_title()
        await pilot.press("!")
        bar.active_text_area()._enter_normal_mode()
        _compute_jinja_now(bar)

        title = _plain_title(bar)
        assert "Prompt · 2 agents" in title
        assert "review" in title
        assert "●" in title
        assert "[NORMAL]" in title
        assert "TODO 2" in title
        assert "jinja ✓" in title


async def test_todo_title_capsule_keeps_running_gold_after_theme_switch() -> None:
    app = _PromptBarApp("TODO TODO: TODO(owner) TODO(owner): note")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        before = _rendered_todo_title_style(bar)

        app.register_theme(
            Theme(
                name="todo-light",
                primary="#0066cc",
                warning="#805500",
                foreground="#111111",
                background="#ffffff",
                dark=False,
            )
        )
        app.theme = "todo-light"
        await pilot.pause()
        after = _rendered_todo_title_style(bar)

        assert "TODO 4" in _plain_title(bar)
        assert after.color == Color.parse("#000000")
        assert after.bgcolor == Color.parse(RUNNING_COLOR)
        assert after.bold is True
        assert after == before
