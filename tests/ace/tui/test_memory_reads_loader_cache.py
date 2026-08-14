"""Cache behavior tests for the per-agent memory-reads loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.ace.tui import memory_reads as memory_reads_module
from sase.ace.tui.memory_reads import (
    _load_memory_reads_for_agent,
    load_memory_reads_for_agent_context,
)
from sase.memory.read_log import MemoryReadEvent, memory_read_log_path

from ._memory_reads_loader_helpers import (
    clear_memory_reads_cache_fixture,
    fake_project_fixture,
    make_agent,
    make_event,
    write_jsonl,
)


def test_cache_invalidates_on_mtime_change(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    log_path = memory_read_log_path("memory-reads-test")
    initial = [
        make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    write_jsonl(log_path, initial)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    first = _load_memory_reads_for_agent(agent)
    assert len(first) == 1

    # Force a future mtime so the cache invalidates even though the throttle
    # window may not have elapsed.
    later = list(initial) + [
        make_event(
            canonical_path="other.md",
            timestamp="2026-05-24T10:10:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    write_jsonl(log_path, later)
    future_mtime_ns = log_path.stat().st_mtime_ns + 10_000_000_000
    os.utime(log_path, ns=(future_mtime_ns, future_mtime_ns))

    # Bypass the throttle window: rewind cached monotonic timestamp.
    for cache in (
        memory_reads_module._memory_reads_cache,
        memory_reads_module._memory_reads_snapshot_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    second = _load_memory_reads_for_agent(agent)
    assert [event.canonical_path for event in second] == [
        "other.md",
        "skill.md",
    ]


def test_snapshot_cache_parses_once_for_distinct_agents_and_revalidates(
    fake_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_a = tmp_path / "artifacts" / "agent_a"
    artifacts_b = tmp_path / "artifacts" / "agent_b"
    artifacts_a.mkdir(parents=True)
    artifacts_b.mkdir(parents=True)
    log_path = memory_read_log_path("memory-reads-test")

    events = [
        make_event(
            canonical_path="alpha.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
            read_id="alpha-read",
        ),
        make_event(
            canonical_path="beta.md",
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
            read_id="beta-read",
        ),
    ]
    write_jsonl(log_path, events)
    parsed_events = list(events)
    parse_count = 0

    def fake_read_memory_read_events(
        *,
        project: str | None = None,
        log_path: Path | None = None,
    ) -> tuple[MemoryReadEvent, ...]:
        nonlocal parse_count
        assert project == "memory-reads-test"
        assert log_path is None
        parse_count += 1
        return tuple(parsed_events)

    monkeypatch.setattr(
        memory_reads_module,
        "read_memory_read_events",
        fake_read_memory_read_events,
    )

    agent_a = make_agent(
        artifacts_dir=artifacts_a,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    agent_b = make_agent(
        artifacts_dir=artifacts_b,
        agent_name="beta",
        workspace_dir=fake_project,
        raw_suffix="20260524-100001",
    )

    assert [
        item.event.canonical_path
        for item in load_memory_reads_for_agent_context(agent_a)
    ] == ["alpha.md"]
    assert [
        item.event.canonical_path
        for item in load_memory_reads_for_agent_context(agent_b)
    ] == ["beta.md"]
    assert parse_count == 1

    parsed_events.append(
        make_event(
            canonical_path="alpha-new.md",
            timestamp="2026-05-24T10:10:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
            read_id="alpha-new-read",
        )
    )
    write_jsonl(log_path, parsed_events)
    future_mtime_ns = log_path.stat().st_mtime_ns + 10_000_000_000
    os.utime(log_path, ns=(future_mtime_ns, future_mtime_ns))
    for cache in (
        memory_reads_module._memory_reads_cache,
        memory_reads_module._memory_reads_snapshot_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    assert [
        item.event.canonical_path
        for item in load_memory_reads_for_agent_context(agent_a)
    ] == ["alpha-new.md", "alpha.md"]
    assert [
        item.event.canonical_path
        for item in load_memory_reads_for_agent_context(agent_b)
    ] == ["beta.md"]
    assert parse_count == 2
