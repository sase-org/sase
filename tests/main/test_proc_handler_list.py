"""Behavior tests for the ``sase proc list`` handler."""

from __future__ import annotations

import json
import os
import sys

import pytest

from sase.procs import get_proc
from tests.main.proc_handler_helpers import (
    dead_pid,
    dispatch,
    stored,
    proc_home,
)

__all__ = ["proc_home"]


def test_list_renders_a_row_and_glyph_for_every_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each lifecycle state gets its own glyph in the newest-first table."""
    # Give Rich enough deterministic width for every full label under xdist;
    # otherwise the live-duration column can squeeze "Proc pending" to an
    # ellipsis depending on the wall clock when the worker renders the table.
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setattr(
        "sase.procs.runner._supervisor_process_matches", lambda _task: True
    )
    statuses = ("pending", "running", "success", "error", "killed")
    for index, status in enumerate(statuses):
        active = status in ("pending", "running")
        stored(
            f"{index}00000000000",
            status=status,
            label=status,
            created_at=f"2026-07-25T12:0{index}:00Z",
            finished_at=None if active else "2026-07-25T12:09:00Z",
            exit_code=None if active else 0,
            # A live supervisor keeps reconciliation from terminalizing the row.
            pid=os.getpid() if active else None,
        )

    assert dispatch(["proc", "list"]) == 0

    out = capsys.readouterr().out
    for glyph in ("◌", "●", "✓", "✗", "⊘"):
        assert glyph in out
    assert out.index("killed") < out.index("pending")


def test_bare_proc_command_announces_the_list_delegation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``sase proc`` reaches the list view through the shared delegation."""
    from sase.main import entry

    monkeypatch.setattr(sys, "argv", ["sase", "proc"])

    with pytest.raises(SystemExit) as exit_info:
        entry.main()

    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    notice = "No subcommand provided for 'sase proc'; delegating to 'sase proc list'."
    assert notice in out
    assert out.index(notice) < out.index("sase proc run -- <command>")


def test_list_empty_store_renders_the_run_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty store gets a friendly panel that names ``sase proc run``."""
    assert dispatch(["proc", "list"]) == 0

    out = capsys.readouterr().out
    assert "sase proc run -- <command>" in out
    assert "hidden" not in out


def test_list_scopes_to_this_session_and_unattributed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Other sessions' rows are hidden by default and named in the hint."""
    stored("aaaaaaaaaaaa", label="Other session", session_id="20260725T120000Z-42")

    assert dispatch(["proc", "list"]) == 0

    out = capsys.readouterr().out
    assert "Other session" not in out
    assert "1 proc from other sessions is hidden; pass -a/--all." in out


def test_list_keeps_detached_procs_global_even_for_an_explicit_session(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Detached ownership ignores session scope while other sessions stay hidden."""
    stored(
        "aaaaaaaaaaaa",
        label="Global launch",
        kind="detached",
        session_id=None,
    )
    stored(
        "bbbbbbbbbbbb",
        label="Other session",
        session_id="20260725T120000Z-42",
    )

    assert dispatch(["proc", "list", "--session", "none"]) == 0

    out = capsys.readouterr().out
    assert "Global launch" in out
    assert "detached" in out
    assert "Other session" not in out


def test_list_all_includes_other_sessions_with_a_dead_chip(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--all`` shows every row, marking sessions that are no longer live."""
    stored(
        "aaaaaaaaaaaa",
        label="Other",
        session_id="20260725T120000Z-42",
        session_label="ace·sase#3",
    )

    assert dispatch(["proc", "list", "--all"]) == 0

    out = capsys.readouterr().out
    assert "all sessions" in out
    assert "†" in out


def test_list_all_and_session_conflict(capsys: pytest.CaptureFixture[str]) -> None:
    """``--all`` and ``--session`` are mutually exclusive scopes."""
    assert dispatch(["proc", "list", "--all", "-s", "latest"]) == 2

    assert "--all cannot be combined with --session" in capsys.readouterr().err


def test_list_unknown_session_reference_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unresolvable ``--session`` reference reports the live candidates."""
    assert dispatch(["proc", "list", "-s", "nope"]) == 2

    assert "no live session matches" in capsys.readouterr().err


def test_list_applies_status_project_tag_query_and_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Filters compose, and ``--limit`` trims the newest-first result."""
    stored(
        "aaaaaaaaaaaa", label="Docs", tags=["docs"], created_at="2026-07-25T12:00:00Z"
    )
    stored(
        "bbbbbbbbbbbb",
        label="Broken",
        status="error",
        exit_code=3,
        tags=["docs"],
        created_at="2026-07-25T12:01:00Z",
    )
    stored(
        "cccccccccccc",
        label="Elsewhere",
        project="other",
        created_at="2026-07-25T12:02:00Z",
    )

    assert dispatch(["proc", "list", "-S", "error"]) == 0
    errors = capsys.readouterr().out
    assert "Broken" in errors and "Docs" not in errors

    assert dispatch(["proc", "list", "-p", "other"]) == 0
    projects = capsys.readouterr().out
    assert "Elsewhere" in projects and "Broken" not in projects

    assert dispatch(["proc", "list", "-t", "docs", "-n", "1"]) == 0
    limited = capsys.readouterr().out
    assert "Broken" in limited and "Docs" not in limited

    assert dispatch(["proc", "list", "-q", "elsew"]) == 0
    assert "Elsewhere" in capsys.readouterr().out


def test_list_filters_by_repeated_kind_and_detached_shorthand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--kind`` composes, while ``--detached`` selects only global work."""
    stored("aaaaaaaaaaaa", label="Command proc")
    stored("bbbbbbbbbbbb", label="Detached proc", kind="detached")
    stored("cccccccccccc", label="TUI proc", kind="tui")

    assert dispatch(["proc", "list", "--detached"]) == 0
    detached = capsys.readouterr().out
    assert "Detached proc" in detached
    assert "◆" in detached
    assert "Command proc" not in detached
    assert "TUI proc" not in detached

    assert dispatch(["proc", "list", "-k", "command", "-k", "tui"]) == 0
    combined = capsys.readouterr().out
    assert "Command proc" in combined
    assert "⌘" in combined
    assert "TUI proc" in combined
    assert "▣" in combined
    assert "Detached proc" not in combined


def test_list_running_filter_matches_pending_and_running(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--running`` covers both active states and nothing terminal."""
    monkeypatch.setattr(
        "sase.procs.runner._supervisor_process_matches", lambda _task: True
    )
    stored(
        "aaaaaaaaaaaa",
        label="Waiting",
        status="pending",
        finished_at=None,
        exit_code=None,
        pid=os.getpid(),
    )
    stored(
        "bbbbbbbbbbbb",
        label="Working",
        status="running",
        finished_at=None,
        exit_code=None,
        pid=os.getpid(),
    )
    stored("cccccccccccc", label="Finished")

    assert dispatch(["proc", "list", "-r"]) == 0

    out = capsys.readouterr().out
    assert "Waiting" in out and "Working" in out and "Finished" not in out


def test_list_json_envelope_is_stable(capsys: pytest.CaptureFixture[str]) -> None:
    """The JSON envelope carries schema, scope, count, and derived fields."""
    stored("aaaaaaaaaaaa", label="Docs", tags=["docs"])

    assert dispatch(["proc", "list", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["count"] == 1
    assert payload["scope"] == {
        "all": False,
        "include_detached": True,
        "include_unattributed": True,
        "ref": None,
        "session_id": None,
    }
    proc = payload["procs"][0]
    assert proc["proc_id"] == "aaaaaaaaaaaa"
    assert proc["short_id"] == "aaaaaa"
    assert proc["is_terminal"] is True
    assert proc["detached"] is False
    assert proc["duration_seconds"] == 5.0
    assert proc["session_handle"] is None


def test_list_reconciles_a_supervisor_that_never_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A running row whose supervisor is gone renders as an error."""
    stored(
        "aaaaaaaaaaaa",
        label="Ghost",
        status="running",
        finished_at=None,
        exit_code=None,
        pid=dead_pid(),
    )

    assert dispatch(["proc", "list"]) == 0

    assert "✗" in capsys.readouterr().out
    reconciled = get_proc("aaaaaaaaaaaa")
    assert reconciled is not None
    assert reconciled.status == "error"
    assert reconciled.message == "supervisor exited without reporting"
