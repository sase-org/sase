"""Basic row-rendering tests for the agent MEMORY sub-section.

Split from ``test_agent_memory_reads``; shared builders live in
``_agent_memory_reads_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    REASON_LINE_CELL_LIMIT,
)
from sase.ace.tui.widgets.prompt_panel._agent_memory_reads import (
    MAX_VISIBLE_READS,
    append_agent_memory_reads_section,
)
from sase.memory.memory_read_report import memory_read_report_path
from tests.ace.tui.widgets._agent_memory_reads_helpers import (
    make_hint_state,
    make_memory_read_display,
    make_memory_read_event,
    pin_memory_reads_timezone,
)

__all__ = [
    "test_empty_events_appends_nothing",
    "test_empty_events_can_render_placeholder",
    "test_hint_state_maps_each_visible_event_and_aligns_reason",
    "test_long_attributed_reason_wraps_within_limit_and_aligns",
    "test_long_reason_is_wrapped_without_truncation",
    "test_overflow_line_gets_no_hint",
    "test_overflow_renders_truncation_footer",
    "test_overlong_token_is_hard_split_within_limit",
    "test_pathless_batch_event_displays_original_selectors",
    "test_pathless_event_without_selectors_gets_no_hint",
    "test_pathless_strand_event_maps_to_deferred_report",
    "test_single_event_renders_timestamp_path_and_reason",
]


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_memory_reads_timezone(monkeypatch)


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
    event = make_memory_read_event(
        canonical_path="generated_skills.md",
        timestamp="2026-05-24T14:22:08+00:00",
        reason="needed commit hook contract for runtime parity refactor",
    )
    append_agent_memory_reads_section(text, events=(make_memory_read_display(event),))

    plain = text.plain
    assert "▸ MEMORY · 1 read · 1 file\n" in plain
    assert "14:22:08  ◇ generated_skills.md" in plain
    assert "↳ needed commit hook contract for runtime parity refactor" in plain
    assert "last 14:22:08" not in plain
    assert "+ " not in plain
    assert "[1]" not in plain


def test_hint_state_maps_each_visible_event_and_aligns_reason() -> None:
    first = make_memory_read_event(
        canonical_path="tui_perf.md",
        timestamp="2026-05-24T14:22:08+00:00",
        reason="needed latency rules",
        read_id="read-1",
    )
    second = make_memory_read_event(
        canonical_path="tui_perf.md",
        timestamp="2026-05-24T14:21:08+00:00",
        reason="re-read before implementation",
        read_id="read-2",
    )
    state = make_hint_state(start=4)
    text = Text()

    append_agent_memory_reads_section(
        text,
        events=(make_memory_read_display(first), make_memory_read_display(second)),
        hint_state=state,
    )

    assert "◇ [4] tui_perf.md" in text.plain
    assert "◇ [5] tui_perf.md" in text.plain
    assert state.hint_mappings == {
        4: first.resolved_path,
        5: second.resolved_path,
    }
    assert state.memory_reports == {}
    assert state.hint_counter == 6
    lines = text.plain.splitlines()
    first_row = next(line for line in lines if "[4] tui_perf.md" in line)
    first_reason = next(line for line in lines if "needed latency rules" in line)
    assert first_reason.index("↳") == first_row.index("tui_perf.md")

    marker_start = text.plain.index("[4] ")
    marker_styles = [
        str(span.style).lower()
        for span in text.spans
        if span.start <= marker_start and span.end >= marker_start + len("[4] ")
    ]
    assert marker_styles == ["bold #ffff00"]


def test_pathless_strand_event_maps_to_deferred_report() -> None:
    event = make_memory_read_event(
        canonical_path="decisions:corpus-before-mechanism",
        timestamp="2026-05-24T14:22:08+00:00",
        read_id="strand-read",
        resolved_path="",
        kind="strand",
        selectors=("decisions:corpus-before-mechanism",),
        resolved_targets=("decisions:corpus-before-mechanism",),
        depth=0,
    )
    state = make_hint_state()
    text = Text()

    append_agent_memory_reads_section(
        text, events=(make_memory_read_display(event, "coder"),), hint_state=state
    )

    report_path = memory_read_report_path(event)
    assert state.hint_mappings == {1: report_path}
    assert list(state.memory_reports) == [report_path]
    assert state.memory_reports[report_path].event is event
    assert state.memory_reports[report_path].agent_label == "coder"
    assert "◇ [1] decisions:corpus-before-mechanism" in text.plain


def test_pathless_batch_event_displays_original_selectors() -> None:
    event = make_memory_read_event(
        canonical_path="decisions:corpus-before-mechanism",
        timestamp="2026-05-24T14:22:08+00:00",
        read_id="batch-read",
        resolved_path="",
        kind="strand",
        selectors=("decisions:corpus-before-mechanism", "tui_perf.md"),
        resolved_targets=("decisions:corpus-before-mechanism", "tui_perf.md"),
    )
    state = make_hint_state()
    text = Text()

    append_agent_memory_reads_section(
        text, events=(make_memory_read_display(event),), hint_state=state
    )

    assert "decisions:corpus-before-mechanism, tui_perf.md" in text.plain
    assert state.hint_mappings == {1: memory_read_report_path(event)}


def test_pathless_event_without_selectors_gets_no_hint() -> None:
    event = make_memory_read_event(
        canonical_path="",
        timestamp="2026-05-24T14:22:08+00:00",
        read_id="empty-pathless",
        resolved_path="",
        selectors=(),
    )
    state = make_hint_state()
    text = Text()

    append_agent_memory_reads_section(
        text, events=(make_memory_read_display(event),), hint_state=state
    )

    assert state.hint_mappings == {}
    assert state.memory_reports == {}
    assert "[1]" not in text.plain


def test_overflow_renders_truncation_footer() -> None:
    events = tuple(
        make_memory_read_event(
            canonical_path=f"file_{index}.md",
            timestamp=f"2026-05-24T14:{30 - index:02d}:00+00:00",
            reason=f"reason {index}",
            read_id=f"id-{index}",
        )
        for index in range(MAX_VISIBLE_READS + 2)
    )
    text = Text()
    append_agent_memory_reads_section(
        text, events=tuple(make_memory_read_display(event) for event in events)
    )

    plain = text.plain
    assert plain.count("↳") == MAX_VISIBLE_READS
    overflow = len(events) - MAX_VISIBLE_READS
    assert f"+ {overflow} more" in plain
    # Earliest visible footer uses HH:MM of the last (oldest) event.
    earliest_hhmm = events[-1].timestamp[11:16]
    assert f"· {earliest_hhmm} earliest" in plain


def test_overflow_line_gets_no_hint() -> None:
    events = tuple(
        make_memory_read_event(
            canonical_path=f"file_{index}.md",
            timestamp=f"2026-05-24T14:{30 - index:02d}:00+00:00",
            read_id=f"id-{index}",
        )
        for index in range(MAX_VISIBLE_READS + 2)
    )
    state = make_hint_state()
    text = Text()

    append_agent_memory_reads_section(
        text,
        events=tuple(make_memory_read_display(event) for event in events),
        hint_state=state,
    )

    assert len(state.hint_mappings) == MAX_VISIBLE_READS
    assert text.plain.count("[") == MAX_VISIBLE_READS
    overflow_line = next(line for line in text.plain.splitlines() if "+ 2 more" in line)
    assert "[" not in overflow_line


def test_long_reason_is_wrapped_without_truncation() -> None:
    long_reason = " ".join(f"reason-word-{index:02d}" for index in range(18))
    text = Text()
    event = make_memory_read_event(
        canonical_path="skill.md",
        timestamp="2026-05-24T14:00:00+00:00",
        reason=long_reason,
    )
    append_agent_memory_reads_section(text, events=(make_memory_read_display(event),))

    plain = text.plain
    assert "…" not in plain
    assert long_reason in " ".join(plain.split())

    lines = plain.splitlines()
    first_reason_line_index = next(
        index for index, line in enumerate(lines) if "↳ " in line
    )
    first_reason_line = lines[first_reason_line_index]
    continuation_line = lines[first_reason_line_index + 1]

    # Every rendered reason line, including its full prefix, fits in 80 columns.
    for line in lines:
        assert cell_len(line) <= REASON_LINE_CELL_LIMIT
    assert first_reason_line.partition("↳ ")[2]
    assert continuation_line.startswith(" " * len("              ↳ "))
    assert "↳" not in continuation_line
    assert continuation_line.strip()


def test_long_attributed_reason_wraps_within_limit_and_aligns() -> None:
    long_reason = " ".join(f"reason-word-{index:02d}" for index in range(18))
    text = Text()
    event = make_memory_read_event(
        canonical_path="tui_perf.md",
        timestamp="2026-05-24T14:22:08+00:00",
        reason=long_reason,
    )
    append_agent_memory_reads_section(
        text, events=(make_memory_read_display(event, "coder"),)
    )

    plain = text.plain
    assert "…" not in plain
    assert long_reason in " ".join(plain.split())

    lines = plain.splitlines()
    row = next(line for line in lines if "tui_perf.md" in line)
    first_reason_index = next(index for index, line in enumerate(lines) if "↳ " in line)
    first_reason_line = lines[first_reason_index]
    continuation_line = lines[first_reason_index + 1]

    # The wider attributed prefix still keeps every line within 80 columns.
    for line in lines:
        assert cell_len(line) <= REASON_LINE_CELL_LIMIT
    # Reason glyph and continuation align under the primary text column.
    assert first_reason_line.index("↳") == row.index("tui_perf.md")
    assert continuation_line.startswith(" " * (row.index("tui_perf.md") + 2))
    assert "↳" not in continuation_line
    assert continuation_line.strip()


def test_overlong_token_is_hard_split_within_limit() -> None:
    token = "x" * 200
    text = Text()
    event = make_memory_read_event(
        canonical_path="skill.md",
        timestamp="2026-05-24T14:00:00+00:00",
        reason=token,
    )
    append_agent_memory_reads_section(text, events=(make_memory_read_display(event),))

    plain = text.plain
    assert "…" not in plain
    lines = plain.splitlines()
    for line in lines:
        assert cell_len(line) <= REASON_LINE_CELL_LIMIT
    # The unbroken token is split across multiple lines, losing no characters.
    assert plain.count("x") == 200
