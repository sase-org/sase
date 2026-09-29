"""Fork-source wait-dependency tests for run-agent waits.

Split from ``tests.test_run_agent_wait_deps``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.axe.run_agent_wait_deps import initial_dependencies_resolved
from sase.procs import Proc, append_proc
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent

__all__ = [
    "test_fork_source_wait_binds_exact_agent_not_newer_namesake",
    "test_fork_source_wait_keeps_waiting_for_live_clan_member",
    "test_fork_source_wait_releases_failed_agent_dependency",
    "test_fork_source_wait_releases_failed_agent_session_generation",
    "test_fork_source_wait_releases_terminal_clan_generation",
    "test_fork_source_wait_resolves_proc_only_when_terminal",
]


def _artifact_fork_source(
    artifact_dir: Path,
    *,
    kind: str = "agent",
    name: str = "foo",
) -> dict[str, str]:
    return {
        "kind": kind,
        "name": name,
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
    }


def _clan_fork_source(name: str, generation: str) -> dict[str, str]:
    return {"kind": "clan", "name": name, "generation": generation}


def _proc_fork_source(name: str, proc_id: str) -> dict[str, str]:
    return {"kind": "proc", "name": name, "proc_id": proc_id}


def _write_proc(proc_id: str, *, status: str, proc_name: str = "build-docs") -> None:
    append_proc(
        Proc(
            proc_id=proc_id,
            label="Build docs",
            kind="command",
            status=status,
            command=["just", "docs"],
            cwd="/tmp/work",
            origin="xprompt-proc",
            created_at="2026-07-25T12:00:00Z",
            log_path="/tmp/proc.log",
            project="proj",
            proc_name=proc_name,
        )
    )


def test_fork_source_wait_releases_failed_agent_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="failed",
    )

    assert not initial_dependencies_resolved(
        ["foo"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    assert initial_dependencies_resolved(
        ["foo"],
        [],
        wait_fork_sources=[_artifact_fork_source(parent_dir)],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )


def test_fork_source_wait_binds_exact_agent_not_newer_namesake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    parent_dir = make_agent(tmp_path, "proj", "20260506010101", "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506020202",
        "foo",
        done=True,
        outcome="completed",
    )

    assert initial_dependencies_resolved(
        ["foo"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    assert not initial_dependencies_resolved(
        ["foo"],
        [],
        wait_fork_sources=[_artifact_fork_source(parent_dir)],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )


@pytest.mark.parametrize(
    "fork_source_kind",
    [
        "session",
        # legacy agent-family spelling: pre-rename stored fork sources.
        pytest.param("family", id="legacy-family"),
    ],
)
def test_fork_source_wait_releases_failed_agent_session_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fork_source_kind: str,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "planfam")
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "planfam--plan",
        workflow_name="planfam",
        agent_session="planfam",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "planfam--code",
        workflow_name="planfam",
        agent_session="planfam",
        role_suffix="--code",
        parent_timestamp=root_dir.name,
        done=True,
        outcome="failed",
    )

    assert not initial_dependencies_resolved(
        ["planfam"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    assert initial_dependencies_resolved(
        ["planfam"],
        [],
        wait_fork_sources=[
            _artifact_fork_source(root_dir, kind=fork_source_kind, name="planfam")
        ],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )


def test_fork_source_wait_releases_terminal_clan_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "research")
    generation = "20260717010000"
    for suffix, name, outcome in (
        ("20260717010101", "research.done", "completed"),
        ("20260717010202", "research.failed", "failed"),
    ):
        make_agent(
            tmp_path,
            "proj",
            suffix,
            name,
            done=True,
            outcome=outcome,
            extra_meta={
                "agent_clan": "research",
                "agent_clan_generation": generation,
            },
        )

    assert not initial_dependencies_resolved(
        ["research"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    assert initial_dependencies_resolved(
        ["research"],
        [],
        wait_fork_sources=[_clan_fork_source("research", generation)],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )


def test_fork_source_wait_keeps_waiting_for_live_clan_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "research")
    generation = "20260717010000"
    make_agent(
        tmp_path,
        "proj",
        "20260717010101",
        "research.done",
        done=True,
        outcome="completed",
        extra_meta={
            "agent_clan": "research",
            "agent_clan_generation": generation,
        },
    )
    make_agent(
        tmp_path,
        "proj",
        "20260717010202",
        "research.running",
        extra_meta={
            "agent_clan": "research",
            "agent_clan_generation": generation,
        },
    )

    assert not initial_dependencies_resolved(
        ["research"],
        [],
        wait_fork_sources=[_clan_fork_source("research", generation)],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )


@pytest.mark.parametrize(
    ("status", "resolved"),
    [("running", False), ("success", True), ("error", True), ("killed", True)],
)
def test_fork_source_wait_resolves_proc_only_when_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    resolved: bool,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "build-docs")
    _write_proc("proc0123456789ab", status=status, proc_name="build-docs")

    assert (
        initial_dependencies_resolved(
            ["build-docs"],
            [],
            wait_fork_sources=[_proc_fork_source("build-docs", "proc0123456789ab")],
            project_name="proj",
            artifacts_dir=str(waiter_dir),
        )
        is resolved
    )
