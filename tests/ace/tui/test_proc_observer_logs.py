"""Tests for ACE proc observer log buffers and detail-row log reads."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui import proc_observer as po
from sase.ace.tui.proc_observer import ProcObserver, monitor_row_agent_name
from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.procs import Proc
from sase.procs.logs import proc_log_path
from sase.procs.models import ARTIFACTS_LOG_OWNER, STORE_LOG_OWNER


def test_observed_proc_log_is_bounded_and_textual() -> None:
    log = po.ObservedProcLog(max_lines=2, max_chars=100)

    log.append("one\ntwo\nthree")

    snapshot = log.snapshot()
    assert [line.text for line in snapshot.lines] == ["two", "three"]
    assert snapshot.trimmed_count == 1
    assert log.text().startswith("... 1 earlier lines trimmed\n")


def _observer_context_stubs(monkeypatch) -> None:
    monkeypatch.setattr(
        po,
        "load_observer_context",
        lambda: po.ObserverContext(None, None, None, None, "/tmp"),
    )
    monkeypatch.setattr(po, "live_session_ids", lambda: frozenset())


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
