"""Tests for the agent SKILLS prompt-panel sub-section renderer."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel import _agent_memory_reads
from sase.ace.tui.widgets.prompt_panel._agent_skill_uses import (
    MAX_VISIBLE_SKILL_USES,
    append_agent_skills_section,
)
from sase.skills.use_log import SKILL_USE_LOG_SCHEMA_VERSION, SkillUseEvent


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_memory_reads,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def _event(
    *,
    skill_name: str,
    timestamp: str,
    reason: str = "needed it",
    use_id: str | None = None,
) -> SkillUseEvent:
    return SkillUseEvent(
        schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
        id=use_id or skill_name + timestamp,
        timestamp=timestamp,
        project="test",
        cwd="/tmp/test",
        skill_name=skill_name,
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir="/tmp/test/artifacts",
        reason=reason,
        runtime="codex",
    )


def test_empty_events_appends_nothing() -> None:
    text = Text()
    append_agent_skills_section(text, events=())
    assert text.plain == ""


def test_empty_events_can_render_placeholder() -> None:
    text = Text()
    append_agent_skills_section(text, events=(), show_empty=True)
    assert "▸ SKILLS\n" in text.plain
    assert "none recorded" in text.plain


def test_single_event_renders_timestamp_skill_and_reason() -> None:
    text = Text()
    event = _event(
        skill_name="sase_plan",
        timestamp="2026-06-14T14:22:08+00:00",
        reason="needed a reviewed implementation plan",
    )
    append_agent_skills_section(text, events=(event,))

    plain = text.plain
    assert "▸ SKILLS\n" in plain
    assert "  1 uses · 1 skills · last 14:22:08" in plain
    assert "14:22:08  ◆ sase_plan" in plain
    assert "↳ needed a reviewed implementation plan" in plain
    assert "+ " not in plain


def test_overflow_renders_truncation_footer() -> None:
    events = tuple(
        _event(
            skill_name=f"skill_{index}",
            timestamp=f"2026-06-14T14:{30 - index:02d}:00+00:00",
            reason=f"reason {index}",
            use_id=f"id-{index}",
        )
        for index in range(MAX_VISIBLE_SKILL_USES + 2)
    )
    text = Text()
    append_agent_skills_section(text, events=events)

    plain = text.plain
    assert plain.count("↳") == MAX_VISIBLE_SKILL_USES
    overflow = len(events) - MAX_VISIBLE_SKILL_USES
    assert f"+ {overflow} more" in plain
    earliest_hhmm = events[-1].timestamp[11:16]
    assert f"({earliest_hhmm} earliest)" in plain


def test_distinct_skill_count_in_summary() -> None:
    events = (
        _event(
            skill_name="sase_plan",
            timestamp="2026-06-14T14:05:00+00:00",
            use_id="id-1",
        ),
        _event(
            skill_name="sase_plan",
            timestamp="2026-06-14T14:04:00+00:00",
            use_id="id-2",
        ),
        _event(
            skill_name="sase_questions",
            timestamp="2026-06-14T14:03:00+00:00",
            use_id="id-3",
        ),
    )
    text = Text()
    append_agent_skills_section(text, events=events)

    assert "3 uses · 2 skills · last 14:05:00" in text.plain
