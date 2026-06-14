"""Tests for the agent MEMORY prompt-panel sub-section renderer."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from rich.text import Text

from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_memory_reads import (
    MAX_VISIBLE_READS,
    REASON_WRAP_WIDTH,
    append_agent_memory_reads_section,
)
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def _event(
    *,
    canonical_path: str,
    timestamp: str,
    reason: str = "needed it",
    frontmatter_stripped: bool = False,
    read_id: str | None = None,
) -> MemoryReadEvent:
    return MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id=read_id or canonical_path + timestamp,
        timestamp=timestamp,
        project="test",
        cwd="/tmp/test",
        canonical_path=canonical_path,
        resolved_path=f"/tmp/test/memory/{canonical_path}",
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir="/tmp/test/artifacts",
        reason=reason,
        byte_count=64,
        frontmatter_stripped=frontmatter_stripped,
    )


def _display(
    event: MemoryReadEvent, label: str | None = None
) -> MemoryReadDisplayEvent:
    return MemoryReadDisplayEvent(event=event, agent_label=label)


def test_empty_events_appends_nothing() -> None:
    text = Text()
    append_agent_memory_reads_section(text, events=())
    assert text.plain == ""


def test_empty_events_can_render_placeholder() -> None:
    text = Text()
    append_agent_memory_reads_section(text, events=(), show_empty=True)
    assert text.plain == "▸ MEMORY · none recorded\n"


def test_single_event_renders_timestamp_path_and_reason() -> None:
    text = Text()
    event = _event(
        canonical_path="long/generated_skills.md",
        timestamp="2026-05-24T14:22:08+00:00",
        reason="needed commit hook contract for runtime parity refactor",
    )
    append_agent_memory_reads_section(text, events=(_display(event),))

    plain = text.plain
    assert "▸ MEMORY · 1 read · 1 file\n" in plain
    assert "14:22:08  ◇ long/generated_skills.md" in plain
    assert "↳ needed commit hook contract for runtime parity refactor" in plain
    assert "last 14:22:08" not in plain
    assert "+ " not in plain


def test_overflow_renders_truncation_footer() -> None:
    events = tuple(
        _event(
            canonical_path=f"long/file_{index}.md",
            timestamp=f"2026-05-24T14:{30 - index:02d}:00+00:00",
            reason=f"reason {index}",
            read_id=f"id-{index}",
        )
        for index in range(MAX_VISIBLE_READS + 2)
    )
    text = Text()
    append_agent_memory_reads_section(
        text, events=tuple(_display(event) for event in events)
    )

    plain = text.plain
    assert plain.count("↳") == MAX_VISIBLE_READS
    overflow = len(events) - MAX_VISIBLE_READS
    assert f"+ {overflow} more" in plain
    # Earliest visible footer uses HH:MM of the last (oldest) event.
    earliest_hhmm = events[-1].timestamp[11:16]
    assert f"· {earliest_hhmm} earliest" in plain


def test_long_reason_is_wrapped_without_truncation() -> None:
    long_reason = " ".join(f"reason-word-{index:02d}" for index in range(18))
    text = Text()
    event = _event(
        canonical_path="long/skill.md",
        timestamp="2026-05-24T14:00:00+00:00",
        reason=long_reason,
    )
    append_agent_memory_reads_section(text, events=(_display(event),))

    plain = text.plain
    assert "…" not in plain
    assert long_reason in " ".join(plain.split())

    lines = plain.splitlines()
    first_reason_line_index = next(
        index for index, line in enumerate(lines) if "↳ " in line
    )
    first_reason_line = lines[first_reason_line_index]
    continuation_line = lines[first_reason_line_index + 1]

    assert len(first_reason_line.partition("↳ ")[2]) <= REASON_WRAP_WIDTH
    assert continuation_line.startswith(" " * len("              ↳ "))
    assert "↳" not in continuation_line
    assert continuation_line.strip()


def test_frontmatter_marker_present_when_stripped() -> None:
    text = Text()
    event = _event(
        canonical_path="long/skill.md",
        timestamp="2026-05-24T14:00:00+00:00",
        frontmatter_stripped=True,
    )
    append_agent_memory_reads_section(text, events=(_display(event),))

    assert "↩ frontmatter" in text.plain


def test_frontmatter_marker_absent_when_not_stripped() -> None:
    text = Text()
    event = _event(
        canonical_path="long/skill.md",
        timestamp="2026-05-24T14:00:00+00:00",
        frontmatter_stripped=False,
    )
    append_agent_memory_reads_section(text, events=(_display(event),))

    assert "↩ frontmatter" not in text.plain


def test_distinct_path_count_in_summary() -> None:
    events = (
        _event(
            canonical_path="long/a.md",
            timestamp="2026-05-24T14:05:00+00:00",
            read_id="id-1",
        ),
        _event(
            canonical_path="long/a.md",
            timestamp="2026-05-24T14:04:00+00:00",
            read_id="id-2",
        ),
        _event(
            canonical_path="long/b.md",
            timestamp="2026-05-24T14:03:00+00:00",
            read_id="id-3",
        ),
    )
    text = Text()
    append_agent_memory_reads_section(
        text, events=tuple(_display(event) for event in events)
    )

    assert "▸ MEMORY · 3 reads · 2 files\n" in text.plain
    assert "last 14:05:00" not in text.plain


def test_attributed_rows_render_role_labels() -> None:
    text = Text()
    events = (
        _display(
            _event(
                canonical_path="long/tui_perf.md",
                timestamp="2026-05-24T14:22:08+00:00",
                read_id="id-1",
            ),
            "coder",
        ),
        _display(
            _event(
                canonical_path="long/cli_rules.md",
                timestamp="2026-05-24T14:21:00+00:00",
                read_id="id-2",
            ),
            "plan",
        ),
    )
    append_agent_memory_reads_section(text, events=events)

    plain = text.plain
    assert "▸ MEMORY · 2 reads · 2 files · 2 agents\n" in plain
    assert "14:22:08  coder  ◇ long/tui_perf.md" in plain
    assert "14:21:00  plan   ◇ long/cli_rules.md" in plain


def test_role_column_padded_for_unlabeled_rows_in_attributed_lane() -> None:
    text = Text()
    events = (
        _display(
            _event(
                canonical_path="long/tui_perf.md",
                timestamp="2026-05-24T14:22:08+00:00",
                read_id="id-1",
            ),
            "coder",
        ),
        _display(
            _event(
                canonical_path="long/cli_rules.md",
                timestamp="2026-05-24T14:21:00+00:00",
                read_id="id-2",
            ),
            None,
        ),
    )
    append_agent_memory_reads_section(text, events=events)

    lines = text.plain.splitlines()
    labeled = next(line for line in lines if "long/tui_perf.md" in line)
    unlabeled = next(line for line in lines if "long/cli_rules.md" in line)
    # Glyph stays column-aligned even though the second row has no label.
    assert labeled.index("◇") == unlabeled.index("◇")


def test_single_producer_summary_omits_agent_count() -> None:
    text = Text()
    events = (
        _display(
            _event(
                canonical_path="long/a.md",
                timestamp="2026-05-24T14:05:00+00:00",
                read_id="id-1",
            ),
            "plan",
        ),
        _display(
            _event(
                canonical_path="long/b.md",
                timestamp="2026-05-24T14:04:00+00:00",
                read_id="id-2",
            ),
            "plan",
        ),
    )
    append_agent_memory_reads_section(text, events=events)

    assert "▸ MEMORY · 2 reads · 2 files\n" in text.plain
    assert "agents" not in text.plain


def test_attributed_reason_aligns_under_primary_text() -> None:
    text = Text()
    events = (
        _display(
            _event(
                canonical_path="long/tui_perf.md",
                timestamp="2026-05-24T14:22:08+00:00",
                reason="perf budget context",
                read_id="id-1",
            ),
            "coder",
        ),
    )
    append_agent_memory_reads_section(text, events=events)

    lines = text.plain.splitlines()
    row = next(line for line in lines if "long/tui_perf.md" in line)
    reason = next(line for line in lines if "↳" in line)
    assert reason.index("↳") == row.index("long/tui_perf.md")
