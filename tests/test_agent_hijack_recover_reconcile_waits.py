"""Successor-following waits for keep-work recovery."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent


def _hijacked_agent(
    base: Path, name: str, suffix: str, successor: str, state: str
) -> Path:
    agent_dir = make_agent(base, "proj", suffix, name, done=True, outcome="hijacked")
    done_data = {
        "outcome": "hijacked",
        "recovery": {
            "kind": "hijack",
            "state": state,
            "successor": successor,
        },
    }
    (agent_dir / "done.json").write_text(json.dumps(done_data))
    return agent_dir


def test_name_wait_follows_resolved_successor(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "resolved")
    make_agent(
        tmp_path, "proj", "20260506010202", "acme--4", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert dependency_resolution_status(index, ["acme--3"]).resolved


def test_name_wait_follows_failure(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "resolved")
    make_agent(
        tmp_path, "proj", "20260506010202", "acme--4", done=True, outcome="failed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert not dependency_resolution_status(index, ["acme--3"]).resolved


def test_pending_hijack_stays_parked(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "pending")
    make_agent(
        tmp_path, "proj", "20260506010202", "acme--4", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert not dependency_resolution_status(index, ["acme--3"]).resolved


def test_expired_hijack_stays_parked(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "expired")
    make_agent(
        tmp_path, "proj", "20260506010202", "acme--4", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert not dependency_resolution_status(index, ["acme--3"]).resolved


def test_missing_successor_stays_waiting(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--9", "resolved")
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert not dependency_resolution_status(index, ["acme--3"]).resolved


def test_chained_recovery_follows_two_hops(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "resolved")
    _hijacked_agent(tmp_path, "acme--4", "20260506010202", "acme--5", "resolved")
    make_agent(
        tmp_path, "proj", "20260506010303", "acme--5", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert dependency_resolution_status(index, ["acme--3"]).resolved
    assert dependency_resolution_status(index, ["acme--4"]).resolved


def test_session_wait_follows_successor_in_same_session(tmp_path: Path) -> None:
    pre = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "sess--0",
        workflow_name="sess",
        agent_session="sess",
        done=True,
        outcome="hijacked",
    )
    (pre / "done.json").write_text(
        json.dumps(
            {
                "outcome": "hijacked",
                "recovery": {
                    "kind": "hijack",
                    "state": "resolved",
                    "successor": "sess--1",
                },
            }
        )
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "sess--1",
        workflow_name="sess",
        agent_session="sess",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert dependency_resolution_status(index, ["sess"]).resolved


def test_settlement_expired_neither_resolved_nor_failed(tmp_path: Path) -> None:
    from sase.core.wait_dependency_resolution import (
        build_wait_dependency_index,
    )

    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "expired")
    make_agent(
        tmp_path, "proj", "20260506010202", "acme--4", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert not dependency_resolution_status(index, ["acme--3"]).resolved
    assert index.terminal_blocking_artifacts_for_name("acme--3") == ()


def test_settlement_newest_artifact_wins_name_collision(tmp_path: Path) -> None:
    _hijacked_agent(tmp_path, "acme--3", "20260506010101", "acme--4", "resolved")
    _hijacked_agent(tmp_path, "acme--3", "20260506010303", "acme--5", "resolved")
    make_agent(
        tmp_path, "proj", "20260506010404", "acme--5", done=True, outcome="completed"
    )
    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert dependency_resolution_status(index, ["acme--3"]).resolved
    assert index.terminal_blocking_artifacts_for_name("acme--3") == ()
