"""Integration tests for the prompt-panel header AGENT CONTEXT section."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from rich.text import Text

from sase.ace.tui import memory_reads as memory_reads_module
from sase.ace.tui import skill_uses as skill_uses_module
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel import _agent_memory_reads
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_detail_header_summary,
    build_header_text,
)
from sase.memory.read_log import (
    READ_LOG_SCHEMA_VERSION,
    MemoryReadEvent,
    memory_read_log_path,
)
from sase.skills.use_log import (
    SKILL_USE_LOG_SCHEMA_VERSION,
    SkillUseEvent,
    skill_use_log_path,
)

_MAJOR_SECTION_RULE = "\u2500" * 50


@pytest.fixture(autouse=True)
def _setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    memory_reads_module._memory_reads_cache.clear()
    skill_uses_module._skill_uses_cache.clear()
    sase_home = tmp_path / "sase-home"
    sase_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: sase_home))
    monkeypatch.setattr(
        memory_reads_module,
        "project_memory_name",
        lambda _root: "header-test",
    )
    monkeypatch.setattr(
        skill_uses_module,
        "project_memory_name",
        lambda _root: "header-test",
    )
    monkeypatch.setattr(
        _agent_memory_reads,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )
    return sase_home


def _assert_dim_divider_before(header: Text, section: str) -> None:
    plain = header.plain
    section_start = plain.index(section)
    rule_start = plain.rfind(_MAJOR_SECTION_RULE, 0, section_start)
    assert rule_start != -1
    assert plain[rule_start - 1 : section_start] == (f"\n{_MAJOR_SECTION_RULE}\n\n")
    rule_end = rule_start + len(_MAJOR_SECTION_RULE)
    assert any(
        span.start <= rule_start and span.end >= rule_end and str(span.style) == "dim"
        for span in header.spans
    )


def _make_agent(*, artifacts_dir: Path, workspace_dir: Path) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="header-test",
        project_file="/tmp/header-test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 24, 14, 22, 0),
        raw_suffix="20260524-142200",
        agent_name="alpha",
        workspace_dir=str(workspace_dir),
        artifacts_dir=str(artifacts_dir),
    )


def _write_events(events: list[MemoryReadEvent]) -> None:
    path = memory_read_log_path("header-test")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for event in events:
            json.dump(asdict(event), out, sort_keys=True)
            out.write("\n")


def _write_skill_events(events: list[SkillUseEvent]) -> None:
    path = skill_use_log_path("header-test")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for event in events:
            json.dump(asdict(event), out, sort_keys=True)
            out.write("\n")


def _event(
    *,
    canonical_path: str,
    timestamp: str,
    artifacts_dir: str,
    reason: str = "audit reason",
) -> MemoryReadEvent:
    return MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id=canonical_path + timestamp,
        timestamp=timestamp,
        project="header-test",
        cwd="/tmp/header-test",
        canonical_path=canonical_path,
        resolved_path=f"/tmp/header-test/memory/{canonical_path}",
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=artifacts_dir,
        reason=reason,
        byte_count=64,
        frontmatter_stripped=False,
    )


def _skill_event(
    *,
    skill_name: str,
    timestamp: str,
    artifacts_dir: str,
    reason: str = "skill reason",
) -> SkillUseEvent:
    return SkillUseEvent(
        schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
        id=skill_name + timestamp,
        timestamp=timestamp,
        project="header-test",
        cwd="/tmp/header-test",
        skill_name=skill_name,
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=artifacts_dir,
        reason=reason,
        runtime="codex",
    )


def test_header_renders_workflow_variables_before_agent_context(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_events(
        [
            _event(
                canonical_path="long/generated_skills.md",
                timestamp="2026-05-24T14:22:08+00:00",
                artifacts_dir=str(artifacts_dir),
                reason="needed commit hook contract for runtime parity refactor",
            ),
        ]
    )

    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)
    agent.step_output = {"meta_foo": "bar"}

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))
    plain = header.plain

    assert "AGENT CONTEXT\n" in plain
    assert "▸ MEMORY\n" in plain
    assert "▸ SKILLS\n" in plain
    assert "WORKFLOW VARIABLES\n" in plain
    assert "long/generated_skills.md" in plain
    assert "↳ needed commit hook contract for runtime parity refactor" in plain
    assert "none recorded" in plain
    _assert_dim_divider_before(header, "AGENT CONTEXT\n")
    _assert_dim_divider_before(header, "WORKFLOW VARIABLES\n")
    assert plain.index("WORKFLOW VARIABLES\n") < plain.index("AGENT CONTEXT\n")


def test_header_renders_skill_uses_without_memory_reads(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_skill_events(
        [
            _skill_event(
                skill_name="sase_plan",
                timestamp="2026-05-24T14:23:08+00:00",
                artifacts_dir=str(artifacts_dir),
                reason="needed an implementation plan",
            ),
        ]
    )

    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))
    plain = header.plain

    assert "AGENT CONTEXT\n" in plain
    assert "▸ MEMORY\n" in plain
    assert "▸ SKILLS\n" in plain
    assert "sase_plan" in plain
    assert "↳ needed an implementation plan" in plain
    assert "none recorded" in plain


def test_cheap_header_omits_agent_context(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    _write_events(
        [
            _event(
                canonical_path="long/skill.md",
                timestamp="2026-05-24T14:22:08+00:00",
                artifacts_dir=str(artifacts_dir),
            )
        ]
    )

    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)
    header, _ = build_header_text(agent, cheap=True)

    assert "AGENT CONTEXT" not in header.plain
    assert "▸ MEMORY" not in header.plain
    assert "▸ SKILLS" not in header.plain


def test_no_events_omits_agent_context_section(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    agent = _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)

    header, _ = build_header_text(agent, summary=build_detail_header_summary(agent))

    assert "AGENT CONTEXT" not in header.plain
