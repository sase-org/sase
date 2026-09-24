"""Observer exit watches, ref-counted tails, and observed proc tags."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui import proc_observer as po
from sase.ace.tui.proc_observer import ProcObserver
from sase.procs import Proc


def _proc(
    proc_id: str,
    *,
    status: str,
    exit_code: int | None = None,
    session_id: str | None = "session-a",
    log_path: str = "",
    tags: list[str] | None = None,
    origin: str = "ace",
) -> Proc:
    return Proc(
        proc_id=proc_id,
        label=proc_id,
        kind="command",
        status=status,
        command=["true"],
        cwd="/tmp",
        origin=origin,
        created_at="2026-08-15T12:00:00Z",
        started_at="2026-08-15T12:00:00Z",
        finished_at=(
            None if status in {"pending", "running"} else "2026-08-15T12:01:00Z"
        ),
        log_path=log_path,
        session_id=session_id,
        exit_code=exit_code,
        tags=tags or [],
    )


def _stub(monkeypatch, procs: list[Proc]) -> None:
    monkeypatch.setattr(
        po,
        "load_observer_context",
        lambda: po.ObserverContext("session-a", None, None, None, "/tmp"),
    )
    monkeypatch.setattr(po, "live_session_ids", lambda: frozenset({"session-a"}))
    monkeypatch.setattr(po, "read_procs", lambda: procs)


def test_exit_watch_settles_success_from_the_store_row(monkeypatch) -> None:
    procs = [_proc("cmd-1", status="success", exit_code=0)]
    _stub(monkeypatch, procs)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    placeholder = observer.register_pending(
        proc_type="command",
        cl_name="",
        project_file="",
        display_name=": bead list",
    )
    observer.register_exit_watch("cmd-1", placeholder_id=placeholder.proc_id)

    snapshot = observer._build_snapshot()

    assert len(snapshot.exit_completions) == 1
    completion = snapshot.exit_completions[0]
    assert completion.proc_id == "cmd-1"
    assert completion.status == "success"
    assert completion.exit_code == 0
    assert isinstance(completion.finished_at, datetime)
    assert completion.placeholder_id == placeholder.proc_id
    # The settled placeholder is dropped, like the typed-watch path.
    assert placeholder.proc_id not in observer._pending
    # Delivered exactly once.
    assert observer._build_snapshot().exit_completions == ()


def test_exit_watch_reports_error_and_killed_outcomes(monkeypatch) -> None:
    procs = [
        _proc("cmd-err", status="error", exit_code=2),
        _proc("cmd-kill", status="killed", exit_code=None),
    ]
    _stub(monkeypatch, procs)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.register_exit_watch("cmd-err")
    observer.register_exit_watch("cmd-kill")

    snapshot = observer._build_snapshot()

    by_id = {item.proc_id: item for item in snapshot.exit_completions}
    assert by_id["cmd-err"].status == "error"
    assert by_id["cmd-err"].exit_code == 2
    assert by_id["cmd-kill"].status == "killed"
    assert by_id["cmd-kill"].exit_code is None
    assert snapshot.completions == ()


def test_exit_watch_keeps_an_otherwise_irrelevant_proc_visible(
    monkeypatch,
) -> None:
    procs = [
        _proc(
            "cmd-x",
            status="success",
            exit_code=0,
            session_id="session-z",
            origin="cli",
        )
    ]
    _stub(monkeypatch, procs)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)

    assert observer._build_snapshot().projection.rows == ()

    observer.register_exit_watch("cmd-x")
    snapshot = observer._build_snapshot()
    assert [row.proc_id for row in snapshot.projection.rows] == ["cmd-x"]
    assert [item.proc_id for item in snapshot.exit_completions] == ["cmd-x"]


def test_exit_watch_stays_quiet_while_running(monkeypatch) -> None:
    procs = [_proc("cmd-run", status="running")]
    _stub(monkeypatch, procs)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)
    observer.register_exit_watch("cmd-run")

    assert observer._build_snapshot().exit_completions == ()

    procs[0] = _proc("cmd-run", status="success", exit_code=0)
    snapshot = observer._build_snapshot()
    assert [item.proc_id for item in snapshot.exit_completions] == ["cmd-run"]


def test_tail_subscriptions_are_ref_counted(monkeypatch, tmp_path) -> None:
    log_path = tmp_path / "cmd-tail.log"
    log_path.write_text("hello\n", encoding="utf-8")
    procs = [_proc("cmd-tail", status="running", log_path=str(log_path))]
    _stub(monkeypatch, procs)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)

    assert observer._build_snapshot().projection.rows[0].output == ""

    first = observer.subscribe_tail("cmd-tail")
    second = observer.subscribe_tail("cmd-tail")
    assert first != second
    assert observer._build_snapshot().projection.rows[0].output == "hello\n"

    observer.unsubscribe_tail(first)
    assert observer._build_snapshot().projection.rows[0].output == "hello\n"

    observer.unsubscribe_tail(second)
    assert observer._build_snapshot().projection.rows[0].output == ""

    # Unknown tokens are a no-op.
    observer.unsubscribe_tail("tail-missing")


def test_observed_rows_carry_store_tags(monkeypatch) -> None:
    procs = [
        _proc("cmd-tagged", status="success", exit_code=0, tags=["command-line"]),
        _proc("cmd-plain", status="success", exit_code=0),
    ]
    _stub(monkeypatch, procs)
    observer = ProcObserver(on_snapshot=lambda _snapshot: None)

    rows = {row.proc_id: row for row in observer._build_snapshot().projection.rows}
    assert rows["cmd-tagged"].tags == ("command-line",)
    assert rows["cmd-plain"].tags == ()
