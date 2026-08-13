"""Tests for the per-agent memory-reads loader."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui import memory_reads as memory_reads_module
from sase.ace.tui.memory_reads import (
    _load_memory_reads_for_agent,
    load_memory_reads_for_agent_context,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.memory.read_log import (
    READ_LOG_SCHEMA_VERSION,
    MemoryReadEvent,
    memory_read_log_path,
)
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
)


def _make_agent(
    *,
    artifacts_dir: Path | None,
    agent_name: str | None = None,
    workspace_dir: Path | None = None,
    raw_suffix: str = "20260524-100000",
    role_suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="memory-reads-test",
        project_file="/tmp/memory-reads-test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 24, 10, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        workspace_dir=str(workspace_dir) if workspace_dir else None,
        artifacts_dir=str(artifacts_dir) if artifacts_dir else None,
        role_suffix=role_suffix,
    )


def _make_event(
    *,
    canonical_path: str,
    timestamp: str,
    agent_name: str,
    artifacts_dir: str | None,
    reason: str = "context",
    frontmatter_stripped: bool = False,
    project: str = "memory-reads-test",
    read_id: str | None = None,
) -> MemoryReadEvent:
    return MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id=read_id or canonical_path.replace("/", "_") + timestamp,
        timestamp=timestamp,
        project=project,
        cwd="/tmp/memory-reads-test",
        canonical_path=canonical_path,
        resolved_path=f"/tmp/memory-reads-test/memory/{canonical_path}",
        agent_name=agent_name,
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=artifacts_dir,
        reason=reason,
        byte_count=128,
        frontmatter_stripped=frontmatter_stripped,
    )


def _write_jsonl(path: Path, events: list[MemoryReadEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for event in events:
            json.dump(asdict(event), out, sort_keys=True)
            out.write("\n")


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    memory_reads_module._memory_reads_cache.clear()
    memory_reads_module._memory_reads_context_cache.clear()
    memory_reads_module._memory_reads_snapshot_cache.clear()


@pytest.fixture
def fake_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(
        memory_reads_module,
        "project_memory_name",
        lambda _root: "memory-reads-test",
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
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
        ),
        _make_event(
            canonical_path="other.md",
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
        ),
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = _make_agent(
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
        _make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=None,
        ),
        _make_event(
            canonical_path="other.md",
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=None,
        ),
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = _make_agent(
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
        _make_event(
            canonical_path="a.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        _make_event(
            canonical_path="b.md",
            timestamp="2026-05-24T10:05:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
        _make_event(
            canonical_path="c.md",
            timestamp="2026-05-24T10:02:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        ),
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = _make_agent(
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
        _make_event(
            canonical_path=f"file_{index}.md",
            timestamp=f"2026-05-24T10:{index:02d}:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
            read_id=f"id-{index}",
        )
        for index in range(10)
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = _make_agent(
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
    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )

    assert _load_memory_reads_for_agent(agent) == ()


def test_cache_invalidates_on_mtime_change(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    log_path = memory_read_log_path("memory-reads-test")
    initial = [
        _make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
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
    first = _load_memory_reads_for_agent(agent)
    assert len(first) == 1

    # Force a future mtime so the cache invalidates even though the throttle
    # window may not have elapsed.
    later = list(initial) + [
        _make_event(
            canonical_path="other.md",
            timestamp="2026-05-24T10:10:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    _write_jsonl(log_path, later)
    future_mtime_ns = log_path.stat().st_mtime_ns + 10_000_000_000
    import os as _os

    _os.utime(log_path, ns=(future_mtime_ns, future_mtime_ns))

    # Bypass the throttle window: rewind cached monotonic timestamp.
    for cache in (
        memory_reads_module._memory_reads_cache,
        memory_reads_module._memory_reads_snapshot_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    second = _load_memory_reads_for_agent(agent)
    assert [event.canonical_path for event in second] == [
        "other.md",
        "skill.md",
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
    log_path = memory_read_log_path("memory-reads-test")

    events = [
        _make_event(
            canonical_path="alpha.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
            read_id="alpha-read",
        ),
        _make_event(
            canonical_path="beta.md",
            timestamp="2026-05-24T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
            read_id="beta-read",
        ),
    ]
    _write_jsonl(log_path, events)
    parsed_events = list(events)
    parse_count = 0

    def fake_read_memory_read_events(
        *,
        project: str | None = None,
        log_path: Path | None = None,
    ) -> tuple[MemoryReadEvent, ...]:
        nonlocal parse_count
        assert project == "memory-reads-test"
        assert log_path is None
        parse_count += 1
        return tuple(parsed_events)

    monkeypatch.setattr(
        memory_reads_module,
        "read_memory_read_events",
        fake_read_memory_read_events,
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
    assert parse_count == 1

    parsed_events.append(
        _make_event(
            canonical_path="alpha-new.md",
            timestamp="2026-05-24T10:10:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
            read_id="alpha-new-read",
        )
    )
    _write_jsonl(log_path, parsed_events)
    future_mtime_ns = log_path.stat().st_mtime_ns + 10_000_000_000
    import os as _os

    _os.utime(log_path, ns=(future_mtime_ns, future_mtime_ns))
    for cache in (
        memory_reads_module._memory_reads_cache,
        memory_reads_module._memory_reads_snapshot_cache,
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
    assert parse_count == 2


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
        _make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(other_artifacts),
        )
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = _make_agent(
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

    event = _make_event(
        canonical_path="skill.md",
        timestamp="2026-05-24T10:00:00+00:00",
        agent_name="alpha",
        artifacts_dir=str(real_dir) + "/",
    )
    _write_jsonl(memory_read_log_path("memory-reads-test"), [event])

    agent = _make_agent(
        artifacts_dir=symlink_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_memory_reads_for_agent(agent)

    assert [event.canonical_path for event in result] == ["skill.md"]


def test_context_single_agent_has_no_labels(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        _make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    agent = _make_agent(
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
        _make_event(
            canonical_path="cli_rules.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha--plan",
            artifacts_dir=str(plan_dir),
            read_id="plan-read",
        ),
        _make_event(
            canonical_path="tui_perf.md",
            timestamp="2026-05-24T10:05:00+00:00",
            agent_name="alpha--code",
            artifacts_dir=str(coder_dir),
            read_id="coder-read",
        ),
        _make_event(
            canonical_path="generated_skills.md",
            timestamp="2026-05-24T10:02:00+00:00",
            agent_name="alpha--q",
            artifacts_dir=str(q_dir),
            read_id="q-read",
        ),
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    root = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = _make_agent(
        artifacts_dir=coder_dir,
        agent_name="alpha--code",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    question = _make_agent(
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
        _make_event(
            canonical_path="tui_perf.md",
            timestamp="2026-05-24T10:05:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(feedback_dir),
            read_id="feedback-read",
        )
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    root = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    feedback = _make_agent(
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
        _make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha--code",
            artifacts_dir=str(other_dir),
            read_id="mismatch-read",
        )
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    root = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = _make_agent(
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
        _make_event(
            canonical_path="skill.md",
            timestamp="2026-05-24T10:00:00+00:00",
            agent_name="alpha--plan",
            artifacts_dir=str(plan_dir),
            read_id="plan-read",
        )
    ]
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    root = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    # Synthetic planner row sharing the root artifacts dir (distinct identity).
    synthetic = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan-2",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = _make_agent(
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
            _make_event(
                canonical_path=f"file_{index}.md",
                timestamp=f"2026-05-24T10:{index:02d}:00+00:00",
                agent_name=name,
                artifacts_dir=str(directory),
                read_id=f"id-{index}",
            )
        )
    _write_jsonl(memory_read_log_path("memory-reads-test"), events)

    root = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=fake_project,
        raw_suffix="20260524-100000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = _make_agent(
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
