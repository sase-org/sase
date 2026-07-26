"""Tests for the Tasks tab's off-thread durable-store reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.modals.tasks_store_rows import (
    _store_task_row,
    load_store_task_rows,
)
from sase.sessions import SessionIdentity
from sase.tasks import BackgroundTask, append_task, task_log_path


@pytest.fixture(autouse=True)
def _sandboxed_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "sase.sessions.live_sessions",
        lambda: [
            SessionIdentity(
                session_id="session-mine",
                kind="ace",
                pid=1234,
                started_at="2026-07-25T12:00:00Z",
                project="sase",
                workspace_num=14,
            )
        ],
    )


def _append(
    task_id: str,
    *,
    session_id: str | None,
    status: str = "running",
    label: str | None = None,
    kind: str = "command",
) -> BackgroundTask:
    task = BackgroundTask(
        task_id=task_id,
        label=label or f"task {task_id}",
        kind=kind,
        status=status,
        command=["sleep", "5"],
        cwd="/tmp",
        origin="cli",
        created_at=f"2026-07-25T12:0{len(task_id)}:00Z",
        log_path=str(task_log_path(task_id)),
        session_id=session_id,
        session_label="ace·sase#7" if session_id else None,
    )
    append_task(task)
    return task


def test_default_scope_keeps_this_session_and_unattributed_rows() -> None:
    _append("aaa111", session_id="session-mine")
    _append("bbb222", session_id="session-other")
    _append("ccc333", session_id=None)

    snapshot = load_store_task_rows(session_id="session-mine", all_sessions=False)

    assert {row.task_id for row in snapshot.rows} == {"aaa111", "ccc333"}
    assert snapshot.mtime is not None
    assert all(row.store_backed for row in snapshot.rows)


def test_default_scope_keeps_detached_rows_globally() -> None:
    """Detached kind stays visible even if malformed legacy attribution exists."""
    _append(
        "aaa111",
        session_id="session-other",
        kind="detached",
        label="global detached",
    )
    _append("bbb222", session_id="session-other", label="other command")

    snapshot = load_store_task_rows(session_id="session-mine", all_sessions=False)

    assert [row.task_id for row in snapshot.rows] == ["aaa111"]
    assert snapshot.rows[0].task_type == "detached"


def test_all_sessions_scope_marks_dead_sessions() -> None:
    _append("bbb222", session_id="session-other")
    _append("ddd444", session_id="session-mine")

    snapshot = load_store_task_rows(session_id="session-mine", all_sessions=True)

    by_id = {row.task_id: row for row in snapshot.rows}
    assert set(by_id) == {"bbb222", "ddd444"}
    assert by_id["ddd444"].session_live is True
    # ``session-other`` is not in the live registry, so its rows render dead.
    assert by_id["bbb222"].session_live is False


def test_unchanged_store_is_reported_without_rereading_rows() -> None:
    _append("aaa111", session_id="session-mine")
    first = load_store_task_rows(session_id="session-mine", all_sessions=False)

    second = load_store_task_rows(
        session_id="session-mine",
        all_sessions=False,
        known_mtime=first.mtime,
        known_detail_task_id=first.detail_task_id,
    )

    assert second.unchanged is True
    assert second.rows == []
    assert second.mtime == first.mtime


def test_only_the_detail_row_loads_its_log_tail() -> None:
    task = _append("aaa111", session_id="session-mine")
    other = _append("bbb222", session_id="session-mine")
    for record, text in ((task, "detail output\n"), (other, "other output\n")):
        path = task_log_path(record.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    snapshot = load_store_task_rows(
        session_id="session-mine",
        all_sessions=False,
        detail_task_id="aaa111",
    )

    by_id = {row.task_id: row for row in snapshot.rows}
    assert by_id["aaa111"].output == "detail output\n"
    assert by_id["bbb222"].output == ""


def test_store_task_row_carries_display_state() -> None:
    row = _store_task_row(
        BackgroundTask(
            task_id="eee555",
            label="Epic launch · auth",
            kind="command",
            status="killed",
            command=["sase", "bead", "work"],
            cwd="/tmp",
            origin="epic-launch",
            created_at="2026-07-25T12:00:00Z",
            started_at="2026-07-25T12:00:01Z",
            finished_at="2026-07-25T12:00:09Z",
            log_path="/tmp/eee555.log",
            session_id="session-mine",
            session_label="ace·sase#14",
            message="task killed",
            exit_code=None,
        ),
        live_session_ids=frozenset({"session-mine"}),
    )

    assert row.label == "Epic launch · auth"
    assert row.status == "killed"
    assert row.error == "task killed"
    assert row.command == ["sase", "bead", "work"]
    assert row.durable_task_id == "eee555"
    assert row.session_live is True
    assert row.finished_at is not None
