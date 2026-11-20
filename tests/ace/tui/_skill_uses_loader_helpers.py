"""Shared builders and fixtures for the skill-uses loader tests."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui import skill_uses as skill_uses_module
from sase.ace.tui.models.agent import Agent, AgentType
from sase.skills.use_log import (
    SKILL_USE_LOG_SCHEMA_VERSION,
    SkillUseEvent,
)


def make_agent(
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


def make_event(
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


def write_jsonl(path: Path, events: list[SkillUseEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for event in events:
            json.dump(asdict(event), out, sort_keys=True)
            out.write("\n")


@pytest.fixture(autouse=True)
def clear_skill_uses_cache_fixture() -> None:
    skill_uses_module._skill_uses_cache.clear()
    skill_uses_module._skill_uses_context_cache.clear()


@pytest.fixture(name="fake_project")
def fake_project_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
