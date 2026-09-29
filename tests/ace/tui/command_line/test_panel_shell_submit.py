"""Submit and rendering tests for the ``:`` Command Line.

The submit happy path and failure path, block-output rendering, and
pump-free tail polling.
"""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.command_line.block_render import (
    block_header_right,
    collapsed_body_lines,
    gutter_glyph,
    render_block_output,
    sanitize_block_output,
)
from sase.ace.tui.command_line.context import (
    CommandLineContext,
    working_context_chip,
)
from sase.ace.tui.command_line.session import CommandLineSession
from sase.ace.tui.command_line.submit import (
    apply_exit_completion,
    apply_local_block,
    apply_submit_failure,
    apply_submit_success,
    prepare_submit,
)

__all__ = [
    "test_collapsed_body_shows_last_12_lines",
    "test_context_chip_marks_pins_and_truncates",
    "test_exit_elapsed_uses_one_clock_for_live_blocks",
    "test_gutter_and_header_metadata",
    "test_prepare_submit_rejects_blank_and_guards_double_enter",
    "test_sanitize_collapses_cr_and_drops_osc_keeps_sgr",
    "test_screen_submit_uses_thread_worker_not_await",
    "test_submit_failure_path_restores_state",
    "test_submit_success_and_exit_settle",
    "test_tail_polling_never_touches_message_pump",
]


# -- submit ---------------------------------------------------------------------


def test_prepare_submit_rejects_blank_and_guards_double_enter() -> None:
    """Blank lines never submit; the same line within 300 ms is dropped."""
    session = CommandLineSession()
    assert prepare_submit(session, "   ") is None
    first = prepare_submit(session, "bead list")
    assert first is not None and first.tokens == ["bead", "list"]
    assert prepare_submit(session, "bead list") is None
    session.last_submit_at -= 10.0
    assert prepare_submit(session, "bead list") is not None


def test_submit_failure_path_restores_state() -> None:
    """A failed submit turns the block red with the error."""
    session = CommandLineSession()
    block = session.add_block("bead list")
    apply_submit_failure(block, "boom")
    assert block.status == "submit_failed"
    assert block.error == "boom"


def test_submit_success_and_exit_settle() -> None:
    """Attaching a proc marks running; the exit completion settles it."""
    session = CommandLineSession()
    block = session.add_block("bead list")
    apply_submit_success(block, SimpleNamespace(proc_id="proc123"), placeholder_id="p1")
    assert block.status == "running"
    assert block.proc_id == "proc123"
    apply_exit_completion(block, exit_code=0, status="done")
    assert block.status == "success"
    assert block.exit_code == 0
    failed = session.add_block("bead close sase-zz")
    apply_exit_completion(failed, exit_code=2, status="done")
    assert failed.status == "error"


def test_exit_elapsed_uses_one_clock_for_live_blocks() -> None:
    """A live block's elapsed is seconds since submit, not an epoch timestamp.

    ``finished_at`` is wall-clock time (it renders the ``HH:MM`` stamp), so a
    fresh block must start on the same clock.
    """
    session = CommandLineSession()
    block = session.add_block("bead list")
    apply_submit_success(block, SimpleNamespace(proc_id="proc124"), placeholder_id="p2")
    apply_exit_completion(block, exit_code=0, status="done")
    assert block.elapsed is not None
    assert 0.0 <= block.elapsed < 60.0
    local = session.add_block("history")
    apply_local_block(local, status="builtin", text="", exit_code=0)
    assert local.elapsed is not None
    assert 0.0 <= local.elapsed < 60.0


# -- rendering -------------------------------------------------------------------


def test_sanitize_collapses_cr_and_drops_osc_keeps_sgr() -> None:
    """``\\r`` overwrites collapse, OSC sequences drop, SGR colors survive."""
    cleaned = sanitize_block_output("old\rnew\x1b]0;title\x07\x1b[31mred\x1b[0m")
    assert "old" not in cleaned
    assert "title" not in cleaned
    assert "\x1b[31m" in cleaned


def test_collapsed_body_shows_last_12_lines() -> None:
    """Collapsed blocks show the last 12 lines plus the hidden count."""
    text = "\n".join(f"line {index}" for index in range(20))
    lines, hidden = collapsed_body_lines(text)
    assert hidden == 8
    assert lines == [f"line {index}" for index in range(8, 20)]
    assert render_block_output("proc1", len(text), text) is not None


def test_gutter_and_header_metadata() -> None:
    """Gutter glyphs and right-aligned metadata follow the visual language."""
    assert gutter_glyph("running") == "⠹"
    assert gutter_glyph("success") == "✓"
    assert gutter_glyph("error") == "✗"
    header = block_header_right(
        "success",
        exit_code=0,
        elapsed=0.9,
        finished_at=1700000000.0,
        proc_id="470vtqab",
    )
    assert "exit 0" in header
    assert "proc 470vtq" in header
    assert "running 0s" in block_header_right("running", elapsed=0.2)


def test_context_chip_marks_pins_and_truncates() -> None:
    """The chip shows project plus path, marks pins, and middle-truncates."""
    context = CommandLineContext(cwd="/home/u/projects/sase", project="sase")
    assert working_context_chip(context) == "⌂ +sase · /home/u/projects/sase"
    pinned = CommandLineContext(cwd="/tmp", project=None, pinned=True)
    assert working_context_chip(pinned).endswith("(pinned)")
    long_context = CommandLineContext(cwd="/" + "a" * 100, project="sase")
    assert len(working_context_chip(long_context, max_width=48)) <= 48


# -- pump-free tail regression ----------------------------------------------------


def test_tail_polling_never_touches_message_pump() -> None:
    """The tail loop is a plain coroutine driven by ``spawn_pump_free_task``."""
    import asyncio
    import inspect

    from sase.ace.tui.command_line.transcript import CommandLineTranscript

    assert inspect.iscoroutinefunction(CommandLineTranscript._tail_loop)
    source = inspect.getsource(CommandLineTranscript.start_tail_task)
    assert "spawn_pump_free_task" in source
    assert "call_after_refresh" not in source
    assert asyncio.iscoroutinefunction(CommandLineTranscript._tail_loop)


def test_screen_submit_uses_thread_worker_not_await() -> None:
    """Submission fans out to a worker; the keystroke path never awaits I/O."""
    import inspect

    from sase.ace.tui.command_line import screen as screen_module

    worker_source = inspect.getsource(screen_module.CommandLineScreen._submit_worker)
    assert "to_thread" in worker_source
    submit_source = inspect.getsource(
        screen_module.CommandLineScreen.submit_current_line
    )
    assert "await" not in submit_source
