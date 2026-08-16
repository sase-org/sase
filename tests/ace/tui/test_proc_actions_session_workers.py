"""Session-worker concurrency guards in ``ProcActionsMixin``."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.proc_actions import ProcActionsMixin, TrackedProcResult
from sase.ace.tui.modals.plugins_browser_sase_update_procs import (
    running_background_procs,
)
from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcObserverSnapshot,
    ProcProjection,
)
from sase.core.time import local_now
from sase.procs import store as proc_store


class _ProcHost(ProcActionsMixin):
    def __init__(self, projection: ProcProjection | None = None) -> None:
        self._proc_projection = projection or ProcProjection()
        self._durable_submit_workers: dict[str, Any] = {}
        self._session_workers: dict[str, Any] = {}
        self._session_completion_callbacks: dict[str, Any] = {}
        self._proc_completion_callbacks: dict[str, Any] = {}
        self._proc_pending_scopes: dict[str, frozenset[str]] = {}
        self.submitted_handles: list[Any] = []
        self._proc_observer = SimpleNamespace(
            register_pending=self._register_pending,
            register_submitted=self._register_submitted,
            remove_pending=lambda _placeholder_id: None,
        )
        self.notices: list[tuple[str, str]] = []
        self.workers: list[Any] = []
        self.pending_count = 0
        self.indicator_counts: list[int] = []

    def _register_submitted(self, **kwargs: Any) -> None:
        self.submitted_handles.append(kwargs)

    def _register_pending(self, **kwargs: Any) -> ObservedProc:
        self.pending_count += 1
        return ObservedProc(
            proc_id=f"pending-{self.pending_count}",
            proc_type=kwargs["proc_type"],
            cl_name=kwargs["cl_name"],
            project_file=kwargs["project_file"],
            status="pending",
            message="pending",
            started_at=local_now(),
            display_name=kwargs["display_name"],
            exclusive_scopes=frozenset(kwargs.get("exclusive_scopes", ())),
        )

    def notify(self, message: str, severity: str = "information") -> None:
        self.notices.append((message, severity))

    def run_worker(self, fn: Any, *, thread: bool = False) -> Any:
        assert thread is True
        worker = SimpleNamespace(result=None, error=None, _fn=fn)
        self.workers.append(worker)
        return worker

    def _update_proc_indicator(self) -> None:
        self.indicator_counts.append(self._effective_proc_projection().active_count)

    def _reload_and_reposition(self) -> None:
        return None

    def complete_session_worker(self, index: int = 0) -> None:
        worker = self.workers[index]
        worker.result = worker._fn()
        self._on_session_worker_completed(worker)

    def fail_session_worker(self, index: int = 0) -> None:
        worker = self.workers[index]
        worker.error = RuntimeError("boom")
        self._on_session_worker_error(worker)


def _ok() -> TrackedProcResult[None]:
    return TrackedProcResult(success=True, message="ok")


def _durable_row(*, scope: str) -> ObservedProc:
    return ObservedProc(
        proc_id="durable-1",
        proc_type="durable-update",
        cl_name="sase",
        project_file="",
        status="running",
        message="running",
        started_at=local_now(),
        exclusive_scopes=frozenset({scope}),
    )


def test_session_worker_rejects_duplicate_dedup_key() -> None:
    host = _ProcHost()

    first = host._submit_session_worker(
        "update",
        _ok,
        dedup_key="same",
        duplicate_message="already running",
    )
    second = host._submit_session_worker(
        "update",
        _ok,
        dedup_key="same",
        duplicate_message="already running",
    )

    assert first is not None
    assert second is None
    assert len(host.workers) == 1
    assert host.notices == [("already running", "warning")]


def test_session_worker_scope_overlap_rejects_but_disjoint_scope_runs() -> None:
    host = _ProcHost()

    assert (
        host._submit_session_worker(
            "sync",
            _ok,
            exclusive_scopes=("agents-sync",),
        )
        is not None
    )
    assert (
        host._submit_session_worker(
            "sync",
            _ok,
            exclusive_scopes=("agents-sync", "sase-update"),
        )
        is None
    )
    assert (
        host._submit_session_worker(
            "sync",
            _ok,
            exclusive_scopes=("agent-cli-update",),
        )
        is not None
    )
    assert len(host.workers) == 2


def test_session_workers_without_explicit_claims_can_overlap() -> None:
    host = _ProcHost()

    assert host._submit_session_worker("one", _ok, cl_name="shared") is not None
    assert host._submit_session_worker("two", _ok, cl_name="shared") is not None

    assert len(host.workers) == 2
    assert host.notices == []


def test_durable_scope_blocks_session_worker() -> None:
    host = _ProcHost(
        ProcProjection(rows=(_durable_row(scope="sase-update"),), active_count=1)
    )

    result = host._submit_session_worker(
        "sase-update",
        _ok,
        exclusive_scopes=("sase-update",),
        duplicate_message="durable already owns it",
    )

    assert result is None
    assert host.workers == []
    assert host.notices == [("durable already owns it", "warning")]


def test_pending_durable_scope_blocks_session_worker() -> None:
    host = _ProcHost()
    host._proc_pending_scopes["pending-1"] = frozenset({"agents-sync"})

    result = host._submit_session_worker(
        "agents-sync",
        _ok,
        exclusive_scopes=("agents-sync",),
        duplicate_message="pending durable already owns it",
    )

    assert result is None
    assert host.workers == []
    assert host.notices == [("pending durable already owns it", "warning")]


def test_session_scope_blocks_durable_submit() -> None:
    host = _ProcHost()
    host._submit_session_worker("sase-update", _ok, exclusive_scopes=("sase-update",))

    result = host._submit_durable_proc(
        ["sase", "patch", "status"],
        operation="patch.status",
        request={"payload": {"name": "demo"}},
        request_fingerprint="sha256:demo",
        concurrency_keys=("sase-update",),
        duplicate_message="session already owns it",
    )

    assert result is None
    assert host.pending_count == 0
    assert host.notices == [("session already owns it", "warning")]


def test_session_claim_releases_after_completion_and_error() -> None:
    host = _ProcHost()
    host._submit_session_worker("update", _ok, dedup_key="same")

    host.complete_session_worker()

    assert host._submit_session_worker("update", _ok, dedup_key="same") is not None
    host.fail_session_worker(1)
    assert host._submit_session_worker("update", _ok, dedup_key="same") is not None


def test_session_worker_appears_in_effective_projection_and_counts() -> None:
    host = _ProcHost(ProcProjection(session_id="session-mine"))

    submitted = host._submit_session_worker("sync", _ok, display_name="local sync")

    assert submitted is not None
    effective = host._effective_proc_projection()
    assert effective.active_count == 1
    assert [row.proc_id for row in effective.rows] == [submitted.proc_id]
    assert submitted.session_id == "session-mine"
    assert effective.scoped_rows(all_sessions=False) == [submitted]
    assert host.indicator_counts == [1]
    assert running_background_procs(host) == [submitted]


def test_session_overlay_preserves_rows_across_observer_snapshots() -> None:
    host = _ProcHost(ProcProjection(session_id="session-mine"))
    submitted = host._submit_session_worker("sync", _ok)
    assert submitted is not None
    durable = _durable_row(scope="other")

    host._apply_proc_observer_snapshot(
        ProcObserverSnapshot(
            projection=ProcProjection(
                rows=(durable,),
                active_count=1,
                session_id="session-mine",
            )
        )
    )

    effective = host._effective_proc_projection()
    assert {row.proc_id for row in effective.rows} == {
        submitted.proc_id,
        durable.proc_id,
    }
    assert effective.active_count == 2
    assert host._proc_projection.rows == (durable,)


def test_session_overlay_removes_row_after_success_and_error() -> None:
    host = _ProcHost(ProcProjection(session_id="session-mine"))
    first = host._submit_session_worker("sync", _ok)
    assert first is not None
    host.complete_session_worker()

    assert host._effective_proc_projection().rows == ()
    assert host.indicator_counts[-1] == 0
    assert running_background_procs(host) == []

    second = host._submit_session_worker("sync", _ok)
    assert second is not None
    host.fail_session_worker(1)

    assert host._effective_proc_projection().rows == ()
    assert running_background_procs(host) == []


def test_session_and_durable_rows_dedup_and_exclude_across_overlay() -> None:
    host = _ProcHost(
        ProcProjection(
            rows=(_durable_row(scope="sase-update"),),
            active_count=1,
            session_id="session-mine",
        )
    )
    local = host._submit_session_worker(
        "agents-sync",
        _ok,
        exclusive_scopes=("agents-sync",),
    )
    assert local is not None

    blocked_by_local = host._submit_session_worker(
        "agents-sync",
        _ok,
        exclusive_scopes=("agents-sync",),
        duplicate_message="local already owns it",
    )
    blocked_by_durable = host._submit_session_worker(
        "sase-update",
        _ok,
        exclusive_scopes=("sase-update",),
        duplicate_message="durable already owns it",
    )

    assert blocked_by_local is None
    assert blocked_by_durable is None
    assert host.notices == [
        ("local already owns it", "warning"),
        ("durable already owns it", "warning"),
    ]
    assert host._effective_proc_projection().scope_conflict({"agents-sync"}) is local
    assert host._effective_proc_projection().scope_conflict({"sase-update"}) is not None


def test_session_overlay_never_registers_observer_or_writes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[object] = []
    monkeypatch.setattr(
        proc_store,
        "append_proc",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )
    host = _ProcHost(ProcProjection(session_id="session-mine"))

    submitted = host._submit_session_worker("sync", _ok)

    assert submitted is not None
    assert host.pending_count == 0
    assert host.submitted_handles == []
    assert writes == []
    assert submitted.store_backed is False
