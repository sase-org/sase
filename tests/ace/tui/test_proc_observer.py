"""Tests for the read-only ACE proc observer."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui import proc_observer as po
from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcObserver,
    ProcProjection,
    compose_proc_projection,
    monitor_row_agent_name,
    proc_projection_for,
)
from sase.core.time import local_now
from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.ops import DurableOperationResult
from sase.procs import Proc
from sase.procs.logs import proc_log_path
from sase.procs.models import ARTIFACTS_LOG_OWNER, STORE_LOG_OWNER


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


def test_projection_scope_keeps_dead_session_rows_visible_but_inactive() -> None:
    mine = ObservedProc(
        proc_id="mine",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="mine",
        started_at=local_now(),
        session_id="session-a",
        session_live=True,
    )
    dead = ObservedProc(
        proc_id="dead",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="dead",
        started_at=local_now(),
        session_id="session-dead",
        session_live=False,
    )
    unattributed = ObservedProc(
        proc_id="unattributed",
        proc_type="command",
        cl_name="",
        project_file="",
        status="settling",
        message="unattributed",
        started_at=local_now(),
        session_id=None,
    )
    other = ObservedProc(
        proc_id="other",
        proc_type="command",
        cl_name="",
        project_file="",
        status="pending",
        message="other",
        started_at=local_now(),
        session_id="session-b",
        session_live=True,
    )
    projection = ProcProjection(
        rows=(mine, dead, unattributed, other),
        session_id="session-a",
    )

    assert projection.scoped_rows(all_sessions=False) == [mine, dead, unattributed]
    assert projection.active_rows() == [mine, unattributed]
    assert projection.active_rows(all_sessions=True) == [mine, unattributed, other]


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
        "_load_context",
        lambda: po._ObserverContext("session-a", None, None, None, "/tmp"),
    )
    monkeypatch.setattr(po, "_live_session_ids", lambda: frozenset({"session-a"}))
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
        "_load_context",
        lambda: po._ObserverContext(None, None, None, None, "/tmp"),
    )
    monkeypatch.setattr(po, "_live_session_ids", lambda: frozenset())
    monkeypatch.setattr(po, "read_procs", lambda: procs)

    snapshot = ProcObserver(on_snapshot=lambda _snapshot: None)._build_snapshot()

    assert snapshot.projection.active_count == 2
    assert snapshot.projection.active_monitor_count == 1
    assert [row.proc_id for row in snapshot.projection.active_monitor_rows()] == [
        "monitor-proc"
    ]


def test_active_monitor_rows_filters_active_rows_by_origin() -> None:
    ace_row = ObservedProc(
        proc_id="ace",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="",
        started_at=local_now(),
        origin="ace",
    )
    monitor_row = ObservedProc(
        proc_id="monitor",
        proc_type="detached",
        cl_name="",
        project_file="",
        status="running",
        message="",
        started_at=local_now(),
        origin="monitor",
    )
    projection = ProcProjection(rows=(ace_row, monitor_row))

    assert [row.proc_id for row in projection.active_rows()] == ["ace", "monitor"]
    assert [row.proc_id for row in projection.active_monitor_rows()] == ["monitor"]


def test_compose_proc_projection_counts_monitor_rows_and_keeps_overlay_rows_blue() -> (
    None
):
    durable_monitor = ObservedProc(
        proc_id="durable-monitor",
        proc_type="detached",
        cl_name="",
        project_file="",
        status="running",
        message="",
        started_at=local_now(),
        origin="monitor",
    )
    durable = ProcProjection(
        rows=(durable_monitor,),
        active_count=1,
        active_monitor_count=1,
        session_id="session-a",
    )
    # Session-local overlay rows are ACE-owned by construction and default to
    # origin="", so they must stay counted on the blue (non-monitor) side.
    overlay = ObservedProc(
        proc_id="overlay",
        proc_type="command",
        cl_name="demo",
        project_file="",
        status="running",
        message="",
        started_at=local_now(),
    )

    projection = compose_proc_projection(durable, [overlay])

    assert projection.active_count == 2
    assert projection.active_monitor_count == 1


def test_store_proc_row_adapts_durable_state(monkeypatch) -> None:
    monkeypatch.setattr(
        po, "_read_log_tail", lambda proc_id, log_path="": f"log {proc_id}\n"
    )
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


def _observer_context_stubs(monkeypatch) -> None:
    monkeypatch.setattr(
        po,
        "_load_context",
        lambda: po._ObserverContext(None, None, None, None, "/tmp"),
    )
    monkeypatch.setattr(po, "_live_session_ids", lambda: frozenset())


def _monitor_proc(*, proc_id: str, log_path: str, shell_name: str | None) -> Proc:
    return Proc(
        proc_id=proc_id,
        label="just check-full",
        kind="detached",
        status="running",
        command=["sleep", "120"],
        cwd="/tmp",
        origin=MONITOR_PROC_ORIGIN,
        created_at="2026-08-15T12:00:00Z",
        started_at="2026-08-15T12:00:00Z",
        log_path=log_path,
        log_owner=ARTIFACTS_LOG_OWNER,
        shell_name=shell_name,
    )


def test_monitor_detail_row_reads_artifacts_log_including_rotated_sibling(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "artifacts" / "live_reply.md"
    log_path.parent.mkdir(parents=True)
    log_path.with_name(f"{log_path.name}.1").write_text(
        "rotated-only\nolder-current\n", encoding="utf-8"
    )
    log_path.write_text("current-tail\n", encoding="utf-8")
    proc = _monitor_proc(
        proc_id="mon-1", log_path=str(log_path), shell_name="acme--mon"
    )
    _observer_context_stubs(monkeypatch)
    monkeypatch.setattr(po, "read_procs", lambda: [proc])

    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.set_detail_proc(proc.proc_id)
    snapshot = observer._build_snapshot()
    row = snapshot.projection.rows[0]

    assert row.output == "rotated-only\nolder-current\ncurrent-tail\n"
    assert "rotated-only" in row.output
    assert row.log_path == str(log_path)
    assert row.shell_name == "acme--mon"
    assert monitor_row_agent_name(row) == "acme--mon"


def test_store_owned_detail_row_reads_store_log(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    proc_id = "store-owned"
    store_log = proc_log_path(proc_id)
    store_log.parent.mkdir(parents=True)
    store_log.write_text("store-only\n", encoding="utf-8")
    decoy = tmp_path / "artifacts" / "live_reply.md"
    decoy.parent.mkdir(parents=True)
    decoy.write_text("should-not-read\n", encoding="utf-8")
    proc = Proc(
        proc_id=proc_id,
        label="sync",
        kind="command",
        status="running",
        command=["true"],
        cwd="/tmp",
        origin="ace",
        created_at="2026-08-15T12:00:00Z",
        started_at="2026-08-15T12:00:00Z",
        log_path=str(store_log),
        log_owner=STORE_LOG_OWNER,
        shell_name="demo--build",
    )
    _observer_context_stubs(monkeypatch)
    monkeypatch.setattr(po, "read_procs", lambda: [proc])

    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.set_detail_proc(proc_id)
    snapshot = observer._build_snapshot()
    row = snapshot.projection.rows[0]

    assert row.output == "store-only\n"
    assert row.log_path == str(store_log)
    assert row.shell_name == "demo--build"


def test_monitor_missing_log_yields_empty_output(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "artifacts" / "live_reply.md"
    proc = _monitor_proc(
        proc_id="mon-missing", log_path=str(log_path), shell_name="acme--mon"
    )
    _observer_context_stubs(monkeypatch)
    monkeypatch.setattr(po, "read_procs", lambda: [proc])

    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.set_detail_proc(proc.proc_id)
    row = observer._build_snapshot().projection.rows[0]

    assert row.output == ""
    assert row.log_path == str(log_path)
    assert row.shell_name == "acme--mon"


def test_monitor_row_without_shell_name_round_trips_none(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "artifacts" / "live_reply.md"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("alive\n", encoding="utf-8")
    proc = _monitor_proc(proc_id="mon-anon", log_path=str(log_path), shell_name=None)
    _observer_context_stubs(monkeypatch)
    monkeypatch.setattr(po, "read_procs", lambda: [proc])

    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.set_detail_proc(proc.proc_id)
    row = observer._build_snapshot().projection.rows[0]

    assert row.output == "alive\n"
    assert row.shell_name is None
    assert monitor_row_agent_name(row) is None


def test_appending_monitor_log_changes_published_snapshot_signature(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "artifacts" / "live_reply.md"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("initial\n", encoding="utf-8")
    proc = _monitor_proc(
        proc_id="mon-grow", log_path=str(log_path), shell_name="acme--mon"
    )
    _observer_context_stubs(monkeypatch)
    monkeypatch.setattr(po, "read_procs", lambda: [proc])
    snapshots: list[po.ProcObserverSnapshot] = []
    observer = ProcObserver(on_snapshot=snapshots.append)
    observer.set_detail_proc(proc.proc_id)

    first = observer.poll_once()
    unchanged = observer.poll_once()
    log_path.write_text("initial\nappended\n", encoding="utf-8")
    second = observer.poll_once()

    assert first is not None
    assert first.projection.rows[0].output == "initial\n"
    assert unchanged is not None
    assert unchanged.projection.rows[0].output == "initial\n"
    assert second is not None
    assert second.projection.rows[0].output == "initial\nappended\n"
    assert po._snapshot_signature(first) != po._snapshot_signature(second)
    assert len(snapshots) == 2
