from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from sase.agent.identity import AgentIdentity, discover_agent_runtime
from sase.skills.use_log import (
    SKILL_USE_LOG_SCHEMA_VERSION,
    SkillUseError,
    append_skill_use_event,
    build_skill_use_event,
    filter_skill_use_events,
    normalize_skill_name,
    normalize_skill_reason,
    read_skill_use_events,
    skill_use_log_path,
    summarize_skill_uses_by_agent,
    summarize_skill_uses_by_skill,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_skill_use_event_tracks_agent_and_runtime(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    _write(
        artifacts_dir / "agent_meta.json",
        json.dumps({"name": "agent-a", "llm_provider": "codex"}),
    )

    event = build_skill_use_event(
        " sase_plan ",
        reason=" Need a plan ",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", str(artifacts_dir)),
        project="proj",
        cwd=tmp_path,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=UTC),
        use_id="skill-a",
    )

    assert event.schema_version == SKILL_USE_LOG_SCHEMA_VERSION
    assert event.id == "skill-a"
    assert event.timestamp == "2026-06-14T12:00:00+00:00"
    assert event.project == "proj"
    assert event.skill_name == "sase_plan"
    assert event.agent_name == "agent-a"
    assert event.artifacts_dir == str(artifacts_dir)
    assert event.reason == "Need a plan"
    assert event.runtime == "codex"


def test_discover_agent_runtime_falls_back_to_model_prefix(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    _write(artifacts_dir / "agent_meta.json", json.dumps({"model": "gemini/pro"}))

    assert (
        discover_agent_runtime({"SASE_ARTIFACTS_DIR": str(artifacts_dir)}) == "gemini"
    )


def test_normalizers_reject_empty_values() -> None:
    with pytest.raises(SkillUseError, match="skill name"):
        normalize_skill_name("  ")
    with pytest.raises(SkillUseError, match="reason"):
        normalize_skill_reason("  ")


def test_append_and_read_skill_use_events_tolerates_malformed_jsonl(
    tmp_path: Path,
) -> None:
    event = build_skill_use_event(
        "sase_plan",
        reason="Need plan",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", "/tmp/artifacts"),
        project="proj",
        cwd=tmp_path,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=UTC),
        use_id="skill-a",
        runtime="codex",
    )
    log_path = tmp_path / "state" / "skill_uses.jsonl"

    append_skill_use_event(event, log_path=log_path)
    with log_path.open("a", encoding="utf-8") as f:
        f.write("not json\n")
        f.write(json.dumps({"schema_version": 1, "id": "missing-fields"}) + "\n")

    assert read_skill_use_events(log_path=log_path) == (event,)


def test_skill_use_log_path_uses_project_state_under_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert skill_use_log_path("proj") == (
        tmp_path / ".sase" / "projects" / "proj" / "skill_uses.jsonl"
    )


def test_skill_use_aggregation_groups_by_skill_and_agent(tmp_path: Path) -> None:
    base = build_skill_use_event(
        "sase_plan",
        reason="First",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", None),
        project="proj",
        cwd=tmp_path,
        now=datetime(2026, 6, 14, 12, 0, tzinfo=UTC),
        use_id="skill-a",
        runtime="codex",
    )
    second = replace(
        base,
        id="skill-b",
        timestamp="2026-06-14T12:01:00+00:00",
        agent_name="agent-b",
        reason="Second",
    )
    other = replace(
        base,
        id="skill-c",
        timestamp="2026-06-14T12:02:00+00:00",
        skill_name="sase_questions",
        agent_name="agent-a",
        reason="Third",
    )

    skill_summaries = summarize_skill_uses_by_skill([base, second, other])
    agent_summaries = summarize_skill_uses_by_agent([base, second, other])

    assert skill_summaries[0].skill_name == "sase_plan"
    assert skill_summaries[0].use_count == 2
    assert skill_summaries[0].distinct_agent_count == 2
    assert skill_summaries[0].last_agent == "agent-b"
    assert skill_summaries[0].last_reason == "Second"
    assert skill_summaries[1].skill_name == "sase_questions"
    assert agent_summaries[0].agent_name == "agent-a"
    assert agent_summaries[0].use_count == 2
    assert agent_summaries[0].distinct_skill_count == 2
    assert agent_summaries[1].agent_name == "agent-b"
    assert filter_skill_use_events(
        [base, second, other],
        skill_name="sase_plan",
        agent_name="agent-b",
    ) == (second,)
