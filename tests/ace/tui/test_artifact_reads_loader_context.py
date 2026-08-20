"""Agent-family context tests for the artifact-reads loader."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.artifact_reads import load_artifact_reads_for_agent_context
from sase.artifact_read_log import artifact_read_log_path
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
)

from ._artifact_reads_loader_helpers import (
    clear_artifact_reads_cache_fixture,
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
            ref="plan:skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    write_jsonl(artifact_read_log_path("artifact-reads-test"), events)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = load_artifact_reads_for_agent_context(agent)

    assert [item.event.ref for item in result] == ["plan:skill.md"]
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
            ref="plan:cli_rules.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha--plan",
            artifacts_dir=str(plan_dir),
            read_id="plan-read",
        ),
        make_event(
            ref="plan:tui_perf.md",
            timestamp="2026-05-24T10:05:00+00:00",
            agent_name="alpha--code",
            artifacts_dir=str(coder_dir),
            read_id="coder-read",
        ),
        make_event(
            ref="research:generated.md",
            timestamp="2026-05-24T10:02:00+00:00",
            agent_name="alpha--q",
            artifacts_dir=str(q_dir),
            read_id="q-read",
        ),
    ]
    write_jsonl(artifact_read_log_path("artifact-reads-test"), events)

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

    result = load_artifact_reads_for_agent_context(root)

    assert [(item.event.ref, item.agent_label) for item in result] == [
        ("plan:tui_perf.md", "coder"),
        ("research:generated.md", "q"),
        ("plan:cli_rules.md", "plan"),
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
            ref="plan:skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha--code",
            artifacts_dir=str(other_dir),
            read_id="mismatch-read",
        )
    ]
    write_jsonl(artifact_read_log_path("artifact-reads-test"), events)

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

    assert load_artifact_reads_for_agent_context(root) == ()


def test_context_dedupes_by_event_id(fake_project: Path, tmp_path: Path) -> None:
    plan_dir = tmp_path / "artifacts" / "plan"
    coder_dir = tmp_path / "artifacts" / "coder"
    plan_dir.mkdir(parents=True)
    coder_dir.mkdir(parents=True)

    events = [
        make_event(
            ref="plan:skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha--plan",
            artifacts_dir=str(plan_dir),
            read_id="shared-read",
        ),
        make_event(
            ref="plan:skill.md",
            timestamp="2026-05-24T10:05:00+00:00",
            agent_name="alpha--code",
            artifacts_dir=str(coder_dir),
            read_id="shared-read",
        ),
    ]
    write_jsonl(artifact_read_log_path("artifact-reads-test"), events)

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

    result = load_artifact_reads_for_agent_context(root)

    assert [(item.event.ref, item.agent_label) for item in result] == [
        ("plan:skill.md", "plan")
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
                ref=f"plan:file_{index}.md",
                timestamp=f"2026-05-24T10:{index:02d}:00+00:00",
                agent_name=name,
                artifacts_dir=str(directory),
                read_id=f"id-{index}",
            )
        )
    write_jsonl(artifact_read_log_path("artifact-reads-test"), events)

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

    result = load_artifact_reads_for_agent_context(root, limit=2)

    assert [item.event.ref for item in result] == [
        "plan:file_5.md",
        "plan:file_4.md",
    ]
    assert [item.agent_label for item in result] == ["coder", "plan"]
