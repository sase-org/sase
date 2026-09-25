"""Transcript-block tests for the ``:`` Command Line (transcript-blocks phase).

Covers NORMAL-mode block navigation and every block action (kill and pager
stubbed), completion toasts while hidden, unseen dots, restore after a TUI
restart (window and limit), pruned-record handling, log-rotation markers,
and the Procs ``⏎`` routing back to a block.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.command_line.exits import (
    _completion_toast_text,
    deliver_command_line_exit,
)
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
from sase.ace.tui.modals.procs_pane_agent_jump import (
    _is_command_line_row,
    _open_command_line_on_block,
)


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


# -- toasts ------------------------------------------------------------------------


def _exit_app(**overrides: Any) -> SimpleNamespace:
    app = SimpleNamespace(screen=object())
    for key, value in overrides.items():
        setattr(app, key, value)
    return app


def test_completion_toast_text_success_and_failure() -> None:
    """Hidden finishes toast with exit metadata and the live ``:`` hint."""
    app = _exit_app(
        _keymap_registry=SimpleNamespace(app=SimpleNamespace(open_command_line="colon"))
    )
    done = CommandLineBlock(block_id="b1", line="bead list")
    done.status = "success"
    done.exit_code = 0
    done.elapsed = 0.9
    assert (
        _completion_toast_text(app, done) == "✓ bead list · exit 0 · 0.9s — : to view"
    )

    failed = CommandLineBlock(block_id="b2", line="bead close sase-zz")
    failed.status = "error"
    failed.exit_code = 2
    failed.elapsed = 0.7
    assert "✗ bead close sase-zz · exit 2 · 0.7s" in _completion_toast_text(app, failed)


def test_completion_toast_omits_hint_while_unbound() -> None:
    """The ``to view`` hint disappears while the panel key is unbound."""
    app = _exit_app(
        _keymap_registry=SimpleNamespace(
            app=SimpleNamespace(open_command_line="unbound")
        )
    )
    done = CommandLineBlock(block_id="b1", line="bead list")
    done.status = "success"
    done.exit_code = 0
    text = _completion_toast_text(app, done)
    assert "to view" not in text
    assert text.startswith("✓ bead list")


def test_deliver_exit_toasts_when_hidden_and_marks_unseen() -> None:
    """A finish while hidden toasts at error severity and dots the block."""
    from sase.ace.tui.command_line.session import command_line_session_for

    notices: list[tuple[str, str]] = []
    app = _exit_app(
        notify=lambda message, **kwargs: notices.append(
            (message, kwargs.get("severity", ""))
        ),
        _keymap_registry=SimpleNamespace(
            app=SimpleNamespace(open_command_line="colon")
        ),
    )
    session = command_line_session_for(app)
    block = session.add_block("bead close sase-zz")
    block.proc_id = "proc-1"
    block.status = "running"
    completion = SimpleNamespace(proc_id="proc-1", exit_code=2, status="done")
    assert deliver_command_line_exit(app, completion) is True
    assert block.status == "error"
    assert block.unseen is True
    assert len(notices) == 1
    assert notices[0][1] == "error"
    assert "✗ bead close sase-zz" in notices[0][0]


# -- Procs-pane routing ---------------------------------------------------------------


def test_is_command_line_row_checks_tag() -> None:
    """Only ``command-line``-tagged rows divert Procs ``⏎`` to the panel."""
    assert _is_command_line_row(SimpleNamespace(tags=("command-line",))) is True
    assert _is_command_line_row(SimpleNamespace(tags=())) is False
    assert _is_command_line_row(SimpleNamespace(tags=None)) is False


def test_open_command_line_on_block_reports_pruned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pruned jump still opens the panel and warns."""
    import sase.ace.tui.command_line.restore as restore_module

    opened: list[str] = []
    notices: list[str] = []
    app = SimpleNamespace(
        action_open_command_line=lambda: opened.append("panel"),
        notify=lambda message, **kwargs: notices.append(message),
    )
    monkeypatch.setattr(restore_module, "ensure_block_for_proc", lambda s, p: None)
    assert _open_command_line_on_block(app, "gone") is False
    assert opened == ["panel"]
    assert notices == ["Proc record pruned"]
    from sase.ace.tui.command_line.session import command_line_session_for

    assert command_line_session_for(app).focus_block_proc_id == "gone"


def test_open_command_line_on_block_selects_existing() -> None:
    """A jump to a known block opens the panel without a warning."""
    from sase.ace.tui.command_line.session import command_line_session_for

    opened: list[str] = []
    app = SimpleNamespace(
        action_open_command_line=lambda: opened.append("panel"),
        notify=lambda message, **kwargs: (_ for _ in ()).throw(
            AssertionError("no warning expected")
        ),
    )
    session = command_line_session_for(app)
    block = session.add_block("bead show p1")
    block.proc_id = "p1"
    assert _open_command_line_on_block(app, "p1") is True
    assert opened == ["panel"]
    assert session.focus_block_proc_id == "p1"


async def _open_seeded_panel(
    page: Any,
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
) -> Any:
    """Open the panel with restore stubbed and *lines* seeded as blocks."""
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.screen import CommandLineScreen
    from sase.ace.tui.command_line.session import command_line_session_for

    monkeypatch.setattr(screen_module, "read_command_line_store_rows", lambda: [])

    def _mark_loaded(block: CommandLineBlock) -> bool:
        block.tail_loaded = True
        return True

    monkeypatch.setattr(screen_module, "load_block_tail_text", _mark_loaded)
    page.app.action_open_command_line()
    await page.expect_modal("CommandLineScreen")
    screen = page.app.screen
    assert isinstance(screen, CommandLineScreen)
    session = command_line_session_for(page.app)
    for line in lines:
        session.add_block(line)
    screen.refresh_transcript()
    await page.pause()
    return screen


def _to_normal(screen: Any) -> Any:
    from sase.ace.tui.command_line.input import CommandLineInput

    widget = screen.query_one(CommandLineInput)
    widget._enter_normal_mode()
    return widget


async def test_block_keys_select_move_and_switch_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``j``/``k``/``g``/``G`` move the bar and swap the footer hints."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.screen import (
        COMMAND_LINE_BLOCK_HINTS,
        COMMAND_LINE_INPUT_HINTS,
    )
    from sase.ace.tui.command_line.session import command_line_session_for
    from textual.widgets import Static

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_seeded_panel(
                page, monkeypatch, ["bead list", "bead show sase-1"]
            )
            _to_normal(screen)
            assert screen.handle_block_nav_key("j") is True
            session = command_line_session_for(page.app)
            selected = session.selected_block()
            assert selected is session.blocks[-1]
            assert selected is not None and selected.unseen is False
            keys = screen.query_one("#command-line-keys", Static)
            assert "o expand" in keys.content
            assert COMMAND_LINE_BLOCK_HINTS in keys.content
            screen.handle_block_nav_key("k")
            assert session.selected_block() is session.blocks[0]
            screen.handle_block_nav_key("G")
            assert session.selected_block() is session.blocks[-1]
            screen.handle_block_nav_key("g")
            assert session.selected_block() is session.blocks[0]
            screen.focus_input()
            assert session.selected_block() is None
            assert COMMAND_LINE_INPUT_HINTS in keys.content


async def test_forwarded_j_key_moves_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A NORMAL-mode ``j`` in the input reaches the transcript selection."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_seeded_panel(
                page, monkeypatch, ["bead list", "bead show sase-1"]
            )
            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead list --status open")
            await page.pause()
            widget._enter_normal_mode()
            await page.pause()
            await page.press("j")
            await page.pause()
            session = command_line_session_for(page.app)
            assert session.selected_block() is session.blocks[-1]
            assert widget.text == "bead list --status open"


async def test_o_toggles_expand_and_x_removes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``o`` expands/collapses and ``x`` removes the selected block."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_seeded_panel(
                page, monkeypatch, ["bead list", "bead show sase-1"]
            )
            session = command_line_session_for(page.app)
            assert screen.handle_block_nav_key("bogus") is False
            screen.handle_block_nav_key("j")
            assert screen.handle_block_nav_key("o") is True
            expanded = session.selected_block()
            assert expanded is not None and expanded.expanded is True
            screen.handle_block_nav_key("o")
            collapsed = session.selected_block()
            assert collapsed is not None and collapsed.expanded is False
            assert screen.handle_block_nav_key("x") is True
            assert [block.line for block in session.blocks] == ["bead list"]
            assert session.selected_block() is session.blocks[0]


async def test_e_loads_line_into_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``e`` loads the selected command back into the input for editing."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.input import CommandLineInput

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_seeded_panel(page, monkeypatch, ["bead show sase-9"])
            screen.handle_block_nav_key("j")
            assert screen.handle_block_nav_key("e") is True
            assert screen.query_one(CommandLineInput).text == "bead show sase-9"
            assert screen.selected_block() is None


async def test_r_reruns_and_R_appends_confirm_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``r`` reruns the line; ``R`` reruns visibly appended with ``-y``."""
    from types import SimpleNamespace as _NS
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.session import command_line_session_for

    counter = {"n": 0}

    def _fake_submit(**kwargs: object) -> object:
        counter["n"] += 1
        return _NS(proc_id=f"proc-rerun-{counter['n']}")

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
        mock_patch.object(screen_module, "submit_in_worker", side_effect=_fake_submit),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            screen.handle_block_nav_key("j")
            assert screen.handle_block_nav_key("r") is True
            assert [block.line for block in session.blocks] == [
                "bead list",
                "bead list",
            ]
            assert session.selected_block() is session.blocks[-1]
            await page.pause_until_cpu_idle()
            assert session.blocks[-1].proc_id == "proc-rerun-1"
            screen.handle_block_nav_key("R")
            assert session.blocks[-1].line == "bead list -y"
            screen.handle_block_nav_key("R")
            assert session.blocks[-1].line == "bead list -y"


async def test_v_opens_pager_for_selected_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``v`` pushes the pager with the block's full output."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.pager.screen import PagerScreen

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            session.blocks[0].tail_text = "line one\nline two\n"
            session.blocks[0].tail_loaded = True
            screen.handle_block_nav_key("j")
            assert screen.handle_block_nav_key("v") is True
            await page.expect_modal("PagerScreen")
            assert isinstance(page.app.screen, PagerScreen)


async def test_v_loads_an_unloaded_tail_then_opens_pager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``v`` resumes on the app loop and opens the pager after a tail load."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.pager.screen import PagerScreen

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            block = session.blocks[0]
            block.proc_id = "proc-unloaded-tail"
            block.tail_loaded = False

            def _load_tail(loaded: CommandLineBlock) -> bool:
                loaded.tail_text = "loaded after v"
                loaded.tail_loaded = True
                return True

            monkeypatch.setattr(screen_module, "load_block_tail_text", _load_tail)
            screen.handle_block_nav_key("j")
            assert screen.handle_block_nav_key("v") is True
            await page.expect_modal("PagerScreen")
            assert isinstance(page.app.screen, PagerScreen)
            assert page.app.screen.document.sections[0].body.plain == "loaded after v"


async def test_p_opens_procs_with_focus_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``p`` opens Admin Center → Procs with the proc selected."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            session.blocks[0].proc_id = "proc-focus-1"
            screen.handle_block_nav_key("j")
            calls: list[tuple[Any, Any]] = []
            monkeypatch.setattr(
                page.app,
                "_open_config_center",
                lambda tab, **kwargs: calls.append((tab, kwargs)),
            )
            assert screen.handle_block_nav_key("p") is True
            assert calls == [("procs", {"proc_focus_target": "proc-focus-1"})]


async def test_y_and_Y_copy_output_and_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``y`` copies the output and ``Y`` copies the command line."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            session.blocks[0].tail_text = "some output\n"
            screen.handle_block_nav_key("j")
            copied: list[tuple[Any, Any]] = []

            def _stub_copy(owner: Any, value: Any, **kwargs: Any) -> None:
                copied.append((value, kwargs))

            monkeypatch.setattr(
                "sase.ace.tui.actions.clipboard.schedule_copy_delivery",
                _stub_copy,
            )
            assert screen.handle_block_nav_key("y") is True
            assert screen.handle_block_nav_key("Y") is True
            assert copied[0][0] == "some output\n"
            assert copied[1][0] == "bead list"


async def test_K_warns_when_finished_and_confirms_when_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``K`` warns on finished blocks and confirms (stubbed kill) on running."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_seeded_panel(page, monkeypatch, ["bead list"])
            session = command_line_session_for(page.app)
            session.blocks[0].status = "success"
            screen.handle_block_nav_key("j")
            notices: list[str] = []
            monkeypatch.setattr(
                page.app, "notify", lambda message, **kwargs: notices.append(message)
            )
            assert screen.handle_block_nav_key("K") is True
            assert notices == ["Proc already finished"]

            session.blocks[0].status = "running"
            session.blocks[0].proc_id = "proc-kill-1"
            killed: list[str] = []

            def _stub_kill(proc_id: str) -> str | None:
                killed.append(proc_id)
                return None

            monkeypatch.setattr(
                "sase.ace.tui.modals.procs_store_rows.kill_store_task",
                _stub_kill,
            )
            pushed: dict[str, Any] = {}
            orig_push = page.app.push_screen

            def _capture(pushed_screen: Any, callback: Any = None) -> Any:
                pushed["callback"] = callback
                return orig_push(pushed_screen, callback)

            monkeypatch.setattr(page.app, "push_screen", _capture)
            assert screen.handle_block_nav_key("K") is True
            await page.expect_modal("ConfirmActionModal")
            pushed["callback"](True)
            assert killed == ["proc-kill-1"]


async def test_procs_jump_focus_selects_block_on_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Procs ``⏎`` jump opens the panel with that block selected."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.session import command_line_session_for

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            from sase.ace.tui.command_line import screen as screen_module

            monkeypatch.setattr(
                screen_module, "read_command_line_store_rows", lambda: []
            )
            session = command_line_session_for(page.app)
            block = session.add_block("bead show p1")
            block.proc_id = "proc-jump-1"
            block.status = "success"
            session.focus_block_proc_id = "proc-jump-1"
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            await page.pause()
            assert session.selected_block() is block


def test_procs_enter_routes_command_line_rows_to_panel() -> None:
    """``⏎`` on a command-line row opens the block; other rows keep routing."""
    from sase.ace.tui.modals.procs_pane_agent_jump import ProcsPaneAgentJumpMixin

    calls: list[str] = []

    class _StubPane(ProcsPaneAgentJumpMixin):
        jump_mode_active = False

        def __init__(self, task: Any) -> None:
            self._task = task

        def _get_selected_task(self) -> Any:
            return self._task

        def action_open_command_line_block(self) -> None:
            calls.append("block")

        def action_open_monitor_agent(self) -> None:
            calls.append("agent")

    event: Any = SimpleNamespace(stopped=False)
    event.stop = lambda: setattr(event, "stopped", True)
    _StubPane(SimpleNamespace(tags=("command-line",))).on_option_list_option_selected(
        event
    )
    assert calls == ["block"]
    assert event.stopped is True

    _StubPane(
        SimpleNamespace(tags=(), origin="ace", proc_id="p1")
    ).on_option_list_option_selected(event)
    assert calls == ["block", "agent"]
