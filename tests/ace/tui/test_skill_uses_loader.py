"""Tests for the per-agent skill-uses loader."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui import skill_uses as skill_uses_module
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.skill_uses import (
    _load_skill_uses_for_agent,
    load_skill_uses_for_agent_context,
)
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
)
from sase.skills.use_log import (
    SKILL_USE_LOG_SCHEMA_VERSION,
    SkillUseEvent,
    skill_use_log_path,
)

HISTORICAL_Q_SUFFIX = "--q"


def _make_agent(
    *,
    artifacts_dir: Path | None,
    agent_name: str | None = None,
    workspace_dir: Path | None = None,
    raw_suffix: str = "20260614-100000",
    role_suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="skill-uses-test",
        project_file="/tmp/skill-uses-test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 14, 10, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        workspace_dir=str(workspace_dir) if workspace_dir else None,
        artifacts_dir=str(artifacts_dir) if artifacts_dir else None,
        role_suffix=role_suffix,
    )


def _make_event(
    *,
    skill_name: str,
    timestamp: str,
    agent_name: str,
    artifacts_dir: str | None,
    reason: str = "context",
    project: str = "skill-uses-test",
    use_id: str | None = None,
) -> SkillUseEvent:
    return SkillUseEvent(
        schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
        id=use_id or skill_name + timestamp,
        timestamp=timestamp,
        project=project,
        cwd="/tmp/skill-uses-test",
        skill_name=skill_name,
        agent_name=agent_name,
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=artifacts_dir,
        reason=reason,
        runtime="codex",
    )


def _write_jsonl(path: Path, events: list[SkillUseEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for event in events:
            json.dump(asdict(event), out, sort_keys=True)
            out.write("\n")


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    skill_uses_module._skill_uses_cache.clear()
    skill_uses_module._skill_uses_context_cache.clear()
    skill_uses_module._skill_uses_snapshot_cache.clear()


@pytest.fixture
def fake_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(
        skill_uses_module,
        "project_memory_name",
        lambda _root: "skill-uses-test",
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
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
        ),
        _make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
        ),
    ]
    _write_jsonl(skill_use_log_path("skill-uses-test"), events)

    agent = _make_agent(
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
        _make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=None,
        ),
        _make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=None,
        ),
    ]
    _write_jsonl(skill_use_log_path("skill-uses-test"), events)

    agent = _make_agent(
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
        _make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        _make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:05:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        _make_event(
            skill_name="sase_notify",
            timestamp="2026-06-14T10:02:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
    ]
    _write_jsonl(skill_use_log_path("skill-uses-test"), events)

    agent = _make_agent(
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
        _make_event(
            skill_name=f"skill_{index}",
            timestamp=f"2026-06-14T10:{index:02d}:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
            use_id=f"id-{index}",
        )
        for index in range(10)
    ]
    _write_jsonl(skill_use_log_path("skill-uses-test"), events)

    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_skill_uses_for_agent(agent, limit=3)

    assert len(result) == 3
    assert result[0].skill_name == "skill_9"


def test_cache_invalidates_on_mtime_change(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    log_path = skill_use_log_path("skill-uses-test")
    initial = [
        _make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
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
    first = _load_skill_uses_for_agent(agent)
    assert len(first) == 1

    later = list(initial) + [
        _make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:10:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    _write_jsonl(log_path, later)
    future_mtime_ns = log_path.stat().st_mtime_ns + 10_000_000_000
    import os as _os

    _os.utime(log_path, ns=(future_mtime_ns, future_mtime_ns))

    for cache in (
        skill_uses_module._skill_uses_cache,
        skill_uses_module._skill_uses_snapshot_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    second = _load_skill_uses_for_agent(agent)
    assert [event.skill_name for event in second] == [
        "sase_questions",
        "sase_plan",
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
    log_path = skill_use_log_path("skill-uses-test")

    events = [
        _make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
            use_id="alpha-use",
        ),
        _make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
            use_id="beta-use",
        ),
    ]
    _write_jsonl(log_path, events)
    parsed_events = list(events)
    parse_count = 0

    def fake_read_skill_use_events(
        *,
        project: str | None = None,
        log_path: Path | None = None,
    ) -> tuple[SkillUseEvent, ...]:
        nonlocal parse_count
        assert project == "skill-uses-test"
        assert log_path is None
        parse_count += 1
        return tuple(parsed_events)

    monkeypatch.setattr(
        skill_uses_module,
        "read_skill_use_events",
        fake_read_skill_use_events,
    )

    agent_a = _make_agent(
        artifacts_dir=artifacts_a,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    agent_b = _make_agent(
        artifacts_dir=artifacts_b,
        agent_name="beta",
        workspace_dir=fake_project,
        raw_suffix="20260614-100001",
    )

    assert [
        item.event.skill_name for item in load_skill_uses_for_agent_context(agent_a)
    ] == ["sase_plan"]
    assert [
        item.event.skill_name for item in load_skill_uses_for_agent_context(agent_b)
    ] == ["sase_questions"]
    assert parse_count == 1

    parsed_events.append(
        _make_event(
            skill_name="sase_memory_read",
            timestamp="2026-06-14T10:10:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
            use_id="alpha-new-use",
        )
    )
    _write_jsonl(log_path, parsed_events)
    future_mtime_ns = log_path.stat().st_mtime_ns + 10_000_000_000
    import os as _os

    _os.utime(log_path, ns=(future_mtime_ns, future_mtime_ns))
    for cache in (
        skill_uses_module._skill_uses_cache,
        skill_uses_module._skill_uses_snapshot_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    assert [
        item.event.skill_name for item in load_skill_uses_for_agent_context(agent_a)
    ] == ["sase_memory_read", "sase_plan"]
    assert [
        item.event.skill_name for item in load_skill_uses_for_agent_context(agent_b)
    ] == ["sase_questions"]
    assert parse_count == 2


def test_context_single_agent_has_no_labels(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        _make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    _write_jsonl(skill_use_log_path("skill-uses-test"), events)

    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = load_skill_uses_for_agent_context(agent)

    assert [item.event.skill_name for item in result] == ["sase_plan"]
    assert [item.agent_label for item in result] == [None]


def test_context_aggregates_family_with_role_labels(
    fake_project: Path, tmp_path: Path
) -> None:
    plan_dir = tmp_path / "artifacts" / "plan"
    coder_dir = tmp_path / "artifacts" / "coder"
    q_dir = tmp_path / "artifacts" / "q"
    for directory in (plan_dir, coder_dir, q_dir):
        directory.mkdir(parents=True)

    events = [
        _make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha--plan",
            artifacts_dir=str(plan_dir),
            use_id="plan-use",
        ),
        _make_event(
            skill_name="sase_git_commit",
            timestamp="2026-06-14T10:05:00+00:00",
            agent_name="alpha--code",
            artifacts_dir=str(coder_dir),
            use_id="coder-use",
        ),
        _make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:02:00+00:00",
            agent_name="alpha--q",
            artifacts_dir=str(q_dir),
            use_id="q-use",
        ),
    ]
    _write_jsonl(skill_use_log_path("skill-uses-test"), events)

    root = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = _make_agent(
        artifacts_dir=coder_dir,
        agent_name="alpha--code",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    question = _make_agent(
        artifacts_dir=q_dir,
        agent_name="alpha--q",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-q",
        role_suffix=HISTORICAL_Q_SUFFIX,
    )
    root.followup_agents = [coder, question]

    result = load_skill_uses_for_agent_context(root)

    assert [(item.event.skill_name, item.agent_label) for item in result] == [
        ("sase_git_commit", "coder"),
        ("sase_questions", "q"),
        ("sase_plan", "plan"),
    ]


def test_context_labels_phase_feedback_member_by_suffix(
    fake_project: Path, tmp_path: Path
) -> None:
    plan_dir = tmp_path / "artifacts" / "plan"
    feedback_dir = tmp_path / "artifacts" / "feedback"
    plan_dir.mkdir(parents=True)
    feedback_dir.mkdir(parents=True)

    # The inherited root agent name is still in the environment, so the event
    # records "alpha"; attribution is by the feedback follow-up artifacts dir.
    events = [
        _make_event(
            skill_name="sase_memory_read",
            timestamp="2026-06-14T10:05:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(feedback_dir),
            use_id="feedback-use",
        )
    ]
    _write_jsonl(skill_use_log_path("skill-uses-test"), events)

    root = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    feedback = _make_agent(
        artifacts_dir=feedback_dir,
        agent_name="alpha--plan-0",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan-0",
        role_suffix=f"{PLAN_CHAIN_PLAN_SUFFIX}-0",
    )
    feedback.agent_family_role = "feedback"
    root.followup_agents = [feedback]

    result = load_skill_uses_for_agent_context(root)

    # The phase-feedback member renders by its concrete suffix name, not fb2.
    assert [(item.event.skill_name, item.agent_label) for item in result] == [
        ("sase_memory_read", "plan-0"),
    ]


def test_context_artifacts_dir_mismatch_does_not_fall_back_to_name(
    fake_project: Path, tmp_path: Path
) -> None:
    plan_dir = tmp_path / "artifacts" / "plan"
    coder_dir = tmp_path / "artifacts" / "coder"
    other_dir = tmp_path / "artifacts" / "other"
    for directory in (plan_dir, coder_dir, other_dir):
        directory.mkdir(parents=True)

    events = [
        _make_event(
            skill_name="sase_git_commit",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha--code",
            artifacts_dir=str(other_dir),
            use_id="mismatch-use",
        )
    ]
    _write_jsonl(skill_use_log_path("skill-uses-test"), events)

    root = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = _make_agent(
        artifacts_dir=coder_dir,
        agent_name="alpha--code",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    root.followup_agents = [coder]

    assert load_skill_uses_for_agent_context(root) == ()


def test_context_dedupes_synthetic_planner_sharing_root_dir(
    fake_project: Path, tmp_path: Path
) -> None:
    plan_dir = tmp_path / "artifacts" / "plan"
    coder_dir = tmp_path / "artifacts" / "coder"
    plan_dir.mkdir(parents=True)
    coder_dir.mkdir(parents=True)

    events = [
        _make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha--plan",
            artifacts_dir=str(plan_dir),
            use_id="plan-use",
        )
    ]
    _write_jsonl(skill_use_log_path("skill-uses-test"), events)

    root = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    synthetic = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan-2",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = _make_agent(
        artifacts_dir=coder_dir,
        agent_name="alpha--code",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    root.followup_agents = [synthetic, coder]

    result = load_skill_uses_for_agent_context(root)

    assert [(item.event.skill_name, item.agent_label) for item in result] == [
        ("sase_plan", "plan")
    ]


def test_context_caps_to_limit_newest_first(fake_project: Path, tmp_path: Path) -> None:
    plan_dir = tmp_path / "artifacts" / "plan"
    coder_dir = tmp_path / "artifacts" / "coder"
    plan_dir.mkdir(parents=True)
    coder_dir.mkdir(parents=True)

    events = []
    for index in range(6):
        directory = plan_dir if index % 2 == 0 else coder_dir
        name = "alpha--plan" if index % 2 == 0 else "alpha--code"
        events.append(
            _make_event(
                skill_name=f"skill_{index}",
                timestamp=f"2026-06-14T10:{index:02d}:00+00:00",
                agent_name=name,
                artifacts_dir=str(directory),
                use_id=f"id-{index}",
            )
        )
    _write_jsonl(skill_use_log_path("skill-uses-test"), events)

    root = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = _make_agent(
        artifacts_dir=coder_dir,
        agent_name="alpha--code",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    root.followup_agents = [coder]

    result = load_skill_uses_for_agent_context(root, limit=2)

    assert [item.event.skill_name for item in result] == ["skill_5", "skill_4"]
    assert [item.agent_label for item in result] == ["coder", "plan"]
