"""Tests for the Rust proc-store facade: CRUD round trips and the
reserve/claim/settle proc-shell lifecycle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.procs import (
    PROC_WIRE_SCHEMA_VERSION,
    ProcFinish,
    ProcSettlement,
    ProcStopRequest,
    ProcSupervisorClaim,
    append_proc,
    begin_proc_settlement,
    claim_proc_supervisor,
    finish_proc,
    get_proc,
    read_proc_snapshot,
    read_procs,
    request_proc_stop,
    reserve_proc,
    update_proc,
)

from tests._procs_facade_helpers import _proc, _reserve


def test_rust_facade_round_trip_update_and_get(tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    proc = _proc("0123456789ab")

    appended = append_proc(proc, path=store, history_limit=5)
    updated = update_proc(
        proc.proc_id,
        path=store,
        status="running",
        phase=None,
        pid=4321,
    )

    assert appended.schema_version == PROC_WIRE_SCHEMA_VERSION
    assert updated.matched is True
    assert updated.proc is not None
    assert updated.proc.status == "running"
    assert updated.proc.phase is None
    assert updated.proc.pid == 4321
    assert get_proc(proc.proc_id, path=store) == updated.proc
    assert read_procs(path=store, status="running") == [updated.proc]


def test_get_proc_resolves_many_ids_from_one_snapshot(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import sase.procs.store as proc_store

    store = tmp_path / "procs.jsonl"
    first = _proc("aaaaaaaaaaaa", created_at="2026-07-25T12:00:00Z")
    second = _proc("bbbbbbbbbbbb", created_at="2026-07-25T12:01:00Z")
    append_proc(first, path=store, history_limit=10)
    append_proc(second, path=store, history_limit=10)

    snapshot = read_proc_snapshot(path=store)
    reads: list[str] = []
    original = proc_store._call_binding

    def counting(name: str, *args: object) -> object:
        if name == "read_procs_snapshot":
            reads.append(name)
        return original(name, *args)

    monkeypatch.setattr(proc_store, "_call_binding", counting)

    found_first = get_proc(first.proc_id, snapshot=snapshot)
    found_second = get_proc(second.proc_id, snapshot=snapshot)
    assert found_first is not None
    assert found_first.proc_id == first.proc_id
    assert found_second is not None
    assert found_second.proc_id == second.proc_id
    assert get_proc("missingxxxxx", snapshot=snapshot) is None
    assert reads == []

    assert get_proc(first.proc_id, path=store) is not None
    assert reads == ["read_procs_snapshot"]


def test_proc_shell_reserve_conflicts_and_lifecycle_facade(tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"

    reserved = reserve_proc(_reserve("reserved-one"), path=store, history_limit=10)
    assert reserved.reserved is True
    assert reserved.replayed is False
    assert reserved.proc.schema_version == PROC_WIRE_SCHEMA_VERSION
    assert reserved.proc.lifecycle == "proc-shell"
    assert reserved.proc.argv == ["just", "docs"]

    replay = reserve_proc(
        _reserve("other-proc", fingerprint="fingerprint"),
        path=store,
        history_limit=10,
    )
    assert replay.reserved is False
    assert replay.replayed is True
    assert replay.proc.proc_id == "reserved-one"

    with pytest.raises(ValueError, match="shell_name"):
        reserve_proc(
            _reserve("conflict-one", fingerprint="different"),
            path=store,
            history_limit=10,
        )

    with pytest.raises(ValueError, match="concurrency_key"):
        reserve_proc(
            _reserve(
                "conflict-two",
                shell_name="agent--test",
                fingerprint="third",
                concurrency_keys=["docs"],
            ),
            path=store,
            history_limit=10,
        )

    with pytest.raises(ValueError, match="claimed"):
        finish_proc(
            ProcFinish(
                proc_id="reserved-one",
                supervisor_id="supervisor-a",
                status="success",
                finished_at="2026-07-25T12:00:10Z",
                exit_code=0,
            ),
            path=store,
        )

    claimed = claim_proc_supervisor(
        ProcSupervisorClaim(
            proc_id="reserved-one",
            supervisor_id="supervisor-a",
            claimed_at="2026-07-25T12:00:01Z",
            pid=123,
            pgid=123,
        ),
        path=store,
    ).proc
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.supervisor_id == "supervisor-a"

    stopped = request_proc_stop(
        ProcStopRequest(
            proc_id="reserved-one",
            requested_by="agent-one",
            requested_at="2026-07-25T12:00:02Z",
            reason="user",
        ),
        path=store,
    ).proc
    assert stopped is not None
    assert stopped.status == "running"
    assert stopped.stop_requested_by == "agent-one"

    with pytest.raises(ValueError, match="transition"):
        update_proc(
            "reserved-one",
            path=store,
            status="success",
            finished_at="2026-07-25T12:00:10Z",
        )

    settling = begin_proc_settlement(
        ProcSettlement(
            proc_id="reserved-one",
            supervisor_id="supervisor-a",
            settling_at="2026-07-25T12:00:03Z",
            exit_code=0,
            message="done",
        ),
        path=store,
    ).proc
    assert settling is not None
    assert settling.status == "settling"

    finished = finish_proc(
        ProcFinish(
            proc_id="reserved-one",
            supervisor_id="supervisor-a",
            status="success",
            finished_at="2026-07-25T12:00:10Z",
            exit_code=0,
            message="done",
            result={"ok": True},
        ),
        path=store,
    ).proc
    assert finished is not None
    assert finished.status == "success"
    assert finished.finished_by == "supervisor-a"
    assert finished.result == {"ok": True}
