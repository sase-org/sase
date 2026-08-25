"""Tests for the agent GLOSSARY prompt-panel sub-section renderer."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.glossary_reads import GlossaryReadDisplayEvent
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    REASON_LINE_CELL_LIMIT,
)
from sase.ace.tui.widgets.prompt_panel._agent_glossary_reads import (
    MAX_VISIBLE_READS,
    append_agent_glossary_reads_section,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.memory.legacy_glossary_read_log import (
    GLOSSARY_READ_LOG_SCHEMA_VERSION,
    GlossaryReadEvent,
)
from sase.memory.legacy_glossary_read_report import glossary_read_report_path


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def _event(
    *,
    terms: tuple[str, ...],
    timestamp: str,
    related_terms: tuple[str, ...] = (),
    reason: str = "needed it",
    read_id: str | None = None,
    source_path: str | None = "/tmp/test/sase/sase.yml",
) -> GlossaryReadEvent:
    return GlossaryReadEvent(
        schema_version=GLOSSARY_READ_LOG_SCHEMA_VERSION,
        id=read_id or "_".join(terms) + timestamp,
        timestamp=timestamp,
        project="test",
        cwd="/tmp/test",
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir="/tmp/test/artifacts",
        reason=reason,
        terms=terms,
        related_terms=related_terms,
        depth_limit=None,
        definition_bytes=64,
        source_path=source_path,
    )


def _display(
    event: GlossaryReadEvent, label: str | None = None
) -> GlossaryReadDisplayEvent:
    return GlossaryReadDisplayEvent(event=event, agent_label=label)


def _hint_state(start: int = 1) -> HeaderHintState:
    return HeaderHintState(
        hint_counter=start,
        hint_mappings={},
        workspace_dir=None,
        tool_call_reports={},
    )


def test_empty_events_appends_nothing() -> None:
    text = Text()
    append_agent_glossary_reads_section(text, events=())
    assert text.plain == ""


def test_empty_events_can_render_placeholder() -> None:
    text = Text()
    append_agent_glossary_reads_section(text, events=(), show_empty=True)
    assert text.plain == "▸ GLOSSARY · none recorded\n"


def test_single_event_renders_timestamp_term_and_reason() -> None:
    text = Text()
    event = _event(
        terms=("Agent Hood",),
        timestamp="2026-05-24T14:22:08+00:00",
        reason="needed the hood/agent distinction for the bead prompt",
    )
    append_agent_glossary_reads_section(text, events=(_display(event),))

    plain = text.plain
    assert "▸ GLOSSARY · 1 read · 1 term\n" in plain
    assert "14:22:08  ◈ Agent Hood" in plain
    assert "↳ needed the hood/agent distinction for the bead prompt" in plain
    assert "+" not in plain.split("\n")[1]
    assert "[1]" not in plain


def test_related_terms_render_as_suffix() -> None:
    text = Text()
    event = _event(
        terms=("Agent Hood",),
        timestamp="2026-05-24T14:22:08+00:00",
        related_terms=("Sase Agent", "Agent Shell"),
    )
    append_agent_glossary_reads_section(text, events=(_display(event),))

    assert "Agent Hood +2 related" in text.plain


def test_hint_state_maps_each_visible_event_and_aligns_reason() -> None:
    first = _event(
        terms=("Agent Hood",),
        timestamp="2026-05-24T14:22:08+00:00",
        reason="needed the hood/agent distinction",
        read_id="read-1",
        source_path="/tmp/test/sase/sase.yml",
    )
    second = _event(
        terms=("Stitch",),
        timestamp="2026-05-24T14:21:08+00:00",
        reason="confirming stitch vs commit",
        read_id="read-2",
        source_path="/tmp/test/sase/sase.yml",
    )
    state = _hint_state(start=4)
    text = Text()

    append_agent_glossary_reads_section(
        text,
        events=(_display(first), _display(second)),
        hint_state=state,
    )

    first_path = glossary_read_report_path(first)
    second_path = glossary_read_report_path(second)
    assert "◈ [4] Agent Hood" in text.plain
    assert "◈ [5] Stitch" in text.plain
    assert state.hint_mappings == {
        4: first_path,
        5: second_path,
    }
    assert set(state.glossary_reports) == {first_path, second_path}
    assert state.glossary_reports[first_path].event is first
    assert state.glossary_reports[second_path].event is second
    assert state.hint_counter == 6
    lines = text.plain.splitlines()
    first_row = next(line for line in lines if "[4] Agent Hood" in line)
    first_reason = next(line for line in lines if "needed the hood/agent" in line)
    assert first_reason.index("↳") == first_row.index("Agent Hood")


def test_event_without_terms_gets_no_hint() -> None:
    event = _event(
        terms=(),
        timestamp="2026-05-24T14:22:08+00:00",
        source_path="/tmp/test/sase/sase.yml",
    )
    state = _hint_state()
    text = Text()

    append_agent_glossary_reads_section(
        text, events=(_display(event),), hint_state=state
    )

    assert state.hint_mappings == {}
    assert state.glossary_reports == {}
    assert state.hint_counter == 1
    assert "[1]" not in text.plain


def test_event_without_source_path_still_gets_hint() -> None:
    event = _event(
        terms=("Agent Hood",),
        timestamp="2026-05-24T14:22:08+00:00",
        source_path=None,
    )
    state = _hint_state()
    text = Text()

    append_agent_glossary_reads_section(
        text, events=(_display(event),), hint_state=state
    )

    report_path = glossary_read_report_path(event)
    assert state.hint_mappings == {1: report_path}
    assert report_path in state.glossary_reports
    assert "[1]" in text.plain


def test_overflow_renders_truncation_footer() -> None:
    events = tuple(
        _event(
            terms=(f"Term {index}",),
            timestamp=f"2026-05-24T14:{30 - index:02d}:00+00:00",
            reason=f"reason {index}",
            read_id=f"id-{index}",
        )
        for index in range(MAX_VISIBLE_READS + 2)
    )
    text = Text()
    append_agent_glossary_reads_section(
        text, events=tuple(_display(event) for event in events)
    )

    plain = text.plain
    assert plain.count("↳") == MAX_VISIBLE_READS
    overflow = len(events) - MAX_VISIBLE_READS
    assert f"+ {overflow} more" in plain
    earliest_hhmm = events[-1].timestamp[11:16]
    assert f"· {earliest_hhmm} earliest" in plain


def test_overflow_line_gets_no_hint() -> None:
    events = tuple(
        _event(
            terms=(f"Term {index}",),
            timestamp=f"2026-05-24T14:{30 - index:02d}:00+00:00",
            read_id=f"id-{index}",
        )
        for index in range(MAX_VISIBLE_READS + 2)
    )
    state = _hint_state()
    text = Text()

    append_agent_glossary_reads_section(
        text,
        events=tuple(_display(event) for event in events),
        hint_state=state,
    )

    assert len(state.hint_mappings) == MAX_VISIBLE_READS
    assert text.plain.count("[") == MAX_VISIBLE_READS
    overflow_line = next(line for line in text.plain.splitlines() if "+ 2 more" in line)
    assert "[" not in overflow_line


def test_long_reason_is_wrapped_without_truncation() -> None:
    long_reason = " ".join(f"reason-word-{index:02d}" for index in range(18))
    text = Text()
    event = _event(
        terms=("Agent Hood",),
        timestamp="2026-05-24T14:00:00+00:00",
        reason=long_reason,
    )
    append_agent_glossary_reads_section(text, events=(_display(event),))

    plain = text.plain
    assert "…" not in plain
    assert long_reason in " ".join(plain.split())

    lines = plain.splitlines()
    for line in lines:
        assert cell_len(line) <= REASON_LINE_CELL_LIMIT


def test_distinct_term_count_in_summary() -> None:
    events = (
        _event(
            terms=("Agent Hood",),
            timestamp="2026-05-24T14:05:00+00:00",
            read_id="id-1",
        ),
        _event(
            terms=("Agent Hood",),
            timestamp="2026-05-24T14:04:00+00:00",
            read_id="id-2",
        ),
        _event(
            terms=("Stitch",),
            timestamp="2026-05-24T14:03:00+00:00",
            read_id="id-3",
        ),
    )
    text = Text()
    append_agent_glossary_reads_section(
        text, events=tuple(_display(event) for event in events)
    )

    assert "▸ GLOSSARY · 3 reads · 2 terms\n" in text.plain


def test_attributed_rows_render_role_labels() -> None:
    text = Text()
    events = (
        _display(
            _event(
                terms=("Agent Hood",),
                timestamp="2026-05-24T14:22:08+00:00",
                read_id="id-1",
            ),
            "coder",
        ),
        _display(
            _event(
                terms=("Stitch",),
                timestamp="2026-05-24T14:21:00+00:00",
                read_id="id-2",
            ),
            "plan",
        ),
    )
    append_agent_glossary_reads_section(text, events=events)

    plain = text.plain
    assert "▸ GLOSSARY · 2 reads · 2 terms · 2 agents\n" in plain
    assert "14:22:08  coder  ◈ Agent Hood" in plain
    assert "14:21:00  plan   ◈ Stitch" in plain


def test_single_producer_summary_omits_agent_count() -> None:
    text = Text()
    events = (
        _display(
            _event(
                terms=("Agent Hood",),
                timestamp="2026-05-24T14:05:00+00:00",
                read_id="id-1",
            ),
            "plan",
        ),
        _display(
            _event(
                terms=("Stitch",),
                timestamp="2026-05-24T14:04:00+00:00",
                read_id="id-2",
            ),
            "plan",
        ),
    )
    append_agent_glossary_reads_section(text, events=events)

    assert "▸ GLOSSARY · 2 reads · 2 terms\n" in text.plain
    assert "agents" not in text.plain


def test_multi_term_request_joins_primary_text() -> None:
    text = Text()
    event = _event(
        terms=("Agent Hood", "Sase Agent"),
        timestamp="2026-05-24T14:22:08+00:00",
    )
    append_agent_glossary_reads_section(text, events=(_display(event),))

    assert "◈ Agent Hood, Sase Agent" in text.plain
