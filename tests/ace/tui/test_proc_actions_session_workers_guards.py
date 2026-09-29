"""Session-worker dedup and scope-concurrency guards."""

from __future__ import annotations

from sase.ace.tui.proc_observer import ProcProjection
from tests.ace.tui._proc_actions_session_workers_shared import (
    ProcHost,
    durable_row,
    ok_result,
)

__all__ = [
    "test_durable_scope_blocks_session_worker",
    "test_pending_durable_scope_blocks_session_worker",
    "test_session_claim_releases_after_completion_and_error",
    "test_session_scope_blocks_durable_submit",
    "test_session_worker_rejects_duplicate_dedup_key",
    "test_session_worker_scope_overlap_rejects_but_disjoint_scope_runs",
    "test_session_workers_without_explicit_claims_can_overlap",
]


def test_session_worker_rejects_duplicate_dedup_key() -> None:
    host = ProcHost()

    first = host._submit_session_worker(
        "update",
        ok_result,
        dedup_key="same",
        duplicate_message="already running",
    )
    second = host._submit_session_worker(
        "update",
        ok_result,
        dedup_key="same",
        duplicate_message="already running",
    )

    assert first is not None
    assert second is None
    assert len(host.workers) == 1
    assert host.notices == [("already running", "warning")]


def test_session_worker_scope_overlap_rejects_but_disjoint_scope_runs() -> None:
    host = ProcHost()

    assert (
        host._submit_session_worker(
            "sync",
            ok_result,
            exclusive_scopes=("agents-sync",),
        )
        is not None
    )
    assert (
        host._submit_session_worker(
            "sync",
            ok_result,
            exclusive_scopes=("agents-sync", "sase-update"),
        )
        is None
    )
    assert (
        host._submit_session_worker(
            "sync",
            ok_result,
            exclusive_scopes=("agent-cli-update",),
        )
        is not None
    )
    assert len(host.workers) == 2


def test_session_workers_without_explicit_claims_can_overlap() -> None:
    host = ProcHost()

    assert host._submit_session_worker("one", ok_result, cl_name="shared") is not None
    assert host._submit_session_worker("two", ok_result, cl_name="shared") is not None

    assert len(host.workers) == 2
    assert host.notices == []


def test_durable_scope_blocks_session_worker() -> None:
    host = ProcHost(
        ProcProjection(rows=(durable_row(scope="sase-update"),), active_count=1)
    )

    result = host._submit_session_worker(
        "sase-update",
        ok_result,
        exclusive_scopes=("sase-update",),
        duplicate_message="durable already owns it",
    )

    assert result is None
    assert host.workers == []
    assert host.notices == [("durable already owns it", "warning")]


def test_pending_durable_scope_blocks_session_worker() -> None:
    host = ProcHost()
    host._proc_pending_scopes["pending-1"] = frozenset({"agents-sync"})

    result = host._submit_session_worker(
        "agents-sync",
        ok_result,
        exclusive_scopes=("agents-sync",),
        duplicate_message="pending durable already owns it",
    )

    assert result is None
    assert host.workers == []
    assert host.notices == [("pending durable already owns it", "warning")]


def test_session_scope_blocks_durable_submit() -> None:
    host = ProcHost()
    host._submit_session_worker(
        "sase-update", ok_result, exclusive_scopes=("sase-update",)
    )

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
    host = ProcHost()
    host._submit_session_worker("update", ok_result, dedup_key="same")

    host.complete_session_worker()

    assert (
        host._submit_session_worker("update", ok_result, dedup_key="same") is not None
    )
    host.fail_session_worker(1)
    assert (
        host._submit_session_worker("update", ok_result, dedup_key="same") is not None
    )
