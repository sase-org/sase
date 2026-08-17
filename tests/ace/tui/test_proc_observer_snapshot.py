"""Tests for ACE proc observer snapshots built from durable proc state."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui import _proc_observer_store as po_store
from sase.ace.tui import proc_observer as po
from sase.ace.tui.proc_observer import ProcObserver, monitor_row_agent_name
from sase.ops import DurableOperationResult
from sase.procs import Proc


def test_observer_active_count_uses_session_scoped_live_rows(monkeypatch) -> None:
    procs = [
        Proc(
            proc_id="mine",
            label="mine",
            kind="command",
            status="running",
            command=["true"],
            cwd="/tmp",
            origin="ace",
            created_at="2026-08-15T12:00:00Z",
            started_at="2026-08-15T12:00:00Z",
            log_path="/tmp/mine.log",
            session_id="session-a",
        ),
        Proc(
            proc_id="dead",
            label="dead",
            kind="command",
            status="running",
            command=["true"],
            cwd="/tmp",
            origin="ace",
            created_at="2026-08-15T12:00:00Z",
            started_at="2026-08-15T12:00:00Z",
            log_path="/tmp/dead.log",
            session_id="session-dead",
        ),
        Proc(
            proc_id="other",
            label="other",
            kind="command",
            status="running",
            command=["true"],
            cwd="/tmp",
            origin="ace",
            created_at="2026-08-15T12:00:00Z",
            started_at="2026-08-15T12:00:00Z",
            log_path="/tmp/other.log",
            session_id="session-b",
        ),
        Proc(
            proc_id="unattributed",
            label="unattributed",
            kind="command",
            status="pending",
            command=["true"],
            cwd="/tmp",
            origin="ace",
            created_at="2026-08-15T12:00:00Z",
            started_at="2026-08-15T12:00:00Z",
            log_path="/tmp/unattributed.log",
            session_id=None,
        ),
    ]
    monkeypatch.setattr(
        po,
        "load_observer_context",
        lambda: po.ObserverContext("session-a", None, None, None, "/tmp"),
    )
    monkeypatch.setattr(po, "live_session_ids", lambda: frozenset({"session-a"}))
    monkeypatch.setattr(po, "read_procs", lambda: procs)

    snapshot = ProcObserver(on_snapshot=lambda _snapshot: None)._build_snapshot()

    assert snapshot.projection.active_count == 2
    assert [row.proc_id for row in snapshot.projection.active_rows()] == [
        "mine",
        "unattributed",
    ]


def test_observer_active_monitor_count_isolates_monitor_origin_rows(
    monkeypatch,
) -> None:
    procs = [
        Proc(
            proc_id="ace-proc",
            label="ace",
            kind="command",
            status="running",
            command=["true"],
            cwd="/tmp",
            origin="ace",
            created_at="2026-08-15T12:00:00Z",
            started_at="2026-08-15T12:00:00Z",
            log_path="/tmp/ace.log",
            session_id=None,
        ),
        Proc(
            proc_id="monitor-proc",
            label="monitor",
            kind="detached",
            status="running",
            command=["sleep", "120"],
            cwd="/tmp",
            origin="monitor",
            created_at="2026-08-15T12:00:00Z",
            started_at="2026-08-15T12:00:00Z",
            log_path="/tmp/monitor.log",
            session_id=None,
        ),
    ]
    monkeypatch.setattr(
        po,
        "load_observer_context",
        lambda: po.ObserverContext(None, None, None, None, "/tmp"),
    )
    monkeypatch.setattr(po, "live_session_ids", lambda: frozenset())
    monkeypatch.setattr(po, "read_procs", lambda: procs)

    snapshot = ProcObserver(on_snapshot=lambda _snapshot: None)._build_snapshot()

    assert snapshot.projection.active_count == 2
    assert snapshot.projection.active_monitor_count == 1
    assert [row.proc_id for row in snapshot.projection.active_monitor_rows()] == [
        "monitor-proc"
    ]


def test_store_proc_row_adapts_durable_state(monkeypatch) -> None:
    monkeypatch.setattr(
        po_store, "_read_log_tail", lambda proc_id, log_path="": f"log {proc_id}\n"
    )
    row = po.store_proc_row(
        Proc(
            proc_id="proc-1",
            label="Patch sync",
            kind="command",
            status="error",
            command=["sase", "patch", "sync"],
            cwd="/tmp",
            origin="ace",
            created_at="2026-08-15T12:00:00Z",
            started_at="2026-08-15T12:00:01Z",
            finished_at="2026-08-15T12:00:05Z",
            log_path="/tmp/proc-1.log",
            cl_name="demo",
            message="failed",
            concurrency_keys=["ace:patch:demo"],
            session_id="session-a",
            session_label="ace-sase",
            shell_name="demo--build",
        ),
        live_session_ids=frozenset({"session-a"}),
        with_output=True,
    )

    assert row.proc_id == "proc-1"
    assert row.output == "log proc-1\n"
    assert row.error == "failed"
    assert row.store_backed is True
    assert row.exclusive_scopes == frozenset({"ace:patch:demo"})
    assert row.session_live is True
    assert row.origin == "ace"
    assert row.log_path == "/tmp/proc-1.log"
    assert row.shell_name == "demo--build"
    assert monitor_row_agent_name(row) is None


def test_observer_delivers_terminal_completion_once(
    monkeypatch, tmp_path: Path
) -> None:
    result_path = tmp_path / "result.json"
    proc = Proc(
        proc_id="proc-1",
        label="Patch sync",
        kind="command",
        status="success",
        command=["sase", "patch", "sync"],
        cwd="/tmp",
        origin="ace",
        created_at="2026-08-15T12:00:00Z",
        started_at="2026-08-15T12:00:00Z",
        finished_at="2026-08-15T12:00:05Z",
        log_path="/tmp/proc-1.log",
        result={"result_path": str(result_path)},
    )
    monkeypatch.setattr(
        po,
        "load_observer_context",
        lambda: po.ObserverContext(None, None, None, None, "/tmp"),
    )
    monkeypatch.setattr(po, "live_session_ids", lambda: frozenset())
    monkeypatch.setattr(po, "read_procs", lambda: [proc])
    monkeypatch.setattr(
        po_store,
        "read_operation_result",
        lambda *_args, **_kwargs: DurableOperationResult(
            operation="patch.sync",
            proc_id="proc-1",
            success=True,
            message="synced",
            payload={"ok": True},
        ),
    )
    snapshots = []
    observer = ProcObserver(on_snapshot=snapshots.append)

    pending = observer.register_pending(
        proc_type="patch",
        cl_name="demo",
        project_file="project.sase",
        display_name="sync demo",
    )
    observer.register_submitted(
        placeholder_id=pending.proc_id,
        proc_id="proc-1",
        operation="patch.sync",
        result_path=str(result_path),
    )

    first = observer.poll_once()
    second = observer.poll_once()

    assert first is not None
    assert [completion.proc_id for completion in first.completions] == ["proc-1"]
    assert first.completions[0].result is not None
    assert first.completions[0].result.message == "synced"
    assert second is not None
    assert second.completions == ()
    assert len(snapshots) == 1
