"""Agent-family context tests for the memory-reads loader."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.memory_reads import load_memory_reads_for_agent_context
from sase.memory.read_log import memory_read_log_path
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
)

from ._memory_reads_loader_helpers import (
    clear_memory_reads_cache_fixture,
    fake_project_fixture,
    make_agent,
    make_event,
    write_jsonl,
)


def test_context_single_agent_has_no_labels(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = load_memory_reads_for_agent_context(agent)

    assert [item.event.canonical_path for item in result] == ["skill.md"]
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
        make_event(
            canonical_path="cli_rules.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha--plan",
            artifacts_dir=str(plan_dir),
            read_id="plan-read",
        ),
        make_event(
            canonical_path="tui_perf.md",
            timestamp="2026-05-24T10:05:00+00:00",
            agent_name="alpha--code",
            artifacts_dir=str(coder_dir),
            read_id="coder-read",
        ),
        make_event(
            canonical_path="generated_skills.md",
            timestamp="2026-05-24T10:02:00+00:00",
            agent_name="alpha--q",
            artifacts_dir=str(q_dir),
            read_id="q-read",
        ),
    ]
    write_jsonl(memory_read_log_path("memory-reads-test"), events)

    root = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = make_agent(
        artifacts_dir=coder_dir,
        agent_name="alpha--code",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    question = make_agent(
        artifacts_dir=q_dir,
        agent_name="alpha--q",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-q",
        role_suffix=PLAN_CHAIN_QUESTION_SUFFIX,
    )
    root.followup_agents = [coder, question]

    result = load_memory_reads_for_agent_context(root)

    # Newest first across the whole family, each labeled by its producer.
    assert [(item.event.canonical_path, item.agent_label) for item in result] == [
        ("tui_perf.md", "coder"),
        ("generated_skills.md", "q"),
        ("cli_rules.md", "plan"),
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
            canonical_path="tui_perf.md",
            timestamp="2026-05-24T10:05:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(feedback_dir),
            read_id="feedback-read",
        )
    ]
    write_jsonl(memory_read_log_path("memory-reads-test"), events)

    root = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    feedback = make_agent(
        artifacts_dir=feedback_dir,
        agent_name="alpha--plan-0",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan-0",
        role_suffix=f"{PLAN_CHAIN_PLAN_SUFFIX}-0",
    )
    feedback.agent_family_role = "feedback"
    root.followup_agents = [feedback]

    result = load_memory_reads_for_agent_context(root)

    # The phase-feedback member renders by its concrete suffix name, not fb2.
    assert [(item.event.canonical_path, item.agent_label) for item in result] == [
        ("tui_perf.md", "plan-0"),
    ]


def test_context_artifacts_dir_mismatch_does_not_fall_back_to_name(
    fake_project: Path, tmp_path: Path
) -> None:
    plan_dir = tmp_path / "artifacts" / "plan"
    coder_dir = tmp_path / "artifacts" / "coder"
    other_dir = tmp_path / "artifacts" / "other"
    for directory in (plan_dir, coder_dir, other_dir):
        directory.mkdir(parents=True)

    # Event carries a coder agent_name but an unrelated artifacts_dir: must NOT
    # be attributed to the coder via name fallback because it has a dir.
    events = [
        make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha--code",
            artifacts_dir=str(other_dir),
            read_id="mismatch-read",
        )
    ]
    write_jsonl(memory_read_log_path("memory-reads-test"), events)

    root = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = make_agent(
        artifacts_dir=coder_dir,
        agent_name="alpha--code",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    root.followup_agents = [coder]

    assert load_memory_reads_for_agent_context(root) == ()


def test_context_dedupes_synthetic_planner_sharing_root_dir(
    fake_project: Path, tmp_path: Path
) -> None:
    plan_dir = tmp_path / "artifacts" / "plan"
    coder_dir = tmp_path / "artifacts" / "coder"
    plan_dir.mkdir(parents=True)
    coder_dir.mkdir(parents=True)

    events = [
        make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha--plan",
            artifacts_dir=str(plan_dir),
            read_id="plan-read",
        )
    ]
    write_jsonl(memory_read_log_path("memory-reads-test"), events)

    root = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    # Synthetic planner row sharing the root artifacts dir (distinct identity).
    synthetic = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan-2",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = make_agent(
        artifacts_dir=coder_dir,
        agent_name="alpha--code",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    root.followup_agents = [synthetic, coder]

    result = load_memory_reads_for_agent_context(root)

    assert [(item.event.canonical_path, item.agent_label) for item in result] == [
        ("skill.md", "plan")
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
                canonical_path=f"file_{index}.md",
                timestamp=f"2026-05-24T10:{index:02d}:00+00:00",
                agent_name=name,
                artifacts_dir=str(directory),
                read_id=f"id-{index}",
            )
        )
    write_jsonl(memory_read_log_path("memory-reads-test"), events)

    root = make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = make_agent(
        artifacts_dir=coder_dir,
        agent_name="alpha--code",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    root.followup_agents = [coder]

    result = load_memory_reads_for_agent_context(root, limit=2)

    assert [item.event.canonical_path for item in result] == [
        "file_5.md",
        "file_4.md",
    ]
    assert [item.agent_label for item in result] == ["coder", "plan"]
