"""Tests for proc-store reads during monitor reconciliation."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from sase.monitor.store import (
    active_monitor_for_lane,
    list_monitors,
    monitor_blocking_start_for_lane,
    reconcile_dead_supervisors,
)

from ._fixtures import DEAD_PID, make_starter_agent, patch_project_records


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def test_reconcile_dead_supervisors_reads_proc_store_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.reconcile as reconcile_module
    import sase.procs.store as proc_store

    dirs = [
        make_starter_agent(
            "proj",
            f"20260812{120000 + index:06d}",
            f"acme--mon{index}",
            agent_family="acme",
            agent_family_role="monitor",
            monitor_id=f"mon{index:09d}",
            monitor_state="running",
            monitor_command="sleep 60",
            pid=DEAD_PID,
        )
        for index in range(8)
    ]
    patch_project_records(monkeypatch, dirs)
    monkeypatch.setattr(reconcile_module, "supervisor_is_alive", lambda *_a, **_k: True)
    reads = _count_proc_store_reads(monkeypatch, proc_store)

    assert reconcile_dead_supervisors(project="proj") == []
    assert reads == ["read_procs_snapshot"]


def test_lane_helpers_read_proc_store_once_per_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.reconcile as reconcile_module
    import sase.procs.store as proc_store

    dirs = [
        make_starter_agent(
            "proj",
            f"20260812{120000 + index:06d}",
            f"acme--mon{index}",
            agent_family="acme",
            agent_family_role="monitor",
            monitor_id=f"lane{index:08d}",
            monitor_state="running",
            monitor_command="sleep 60",
            pid=DEAD_PID,
        )
        for index in range(8)
    ]
    patch_project_records(monkeypatch, dirs)
    monkeypatch.setattr(reconcile_module, "supervisor_is_alive", lambda *_a, **_k: True)
    reads = _count_proc_store_reads(monkeypatch, proc_store)

    active = active_monitor_for_lane("proj", "acme")
    assert active is not None
    assert reads == ["read_procs_snapshot"]

    reads.clear()
    blocking = monitor_blocking_start_for_lane("proj", "acme")
    assert blocking is not None
    assert reads == ["read_procs_snapshot"]


def test_lane_helpers_skip_the_proc_store_without_a_lane_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.procs.store as proc_store

    other_lane = make_starter_agent(
        "proj",
        "20260812120000",
        "beta--mon",
        agent_family="beta",
        agent_family_role="monitor",
        monitor_id="beta00001",
        monitor_state="running",
        monitor_command="sleep 60",
        pid=DEAD_PID,
    )
    patch_project_records(monkeypatch, [other_lane])
    reads = _count_proc_store_reads(monkeypatch, proc_store)

    assert active_monitor_for_lane("proj", "acme") is None
    assert monitor_blocking_start_for_lane("proj", "acme") is None
    assert reads == []


def test_list_monitors_proc_store_reads_do_not_scale_with_record_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.reconcile as reconcile_module
    import sase.procs.store as proc_store

    monkeypatch.setattr(reconcile_module, "supervisor_is_alive", lambda *_a, **_k: True)

    def count_reads(record_count: int, *, clock_base: int) -> int:
        dirs = [
            make_starter_agent(
                "proj",
                f"20260812{clock_base + index:06d}",
                f"acme--mon{clock_base}{index}",
                agent_family="acme",
                agent_family_role="monitor",
                monitor_id=f"m{clock_base:05d}{index:06d}",
                monitor_state="running",
                monitor_command="sleep 60",
                pid=DEAD_PID,
            )
            for index in range(record_count)
        ]
        patch_project_records(monkeypatch, dirs)
        reads = _count_proc_store_reads(monkeypatch, proc_store)
        listed = list_monitors(project="proj")
        assert len(listed) == record_count
        return len(reads)

    small = count_reads(3, clock_base=120000)
    large = count_reads(12, clock_base=130000)
    assert small == large
    assert 1 <= small <= 2


def _count_proc_store_reads(
    monkeypatch: pytest.MonkeyPatch, proc_store: Any
) -> list[str]:
    """Count this thread's proc-store reads until the patch is undone.

    The binding patch is process-global, so a background reconcile pass
    from an unrelated test -- ACE schedules one through
    ``asyncio.to_thread`` -- would otherwise land in the caller's counter
    and inflate it under the full parallel lane.
    """
    reads: list[str] = []
    original = proc_store._call_binding
    owner = threading.get_ident()

    def counting(name: str, *args: object) -> object:
        if name == "read_procs_snapshot" and threading.get_ident() == owner:
            reads.append(name)
        return original(name, *args)

    monkeypatch.setattr(proc_store, "_call_binding", counting)
    return reads
