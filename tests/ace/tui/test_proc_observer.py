"""Tests for the read-only ACE proc observer."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui import proc_observer as po
from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcObserver,
    ProcProjection,
    compose_proc_projection,
    proc_projection_for,
)
from sase.core.time import local_now
from sase.ops import DurableOperationResult
from sase.procs import Proc


def test_observed_proc_log_is_bounded_and_textual() -> None:
    log = po._ObservedProcLog(max_lines=2, max_chars=100)

    log.append("one\ntwo\nthree")

    snapshot = log.snapshot()
    assert [line.text for line in snapshot.lines] == ["two", "three"]
    assert snapshot.trimmed_count == 1
    assert log.text().startswith("... 1 earlier lines trimmed\n")


def test_projection_detects_active_scope_conflicts() -> None:
    running = ObservedProc(
        proc_id="run",
        proc_type="patch",
        cl_name="demo",
        project_file="project.sase",
        status="running",
        message="running",
        started_at=local_now(),
        exclusive_scopes=frozenset({"ace:patch:demo"}),
    )
    done = ObservedProc(
        proc_id="done",
        proc_type="patch",
        cl_name="demo",
        project_file="project.sase",
        status="success",
        message="done",
        started_at=local_now(),
        exclusive_scopes=frozenset({"ace:patch:done"}),
    )

    projection = ProcProjection(rows=(done, running), active_count=1)

    assert projection.scope_conflict({"ace:patch:demo"}) is running
    assert projection.scope_conflict({"ace:patch:done"}) is None


def test_projection_scope_includes_unattributed_rows() -> None:
    mine = ObservedProc(
        proc_id="mine",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="mine",
        started_at=local_now(),
        session_id="session-a",
    )
    unattributed = ObservedProc(
        proc_id="unattributed",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="unattributed",
        started_at=local_now(),
        session_id=None,
    )
    other = ObservedProc(
        proc_id="other",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="other",
        started_at=local_now(),
        session_id="session-b",
    )
    projection = ProcProjection(
        rows=(mine, unattributed, other),
        active_count=3,
        session_id="session-a",
    )

    assert projection.scoped_rows(all_sessions=False) == [mine, unattributed]
    assert projection.scoped_rows(all_sessions=True) == [mine, unattributed, other]


def test_compose_proc_projection_attributes_and_counts_session_rows() -> None:
    durable = ObservedProc(
        proc_id="durable",
        proc_type="patch",
        cl_name="demo",
        project_file="",
        status="running",
        message="durable",
        started_at=local_now(),
        session_id="session-a",
    )
    local = ObservedProc(
        proc_id="session-1",
        proc_type="sync",
        cl_name="",
        project_file="",
        status="running",
        message="local",
        started_at=local_now(),
    )
    projection = compose_proc_projection(
        ProcProjection(rows=(durable,), active_count=1, session_id="session-a"),
        (local,),
    )

    assert projection.active_count == 2
    assert projection.session_id == "session-a"
    local_row = next(row for row in projection.rows if row.proc_id == "session-1")
    assert local_row.session_id == "session-a"
    assert local_row.session_live is True


def test_proc_projection_for_prefers_effective_method() -> None:
    durable = ProcProjection(session_id="ignored")
    effective = ProcProjection(session_id="effective", active_count=2)
    app = type(
        "_App",
        (),
        {
            "_proc_projection": durable,
            "_effective_proc_projection": lambda self: effective,
        },
    )()

    assert proc_projection_for(app) is effective
    assert proc_projection_for(type("_Bare", (), {})()) == ProcProjection()


def test_store_proc_row_adapts_durable_state(monkeypatch) -> None:
    monkeypatch.setattr(po, "_read_log_tail", lambda proc_id: f"log {proc_id}\n")
    row = po._store_proc_row(
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
        po, "_load_context", lambda: po._ObserverContext(None, None, None, None, "/tmp")
    )
    monkeypatch.setattr(po, "_live_session_ids", lambda: frozenset())
    monkeypatch.setattr(po, "read_procs", lambda: [proc])
    monkeypatch.setattr(
        po,
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
