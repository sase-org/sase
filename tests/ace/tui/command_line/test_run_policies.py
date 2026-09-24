"""Run-policy tests for the ``:`` Command Line (run-policies phase).

Covers policy routing for every predicate (suspend and subprocess stubbed),
the declined → ``R`` flow, each built-in (``cd``, ``clear``, ``help``,
``history``), cd pin/unpin effects on the chip and submission cwd, and the
guard that built-in names never collide with top-level spec commands.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.command_line.block_render import (
    block_header_right,
    gutter_glyph,
)
from sase.ace.tui.command_line.builtins import (
    BUILTIN_NAMES,
    builtin_name_for,
    render_help,
    render_history,
    run_cd,
    run_clear,
)
from sase.ace.tui.command_line.context import (
    CommandLineContext,
    resolve_working_context,
    working_context_chip,
)
from sase.ace.tui.command_line.policies import (
    append_confirm_flag,
    deny_note_for,
    is_confirmation_declined,
    run_in_terminal,
    submit_route_for,
)
from sase.ace.tui.command_line.session import (
    CommandLineBlock,
    CommandLineSession,
)
from sase.ace.tui.command_line.submit import (
    apply_exit_completion,
    apply_local_block,
    capture_resolve_context,
)
from sase.history import command_line as history_store


def _context(
    policy: str = "proc",
    note: str | None = None,
    *,
    confirms: bool = False,
    confirm_flag_present: bool = False,
) -> dict[str, Any]:
    return {
        "run_policy": {"policy": policy, "note": note},
        "confirms": confirms,
        "confirm_flag_present": confirm_flag_present,
    }


def _block(**kwargs: Any) -> CommandLineBlock:
    return CommandLineBlock(block_id="block-1", line="bead close sase-1", **kwargs)


# -- policy routing --------------------------------------------------------


def test_submit_route_defaults_to_proc() -> None:
    """Missing, empty, or unknown policies all route to the proc path."""
    assert submit_route_for(None) == "proc"
    assert submit_route_for({}) == "proc"
    assert submit_route_for(_context("proc")) == "proc"
    assert submit_route_for(_context("teleport")) == "proc"


def test_submit_route_foreground_and_deny() -> None:
    """Foreground and deny policies route off the proc path."""
    assert submit_route_for(_context("foreground")) == "foreground"
    assert submit_route_for(_context("deny", note="use a service")) == "deny"


def test_deny_note_never_blank() -> None:
    """Deny blocks always show the policy note or a fallback."""
    assert deny_note_for(_context("deny", note="use a service")) == "use a service"
    assert deny_note_for(_context("deny")) == "not runnable from the Command Line"
    assert deny_note_for(None) == "not runnable from the Command Line"


def test_run_in_terminal_suspends_and_returns_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreground runs suspend the app and report the process exit code."""
    import sase.ace.tui.command_line.policies as policies_module

    calls: dict[str, Any] = {}
    suspended = {"active": False}

    class _FakeApp:
        @contextmanager
        def suspend(self):  # type: ignore[no-untyped-def]
            suspended["active"] = True
            try:
                yield
            finally:
                suspended["active"] = False

    def _fake_run(
        argv: list[str], *, cwd: str | None, env: Any, check: bool
    ) -> SimpleNamespace:
        calls["argv"] = argv
        calls["cwd"] = cwd
        assert suspended["active"] is True
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(policies_module.subprocess, "run", _fake_run)
    exit_code = run_in_terminal(_FakeApp(), ["sase", "prompt", "edit"], cwd="/tmp")
    assert exit_code == 3
    assert calls["argv"] == ["sase", "prompt", "edit"]
    assert calls["cwd"] == "/tmp"
    assert suspended["active"] is False


# -- confirmation-aware declined blocks ------------------------------------


def test_append_confirm_flag_is_visible_and_idempotent() -> None:
    """``R`` appends ``-y`` visibly and never duplicates an existing flag."""
    assert append_confirm_flag("bead close sase-1") == "bead close sase-1 -y"
    assert append_confirm_flag("bead close sase-1 -y") == "bead close sase-1 -y"
    assert append_confirm_flag("bead close sase-1 --yes") == "bead close sase-1 --yes"
    assert append_confirm_flag("bead close --yes=all sase-1") == (
        "bead close --yes=all sase-1"
    )


def test_is_confirmation_declined_matrix() -> None:
    """Only confirms-without-flag plus a non-zero exit counts as declined."""
    assert (
        is_confirmation_declined(confirms=True, confirm_flag_present=False, exit_code=2)
        is True
    )
    assert (
        is_confirmation_declined(confirms=True, confirm_flag_present=True, exit_code=2)
        is False
    )
    assert (
        is_confirmation_declined(confirms=True, confirm_flag_present=False, exit_code=0)
        is False
    )
    assert (
        is_confirmation_declined(
            confirms=False, confirm_flag_present=False, exit_code=2
        )
        is False
    )
    assert (
        is_confirmation_declined(
            confirms=True, confirm_flag_present=False, exit_code=None
        )
        is False
    )


def test_exit_completion_marks_declined_blocks() -> None:
    """A confirms-without-``-y`` failure settles as ``⊘ declined``."""
    block = _block(confirms=True, confirm_flag_present=False)
    apply_exit_completion(block, exit_code=2, status="success")
    assert block.status == "error"
    assert block.declined is True
    assert gutter_glyph(block.status, declined=block.declined) == "⊘"
    assert (
        block_header_right(block.status, exit_code=2, declined=block.declined)
        == "declined · exit 2 · R rerun with -y"
    )


def test_exit_completion_leaves_non_declines_alone() -> None:
    """Success, ``-y`` runs, and kills never render as declined."""
    confirmed = _block(confirms=True, confirm_flag_present=True)
    apply_exit_completion(confirmed, exit_code=2, status="success")
    assert confirmed.declined is False
    assert gutter_glyph(confirmed.status) == "✗"

    passed = _block(confirms=True, confirm_flag_present=False)
    apply_exit_completion(passed, exit_code=0, status="success")
    assert passed.status == "success"
    assert passed.declined is False

    killed = _block(confirms=True, confirm_flag_present=False)
    apply_exit_completion(killed, exit_code=None, status="killed")
    assert killed.declined is False


def test_capture_resolve_context_feeds_declined_logic() -> None:
    """Submit-time capture carries the resolver's confirm flags to the block."""
    block = _block()
    capture_resolve_context(block, _context(confirms=True))
    assert (block.confirms, block.confirm_flag_present) == (True, False)
    capture_resolve_context(block, None)
    assert (block.confirms, block.confirm_flag_present) == (False, False)


# -- local (non-proc) blocks -------------------------------------------------


def test_apply_local_block_finishes_instantly() -> None:
    """Denied, foreground, and built-in blocks finish with no proc."""
    for status in ("denied", "foreground", "builtin"):
        block = _block()
        apply_local_block(block, status=status, text="note", exit_code=2)
        assert block.status == status
        assert block.tail_text == "note"
        assert block.tail_loaded is True
        assert block.proc_id is None
        assert block.running is False


def test_renderers_cover_policy_statuses() -> None:
    """Every new status has a distinct gutter and header."""
    assert gutter_glyph("foreground") == "↗"
    assert gutter_glyph("builtin") == "›"
    assert gutter_glyph("denied") == "⊘"
    assert block_header_right("foreground", exit_code=0) == "ran in terminal · exit 0"
    assert block_header_right("denied") == "not run"
    assert block_header_right("builtin") == "built-in"


def test_block_widgets_render_policy_blocks() -> None:
    """Transcript widgets show the policy glyphs, hints, and bodies."""
    from sase.ace.tui.command_line.transcript import CommandLineBlockWidget

    declined = _block()
    declined.status = "error"
    declined.tail_text = "Restart would stop 1 agent.\n"
    declined.exit_code = 2
    declined.declined = True
    text = str(CommandLineBlockWidget.render_block(declined))
    assert "⊘" in text
    assert "declined · exit 2 · R rerun with -y" in text
    assert "Restart would stop 1 agent." in text

    denied = _block()
    denied.status = "denied"
    denied.tail_text = "You're already in the TUI\n"
    text = str(CommandLineBlockWidget.render_block(denied))
    assert "⊘" in text
    assert "not run" in text
    assert "You're already in the TUI" in text

    foreground = _block()
    foreground.status = "foreground"
    foreground.exit_code = 0
    text = str(CommandLineBlockWidget.render_block(foreground))
    assert "↗" in text
    assert "ran in terminal · exit 0" in text

    builtin = _block()
    builtin.status = "builtin"
    builtin.tail_text = "pinned · /tmp\n"
    text = str(CommandLineBlockWidget.render_block(builtin))
    assert "›" in text
    assert "built-in" in text
    assert "pinned · /tmp" in text


# -- built-ins ---------------------------------------------------------------


def test_builtin_names_recognized_by_first_token() -> None:
    """Only a first-token built-in name intercepts the line."""
    for name in BUILTIN_NAMES:
        assert builtin_name_for([name]) == name
        assert builtin_name_for([name, "extra", "args"]) == name
    assert builtin_name_for([]) is None
    assert builtin_name_for(["bead", "list"]) is None
    assert builtin_name_for(["bead", "cd"]) is None


def _top_level_spec_commands() -> set[str]:
    """Return live top-level ``sase`` command names (guard-test source)."""
    from sase.completion.build import build_spec

    return {child.name for child in build_spec().root.subcommands}


def test_builtin_names_never_collide_with_spec_commands() -> None:
    """Guard: ``<cmd> -h`` keeps reaching argparse for every built-in name."""
    assert sorted(set(BUILTIN_NAMES) & _top_level_spec_commands()) == []


def test_cd_pins_unpins_and_rejects(tmp_path: Path) -> None:
    """``cd`` pins real dirs, ``cd -`` unpins, and errors stay unpinned."""
    session = CommandLineSession()
    target = tmp_path / "work"
    target.mkdir()

    outcome = run_cd(session, str(target), cwd="/")
    assert outcome.exit_code == 0
    assert session.cwd_pin == str(target)
    assert "pinned" in outcome.text

    outcome = run_cd(session, "-", cwd="/")
    assert outcome.exit_code == 0
    assert session.cwd_pin is None
    assert "unpinned" in outcome.text

    outcome = run_cd(session, str(tmp_path / "missing"), cwd="/")
    assert outcome.exit_code == 2
    assert session.cwd_pin is None

    outcome = run_cd(session, None, cwd="/")
    assert "usage" in outcome.text
    assert session.cwd_pin is None


def test_cd_resolves_relative_paths_and_projects(tmp_path: Path) -> None:
    """Relative dirs resolve against the submission cwd; ``+name`` via lookup."""
    session = CommandLineSession()
    (tmp_path / "sub").mkdir()
    outcome = run_cd(session, "sub", cwd=str(tmp_path))
    assert session.cwd_pin == str(tmp_path / "sub")

    outcome = run_cd(
        session, "+sase", cwd="/", resolve_project=lambda name: "/proj/sase"
    )
    assert outcome.exit_code == 0
    assert session.cwd_pin == "/proj/sase"

    outcome = run_cd(session, "+nope", cwd="/", resolve_project=lambda name: None)
    assert outcome.exit_code == 2


def test_cd_pin_drives_chip_and_submission_cwd(tmp_path: Path) -> None:
    """A pin marks the chip and becomes the next submission's cwd."""
    session = CommandLineSession()
    session.cwd_pin = str(tmp_path)
    context = resolve_working_context(SimpleNamespace(), session)
    assert context.cwd == str(tmp_path)
    assert context.pinned is True
    assert "(pinned)" in working_context_chip(context)
    assert isinstance(context, CommandLineContext)


def test_clear_keeps_running_blocks() -> None:
    """``clear`` drops finished blocks; running procs are untouched."""
    session = CommandLineSession()
    finished = session.add_block("bead list")
    finished.status = "success"
    running = session.add_block("agent wait x")
    running.status = "running"
    outcome = run_clear(session)
    assert outcome.exit_code == 0
    assert session.blocks == [running]


def test_help_renders_command_help() -> None:
    """``help`` renders usage, options, and children from ``command_help``."""
    view = {
        "usage": "bead close ‹ID…› [-n NOTE]",
        "summary": "Close beads.",
        "positionals": [{"metavar": "ID…", "summary": "Bead ids."}],
        "options": [{"strings": ["-n", "--note"], "summary": "Note."}],
        "children": [{"name": "list", "summary": "List beads."}],
    }
    outcome = render_help(view, ["bead", "close"])
    assert outcome.exit_code == 0
    assert "bead close" in outcome.text
    assert "-n" in outcome.text
    assert "ID…" in outcome.text

    missing = render_help(None, ["bead", "nope"])
    assert missing.exit_code == 2
    assert "bead nope" in missing.text


def test_history_lists_and_filters() -> None:
    """``history`` lists recent lines and filters on an optional query."""
    entries = [
        SimpleNamespace(line="bead list"),
        SimpleNamespace(line="agent wait x"),
    ]
    assert render_history(entries, None).text == "bead list\nagent wait x"
    assert render_history(entries, "agent").text == "agent wait x"
    assert render_history(entries, "zzz").text == "(no matching history)"


# -- panel submit wiring -----------------------------------------------------


async def _open_panel(
    page: Any, monkeypatch: pytest.MonkeyPatch, history_file: Path
) -> Any:
    """Open the panel with restore stubbed and history isolated to tmp."""
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.screen import CommandLineScreen

    monkeypatch.setattr(screen_module, "read_command_line_store_rows", lambda: [])
    monkeypatch.setattr(history_store, "_history_file_override", history_file)
    page.app.action_open_command_line()
    await page.expect_modal("CommandLineScreen")
    screen = page.app.screen
    assert isinstance(screen, CommandLineScreen)
    screen.transcript.stop_tail_task()
    await page.pause()
    return screen


async def test_deny_submit_adds_block_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Deny-policy lines render ``⊘ not run`` with the note and no history."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.feature_flags import override_flags

    history_file = tmp_path / "command_line_history.json"
    monkeypatch.setattr(
        screen_module,
        "resolve_command_line",
        lambda app, line, cursor: _context("deny", note="Foreground server"),
    )
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
        override_flags(ace_command_line=True),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_panel(page, monkeypatch, history_file)
            assert screen._submit_line("tui") is True
            session = command_line_session_for(page.app)
            assert len(session.blocks) == 1
            block = session.blocks[0]
            assert block.status == "denied"
            assert block.proc_id is None
            assert "Foreground server" in block.tail_text
            await page.pause_until_cpu_idle()
            assert not history_file.exists()


async def test_foreground_submit_runs_in_terminal_and_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Foreground-policy lines suspend, run, and render a ``↗`` block."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.context import CommandLineContext
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.feature_flags import override_flags

    history_file = tmp_path / "command_line_history.json"
    calls: dict[str, Any] = {}

    def _fake_run(app: Any, argv: list[str], *, cwd: str) -> int:
        calls["argv"] = argv
        calls["cwd"] = cwd
        return 0

    monkeypatch.setattr(
        screen_module,
        "resolve_command_line",
        lambda app, line, cursor: _context("foreground"),
    )
    monkeypatch.setattr(screen_module, "run_in_terminal", _fake_run)
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
        override_flags(ace_command_line=True),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_panel(page, monkeypatch, history_file)
            screen._working_context = CommandLineContext(cwd="/tmp", project=None)
            assert screen._submit_line("prompt edit") is True
            session = command_line_session_for(page.app)
            assert len(session.blocks) == 1
            block = session.blocks[0]
            assert block.status == "foreground"
            assert block.exit_code == 0
            assert block.proc_id is None
            assert calls["argv"] == ["sase", "prompt", "edit"]
            assert calls["cwd"] == "/tmp"


async def test_builtin_cd_submit_pins_and_renders_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``cd`` submits as a ``›`` block and pins the working context."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.context import CommandLineContext
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.feature_flags import override_flags

    history_file = tmp_path / "command_line_history.json"
    target = tmp_path / "work"
    target.mkdir()
    monkeypatch.setattr(
        screen_module, "resolve_command_line", lambda app, line, cursor: None
    )
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
        override_flags(ace_command_line=True),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_panel(page, monkeypatch, history_file)
            screen._working_context = CommandLineContext(cwd="/tmp", project=None)
            assert screen._submit_line(f"cd {target}") is True
            session = command_line_session_for(page.app)
            assert session.cwd_pin == str(target)
            assert len(session.blocks) == 1
            block = session.blocks[0]
            assert block.status == "builtin"
            assert block.proc_id is None
            assert "pinned" in block.tail_text
            assert screen._working_context.pinned is True


async def test_proc_submit_captures_confirm_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proc-path submits capture the resolver flags for declined detection."""
    from types import SimpleNamespace as _NS
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.session import command_line_session_for
    from sase.feature_flags import override_flags

    history_file = tmp_path / "command_line_history.json"
    monkeypatch.setattr(
        screen_module,
        "resolve_command_line",
        lambda app, line, cursor: _context(
            "proc", confirms=True, confirm_flag_present=False
        ),
    )
    monkeypatch.setattr(
        screen_module,
        "submit_in_worker",
        lambda **kwargs: _NS(proc_id="proc-confirm-1"),
    )
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
        override_flags(ace_command_line=True),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            screen = await _open_panel(page, monkeypatch, history_file)
            assert screen._submit_line("bead close sase-1") is True
            session = command_line_session_for(page.app)
            block = session.blocks[0]
            assert block.confirms is True
            assert block.confirm_flag_present is False
