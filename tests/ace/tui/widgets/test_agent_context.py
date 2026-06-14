"""Tests for the AGENT CONTEXT prompt-panel section renderer."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel import _agent_memory_reads
from sase.ace.tui.widgets.prompt_panel._agent_context import (
    append_agent_context_section,
)
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from sase.skills.use_log import SKILL_USE_LOG_SCHEMA_VERSION, SkillUseEvent


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_memory_reads,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def _memory_event() -> MemoryReadEvent:
    return MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id="read-a",
        timestamp="2026-06-14T14:22:08+00:00",
        project="test",
        cwd="/tmp/test",
        canonical_path="long/generated_skills.md",
        resolved_path="/tmp/test/memory/long/generated_skills.md",
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir="/tmp/test/artifacts",
        reason="needed generated skill rules",
        byte_count=64,
        frontmatter_stripped=False,
    )


def _skill_event() -> SkillUseEvent:
    return SkillUseEvent(
        schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
        id="skill-a",
        timestamp="2026-06-14T14:23:08+00:00",
        project="test",
        cwd="/tmp/test",
        skill_name="sase_plan",
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir="/tmp/test/artifacts",
        reason="needed an implementation plan",
        runtime="codex",
    )


def test_empty_context_appends_nothing() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(), skill_uses=())
    assert text.plain == ""


def test_memory_only_context_shows_empty_skills_placeholder() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(_memory_event(),), skill_uses=())

    plain = text.plain
    assert "AGENT CONTEXT\n" in plain
    assert "▸ MEMORY\n" in plain
    assert "long/generated_skills.md" in plain
    assert "▸ SKILLS\n" in plain
    assert "none recorded" in plain


def test_skills_only_context_shows_empty_memory_placeholder() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(), skill_uses=(_skill_event(),))

    plain = text.plain
    assert "AGENT CONTEXT\n" in plain
    assert "▸ MEMORY\n" in plain
    assert "▸ SKILLS\n" in plain
    assert "sase_plan" in plain
    assert "none recorded" in plain


def test_memory_and_skills_render_in_parent_context_order() -> None:
    text = Text()
    append_agent_context_section(
        text,
        memory_reads=(_memory_event(),),
        skill_uses=(_skill_event(),),
    )

    plain = text.plain
    assert plain.index("AGENT CONTEXT\n") < plain.index("▸ MEMORY\n")
    assert plain.index("▸ MEMORY\n") < plain.index("▸ SKILLS\n")
    assert "needed generated skill rules" in plain
    assert "needed an implementation plan" in plain
