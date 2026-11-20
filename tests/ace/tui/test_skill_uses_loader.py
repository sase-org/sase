"""Tests for selecting an agent's skill-use events."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.skill_uses import _load_skill_uses_for_agent
from sase.skills.use_log import skill_use_log_path

from ._skill_uses_loader_helpers import (
    clear_skill_uses_cache_fixture,
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
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
        ),
        make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
        ),
    ]
    write_jsonl(skill_use_log_path("skill-uses-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_a,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_skill_uses_for_agent(agent)

    assert [event.skill_name for event in result] == ["sase_plan"]


def test_fallback_to_agent_name_when_artifacts_dir_missing(
    fake_project: Path, tmp_path: Path
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=None,
        ),
        make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=None,
        ),
    ]
    write_jsonl(skill_use_log_path("skill-uses-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_skill_uses_for_agent(agent)

    assert [event.skill_name for event in result] == ["sase_plan"]


def test_results_are_newest_first(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:05:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        make_event(
            skill_name="sase_notify",
            timestamp="2026-06-14T10:02:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
    ]
    write_jsonl(skill_use_log_path("skill-uses-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_skill_uses_for_agent(agent)

    assert [event.skill_name for event in result] == [
        "sase_questions",
        "sase_notify",
        "sase_plan",
    ]


def test_limit_caps_returned_events(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            skill_name=f"skill_{index}",
            timestamp=f"2026-06-14T10:{index:02d}:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
            use_id=f"id-{index}",
        )
        for index in range(10)
    ]
    write_jsonl(skill_use_log_path("skill-uses-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_skill_uses_for_agent(agent, limit=3)

    assert len(result) == 3
    assert result[0].skill_name == "skill_9"
