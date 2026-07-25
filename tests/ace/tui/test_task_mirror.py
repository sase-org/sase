"""Tests for mirroring in-TUI tasks into the durable task store."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

import sase.ace.tui.task_mirror as tm
from sase.ace.tui.task_mirror import TaskMirror
from sase.ace.tui.task_queue import TaskInfo
from sase.sessions import SessionIdentity
from sase.tasks import read_task_log_tail, read_tasks


@pytest.fixture
def sandboxed_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the durable store at a temporary SASE home."""
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    identity = SessionIdentity(
        session_id="session-mirror",
        kind="ace",
        pid=1234,
        started_at="2026-07-25T12:00:00Z",
        project="sase",
        workspace_num=14,
        cwd=str(tmp_path),
    )
    monkeypatch.setattr("sase.sessions.current_session_id", lambda: identity.session_id)
    monkeypatch.setattr("sase.sessions.live_sessions", lambda: [identity])
    return home


def _task_info(task_id: str = "local-1", *, label: str = "sync sase-42") -> TaskInfo:
    return TaskInfo(
        task_id=task_id,
        task_type="sync",
        cl_name="sase-42",
        project_file="",
        status="running",
        message=f"{label} started",
        started_at=datetime.now(),
        display_name=label,
        command=["sase", "ace", "sync"],
    )


def _stop(mirror: TaskMirror) -> None:
    mirror.stop(timeout=5.0)


def test_mirror_defers_every_store_write_to_the_writer_thread(
    monkeypatch: pytest.MonkeyPatch, sandboxed_home: Path
) -> None:
    """``track``/``finish`` enqueue only; the writer thread does the I/O."""
    del sandboxed_home
    writes: list[tuple[str, int]] = []
    caller = threading.get_ident()

    monkeypatch.setattr(
        tm,
        "append_task",
        lambda record: writes.append(("append", threading.get_ident())),
    )
    monkeypatch.setattr(
        tm,
        "update_task",
        lambda task_id, **changes: writes.append(("update", threading.get_ident())),
    )
    monkeypatch.setattr(
        tm,
        "append_task_log_text",
        lambda task_id, text: writes.append(("log", threading.get_ident())),
    )

    mirror = TaskMirror()
    assert mirror.start() is True
    try:
        info = _task_info()
        info.log.append("first line")
        task_id = mirror.track(info)
        assert task_id is not None
        assert info.durable_task_id == task_id
        # Submitting from the UI thread must not have written anything yet.
        assert writes == []

        assert mirror.flush(timeout=5.0) is True
        mirror.finish(info, status="success", message="done", exit_code=0)
        assert mirror.flush(timeout=5.0) is True
    finally:
        _stop(mirror)

    kinds = [kind for kind, _ident in writes]
    assert kinds == ["append", "log", "update"]
    assert all(ident != caller for _kind, ident in writes)


def test_mirror_writes_row_log_and_terminal_update(sandboxed_home: Path) -> None:
    del sandboxed_home
    mirror = TaskMirror()
    assert mirror.start() is True
    try:
        info = _task_info()
        info.log.append("remote: counting objects")
        task_id = mirror.track(info)
        assert task_id is not None
        assert mirror.flush(timeout=5.0) is True

        rows = read_tasks()
        assert [row.task_id for row in rows] == [task_id]
        row = rows[0]
        assert row.kind == "tui"
        assert row.origin == "ace"
        assert row.status == "running"
        assert row.session_id == "session-mirror"
        assert row.session_label == "ace·sase#14"
        assert row.project == "sase"
        assert row.workspace_num == 14
        assert row.cl_name == "sase-42"
        assert row.tags == ["ace", "sync"]
        assert "remote: counting objects" in read_task_log_tail(task_id, 10)

        info.log.append("second line")
        info.status = "success"
        mirror.finish(info, status="success", message="synced", exit_code=0)
        assert mirror.flush(timeout=5.0) is True
    finally:
        _stop(mirror)

    row = read_tasks()[0]
    assert row.status == "success"
    assert row.message == "synced"
    assert row.exit_code == 0
    assert row.finished_at is not None
    tail = read_task_log_tail(row.task_id, 10)
    assert tail.splitlines() == ["remote: counting objects", "second line"]


def test_mirror_flushes_only_new_log_lines(sandboxed_home: Path) -> None:
    del sandboxed_home
    mirror = TaskMirror()
    assert mirror.start() is True
    try:
        info = _task_info()
        info.log.append("line 1")
        task_id = mirror.track(info)
        assert task_id is not None
        assert mirror.flush(timeout=5.0) is True

        info.log.append("line 2")
        mirror.finish(info, status="error", message="boom", exit_code=2)
        assert mirror.flush(timeout=5.0) is True
    finally:
        _stop(mirror)

    assert read_task_log_tail(str(task_id), 10) == "line 1\nline 2\n"
    row = read_tasks()[0]
    assert row.status == "error"
    assert row.exit_code == 2


def test_progress_tick_does_not_terminalize_before_finish(
    sandboxed_home: Path,
) -> None:
    """The explicit finish op owns terminal status writes.

    A UI task can briefly carry a terminal-looking queue status before its
    worker result is delivered to the mirror.  The durable store intentionally
    keeps the first terminal status, so progress mirroring must not race the
    final completion write.
    """
    del sandboxed_home
    mirror = TaskMirror()
    assert mirror.start() is True
    try:
        info = _task_info()
        task_id = mirror.track(info)
        assert task_id is not None
        assert mirror.flush(timeout=5.0) is True

        info.status = "error"
        mirror._tick()
        mirror.finish(info, status="success", message="started", exit_code=0)
        assert mirror.flush(timeout=5.0) is True
    finally:
        _stop(mirror)

    row = read_tasks()[0]
    assert row.status == "success"
    assert row.message == "started"
    assert row.exit_code == 0


def test_mirror_reports_detached_task_count_for_this_session(
    sandboxed_home: Path,
) -> None:
    del sandboxed_home
    from sase.tasks import BackgroundTask, append_task

    for index, (session_id, kind, status) in enumerate(
        (
            ("session-mirror", "command", "running"),
            ("session-mirror", "tui", "running"),
            ("session-other", "command", "running"),
            ("session-mirror", "command", "success"),
        )
    ):
        append_task(
            BackgroundTask(
                task_id=f"row{index}",
                label=f"row {index}",
                kind=kind,
                status=status,
                command=["sleep", "1"],
                cwd="/tmp",
                origin="cli",
                created_at="2026-07-25T12:00:00Z",
                log_path=f"/tmp/row{index}.log",
                session_id=session_id,
            )
        )

    counts: list[int] = []
    mirror = TaskMirror(on_detached_count=counts.append)
    mirror._refresh_detached_count()

    assert counts == [1]
    assert mirror.detached_running_count == 1


def test_mirror_start_is_refused_without_an_isolated_state_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pytest process must never mirror into the real ``~/.sase`` tree."""
    monkeypatch.delenv("SASE_HOME", raising=False)
    monkeypatch.setattr(
        tm,
        "best_effort_test_state_write_allowed",
        lambda target, category: False,
    )
    mirror = TaskMirror()
    assert mirror.start() is False
    assert mirror.running is False
    assert mirror.track(_task_info()) is None


def test_mirror_tick_reconciles_and_mirrors_progress(
    monkeypatch: pytest.MonkeyPatch, sandboxed_home: Path
) -> None:
    del sandboxed_home
    reconciled: list[str] = []
    monkeypatch.setattr(
        tm, "reconcile_running_tasks", lambda: reconciled.append("swept") or []
    )
    updates: list[dict[str, Any]] = []
    monkeypatch.setattr(
        tm,
        "update_task",
        lambda task_id, **changes: updates.append({"task_id": task_id, **changes}),
    )

    mirror = TaskMirror()
    assert mirror.start() is True
    try:
        info = _task_info()
        task_id = mirror.track(info)
        assert mirror.flush(timeout=5.0) is True

        info.phase = "Fetching"
        mirror._tick()
    finally:
        _stop(mirror)

    assert reconciled == ["swept"]
    assert updates == [{"task_id": task_id, "status": "running", "phase": "Fetching"}]
