"""Tests for selecting an agent's artifact-read events."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.artifact_reads import _load_artifact_reads_for_agent
from sase.artifact_read_log import artifact_read_log_path

from ._artifact_reads_loader_helpers import (
    clear_artifact_reads_cache_fixture,
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
            ref="plan:skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
        ),
        make_event(
            ref="plan:other.md",
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
        ),
    ]
    write_jsonl(artifact_read_log_path("artifact-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_a,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_artifact_reads_for_agent(agent)

    assert [event.ref for event in result] == ["plan:skill.md"]


def test_fallback_to_agent_name_when_artifacts_dir_missing(
    fake_project: Path, tmp_path: Path
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            ref="plan:skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=None,
            resolved_path=None,
        ),
        make_event(
            ref="plan:other.md",
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=None,
            resolved_path=None,
        ),
    ]
    write_jsonl(artifact_read_log_path("artifact-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_artifact_reads_for_agent(agent)

    assert [event.ref for event in result] == ["plan:skill.md"]


def test_results_are_newest_first(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            ref="plan:a.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        make_event(
            ref="plan:b.md",
            timestamp="2026-05-24T10:05:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        make_event(
            ref="plan:c.md",
            timestamp="2026-05-24T10:02:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
    ]
    write_jsonl(artifact_read_log_path("artifact-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_artifact_reads_for_agent(agent)

    assert [event.ref for event in result] == [
        "plan:b.md",
        "plan:c.md",
        "plan:a.md",
    ]


def test_limit_caps_returned_events(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            ref=f"plan:file_{index}.md",
            timestamp=f"2026-05-24T10:{index:02d}:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
            read_id=f"id-{index}",
        )
        for index in range(10)
    ]
    write_jsonl(artifact_read_log_path("artifact-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_artifact_reads_for_agent(agent, limit=3)

    assert len(result) == 3
    assert result[0].ref == "plan:file_9.md"


def test_empty_project_returns_empty_tuple(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)
    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )

    assert _load_artifact_reads_for_agent(agent) == ()


def test_event_with_artifacts_dir_does_not_match_other_agent(
    fake_project: Path, tmp_path: Path
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)
    other_artifacts = tmp_path / "artifacts" / "agent_b"
    other_artifacts.mkdir(parents=True)

    events = [
        make_event(
            ref="plan:skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(other_artifacts),
        )
    ]
    write_jsonl(artifact_read_log_path("artifact-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )

    assert _load_artifact_reads_for_agent(agent) == ()


def test_normalizes_trailing_slash_and_symlink(
    fake_project: Path, tmp_path: Path
) -> None:
    real_dir = tmp_path / "real_artifacts"
    real_dir.mkdir()
    symlink_dir = tmp_path / "linked_artifacts"
    symlink_dir.symlink_to(real_dir)

    event = make_event(
        ref="plan:skill.md",
        timestamp="2026-05-24T10:00:00+00:00",
        agent_name="alpha",
        artifacts_dir=str(real_dir) + "/",
    )
    write_jsonl(artifact_read_log_path("artifact-reads-test"), [event])

    agent = make_agent(
        artifacts_dir=symlink_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_artifact_reads_for_agent(agent)

    assert [event.ref for event in result] == ["plan:skill.md"]


def test_malformed_and_unreadable_logs_degrade_to_empty(
    fake_project: Path, tmp_path: Path
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)
    log_path = artifact_read_log_path("artifact-reads-test")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("{not-json\n", encoding="utf-8")

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    assert _load_artifact_reads_for_agent(agent) == ()

    log_path.unlink()
    log_path.mkdir()
    assert _load_artifact_reads_for_agent(agent) == ()
