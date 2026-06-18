"""Tests for the AGENT CONTEXT prompt-panel section renderer."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from rich.text import Text

from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_context_common import count_phrase
from sase.ace.tui.widgets.prompt_panel._agent_context import (
    append_agent_context_section,
)
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from sase.skills.use_log import SKILL_USE_LOG_SCHEMA_VERSION, SkillUseEvent


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def _memory_event() -> MemoryReadDisplayEvent:
    return MemoryReadDisplayEvent(
        event=MemoryReadEvent(
            schema_version=READ_LOG_SCHEMA_VERSION,
            id="read-a",
            timestamp="2026-06-14T14:22:08+00:00",
            project="test",
            cwd="/tmp/test",
            canonical_path="generated_skills.md",
            resolved_path="/tmp/test/memory/generated_skills.md",
            agent_name="alpha",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/tmp/test/artifacts",
            reason="needed generated skill rules",
            byte_count=64,
            frontmatter_stripped=False,
        )
    )


def _skill_event() -> SkillUseDisplayEvent:
    return SkillUseDisplayEvent(
        event=SkillUseEvent(
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
    )


def _span_style_for(text: Text, needle: str) -> str:
    start = text.plain.index(needle)
    end = start + len(needle)
    styles = [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= end
    ]
    assert len(styles) == 1
    return styles[0]


def test_empty_context_appends_nothing() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(), skill_uses=())
    assert text.plain == ""


def test_memory_only_context_omits_empty_skills_lane() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(_memory_event(),), skill_uses=())

    plain = text.plain
    assert "AGENT CONTEXT\n" in plain
    assert "▸ MEMORY · 1 read · 1 file\n" in plain
    assert "generated_skills.md" in plain
    assert "▸ SKILLS" not in plain
    assert "none recorded" not in plain


def test_skills_only_context_omits_empty_memory_lane() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(), skill_uses=(_skill_event(),))

    plain = text.plain
    assert "AGENT CONTEXT\n" in plain
    assert "▸ SKILLS · 1 use · 1 skill\n" in plain
    assert "sase_plan" in plain
    assert "▸ MEMORY" not in plain
    assert "none recorded" not in plain


def test_memory_and_skills_render_in_parent_context_order() -> None:
    text = Text()
    append_agent_context_section(
        text,
        memory_reads=(_memory_event(),),
        skill_uses=(_skill_event(),),
    )

    plain = text.plain
    assert plain.index("AGENT CONTEXT\n") < plain.index("▸ MEMORY")
    assert plain.index("▸ MEMORY") < plain.index("▸ SKILLS")
    assert "needed generated skill rules" in plain
    assert "needed an implementation plan" in plain


def test_count_phrase_pluralizes_context_counts() -> None:
    assert count_phrase(1, "read") == "1 read"
    assert count_phrase(2, "read") == "2 reads"
    assert count_phrase(1, "file") == "1 file"
    assert count_phrase(3, "file") == "3 files"
    assert count_phrase(1, "use") == "1 use"
    assert count_phrase(2, "skill") == "2 skills"


def test_lane_subheaders_use_distinct_accent_colors() -> None:
    text = Text()
    append_agent_context_section(
        text,
        memory_reads=(_memory_event(),),
        skill_uses=(_skill_event(),),
    )

    memory_style = _span_style_for(text, "▸ MEMORY").lower()
    skills_style = _span_style_for(text, "▸ SKILLS").lower()
    assert memory_style == "bold #5fd7ff"
    assert skills_style == "bold #5fd75f"
    assert memory_style != skills_style


def test_memory_and_skills_rows_share_columns() -> None:
    text = Text()
    append_agent_context_section(
        text,
        memory_reads=(_memory_event(),),
        skill_uses=(_skill_event(),),
    )

    lines = text.plain.splitlines()
    memory_row = next(line for line in lines if "◇ generated_skills.md" in line)
    skill_row = next(line for line in lines if "◆ sase_plan" in line)
    memory_reason = next(
        line for line in lines if "needed generated skill rules" in line
    )
    skill_reason = next(
        line for line in lines if "needed an implementation plan" in line
    )

    assert memory_row.index("◇") == skill_row.index("◆")
    assert memory_row.index("generated_skills.md") == skill_row.index("sase_plan")
    assert memory_reason.index("↳") == skill_reason.index("↳")
    assert memory_reason.index("↳") == memory_row.index("generated_skills.md")
