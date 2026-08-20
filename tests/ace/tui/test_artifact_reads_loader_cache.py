"""Cache behavior tests for the per-agent artifact-reads loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.ace.tui import artifact_reads as artifact_reads_module
from sase.ace.tui.artifact_reads import (
    _load_artifact_reads_for_agent,
    load_artifact_reads_for_agent_context,
)
from sase.artifact_read_log import ArtifactReadEvent, artifact_read_log_path

from ._artifact_reads_loader_helpers import (
    clear_artifact_reads_cache_fixture,
    fake_project_fixture,
    make_agent,
    make_event,
    write_jsonl,
)


def test_cache_invalidates_on_mtime_change(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    log_path = artifact_read_log_path("artifact-reads-test")
    initial = [
        make_event(
            ref="plan:skill.md",
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
    first = _load_artifact_reads_for_agent(agent)
    assert len(first) == 1

    later = list(initial) + [
        make_event(
            ref="plan:other.md",
            timestamp="2026-05-24T10:10:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    write_jsonl(log_path, later)
    future_mtime_ns = log_path.stat().st_mtime_ns + 10_000_000_000
    os.utime(log_path, ns=(future_mtime_ns, future_mtime_ns))

    for cache in (
        artifact_reads_module._artifact_reads_cache,
        artifact_reads_module._artifact_reads_snapshot_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    second = _load_artifact_reads_for_agent(agent)
    assert [event.ref for event in second] == [
        "plan:other.md",
        "plan:skill.md",
    ]


def test_reread_throttle_keeps_stale_snapshot_inside_window(
    fake_project: Path, tmp_path: Path
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)
    log_path = artifact_read_log_path("artifact-reads-test")
    initial = [
        make_event(
            ref="plan:skill.md",
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
    first = _load_artifact_reads_for_agent(agent)

    write_jsonl(
        log_path,
        [
            *initial,
            make_event(
                ref="plan:other.md",
                timestamp="2026-05-24T10:10:00+00:00",
                agent_name="alpha",
                artifacts_dir=str(artifacts_dir),
            ),
        ],
    )
    future_mtime_ns = log_path.stat().st_mtime_ns + 10_000_000_000
    os.utime(log_path, ns=(future_mtime_ns, future_mtime_ns))

    throttled = _load_artifact_reads_for_agent(agent)
    assert [event.ref for event in throttled] == [event.ref for event in first]

    for cache in (
        artifact_reads_module._artifact_reads_cache,
        artifact_reads_module._artifact_reads_snapshot_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    refreshed = _load_artifact_reads_for_agent(agent)
    assert [event.ref for event in refreshed] == [
        "plan:other.md",
        "plan:skill.md",
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
    log_path = artifact_read_log_path("artifact-reads-test")

    events = [
        make_event(
            ref="plan:alpha.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
            read_id="alpha-read",
        ),
        make_event(
            ref="plan:beta.md",
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
            read_id="beta-read",
        ),
    ]
    write_jsonl(log_path, events)
    parsed_events = list(events)
    parse_count = 0

    def fake_read_artifact_read_events(
        *,
        project: str | None = None,
        log_path: Path | None = None,
    ) -> tuple[ArtifactReadEvent, ...]:
        nonlocal parse_count
        assert project == "artifact-reads-test"
        assert log_path is not None
        parse_count += 1
        return tuple(parsed_events)

    monkeypatch.setattr(
        artifact_reads_module,
        "read_artifact_read_events",
        fake_read_artifact_read_events,
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
        item.event.ref for item in load_artifact_reads_for_agent_context(agent_a)
    ] == ["plan:alpha.md"]
    assert [
        item.event.ref for item in load_artifact_reads_for_agent_context(agent_b)
    ] == ["plan:beta.md"]
    assert parse_count == 1

    parsed_events.append(
        make_event(
            ref="plan:alpha-new.md",
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
        artifact_reads_module._artifact_reads_cache,
        artifact_reads_module._artifact_reads_snapshot_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    assert [
        item.event.ref for item in load_artifact_reads_for_agent_context(agent_a)
    ] == ["plan:alpha-new.md", "plan:alpha.md"]
    assert [
        item.event.ref for item in load_artifact_reads_for_agent_context(agent_b)
    ] == ["plan:beta.md"]
    assert parse_count == 2
