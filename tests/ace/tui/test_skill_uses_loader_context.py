"""Agent-session context tests for the skill-uses loader."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.skill_uses import load_skill_uses_for_agent_context
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
)
from sase.skills.use_log import skill_use_log_path

from ._skill_uses_loader_helpers import (
    clear_skill_uses_cache_fixture,
    fake_project_fixture,
    make_agent,
    make_event,
    write_jsonl,
)

HISTORICAL_Q_SUFFIX = "--q"


def test_context_single_agent_has_no_labels(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    write_jsonl(skill_use_log_path("skill-uses-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = load_skill_uses_for_agent_context(agent)

    assert [item.event.skill_name for item in result] == ["sase_plan"]
    assert [item.agent_label for item in result] == [None]


def test_context_aggregates_agent_session_with_role_labels(
    fake_project: Path, tmp_path: Path
) -> None:
    plan_dir = tmp_path / "artifacts" / "plan"
    coder_dir = tmp_path / "artifacts" / "coder"
    q_dir = tmp_path / "artifacts" / "q"
    for directory in (plan_dir, coder_dir, q_dir):
        directory.mkdir(parents=True)

    events = [
        make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha--plan",
            artifacts_dir=str(plan_dir),
            use_id="plan-use",
        ),
        make_event(
            skill_name="sase_git_commit",
            timestamp="2026-06-14T10:05:00+00:00",
            agent_name="alpha--code",
            artifacts_dir=str(coder_dir),
            use_id="coder-use",
        ),
        make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:02:00+00:00",
            agent_name="alpha--q",
            artifacts_dir=str(q_dir),
            use_id="q-use",
        ),
    ]
    write_jsonl(skill_use_log_path("skill-uses-test"), events)

    root = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = make_agent(
        artifacts_dir=coder_dir,
        agent_name="alpha--code",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    question = make_agent(
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
        make_event(
            skill_name="sase_memory_read",
            timestamp="2026-06-14T10:05:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(feedback_dir),
            use_id="feedback-use",
        )
    ]
    write_jsonl(skill_use_log_path("skill-uses-test"), events)

    root = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    feedback = make_agent(
        artifacts_dir=feedback_dir,
        agent_name="alpha--plan-0",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan-0",
        role_suffix=f"{PLAN_CHAIN_PLAN_SUFFIX}-0",
    )
    feedback.agent_session_role = "feedback"
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
        make_event(
            skill_name="sase_git_commit",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha--code",
            artifacts_dir=str(other_dir),
            use_id="mismatch-use",
        )
    ]
    write_jsonl(skill_use_log_path("skill-uses-test"), events)

    root = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = make_agent(
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
        make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha--plan",
            artifacts_dir=str(plan_dir),
            use_id="plan-use",
        )
    ]
    write_jsonl(skill_use_log_path("skill-uses-test"), events)

    root = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    synthetic = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan-2",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = make_agent(
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
            make_event(
                skill_name=f"skill_{index}",
                timestamp=f"2026-06-14T10:{index:02d}:00+00:00",
                agent_name=name,
                artifacts_dir=str(directory),
                use_id=f"id-{index}",
            )
        )
    write_jsonl(skill_use_log_path("skill-uses-test"), events)

    root = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260614-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = make_agent(
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
