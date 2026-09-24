"""Tests for the registry that tells tree termination what not to reap."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.process_registry import read_process_registry


def _proc(proc_id: str, pid: int | None, pgid: int | None, kind: str = "command"):
    return SimpleNamespace(proc_id=proc_id, pid=pid, pgid=pgid, kind=kind)


def _agent(pid: int | None, **kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(
        pid=pid,
        project="proj",
        artifacts_dir=kwargs.pop("artifacts_dir", None),
        monitor_id=kwargs.pop("monitor_id", None),
        monitor_state=kwargs.pop("monitor_state", None),
    )


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    data: dict[str, list[Any]] = {"agents": [], "procs": []}
    monkeypatch.setattr(
        "sase.agent.running_listing.list_running_agents",
        lambda **_kwargs: data["agents"],
    )
    monkeypatch.setattr("sase.procs.store.read_procs", lambda **_kwargs: data["procs"])
    return data


def test_procs_become_supervisors_and_tui_procs_are_protected(
    stores: dict[str, list[Any]],
) -> None:
    stores["procs"] = [_proc("p1", 10, 11), _proc("p2", 20, 21, kind="tui")]

    registry = read_process_registry(root_pid=1)

    assert registry is not None
    assert [(s.label, s.pids) for s in registry.supervisors] == [
        ("proc p1", frozenset({10, 11}))
    ]
    assert registry.protected_pids == frozenset({20, 21})


def test_other_agents_are_protected_but_the_target_itself_is_not(
    stores: dict[str, list[Any]],
) -> None:
    stores["agents"] = [_agent(100), _agent(200), _agent(None)]

    registry = read_process_registry(root_pid=100)

    assert registry is not None
    assert registry.protected_pids == frozenset({200})


def test_a_running_monitor_stops_through_its_canonical_stop(
    stores: dict[str, list[Any]],
) -> None:
    stores["agents"] = [
        _agent(300, monitor_id="legacy", monitor_state="running", artifacts_dir="/a"),
        _agent(400, monitor_id="proc-backed", monitor_state="running"),
    ]
    stores["procs"] = [_proc("proc-backed", 400, 401)]

    registry = read_process_registry(root_pid=1)

    assert registry is not None
    labels = {supervisor.label: supervisor.pids for supervisor in registry.supervisors}
    assert labels == {
        "proc proc-backed": frozenset({400, 401}),
        "monitor legacy": frozenset({300}),
    }
    # Supervisors are stopped, never shielded as if they were sibling agents.
    assert registry.protected_pids == frozenset()


def test_an_unreadable_registry_is_reported_as_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**_kwargs: Any) -> None:
        raise OSError("index unavailable")

    monkeypatch.setattr("sase.agent.running_listing.list_running_agents", boom)

    assert read_process_registry(root_pid=1) is None
