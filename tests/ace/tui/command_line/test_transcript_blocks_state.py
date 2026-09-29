"""Session, restore, and rendering tests for transcript blocks.

Session selection, restore mapping/limits, and block rendering for the
``:`` Command Line transcript.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from sase.ace.tui.command_line.restore import (
    RESTORE_LIMIT,
    block_from_proc,
    _command_line_from_proc,
    ensure_block_for_proc,
    load_block_tail_text,
    refresh_pruned_flags,
    restore_missing_blocks,
    _select_restore_rows,
)
from sase.ace.tui.command_line.session import (
    CommandLineBlock,
    CommandLineSession,
)
from sase.ace.tui.command_line.transcript import _CommandLineBlockWidget

__all__ = [
    "test_block_from_proc_maps_terminal_and_running",
    "test_clear_transcript_drops_stale_selection",
    "test_command_line_from_proc_prefers_argv",
    "test_ensure_block_for_proc_adds_missing_block",
    "test_ensure_block_for_proc_pruned",
    "test_first_restored_index",
    "test_load_block_tail_text_missing_log_marks_pruned",
    "test_refresh_pruned_flags_keeps_cached_tail",
    "test_remove_block_keeps_proc_record_and_falls_back",
    "test_render_selected_unseen_divider_and_rotation",
    "test_restore_missing_blocks_skips_known_procs",
    "test_select_first_last_and_empty_session",
    "test_select_restore_rows_enforces_limit_newest",
    "test_select_restore_rows_filters_and_orders",
    "test_selecting_clears_unseen_dot",
    "test_selection_moves_and_enters_at_last_block",
]


def _epoch(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


_NOW = _epoch("2026-09-24T12:00:00Z")


def _row(
    proc_id: str,
    *,
    command: list[str] | None = None,
    label: str | None = None,
    origin: str = "ace",
    tags: list[str] | None = None,
    status: str = "success",
    exit_code: int | None = 0,
    created_at: str = "2026-09-24T11:00:00Z",
    started_at: str | None = "2026-09-24T11:00:00Z",
    finished_at: str | None = "2026-09-24T11:00:05Z",
) -> SimpleNamespace:
    if command is None:
        command = ["sase", "bead", "show", proc_id]
    return SimpleNamespace(
        proc_id=proc_id,
        label=label if label is not None else f": {proc_id}",
        command=command,
        origin=origin,
        tags=tags if tags is not None else ["command-line"],
        status=status,
        exit_code=exit_code,
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
        log_path=f"/tmp/{proc_id}.log",
    )


# -- session selection ---------------------------------------------------------


def test_selection_moves_and_enters_at_last_block() -> None:
    """``j``/``k`` with no selection enter the transcript at the last block."""
    session = CommandLineSession()
    first = session.add_block("bead list")
    last = session.add_block("bead show sase-1")
    assert session.move_selection(1) is last
    assert session.move_selection(1) is last
    assert session.move_selection(-1) is first
    assert session.move_selection(-1) is first


def test_select_first_last_and_empty_session() -> None:
    """``g``/``G`` jump to the ends; an empty transcript deselects."""
    session = CommandLineSession()
    assert session.select_first() is None
    assert session.selected_block_id is None
    first = session.add_block("bead list")
    session.add_block("bead show sase-1")
    last_block = session.blocks[-1]
    assert session.select_first() is first
    assert session.select_last() is last_block


def test_selecting_clears_unseen_dot() -> None:
    """Viewing a block clears its unseen dot."""
    session = CommandLineSession()
    block = session.add_block("bead list")
    block.unseen = True
    assert session.select_block(block.block_id) is block
    assert block.unseen is False
    assert session.select_block("missing") is None
    assert session.selected_block_id is None


def test_remove_block_keeps_proc_record_and_falls_back() -> None:
    """``x`` drops the transcript block and selects a neighbor."""
    session = CommandLineSession()
    first = session.add_block("bead list")
    second = session.add_block("bead show sase-1")
    session.select_block(first.block_id)
    removed = session.remove_block(first.block_id)
    assert removed is first
    assert session.blocks == [second]
    assert session.selected_block() is second
    assert session.remove_block("missing") is None


def test_clear_transcript_drops_stale_selection() -> None:
    """Clearing finished blocks clears a selection that no longer exists."""
    session = CommandLineSession()
    done = session.add_block("bead list")
    done.status = "success"
    session.select_block(done.block_id)
    session.clear_transcript()
    assert session.blocks == []
    assert session.selected_block_id is None


def test_first_restored_index() -> None:
    """The divider sits above the first restored block."""
    session = CommandLineSession()
    assert session.first_restored_index() is None
    session.add_block("bead list")
    restored = session.add_block("bead show sase-1")
    restored.restored = True
    assert session.first_restored_index() == 1


# -- restore selection and mapping ----------------------------------------------


def test_select_restore_rows_filters_and_orders() -> None:
    """Restore keeps tagged ace rows in the window, oldest first."""
    rows = [
        _row("new"),
        _row("other-origin", origin="service"),
        _row("untagged", tags=[]),
        _row("old", created_at="2026-09-20T11:00:00Z"),
        _row("oldest", created_at="2026-09-24T09:00:00Z"),
    ]
    selected = _select_restore_rows(rows, now=_NOW)
    assert [row.proc_id for row in selected] == ["oldest", "new"]


def test_select_restore_rows_enforces_limit_newest() -> None:
    """Restore caps at 20 rows, keeping the newest window."""
    rows = [
        _row(f"proc-{index:02d}", created_at="2026-09-24T11:00:00Z")
        for index in range(25)
    ]
    selected = _select_restore_rows(rows, now=_NOW, limit=RESTORE_LIMIT)
    assert len(selected) == RESTORE_LIMIT
    assert selected[0].proc_id == "proc-19"
    assert selected[-1].proc_id == "proc-00"


def test_command_line_from_proc_prefers_argv() -> None:
    """The input line is recovered from the stored argv first."""
    assert _command_line_from_proc(_row("p1")) == "bead show p1"
    assert (
        _command_line_from_proc(_row("p2", command=[], label=": bead list"))
        == "bead list"
    )


def test_block_from_proc_maps_terminal_and_running() -> None:
    """Finished rows settle at once; active rows restore as running."""
    done = block_from_proc(_row("p1"))
    assert done is not None
    assert (done.status, done.exit_code, done.elapsed) == ("success", 0, 5.0)
    assert done.restored is True
    assert done.tail_loaded is False

    failed = block_from_proc(_row("p2", status="error", exit_code=2))
    assert failed is not None and failed.status == "error"

    killed = block_from_proc(_row("p3", status="killed", exit_code=None))
    assert killed is not None
    assert killed.status == "error" and killed.error == "killed"

    running = block_from_proc(_row("p4", status="running", exit_code=None))
    assert running is not None and running.status == "running"

    assert block_from_proc(_row("p5", command=[], label="")) is None


def test_restore_missing_blocks_skips_known_procs() -> None:
    """Restore never duplicates blocks the transcript already holds."""
    session = CommandLineSession()
    live = session.add_block("bead show p1")
    live.proc_id = "p1"
    added = restore_missing_blocks(session, [_row("p1"), _row("p2")], now=_NOW)
    assert [block.proc_id for block in added] == ["p2"]
    assert [block.line for block in session.blocks] == ["bead show p1", "bead show p2"]
    assert session.blocks[-1].restored is True


def test_refresh_pruned_flags_keeps_cached_tail() -> None:
    """A vanished proc flags ``record pruned`` but keeps its cached tail."""
    session = CommandLineSession()
    gone = session.add_block("bead show p1")
    gone.status = "success"
    gone.proc_id = "p1"
    gone.tail_text = "cached output"
    kept = session.add_block("bead show p2")
    kept.status = "success"
    kept.proc_id = "p2"
    running = session.add_block("agent wait x")
    running.status = "running"
    running.proc_id = "p3"
    newly = refresh_pruned_flags(session, {"p2"})
    assert newly == [gone]
    assert gone.pruned is True
    assert gone.tail_text == "cached output"
    assert kept.pruned is False
    assert running.pruned is False


def test_ensure_block_for_proc_adds_missing_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Procs ``⏎`` jump adds the block when the transcript lacks it."""
    import sase.procs.store as proc_store

    session = CommandLineSession()
    monkeypatch.setattr(proc_store, "get_proc", lambda proc_id: _row(proc_id))
    block = ensure_block_for_proc(session, "p9")
    assert block is not None
    assert block.line == "bead show p9"
    assert session.block_for_proc("p9") is block
    assert ensure_block_for_proc(session, "p9") is block


def test_ensure_block_for_proc_pruned(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pruned record yields no block so the caller can report it."""
    import sase.procs.store as proc_store

    session = CommandLineSession()
    monkeypatch.setattr(proc_store, "get_proc", lambda proc_id: None)
    assert ensure_block_for_proc(session, "gone") is None
    assert session.blocks == []


def test_load_block_tail_text_missing_log_marks_pruned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lazy tail with no log keeps the cache and shows ``record pruned``."""
    import sase.procs.store as proc_store

    block = CommandLineBlock(block_id="cmdline-gone", line="bead show gone")
    block.proc_id = "gone"
    monkeypatch.setattr(proc_store, "get_proc", lambda proc_id: None)
    assert load_block_tail_text(block) is False
    assert block.pruned is True
    assert block.tail_loaded is True


# -- rendering -------------------------------------------------------------------


def test_render_selected_unseen_divider_and_rotation() -> None:
    """The bar, dot, divider, and rotation marker render from session state."""
    block = CommandLineBlock(block_id="b1", line="bead list")
    block.status = "success"
    rendered = _CommandLineBlockWidget.render_block(block)
    assert "▌" not in str(rendered)
    assert "•" not in str(rendered)

    block.unseen = True
    assert "•" in str(_CommandLineBlockWidget.render_block(block))

    selected = _CommandLineBlockWidget.render_block(block, selected=True)
    assert "▌" in str(selected)

    divider = _CommandLineBlockWidget.render_block(block, show_divider=True)
    assert "── earlier ──" in str(divider)

    block.lost_bytes = 12
    assert "earlier output rotated" in str(_CommandLineBlockWidget.render_block(block))

    block.pruned = True
    assert "record pruned" in str(_CommandLineBlockWidget.render_block(block))
