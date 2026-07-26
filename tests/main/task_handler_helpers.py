"""Shared helpers for ``sase task`` handler tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.main.task_handler import handle_task_command
from sase.sessions import SessionIdentity
from sase.tasks import BackgroundTask, append_task, task_log_path


@pytest.fixture(autouse=True)
def task_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point every task, log, and session path at an isolated home."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    use_sessions(monkeypatch, [])
    return home


def use_sessions(
    monkeypatch: pytest.MonkeyPatch, sessions: list[SessionIdentity]
) -> None:
    """Pin every live-session lookup the CLI path can reach."""
    monkeypatch.setattr("sase.sessions.registry.live_sessions", lambda: list(sessions))
    monkeypatch.setattr("sase.sessions.live_sessions", lambda: list(sessions))
    monkeypatch.setattr("sase.main.task_handler.live_sessions", lambda: list(sessions))


# A command that exists everywhere and exits immediately.
NOOP = (sys.executable, "-c", "pass")


def dispatch(argv: list[str]) -> int:
    """Run one ``sase task`` invocation and return its process exit code."""
    with pytest.raises(SystemExit) as exit_info:
        handle_task_command(create_parser().parse_args(argv))
    return int(exit_info.value.code or 0)


def stored(
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
    """Append and return a task with concise test-friendly defaults."""
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


def write_log(task_id: str, text: str) -> None:
    """Write captured output for a stored task."""
    path = task_log_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def dead_pid() -> int:
    """Return a pid that is guaranteed not to be running."""
    import subprocess

    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid
