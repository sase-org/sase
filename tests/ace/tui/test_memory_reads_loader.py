"""Tests for the per-agent memory-reads loader."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui import memory_reads as memory_reads_module
from sase.ace.tui.memory_reads import load_memory_reads_for_agent
from sase.ace.tui.models.agent import Agent, AgentType
from sase.memory.read_log import (
    READ_LOG_SCHEMA_VERSION,
    MemoryReadEvent,
    memory_read_log_path,
)


def _make_agent(
    *,
    artifacts_dir: Path | None,
    agent_name: str | None = None,
    workspace_dir: Path | None = None,
    raw_suffix: str = "20260524-100000",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="memory-reads-test",
        project_file="/tmp/memory-reads-test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 24, 10, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        workspace_dir=str(workspace_dir) if workspace_dir else None,
        artifacts_dir=str(artifacts_dir) if artifacts_dir else None,
    )


def _make_event(
    *,
    canonical_path: str,
    timestamp: str,
    agent_name: str,
    artifacts_dir: str | None,
    reason: str = "context",
    frontmatter_stripped: bool = False,
    project: str = "memory-reads-test",
    read_id: str | None = None,
) -> MemoryReadEvent:
    return MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id=read_id or canonical_path.replace("/", "_") + timestamp,
        timestamp=timestamp,
        project=project,
        cwd="/tmp/memory-reads-test",
        canonical_path=canonical_path,
        resolved_path=f"/tmp/memory-reads-test/memory/{canonical_path}",
        agent_name=agent_name,
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=artifacts_dir,
        reason=reason,
        byte_count=128,
        frontmatter_stripped=frontmatter_stripped,
    )


def _write_jsonl(path: Path, events: list[MemoryReadEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for event in events:
            json.dump(asdict(event), out, sort_keys=True)
            out.write("\n")


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    memory_reads_module._memory_reads_cache.clear()


@pytest.fixture
def fake_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(
        memory_reads_module,
        "project_memory_name",
        lambda _root: "memory-reads-test",
    )
    sase_home = tmp_path / "sase-home"
    sase_home.mkdir()
    monkeypatch.setenv("HOME", str(sase_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: sase_home))
    return project_root


def test_filter_by_artifacts_dir_exact_match(
    fake_project: Path, tmp_path: Path
) -> None:
    artifacts_a = tmp_path / "artifacts" / "agent_a"
    artifacts_b = tmp_path / "artifacts" / "agent_b"
    artifacts_a.mkdir(parents=True)
    artifacts_b.mkdir(parents=True)

    events = [
        _make_event(
            canonical_path="long/skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
        ),
        _make_event(
            canonical_path="long/other.md",
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
        ),
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = _make_agent(
        artifacts_dir=artifacts_a,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = load_memory_reads_for_agent(agent)

    assert [event.canonical_path for event in result] == ["long/skill.md"]


def test_fallback_to_agent_name_when_artifacts_dir_missing(
    fake_project: Path, tmp_path: Path
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        _make_event(
            canonical_path="long/skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=None,
        ),
        _make_event(
            canonical_path="long/other.md",
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=None,
        ),
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = load_memory_reads_for_agent(agent)

    assert [event.canonical_path for event in result] == ["long/skill.md"]


def test_results_are_newest_first(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        _make_event(
            canonical_path="long/a.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        _make_event(
            canonical_path="long/b.md",
            timestamp="2026-05-24T10:05:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        _make_event(
            canonical_path="long/c.md",
            timestamp="2026-05-24T10:02:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = load_memory_reads_for_agent(agent)

    assert [event.canonical_path for event in result] == [
        "long/b.md",
        "long/c.md",
        "long/a.md",
    ]


def test_limit_caps_returned_events(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        _make_event(
            canonical_path=f"long/file_{index}.md",
            timestamp=f"2026-05-24T10:{index:02d}:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
            read_id=f"id-{index}",
        )
        for index in range(10)
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = load_memory_reads_for_agent(agent, limit=3)

    assert len(result) == 3
    assert result[0].canonical_path == "long/file_9.md"


def test_empty_project_returns_empty_tuple(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)
    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )

    assert load_memory_reads_for_agent(agent) == ()


def test_cache_invalidates_on_mtime_change(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    log_path = memory_read_log_path("memory-reads-test")
    initial = [
        _make_event(
            canonical_path="long/skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    _write_jsonl(log_path, initial)

    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    first = load_memory_reads_for_agent(agent)
    assert len(first) == 1

    # Force a future mtime so the cache invalidates even though the throttle
    # window may not have elapsed.
    later = list(initial) + [
        _make_event(
            canonical_path="long/other.md",
            timestamp="2026-05-24T10:10:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    _write_jsonl(log_path, later)
    future_mtime_ns = log_path.stat().st_mtime_ns + 10_000_000_000
    import os as _os

    _os.utime(log_path, ns=(future_mtime_ns, future_mtime_ns))

    # Bypass the throttle window: rewind cached monotonic timestamp.
    for entry in memory_reads_module._memory_reads_cache.values():
        entry.last_read_monotonic = 0.0

    second = load_memory_reads_for_agent(agent)
    assert [event.canonical_path for event in second] == [
        "long/other.md",
        "long/skill.md",
    ]


def test_event_with_artifacts_dir_does_not_match_other_agent(
    fake_project: Path, tmp_path: Path
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)
    other_artifacts = tmp_path / "artifacts" / "agent_b"
    other_artifacts.mkdir(parents=True)

    # Same agent_name but a different artifacts_dir — must NOT match via name
    # fallback because artifacts_dir is set on the event.
    events = [
        _make_event(
            canonical_path="long/skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(other_artifacts),
        )
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )

    assert load_memory_reads_for_agent(agent) == ()


def test_normalizes_trailing_slash_and_symlink(
    fake_project: Path, tmp_path: Path
) -> None:
    real_dir = tmp_path / "real_artifacts"
    real_dir.mkdir()
    symlink_dir = tmp_path / "linked_artifacts"
    symlink_dir.symlink_to(real_dir)

    event = _make_event(
        canonical_path="long/skill.md",
        timestamp="2026-05-24T10:00:00+00:00",
        agent_name="alpha",
        artifacts_dir=str(real_dir) + "/",
    )
    _write_jsonl(memory_read_log_path("memory-reads-test"), [event])

    agent = _make_agent(
        artifacts_dir=symlink_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = load_memory_reads_for_agent(agent)

    assert [event.canonical_path for event in result] == ["long/skill.md"]
