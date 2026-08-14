"""Tests for selecting an agent's memory-read events."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.memory_reads import _load_memory_reads_for_agent
from sase.memory.read_log import memory_read_log_path

from ._memory_reads_loader_helpers import (
    clear_memory_reads_cache_fixture,
    fake_project_fixture,
    make_agent,
    make_event,
    write_jsonl,
)


def test_filter_by_artifacts_dir_exact_match(
    fake_project: Path, tmp_path: Path
) -> None:
    artifacts_a = tmp_path / "artifacts" / "agent_a"
    artifacts_b = tmp_path / "artifacts" / "agent_b"
    artifacts_a.mkdir(parents=True)
    artifacts_b.mkdir(parents=True)

    events = [
        make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
        ),
        make_event(
            canonical_path="other.md",
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
        ),
    ]
    write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_a,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_memory_reads_for_agent(agent)

    assert [event.canonical_path for event in result] == ["skill.md"]


def test_fallback_to_agent_name_when_artifacts_dir_missing(
    fake_project: Path, tmp_path: Path
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=None,
        ),
        make_event(
            canonical_path="other.md",
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=None,
        ),
    ]
    write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_memory_reads_for_agent(agent)

    assert [event.canonical_path for event in result] == ["skill.md"]


def test_results_are_newest_first(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            canonical_path="a.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        make_event(
            canonical_path="b.md",
            timestamp="2026-05-24T10:05:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        make_event(
            canonical_path="c.md",
            timestamp="2026-05-24T10:02:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
    ]
    write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_memory_reads_for_agent(agent)

    assert [event.canonical_path for event in result] == [
        "b.md",
        "c.md",
        "a.md",
    ]


def test_limit_caps_returned_events(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            canonical_path=f"file_{index}.md",
            timestamp=f"2026-05-24T10:{index:02d}:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
            read_id=f"id-{index}",
        )
        for index in range(10)
    ]
    write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_memory_reads_for_agent(agent, limit=3)

    assert len(result) == 3
    assert result[0].canonical_path == "file_9.md"


def test_empty_project_returns_empty_tuple(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)
    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )

    assert _load_memory_reads_for_agent(agent) == ()


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
        make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(other_artifacts),
        )
    ]
    write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )

    assert _load_memory_reads_for_agent(agent) == ()


def test_normalizes_trailing_slash_and_symlink(
    fake_project: Path, tmp_path: Path
) -> None:
    real_dir = tmp_path / "real_artifacts"
    real_dir.mkdir()
    symlink_dir = tmp_path / "linked_artifacts"
    symlink_dir.symlink_to(real_dir)

    event = make_event(
        canonical_path="skill.md",
        timestamp="2026-05-24T10:00:00+00:00",
        agent_name="alpha",
        artifacts_dir=str(real_dir) + "/",
    )
    write_jsonl(memory_read_log_path("memory-reads-test"), [event])

    agent = make_agent(
        artifacts_dir=symlink_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_memory_reads_for_agent(agent)

    assert [event.canonical_path for event in result] == ["skill.md"]
