"""Cache behavior tests for the per-agent glossary-reads loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.ace.tui import glossary_reads as glossary_reads_module
from sase.ace.tui.glossary_reads import (
    _load_glossary_reads_for_agent,
    load_glossary_reads_for_agent_context,
)
from sase.memory.legacy_glossary_read_log import (
    GlossaryReadEvent,
    glossary_read_log_path,
)

from ._glossary_reads_loader_helpers import (
    clear_glossary_reads_cache_fixture,
    fake_project_fixture,
    make_agent,
    make_event,
    write_jsonl,
)


def test_cache_invalidates_on_mtime_change(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    log_path = glossary_read_log_path("glossary-reads-test")
    initial = [
        make_event(
            terms=("Agent Hood",),
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
    first = _load_glossary_reads_for_agent(agent)
    assert len(first) == 1

    # Force a future mtime so the cache invalidates even though the throttle
    # window may not have elapsed.
    later = list(initial) + [
        make_event(
            terms=("Stitch",),
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
        glossary_reads_module._glossary_reads_cache,
        glossary_reads_module._glossary_reads_snapshot_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    second = _load_glossary_reads_for_agent(agent)
    assert [event.terms for event in second] == [
        ("Stitch",),
        ("Agent Hood",),
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
    log_path = glossary_read_log_path("glossary-reads-test")

    events = [
        make_event(
            terms=("Agent Hood",),
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
            read_id="alpha-read",
        ),
        make_event(
            terms=("Stitch",),
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
            read_id="beta-read",
        ),
    ]
    write_jsonl(log_path, events)
    parsed_events = list(events)
    parse_count = 0

    def fake_read_glossary_read_events(
        *,
        project: str | None = None,
        log_path: Path | None = None,
    ) -> tuple[GlossaryReadEvent, ...]:
        nonlocal parse_count
        assert project == "glossary-reads-test"
        assert log_path is None
        parse_count += 1
        return tuple(parsed_events)

    monkeypatch.setattr(
        glossary_reads_module,
        "read_glossary_read_events",
        fake_read_glossary_read_events,
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
        item.event.terms for item in load_glossary_reads_for_agent_context(agent_a)
    ] == [("Agent Hood",)]
    assert [
        item.event.terms for item in load_glossary_reads_for_agent_context(agent_b)
    ] == [("Stitch",)]
    assert parse_count == 1

    parsed_events.append(
        make_event(
            terms=("Agent Family",),
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
        glossary_reads_module._glossary_reads_cache,
        glossary_reads_module._glossary_reads_snapshot_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    assert [
        item.event.terms for item in load_glossary_reads_for_agent_context(agent_a)
    ] == [("Agent Family",), ("Agent Hood",)]
    assert [
        item.event.terms for item in load_glossary_reads_for_agent_context(agent_b)
    ] == [("Stitch",)]
    assert parse_count == 2
