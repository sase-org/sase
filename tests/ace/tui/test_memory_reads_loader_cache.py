"""Cache behavior tests for the per-agent memory-reads loader."""

from __future__ import annotations

import gc
import os
from pathlib import Path
import weakref

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
    for cache in (memory_reads_module._memory_reads_cache,):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    second = _load_memory_reads_for_agent(agent)
    assert [event.canonical_path for event in second] == [
        "other.md",
        "skill.md",
    ]


def test_targeted_queries_replace_snapshot_parse_once(
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

    from sase.memory import _read_log_query_facade as audit_query
    from sase.memory._read_log_query_facade import (
        MemoryAuditSourceIdentity,
        _MemoryAuditRow,
    )

    query_count = 0
    real_query = audit_query.query_memory_audit

    def counting_query(
        log_path_arg: Path,
        *,
        members: list[dict[str, object]],
        limit: int = 50,
        deduplicate: bool = False,
    ) -> tuple[list[_MemoryAuditRow], MemoryAuditSourceIdentity]:
        nonlocal query_count
        query_count += 1
        return real_query(
            log_path_arg, members=members, limit=limit, deduplicate=deduplicate
        )

    monkeypatch.setattr(audit_query, "query_memory_audit", counting_query)

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
    # Two targeted queries (one per agent), no shared project-wide snapshot.
    assert query_count == 2
    assert not hasattr(memory_reads_module, "_memory_reads_snapshot_cache")

    # Cache hits do not re-query.
    assert [
        item.event.canonical_path
        for item in load_memory_reads_for_agent_context(agent_a)
    ] == ["alpha.md"]
    assert query_count == 2

    parsed_events = list(events)
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
        memory_reads_module._memory_reads_context_cache,
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
    # Revalidation re-queries only the drifted selectors.
    assert query_count > 2


def test_evicted_agent_result_reloads_identically_and_releases_its_entry(
    fake_project: Path, tmp_path: Path
) -> None:
    agents = []
    events = []
    for index in range(129):
        artifacts_dir = tmp_path / "artifacts" / f"agent_{index}"
        artifacts_dir.mkdir(parents=True)
        agent_name = f"agent-{index}"
        agents.append(
            make_agent(
                artifacts_dir=artifacts_dir,
                agent_name=agent_name,
                workspace_dir=fake_project,
                raw_suffix=f"20260524-10{index:04d}",
            )
        )
        events.append(
            make_event(
                canonical_path=f"{agent_name}.md",
                timestamp=f"2026-05-24T10:{index // 60:02d}:{index % 60:02d}+00:00",
                agent_name=agent_name,
                artifacts_dir=str(artifacts_dir),
            )
        )

    write_jsonl(memory_read_log_path("memory-reads-test"), events)
    expected = tuple(event.id for event in _load_memory_reads_for_agent(agents[0]))
    for agent in agents[1:]:
        _load_memory_reads_for_agent(agent)

    cache = memory_reads_module._memory_reads_cache
    first_key = memory_reads_module._cache_key("memory-reads-test", agents[0])
    second_key = memory_reads_module._cache_key("memory-reads-test", agents[1])
    assert len(cache) == 128
    assert cache.peek(first_key) is None
    second_entry_ref = weakref.ref(cache.peek(second_key))

    reloaded = tuple(event.id for event in _load_memory_reads_for_agent(agents[0]))
    gc.collect()

    assert reloaded == expected
    assert len(cache) == 128
    assert second_entry_ref() is None
    # No project-wide snapshot survives: bounded per-agent entries only.
    assert not hasattr(memory_reads_module, "_memory_reads_snapshot_cache")


def test_project_switch_keeps_same_agent_results_separate(
    fake_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "shared-agent"
    artifacts_dir.mkdir(parents=True)
    projects = ("project-alpha", "project-beta")
    monkeypatch.setattr(
        memory_reads_module,
        "project_memory_name",
        lambda workspace: Path(workspace).name,
    )
    from sase.memory import _read_log_query_facade as audit_query
    from sase.memory._read_log_query_facade import (
        MemoryAuditSourceIdentity,
        _MemoryAuditRow,
    )

    def fake_query(
        log_path_arg: Path,
        *,
        members: list[dict[str, object]],
        limit: int = 50,
        deduplicate: bool = False,
    ) -> tuple[list[_MemoryAuditRow], MemoryAuditSourceIdentity]:
        # Route by the project encoded in the log path's parent project key.
        # memory_read_log_path places the project in the path; emulate it.
        text = str(log_path_arg)
        if "project-alpha" in text or "project_alpha" in text:
            project: str = "project-alpha"
        else:
            project = "project-beta"
        from sase.memory.read_log import READ_LOG_SCHEMA_VERSION

        event = MemoryReadEvent(
            schema_version=READ_LOG_SCHEMA_VERSION,
            id=f"{project}-id",
            timestamp="2026-05-24T10:00:00+00:00",
            project=project,
            cwd="/tmp/test",
            canonical_path=f"{project}.md",
            resolved_path=f"/tmp/test/{project}.md",
            agent_name="shared-agent",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir=str(artifacts_dir),
            reason="context",
            byte_count=10,
            frontmatter_stripped=False,
        )
        source = MemoryAuditSourceIdentity(
            missing=False, size=10, mtime_ns=1, dev=1, ino=1
        )
        return [_MemoryAuditRow(event=event, member_index=0)], source

    monkeypatch.setattr(audit_query, "query_memory_audit", fake_query)
    agents = tuple(
        make_agent(
            artifacts_dir=artifacts_dir,
            agent_name="shared-agent",
            workspace_dir=tmp_path / project,
            raw_suffix="20260524-100000",
        )
        for project in projects
    )

    alpha = tuple(event.id for event in _load_memory_reads_for_agent(agents[0]))
    beta = tuple(event.id for event in _load_memory_reads_for_agent(agents[1]))
    alpha_again = tuple(event.id for event in _load_memory_reads_for_agent(agents[0]))

    assert alpha == ("project-alpha-id",)
    assert beta == ("project-beta-id",)
    assert alpha_again == alpha
    assert not hasattr(memory_reads_module, "_memory_reads_snapshot_cache")
