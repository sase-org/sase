"""Behavior tests for the ``sase task`` list, show, and run handlers."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.main.task_handler import handle_task_command
from sase.sessions import SessionIdentity
from sase.tasks import BackgroundTask, append_task, get_task, task_log_path


@pytest.fixture(autouse=True)
def task_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point every task, log, and session path at an isolated home."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    _use_sessions(monkeypatch, [])
    return home


def _use_sessions(
    monkeypatch: pytest.MonkeyPatch, sessions: list[SessionIdentity]
) -> None:
    """Pin every live-session lookup the CLI path can reach."""
    monkeypatch.setattr("sase.sessions.registry.live_sessions", lambda: list(sessions))
    monkeypatch.setattr("sase.sessions.live_sessions", lambda: list(sessions))
    monkeypatch.setattr("sase.main.task_handler.live_sessions", lambda: list(sessions))


# A command that exists everywhere and exits immediately.
_NOOP = (sys.executable, "-c", "pass")


def _dispatch(argv: list[str]) -> int:
    """Run one ``sase task`` invocation and return its process exit code."""
    with pytest.raises(SystemExit) as exit_info:
        handle_task_command(create_parser().parse_args(argv))
    return int(exit_info.value.code or 0)


def _stored(
    task_id: str,
    *,
    status: str = "success",
    label: str = "Build docs",
    created_at: str = "2026-07-25T12:00:00Z",
    started_at: str | None = "2026-07-25T12:00:00Z",
    finished_at: str | None = "2026-07-25T12:00:05Z",
    exit_code: int | None = 0,
    session_id: str | None = None,
    session_label: str | None = None,
    project: str | None = "sase",
    tags: list[str] | None = None,
    pid: int | None = None,
    command: list[str] | None = None,
    kind: str = "command",
) -> BackgroundTask:
    task = BackgroundTask(
        task_id=task_id,
        label=label,
        kind=kind,
        status=status,
        command=command or ["just", "docs"],
        cwd="/tmp",
        project=project,
        session_id=session_id,
        session_label=session_label,
        origin="cli",
        tags=tags or [],
        pid=pid,
        exit_code=exit_code,
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
        log_path=str(task_log_path(task_id)),
    )
    append_task(task)
    return task


def _write_log(task_id: str, text: str) -> None:
    path = task_log_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_list_renders_a_row_and_glyph_for_every_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each lifecycle state gets its own glyph in the newest-first table."""
    statuses = ("pending", "running", "success", "error", "killed")
    for index, status in enumerate(statuses):
        active = status in ("pending", "running")
        _stored(
            f"{index}00000000000",
            status=status,
            label=f"Task {status}",
            created_at=f"2026-07-25T12:0{index}:00Z",
            finished_at=None if active else "2026-07-25T12:09:00Z",
            exit_code=None if active else 0,
            # A live supervisor keeps reconciliation from terminalizing the row.
            pid=os.getpid() if active else None,
        )

    assert _dispatch(["task", "list"]) == 0

    out = capsys.readouterr().out
    for glyph in ("◌", "●", "✓", "✗", "⊘"):
        assert glyph in out
    assert out.index("Task killed") < out.index("Task pending")


def test_bare_task_command_announces_the_list_delegation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``sase task`` reaches the list view through the shared delegation."""
    from sase.main import entry

    monkeypatch.setattr(sys, "argv", ["sase", "task"])

    with pytest.raises(SystemExit) as exit_info:
        entry.main()

    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    notice = "No subcommand provided for 'sase task'; delegating to 'sase task list'."
    assert notice in out
    assert out.index(notice) < out.index("sase task run -- <command>")


def test_list_empty_store_renders_the_run_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty store gets a friendly panel that names ``sase task run``."""
    assert _dispatch(["task", "list"]) == 0

    out = capsys.readouterr().out
    assert "sase task run -- <command>" in out
    assert "hidden" not in out


def test_list_scopes_to_this_session_and_unattributed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Other sessions' rows are hidden by default and named in the hint."""
    _stored("aaaaaaaaaaaa", label="Other session", session_id="20260725T120000Z-42")

    assert _dispatch(["task", "list"]) == 0

    out = capsys.readouterr().out
    assert "Other session" not in out
    assert "1 task from other sessions is hidden; pass -a/--all." in out


def test_list_keeps_detached_tasks_global_even_for_an_explicit_session(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Detached ownership ignores session scope while other sessions stay hidden."""
    _stored(
        "aaaaaaaaaaaa",
        label="Global launch",
        kind="detached",
        session_id=None,
    )
    _stored(
        "bbbbbbbbbbbb",
        label="Other session",
        session_id="20260725T120000Z-42",
    )

    assert _dispatch(["task", "list", "--session", "none"]) == 0

    out = capsys.readouterr().out
    assert "Global launch" in out
    assert "detached" in out
    assert "Other session" not in out


def test_list_all_includes_other_sessions_with_a_dead_chip(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--all`` shows every row, marking sessions that are no longer live."""
    _stored(
        "aaaaaaaaaaaa",
        label="Other",
        session_id="20260725T120000Z-42",
        session_label="ace·sase#3",
    )

    assert _dispatch(["task", "list", "--all"]) == 0

    out = capsys.readouterr().out
    assert "all sessions" in out
    assert "†" in out


def test_list_all_and_session_conflict(capsys: pytest.CaptureFixture[str]) -> None:
    """``--all`` and ``--session`` are mutually exclusive scopes."""
    assert _dispatch(["task", "list", "--all", "-s", "latest"]) == 2

    assert "--all cannot be combined with --session" in capsys.readouterr().err


def test_list_unknown_session_reference_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unresolvable ``--session`` reference reports the live candidates."""
    assert _dispatch(["task", "list", "-s", "nope"]) == 2

    assert "no live session matches" in capsys.readouterr().err


def test_list_applies_status_project_tag_query_and_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Filters compose, and ``--limit`` trims the newest-first result."""
    _stored(
        "aaaaaaaaaaaa", label="Docs", tags=["docs"], created_at="2026-07-25T12:00:00Z"
    )
    _stored(
        "bbbbbbbbbbbb",
        label="Broken",
        status="error",
        exit_code=3,
        tags=["docs"],
        created_at="2026-07-25T12:01:00Z",
    )
    _stored(
        "cccccccccccc",
        label="Elsewhere",
        project="other",
        created_at="2026-07-25T12:02:00Z",
    )

    assert _dispatch(["task", "list", "-S", "error"]) == 0
    errors = capsys.readouterr().out
    assert "Broken" in errors and "Docs" not in errors

    assert _dispatch(["task", "list", "-p", "other"]) == 0
    projects = capsys.readouterr().out
    assert "Elsewhere" in projects and "Broken" not in projects

    assert _dispatch(["task", "list", "-t", "docs", "-n", "1"]) == 0
    limited = capsys.readouterr().out
    assert "Broken" in limited and "Docs" not in limited

    assert _dispatch(["task", "list", "-q", "elsew"]) == 0
    assert "Elsewhere" in capsys.readouterr().out


def test_list_filters_by_repeated_kind_and_detached_shorthand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--kind`` composes, while ``--detached`` selects only global work."""
    _stored("aaaaaaaaaaaa", label="Command task")
    _stored("bbbbbbbbbbbb", label="Detached task", kind="detached")
    _stored("cccccccccccc", label="TUI task", kind="tui")

    assert _dispatch(["task", "list", "--detached"]) == 0
    detached = capsys.readouterr().out
    assert "Detached task" in detached
    assert "◆" in detached
    assert "Command task" not in detached
    assert "TUI task" not in detached

    assert _dispatch(["task", "list", "-k", "command", "-k", "tui"]) == 0
    combined = capsys.readouterr().out
    assert "Command task" in combined
    assert "⌘" in combined
    assert "TUI task" in combined
    assert "▣" in combined
    assert "Detached task" not in combined


def test_list_running_filter_matches_pending_and_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--running`` covers both active states and nothing terminal."""
    _stored(
        "aaaaaaaaaaaa",
        label="Waiting",
        status="pending",
        finished_at=None,
        exit_code=None,
        pid=os.getpid(),
    )
    _stored(
        "bbbbbbbbbbbb",
        label="Working",
        status="running",
        finished_at=None,
        exit_code=None,
        pid=os.getpid(),
    )
    _stored("cccccccccccc", label="Finished")

    assert _dispatch(["task", "list", "-r"]) == 0

    out = capsys.readouterr().out
    assert "Waiting" in out and "Working" in out and "Finished" not in out


def test_list_json_envelope_is_stable(capsys: pytest.CaptureFixture[str]) -> None:
    """The JSON envelope carries schema, scope, count, and derived fields."""
    _stored("aaaaaaaaaaaa", label="Docs", tags=["docs"])

    assert _dispatch(["task", "list", "--json"]) == 0

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
    task = payload["tasks"][0]
    assert task["task_id"] == "aaaaaaaaaaaa"
    assert task["short_id"] == "aaaaaa"
    assert task["is_terminal"] is True
    assert task["detached"] is False
    assert task["duration_seconds"] == 5.0
    assert task["session_handle"] is None


def test_list_reconciles_a_supervisor_that_never_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A running row whose supervisor is gone renders as an error."""
    _stored(
        "aaaaaaaaaaaa",
        label="Ghost",
        status="running",
        finished_at=None,
        exit_code=None,
        pid=_dead_pid(),
    )

    assert _dispatch(["task", "list"]) == 0

    assert "✗" in capsys.readouterr().out
    reconciled = get_task("aaaaaaaaaaaa")
    assert reconciled is not None
    assert reconciled.status == "error"
    assert reconciled.message == "supervisor exited without reporting"


def test_show_renders_detail_and_log_tail(capsys: pytest.CaptureFixture[str]) -> None:
    """The default view is the header panel followed by the log tail."""
    _stored("aaaaaaaaaaaa", label="Docs", tags=["docs"])
    _write_log("aaaaaaaaaaaa", "first\nsecond\nthird\n")

    assert _dispatch(["task", "show", "aaa", "-l", "2"]) == 0

    out = capsys.readouterr().out
    assert "Docs" in out
    assert "✓ success" in out
    assert "second" in out and "third" in out
    assert "first" not in out


def test_show_names_detached_global_ownership(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Detached detail makes the lack of a session explicit."""
    _stored("aaaaaaaaaaaa", label="Epic launch", kind="detached")

    assert _dispatch(["task", "show", "aaa"]) == 0

    assert "detached (global; no session owns this task)" in capsys.readouterr().out


def test_show_output_only_prints_the_log_without_chrome(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--output-only`` stays pipe friendly."""
    _stored("aaaaaaaaaaaa", label="Docs")
    _write_log("aaaaaaaaaaaa", "one\ntwo\n")

    assert _dispatch(["task", "show", "aaa", "-o", "-A"]) == 0

    assert capsys.readouterr().out == "one\ntwo\n"


def test_show_json_includes_the_task_and_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--format json`` emits one envelope carrying the captured output."""
    _stored("aaaaaaaaaaaa", label="Docs")
    _write_log("aaaaaaaaaaaa", "captured\n")

    assert _dispatch(["task", "show", "aaa", "-f", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["task"]["label"] == "Docs"
    assert payload["log"] == "captured\n"


def test_show_reports_unknown_short_and_ambiguous_references(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every bad reference is a usage error naming what went wrong."""
    _stored("aaaaaaaaaaaa", label="One")
    _stored("aaaabbbbbbbb", label="Two", created_at="2026-07-25T12:01:00Z")

    assert _dispatch(["task", "show", "zzz"]) == 2
    assert "no task matches reference" in capsys.readouterr().err

    assert _dispatch(["task", "show", "aa"]) == 2
    assert "at least 3 characters" in capsys.readouterr().err

    assert _dispatch(["task", "show", "aaa"]) == 2
    assert "is ambiguous" in capsys.readouterr().err


def test_show_follow_on_a_terminal_task_returns_immediately(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--follow`` prints the retained log once and exits for a done task."""
    _stored("aaaaaaaaaaaa", label="Docs")
    _write_log("aaaaaaaaaaaa", "alpha\nbeta\n")

    assert _dispatch(["task", "show", "aaa", "-F", "-o"]) == 0

    assert capsys.readouterr().out == "alpha\nbeta\n"


def test_show_follow_json_waits_for_the_finished_task(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``--follow --format json`` blocks and reports the terminal record."""
    assert (
        _dispatch(
            [
                "task",
                "run",
                "-q",
                "-c",
                str(tmp_path),
                "--",
                sys.executable,
                "-c",
                "import time; time.sleep(0.3)",
            ]
        )
        == 0
    )
    task_id = capsys.readouterr().out.strip()

    assert _dispatch(["task", "show", task_id, "-F", "-f", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["task"]["status"] == "success"
    assert payload["task"]["finished_at"] is not None


def test_run_without_a_command_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``sase task run`` with nothing after ``--`` explains the syntax."""
    assert _dispatch(["task", "run"]) == 2

    assert "pass it after --" in capsys.readouterr().err


def test_run_prints_the_id_and_the_follow_hint(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A detached submit reports the new id plus how to watch it."""
    assert _dispatch(["task", "run", "-c", str(tmp_path), "--", *_NOOP]) == 0

    out = capsys.readouterr().out.splitlines()
    assert len(out[0]) == 12
    assert out[1] == f"monitor with: sase task show {out[0][:6]} --follow"


def test_run_quiet_prints_only_the_task_id(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``--quiet`` is the scriptable form."""
    assert _dispatch(["task", "run", "-q", "-c", str(tmp_path), "--", *_NOOP]) == 0

    assert len(capsys.readouterr().out.strip()) == 12


def test_run_json_emits_the_created_task(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``--json`` describes the submitted task with its label and tags."""
    exit_code = _dispatch(
        [
            "task",
            "run",
            "-j",
            "-l",
            "Nightly",
            "-t",
            "docs",
            "-c",
            str(tmp_path),
            "--",
            *_NOOP,
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task"]["label"] == "Nightly"
    assert payload["task"]["tags"] == ["docs"]
    assert payload["task"]["origin"] == "cli"


def test_run_derives_a_label_from_the_command(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Without ``--label`` the command itself names the task."""
    _dispatch(["task", "run", "-j", "-c", str(tmp_path), "--", "echo", "hi"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["task"]["label"] == "echo hi"


def test_run_truncates_a_very_long_derived_label(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A derived label stays short enough to render in one table column."""
    _dispatch(["task", "run", "-j", "-c", str(tmp_path), "--", "echo", "x" * 200])

    label = json.loads(capsys.readouterr().out)["task"]["label"]
    assert len(label) == 72
    assert label.endswith("\u2026")


def test_run_rejects_a_missing_working_directory(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A bad ``--cwd`` fails before anything is spawned."""
    missing = tmp_path / "nope"

    assert _dispatch(["task", "run", "-c", str(missing), "--", "true"]) == 1

    assert "is not an existing directory" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("script", "expected"),
    [("raise SystemExit(0)", 0), ("raise SystemExit(3)", 3)],
)
def test_run_wait_streams_output_and_propagates_the_exit_code(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    script: str,
    expected: int,
) -> None:
    """``--wait`` mirrors the task's output and its exit status."""
    exit_code = _dispatch(
        [
            "task",
            "run",
            "-w",
            "-c",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            f"print('streamed', flush=True); {script}",
        ]
    )

    assert exit_code == expected
    assert "streamed" in capsys.readouterr().out


def test_run_wait_reports_a_signalled_command_like_a_shell(
    tmp_path: Path,
) -> None:
    """A child killed by a signal exits ``128 + N`` instead of a negative code."""
    exit_code = _dispatch(
        [
            "task",
            "run",
            "-w",
            "-c",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            "import os, signal; os.kill(os.getpid(), signal.SIGTERM)",
        ]
    )

    assert exit_code == 128 + 15


def test_run_wait_json_keeps_stdout_parseable(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``--json --wait`` streams the log to stderr and finishes on stdout."""
    exit_code = _dispatch(
        [
            "task",
            "run",
            "-j",
            "-w",
            "-c",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            "print('streamed', flush=True)",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "streamed" in captured.err
    assert json.loads(captured.out)["task"]["status"] == "success"


def test_run_attributes_the_task_to_the_resolved_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """With no explicit reference a task lands in the newest live session."""
    identity = SessionIdentity(
        session_id="20260725T120000Z-99",
        kind="ace",
        pid=os.getpid(),
        started_at="2026-07-25T12:00:00Z",
        project="sase",
        workspace_num=16,
    )
    _use_sessions(monkeypatch, [identity])

    _dispatch(["task", "run", "-j", "-c", str(tmp_path), "--", *_NOOP])

    payload = json.loads(capsys.readouterr().out)
    assert payload["task"]["session_id"] == identity.session_id
    assert payload["task"]["session_label"] == "ace\u00b7sase#16"
    assert payload["task"]["session_live"] is True


def test_run_session_none_leaves_the_task_unattributed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--session none`` opts out of session attribution entirely."""
    identity = SessionIdentity(
        session_id="20260725T120000Z-99",
        kind="ace",
        pid=os.getpid(),
        started_at="2026-07-25T12:00:00Z",
    )
    _use_sessions(monkeypatch, [identity])

    _dispatch(["task", "run", "-j", "-s", "none", "-c", str(tmp_path), "--", *_NOOP])

    assert json.loads(capsys.readouterr().out)["task"]["session_id"] is None


def test_run_detached_creates_a_global_detached_kind(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--detached`` uses first-class global ownership, not session-none command."""
    identity = SessionIdentity(
        session_id="20260725T120000Z-99",
        kind="ace",
        pid=os.getpid(),
        started_at="2026-07-25T12:00:00Z",
    )
    _use_sessions(monkeypatch, [identity])

    assert (
        _dispatch(
            [
                "task",
                "run",
                "--detached",
                "--json",
                "--cwd",
                str(tmp_path),
                "--",
                *_NOOP,
            ]
        )
        == 0
    )

    task = json.loads(capsys.readouterr().out)["task"]
    assert task["kind"] == "detached"
    assert task["detached"] is True
    assert task["session_id"] is None
    assert task["session_label"] is None


def test_kill_resolves_prefix_and_marks_active_task_killed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI exposes the store kill path through the same prefix resolver."""
    monkeypatch.setattr("sase.main.task_handler._reconcile_quietly", lambda: None)
    _stored(
        "aaaaaaaaaaaa",
        label="Global launch",
        kind="detached",
        status="running",
        finished_at=None,
        exit_code=None,
    )

    assert _dispatch(["task", "kill", "aaa"]) == 0

    assert "Killed task aaaaaa." in capsys.readouterr().out
    task = get_task("aaaaaaaaaaaa")
    assert task is not None
    assert task.status == "killed"


def test_kill_terminal_task_is_a_json_noop(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Killing completed work succeeds without mutating its terminal state."""
    _stored("aaaaaaaaaaaa", status="success")

    assert _dispatch(["task", "kill", "aaa", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["changed"] is False
    assert payload["task"]["status"] == "success"


def test_kill_reports_bad_task_references(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unknown kill targets are usage errors, just like ``task show``."""
    assert _dispatch(["task", "kill", "zzz"]) == 2
    assert "no task matches reference" in capsys.readouterr().err


def _dead_pid() -> int:
    """Return a pid that is guaranteed not to be running."""
    import subprocess

    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid
